# SAT Explorer Visualization Framework

This document explains how the Explore UI (`frontend/src/pages/ExplorePage.jsx`) collaborates with the dedicated Explore backend (`explore_app/main.py`) to provide satellite raster visualization, GeoJSON overlays, and tile capture/export features.

## System Overview
- **Frontend**: A single-page React experience that bootstraps Leaflet/MapLibre, persists visualization controls in `localStorage`, orchestrates uploads, tile cutting, and file/task management.
- **Explore Backend**: FastAPI app colocated with TiTiler. Handles raster/vector ingestion, storage layout, tile capture, exports, and bridges to the main SAT backend for task creation.
- **Storage Layout** (`explore_app/storage`): Separates originals (`uploads`), derived `cogs`, vector uploads, tile captures/metadata/original tiles, and exports.
- **Shared Contracts**: All frontend actions ultimately target REST endpoints prefixed with `getExploreApiBase()` (e.g., `/upload`, `/tiles/capture`, `/files/list`), while visualization requests resolve against TiTiler’s `/cog/*` routes.

## Frontend: `ExplorePage.jsx`

### UI & State Model
- Uses dozens of `useState` hooks to track visualization params (`mode`, `bidxStr`, `expr`, `rangeMode`, etc.), UI toggles, and operational state (busy spinner, `status`, `tileCuttingMode`).
- Two debounced `useEffect` blocks commit visualization settings and UI layout (`expandedSections`, sidebars) into `localStorage`, enabling session persistence even across reloads.
- References to Leaflet primitives (`mapRef`, `rasterRef`, `vectorRef`, `tileAreasLayerRef`) provide imperative control over the map, overlay lifecycle, and drawn tile rectangles.

### Map Bootstrap & Basemap Handling
- Initializes the Leaflet canvas once, builds a MapLibre base layer from `getTileserverUrl()`, and installs custom controls (scale, coordinate tracker, high-`z-index` vector pane). Basemap visibility is toggled via `showOSM` without interfering with raster overlays.

```
341:455:frontend/src/pages/ExplorePage.jsx
  useEffect(() => {
    if (mapRef.current) return;
    const map = L.map(mapElRef.current, { zoomControl: true, attributionControl: true, preferCanvas: true });
    L.control.scale().addTo(map);
    map.setView([20, 0], 2);
    map.createPane("vectors");
    map.getPane("vectors").style.zIndex = 1200;
    const tileserverUrl = getTileserverUrl();
    const styleUrl = `${tileserverUrl}/styles/osm-bright/style.json`;
    const base = L.maplibreGL({ style: styleUrl, attribution: '', minZoom: 0, maxZoom: 19 }).addTo(map);
    ...
    mapRef.current = map;
    baseRef.current = base;
    return () => { ... map.remove(); ... };
  }, []);
```

### Raster Ingestion & Overlay Construction
1. **Upload**: `handleRasterFile` posts the uploaded file to `/upload`, receiving a file id plus a flag indicating if it was already a COG.
2. **Conversion**: Non-COG uploads immediately trigger `/convert-to-cog?id=<id>` to produce a web-friendly COG in `storage/cogs`.
3. **Metadata fetch**: Pulls `/cog/info` or `/meta` to determine band count and auto-select a default band configuration if nothing is cached in `localStorage`.
4. **Visualization**: Calls `rebuildOverlay` to build a TiTiler `tilejson`, replace any existing raster Leaflet layer, and fit to the returned bounds.

```
725:807:frontend/src/pages/ExplorePage.jsx
  async function handleRasterFile(e) {
    const file = e.target.files?.[0];
    ...
    const form = new FormData();
    form.append("file", file);
    const up = await axios.post(`${API_BASE}/upload`, form, { headers: { "Content-Type": "multipart/form-data" } });
    ...
    const conv = await axios.post(`${API_BASE}/convert-to-cog`, null, { params: { id } });
    ...
    const info = await axios.get(`${API_BASE}/cog/info`, { params: { url: path } });
    ...
    await rebuildOverlay({ fit: true, pathOverride: path });
  }
```

`rebuildOverlay` mirrors TiTiler query semantics. It builds a `URLSearchParams` payload containing band selection, expression mode, `pmin/pmax` vs. manual `rescale`, colormap, resampling, and `scaleX` overrides before requesting `/cog/WebMercatorQuad/tilejson.json`. The resulting `tilejson.tiles[0]` URL becomes a Leaflet `tileLayer` with `maxNativeZoom` derived from the response. Opacity is bound to the `opacity` slider, and the map’s `maxZoom` is temporarily lifted to allow upscaling.

### Vector & Public Overlays
- `handleVectorFile` posts GeoJSONs to `/vector/upload`, which reprojects to EPSG:4326 server-side before returning a `relative_url`. The frontend fetches the processed GeoJSON, draws a Leaflet `geoJSON` layer with dynamic styles, and feeds features into `GeoJSONLegend`.
- Public overlays (Countries, IB, LAC, LOC) load from static `/Countries.geojson` etc. Each overlay retains its color/opacity in `localStorage`, and layer handles are cached in `publicOverlaysRef` so UI toggles simply add/remove layers without refetching.

### Tile Cutting & Capture
- Two capture modes exist:
  - **Viewport capture**: `captureViewportPNG` posts the current map center, zoom, band settings, and `nativeResolutionMode` flag to `/tiles/capture`.
  - **Click capture**: `armClickCapture` flips `tileCuttingMode`; subsequent map clicks call `captureClickPNG`, which delegates to the same backend endpoint with click coordinates.
- Responses add PNGs to the `capturedTiles` list, render bounding boxes via `addTileAreaToMap`, and store metadata for later exports or task creation.
- Right-click cancels `tileCuttingMode`.

### File & Tile Management
- `FileManager` and `TileManager` components drive CRUD flows via `/files/list`, `/files/{id}`, `/tiles/captures`, `/tiles/captures/{tile_id}`, `/tiles/export-8bit`, `/tiles/export-16bit`, `/tiles/save-as-task`, `/tiles/create-task-with-labels`, and `/tiles/add-to-existing-task`.
- Clicking an uploaded file reloads its COG immediately; deleting a file cascades across COG/original/metadata.
- Tile actions include context loading (which reconfigures the raster view to the tile’s viz parameters), exporting zipped tiles, clearing all captures, and pushing captured imagery to SAT tasks.

### Inference Session Integration
- When `session_id` + optional `use_cog` query params are present, `loadInferenceSessionFiles` fetches inference outputs from the main backend (`getApiBase()`), loads rasters/GeoJSON by path, and mirrors the manual upload flow. Session chips and the “End Session” button manage teardown.

## Backend: `explore_app/main.py`

### Service Setup
- Configures FastAPI with logging middleware, permissive CORS, and TiTiler’s `TilerFactory` mounted at `/cog`.
- Ensures storage directories exist for uploads, cogs, vectors, exports, captured tiles, and metadata. Static mounts expose vectors and exports so the frontend can download files directly.
- Determines conversion capabilities at startup (`check_cog_conversion_availability`), preferring GDAL but falling back to `rio_cogeo`.

### Raster Upload & Conversion
- `/upload` accepts GeoTIFFs or image formats, stores them under a UUID, extracts band metadata (preferring rasterio, falling back to GDAL), and writes metadata JSON alongside the file. The response tells the frontend whether the file is already a COG.
- `/convert-to-cog` (plus helper `convert_to_cog_unified`) produces a `*_cog.tif` using GDAL first, falling back to `rio_cogeo`.

```
195:285:explore_app/main.py
@app.post("/upload")
async def upload_geotiff(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    supported_extensions = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp", ".img")
    if ext not in supported_extensions:
        raise HTTPException(400, f"Only {', '.join(supported_extensions)} files are allowed")
    uid = uuid.uuid4().hex
    dst = UPLOADS / f"{uid}{ext}"
    with dst.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    ...
    with rasterio.open(dst) as ds:
        band_info = { "band_count": ds.count, "data_types": [str(dtype) for dtype in ds.dtypes], ... }
```

### Vector Handling
- `/vector/upload` and `/vector/upload-from-path` both ensure GeoJSON is projected to EPSG:4326 via `_reproject_geojson`, save artifacts in `storage/vectors/upload/files`, and return `/vectors/{id}.geojson` URLs.
- `/vector/reproject` offers a pure reprojection API for ad-hoc debugging or data prep.

### File Management APIs
- `/files/list` enumerates all COGs, attaches original filenames, sizes, `band_info`, and absolute `gdal_path`s.
- `/files/{id}` delete/export/convert endpoints maintain parity with frontend operations.

### Tile Capture & Metadata
- `/tiles/capture` is the workhorse invoked by both viewport and click captures. It computes a bounding box (zoom-based or native-resolution), calls TiTiler’s `/cog/bbox` internally via a `TestClient`, stores the PNG, optionally cuts an original GeoTIFF tile via GDAL (preserving bit depth), and writes rich metadata (viz params, bbox, band config) plus a GeoJSON footprint.

```
2490:2838:explore_app/main.py
@app.post("/tiles/capture")
async def capture_tile(...):
    ...
    bbox_url = f"/cog/bbox/{bbox_minx},{bbox_miny},{bbox_maxx},{bbox_maxy}/{tile_size}x{tile_size}.png?url={cog_path}"
    ...
    if mode == "expr" and expr.strip():
        bbox_url += f"&expression={expr.strip()}"
    else:
        for bidx in band_config.split(","):
            bbox_url += f"&bidx={bidx}"
    ...
    metadata = create_tile_metadata(
        tile_id=tile_id,
        original_image_path=original_image_path if original_image_path else cog_path,
        bbox=[bbox_minx, bbox_miny, bbox_maxx, bbox_maxy],
        ...
        mode=mode,
        expr=expr,
        range_mode=range_mode,
        ...
    )
```

- Additional tile routes (`/tiles/captures`, `/tiles/captures/{tile_id}`, `/tiles/captures/{tile_id}` DELETE, `/tiles/captures` DELETE) surface metadata, GeoJSON footprints, cleanup, and export flows.

### Task & Export Routes
- `/tiles/export-8bit` and `/tiles/export-16bit` ZIP PNG tiles or preserved GeoTIFF tiles.
- `/tiles/save-as-task`, `/tiles/create-task-with-labels`, and `/tiles/add-to-existing-task` marshal captured imagery (and optionally original GeoTIFF crops) into the main SAT backend by forwarding requests to `MAIN_BACKEND_URL`.

### Auxiliary Endpoints
- `/files/extract-band-info` retrofits metadata for pre-existing uploads.
- `/health`, `/storage/clear`, script management endpoints, and public static mounts support operations and automation.

## End-to-End Data Flows

### Raster Visualization Flow
1. User uploads or selects an existing raster in the UI.
2. Frontend triggers `/upload` → optional `/convert-to-cog`; backend stores artifacts under `storage/uploads` + `storage/cogs`.
3. Frontend fetches `/cog/info` and calls TiTiler’s `/cog/WebMercatorQuad/tilejson.json`, receives tile URLs, and swaps the Leaflet raster layer.
4. UI controls adjust viz parameters locally; calling `rebuildOverlay` rebuilds query parameters and reloads the TiTiler layer without reuploading.

### Tile Capture to Task Creation
1. User captures tiles (viewport or clicks) → `/tiles/capture` → stored PNG + optional original GeoTIFF cut + metadata.
2. Tile rectangles show up on the map, and `TileManager` lists saved captures via `/tiles/captures`.
3. Exports or task creation flows gather PNGs (and optionally original GeoTIFFs) and POST to `/tiles/save-as-task`, `/tiles/create-task-with-labels`, or `/tiles/add-to-existing-task`, which forward to the main backend service.

### GeoJSON Overlay Flow
1. GeoJSON uploads hit `/vector/upload` (or `upload-from-path` during inference review), which reprojects and stores a sanitized copy.
2. The frontend fetches the processed GeoJSON, renders it on the `vectors` pane, and generates legends + popups.
3. Public overlays simply fetch static files, but stateful toggles let users persist color/opacity preferences.

## Key Integration Points

| Feature | Frontend Hook | Backend Endpoint | Notes |
| --- | --- | --- | --- |
| Raster upload | `handleRasterFile` | `POST /upload`, `POST /convert-to-cog`, `GET /cog/info` | Converts everything to COG for TiTiler compatibility |
| Visualization updates | `rebuildOverlay` | `GET /cog/WebMercatorQuad/tilejson.json` | Builds TiTiler params mirroring UI controls |
| GeoJSON overlay | `handleVectorFile` | `POST /vector/upload`, static `/vectors/{id}.geojson` | Always stored as EPSG:4326 |
| Tile capture | `captureViewportPNG`, `captureClickPNG` | `POST /tiles/capture` | Returns metadata + PNG/original tile paths |
| Tile inventory | `TileManager` | `GET/DELETE /tiles/captures` | Drives exports and task creation |
| File manager | `FileManager` | `/files/list`, `/files/{id}`, `/files/{id}/export` | Keeps COG/original pairs in sync |

## Operational Considerations
- **Local persistence**: Almost every visualization parameter is saved to `localStorage`, so debugging “unexpected” defaults usually means clearing those keys.
- **GDAL vs. rio-cogeo**: Tile cutting with preserved bit depth depends on GDAL Python bindings. Without GDAL, `/tiles/capture` still produces PNGs but skips GeoTIFF crops.
- **TiTiler dependency**: Map rendering and tile capture both hinge on TiTiler endpoints; verify `/cog/*` health before debugging UI rendering issues.
- **Bounds & CRS**: The backend aggressively reprojects GeoJSONs and extracts geographic extents from rasters to keep Leaflet interactions WGS84-first.
- **Concurrency**: `setBusy` gates multi-step workflows; backend logs (`explore_app/logs/`) mirror the same operations for tracing.

## Watcher-Based Inference Service

- **Entrypoint**: `scripts/run_pipeline.py` loads `config/pipeline.yaml`, wires the watcher (`src/watcher.py`), persistent queue (`src/job_queue.py`), orchestrator (`src/orchestrator.py`), and GPU inference runner (`src/inference_runner.py`).
- **Flow**:
  1. The watcher monitors `watcher.input_dir` for GeoTIFF/JP2/etc., applying settle-time checks before enqueueing a job.
  2. `JobQueue` stores state in `queue.persistence_path`, enforces retry/backoff/quarantine.
  3. Worker threads tile imagery via `src/tiler.py`, batch tiles according to `workers.batch_size`, and fan them out to preloaded YOLO/YOLO-OBB models (model → GPU mapping is declared under `models` + `gpus`).
  4. `InferenceRunner` emits per-model GeoJSON (`artifacts.success_dir/<model>/<model>_<job>.geojson`), CSV summaries, optional tile previews, plus a combined GeoJSON under `artifacts.combined`.
  5. `ManifestWriter` records a JSON manifest (paths, durations, model stats) for downstream Explore/UI ingestion, while `health_monitor.py` writes `health.heartbeat_path` snapshots (queue depth, worker liveness, GPU util).
- **Failure Handling**: Exceptions per model or tiling stage trigger detailed per-image logs (`artifacts/logs/images/<job>.log`) and copies of problematic rasters under `artifacts.failure_dir/<job>/`. After `queue.max_retries` attempts the job is quarantined with full metadata for manual inspection.
- **Integration Hooks**: The Explore app can list manifests/combined GeoJSONs to visualize automated detections alongside manual annotations. Future UI can surface heartbeat + queue stats for ops dashboards.

## Extension Ideas
- Surface backend `band_info` (bit depth, CRS, footprint) inside `FileManager` cards so analysts can pick correct `bidx` presets.
- Add optimistic UI updates for tile captures (present placeholder rectangles) while `/tiles/capture` runs to improve perceived responsiveness on large rasters.
- Wire telemetry from `/tiles/*` endpoints into the main monitoring dashboard so large batch operations (e.g., export 16-bit) can be tracked centrally.
- Consider caching TiTiler tilejson responses client-side per `cogPath` + viz hash to avoid redundant rebuilds when toggling UI sections without visual changes.

---
_Last updated: 2025-11-19_

