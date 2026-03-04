# ROI-Based Spatial Filtering and Cropping - Implementation Plan

## Overview
Add Region of Interest (ROI) filtering and cropping capability to process only specific geographic regions of satellite images, reducing computational overhead and improving efficiency.

## Requirements Summary
1. **One GeoJSON per model** - Contains polygon(s) defining ROI in world coordinates
2. **Intersection check** - Check if image bounds intersect with ROI before processing
3. **Crop to intersection** - Process only the intersecting region, not the full image
4. **Output in original coordinates** - All detections must be in original image coordinate space for proper overlay
5. **Partial intersection** - Process only the partial intersecting part
6. **Multiple ROI handling** - If image intersects multiple ROI polygons, union them into single processing region
7. **Single output per image** - One GeoJSON output file per image per model (contains all detections from unioned ROI region)
8. **Backward compatible** - If no ROI specified, process entire image (default behavior)

---

## Architecture Design

### 1. New Components

#### 1.1 `roi_filter.py` (New Module)
**Purpose**: Handle ROI loading, spatial intersection checks, and coordinate transformations

**Key Classes/Functions**:
- `ROIFilter`: Main class for ROI operations
  - `load_roi(geojson_path: Path) -> List[Polygon]`: Load ROI polygons from GeoJSON
  - `get_image_bounds(dataset: gdal.Dataset) -> Polygon`: Extract image geographic bounds
  - `check_intersection(image_bounds: Polygon, roi_polygons: List[Polygon]) -> Optional[Polygon]`: Check if image intersects ROI, return intersection polygon
  - `roi_to_pixel_bounds(intersection_poly: Polygon, dataset: gdal.Dataset) -> Tuple[int, int, int, int]`: Convert geographic intersection to pixel bounds (xmin, ymin, xmax, ymax)
  - `crop_dataset(dataset: gdal.Dataset, pixel_bounds: Tuple) -> gdal.Dataset`: Create cropped virtual dataset

**Dependencies**:
- `shapely` for spatial operations
- `pyproj` for CRS transformations
- `gdal` for image operations

#### 1.2 Configuration Updates

**Add to `ModelConfig` dataclass** (`config_loader.py`):
```python
@dataclass
class ModelConfig:
    # ... existing fields ...
    roi_geojson_path: Optional[Path] = None  # Path to ROI GeoJSON file
```

**Add to `pipeline.yaml` schema**:
```yaml
models:
  - name: "model_name"
    # ... existing config ...
    roi_geojson_path: "path/to/roi.geojson"  # Optional
```

---

## Implementation Steps

### Phase 1: Core ROI Infrastructure

#### Step 1.1: Create `roi_filter.py` Module
**File**: `roi_filter.py`

**Functions to implement**:
1. `load_roi_geojson(geojson_path: Path) -> List[Polygon]`
   - Load GeoJSON file
   - Extract all polygons (handle FeatureCollection, single Feature, or GeometryCollection)
   - Validate polygons are valid
   - Return list of Shapely Polygon objects

2. `get_image_geographic_bounds(dataset: gdal.Dataset) -> Polygon`
   - Extract geotransform from dataset
   - Calculate 4 corner points in pixel space
   - Convert to geographic coordinates using `pixel_to_geo`
   - Create Shapely Polygon from 4 corners
   - Handle images without projection (return None or raise warning)

3. `reproject_polygon(polygon: Polygon, source_crs: CRS, target_crs: CRS) -> Polygon`
   - Transform polygon coordinates between CRS
   - Handle CRS mismatches (ROI in WGS84, image in UTM, etc.)

4. `compute_intersection(image_bounds: Polygon, roi_polygons: List[Polygon]) -> Optional[Polygon]`
   - Check intersection between image bounds and each ROI polygon
   - **Multiple ROI handling**: If image intersects with multiple ROI polygons:
     - Calculate intersection polygon for each ROI that intersects the image
     - Union all intersection polygons into a single polygon
     - This ensures all intersecting ROI regions are processed together
   - Return unioned intersection polygon (or None if no intersection)
   - **Example**: Image intersects ROI1 and ROI2 → Union(Image∩ROI1, Image∩ROI2) → Single processing region

5. `geographic_to_pixel_bounds(intersection_poly: Polygon, dataset: gdal.Dataset) -> Tuple[int, int, int, int]`
   - Sample intersection polygon boundary points
   - Convert each point from geographic to pixel coordinates
   - Find min/max pixel coordinates (xmin, ymin, xmax, ymax)
   - Clamp to image dimensions
   - Return: `(xmin, ymin, xmax, ymax)` in pixel coordinates

6. `create_cropped_dataset(dataset: gdal.Dataset, pixel_bounds: Tuple[int, int, int, int]) -> gdal.Dataset`
   - Use GDAL's `ReadAsArray` with window parameters
   - Or create virtual dataset (VRT) for memory efficiency
   - Adjust geotransform for cropped region
   - Return new dataset handle

**Error Handling**:
- Invalid GeoJSON format
- Empty ROI polygons
- CRS transformation failures
- Images without geotransform/projection

#### Step 1.2: Update Configuration Schema
**File**: `config_loader.py`

**Changes**:
1. Add `roi_geojson_path: Optional[Path]` to `ModelConfig` dataclass
2. Update `ModelConfig.from_dict()` to:
   - Read `roi_geojson_path` from YAML (optional field)
   - Resolve path relative to config base path
   - Validate file exists if provided
   - Log ROI configuration

3. Update configuration logging to show ROI status per model

**Validation**:
- If `roi_geojson_path` is provided, file must exist
- File must be valid GeoJSON
- At least one polygon must be present

---

### Phase 2: Integration with Processing Pipeline

#### Step 2.1: Modify `RasterTiler` Class
**File**: `tiler.py`

**Changes**:
1. Add optional `pixel_bounds` parameter to `__init__`:
   ```python
   def __init__(self, image_path: Path, config: TilingConfig, pixel_bounds: Optional[Tuple[int, int, int, int]] = None):
   ```

2. If `pixel_bounds` provided:
   - Store as instance variable
   - Adjust `self.width` and `self.height` to cropped dimensions
   - Adjust `self.dataset` to cropped region (or use windowed reading)
   - Update `pixel_to_geo()` to account for offset

3. Modify `iter_tiles()` to:
   - Only generate tiles within pixel_bounds
   - Adjust tile offsets relative to original image (for coordinate conversion)

**Key Consideration**: 
- Tile offsets must remain in original image coordinate space
- `global_bounds` in `TileMetadata` must reference original image, not cropped region

#### Step 2.2: Modify `InferenceRunner.process()`
**File**: `inference_runner.py`

**Changes**:
1. **Before opening image with RasterTiler**:
   - For each model, check if ROI is configured
   - If ROI exists:
     - Open image with GDAL (read-only, for bounds extraction)
     - Load ROI polygons
     - Extract image geographic bounds
     - Check intersection
     - If no intersection: skip this model for this image
     - If intersection: calculate pixel bounds

2. **Create ROI filter instance**:
   ```python
   from .roi_filter import ROIFilter
   roi_filter = ROIFilter()
   ```

3. **Per-model ROI processing**:
   ```python
   for model_name, model_config in applicable_models.items():
       # Check if model has ROI configured
       if model_config.roi_geojson_path:
           # Load ROI polygons (may contain multiple polygons)
           roi_polygons = roi_filter.load_roi(model_config.roi_geojson_path)
           logger.info(f"Model '{model_name}': Loaded {len(roi_polygons)} ROI polygon(s)")
           
           # Get image bounds
           image_bounds = roi_filter.get_image_bounds(dataset)
           
           # Check intersection (unions all intersecting ROI polygons)
           intersection = roi_filter.compute_intersection(image_bounds, roi_polygons)
           
           if not intersection:
               # Skip this model - no intersection with any ROI
               logger.info(f"Image does not intersect ROI for model {model_name}, skipping")
               continue
           
           # Log if multiple ROIs were unioned
           intersecting_count = sum(1 for roi in roi_polygons if roi.intersects(image_bounds))
           if intersecting_count > 1:
               logger.info(f"Image intersects {intersecting_count} ROI polygons - unioning into single region")
           
           # Calculate pixel bounds from unioned intersection
           pixel_bounds = roi_filter.geographic_to_pixel_bounds(intersection, dataset)
           logger.info(f"Processing cropped region: {pixel_bounds} (from unioned ROI intersections)")
           
           # Process with cropped region (single output file)
       else:
           # No ROI - process full image (existing behavior)
           pixel_bounds = None
   ```

4. **Pass pixel_bounds to RasterTiler**:
   ```python
   tiler = RasterTiler(image_path, tile_config, pixel_bounds=pixel_bounds)
   ```

5. **Coordinate handling**:
   - All detections from cropped region must be converted back to original image coordinates
   - The `compute_global_obb()` function in `infer.py` already handles tile offsets correctly
   - Ensure pixel_to_geo uses original geotransform, not cropped

#### Step 2.3: Update `infer.py` Coordinate Conversion
**File**: `infer.py`

**Changes**:
1. Ensure `pixel_to_geo()` uses original dataset geotransform (not cropped)
2. `compute_global_obb()` should already work correctly if tile offsets are in original image space
3. No changes needed if RasterTiler maintains original coordinate system

**Verification**:
- Test that detections from cropped region overlay correctly on original image
- Verify coordinates in output GeoJSON match original image bounds

---

### Phase 3: Logging and Monitoring

#### Step 3.1: Add ROI Logging
**Files**: `inference_runner.py`, `roi_filter.py`

**Log messages**:
- ROI loaded successfully (number of polygons)
- Image bounds extracted
- Intersection check result (intersects/doesn't intersect)
- Pixel bounds calculated
- Model skipped due to no intersection
- Cropped region dimensions

**Example log output**:
```
[INFO] Model 'yolo_main': ROI configured from 'roi.geojson'
[INFO]   Loaded 2 ROI polygons from GeoJSON
[INFO]   Image bounds: Polygon with 4 points (EPSG:4326)
[INFO]   Checking intersection with 2 ROI polygons...
[INFO]   ROI 1: Intersects (partial overlap)
[INFO]   ROI 2: Intersects (partial overlap)
[INFO]   Unioning 2 intersecting ROI regions into single processing area
[INFO]   Intersection union: Polygon with 8 points (EPSG:4326)
[INFO]   Cropped region: (100, 200, 1800, 1900) pixels
[INFO]   Processing cropped region: 1700x1700 pixels (original: 2000x2000)
[INFO]   Output: Single GeoJSON file with detections from unioned ROI region
```

#### Step 3.2: Update Health Monitor
**File**: `health_monitor.py` (if needed)

**Optional**: Track ROI filtering statistics:
- Number of images filtered per model
- Average crop ratio (cropped area / original area)

---

### Phase 4: Testing and Validation

#### Step 4.1: Unit Tests
**File**: `test_roi_filter.py` (new)

**Test cases**:
1. Load valid GeoJSON with single polygon
2. Load GeoJSON with multiple polygons
3. Load invalid GeoJSON (should raise error)
4. Extract image bounds from image with projection
5. Extract image bounds from image without projection (should handle gracefully)
6. Intersection check: image fully inside ROI
7. Intersection check: image partially overlaps ROI
8. Intersection check: image outside ROI (no intersection)
9. **Multiple ROI intersection**: Image intersects 2 ROI polygons → verify union
10. **Multiple ROI intersection**: Image intersects 3 ROI polygons → verify union
11. **Multiple ROI intersection**: Image intersects 2 ROIs, one fully inside, one partial → verify union
12. **Multiple ROI intersection**: Image intersects 2 non-overlapping ROIs → verify union creates disconnected region (handled as bounding box)
13. CRS transformation: ROI in WGS84, image in UTM
14. Pixel bounds calculation accuracy
15. Coordinate conversion: cropped pixel → original image coordinates

#### Step 4.2: Integration Tests
**Test scenarios**:
1. Process image with ROI configured - should crop
2. Process image without ROI - should process full image (backward compatible)
3. Process image that doesn't intersect ROI - model should be skipped
4. **Process image intersecting 2 ROI polygons** - should union and process once, single output
5. **Process image intersecting 3+ ROI polygons** - should union all, single output
6. Process image with multiple models, some with ROI, some without
7. Verify output GeoJSON coordinates match original image
8. Verify detections overlay correctly on original image
9. **Verify single output file** when multiple ROIs intersect (not separate files per ROI)

#### Step 4.3: Performance Validation
**Metrics to measure**:
- Processing time reduction (cropped vs full image)
- GPU memory usage reduction
- Number of tiles generated (should be fewer)
- Accuracy: detections in cropped region match full image detections

---

## File Structure Changes

### New Files
```
inference_Script/
├── roi_filter.py          # New: ROI filtering and cropping logic
└── test_roi_filter.py     # New: Unit tests for ROI functionality
```

### Modified Files
```
inference_Script/
├── config_loader.py        # Add roi_geojson_path to ModelConfig
├── tiler.py                # Add pixel_bounds support
├── inference_runner.py     # Integrate ROI filtering before tiling
└── config/
    └── pipeline.yaml       # Add roi_geojson_path example
```

---

## Configuration Example

### Updated `pipeline.yaml`
```yaml
models:
  - name: "yolo_main"
    weights_path: "models/yolo_main.pt"
    type: "yolo"
    device: "cuda:0"
    confidence_threshold: 0.5
    roi_geojson_path: "config/roi_yolo_main.geojson"  # NEW: Optional ROI
    # ... rest of config ...
  
  - name: "yolo_obb"
    weights_path: "models/yolo_obb.pt"
    type: "yolo_obb"
    device: "cuda:0"
    confidence_threshold: 0.6
    # No ROI - processes full image (backward compatible)
    # ... rest of config ...
```

### Example ROI GeoJSON (Single ROI)
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-122.5, 37.7],
          [-122.3, 37.7],
          [-122.3, 37.9],
          [-122.5, 37.9],
          [-122.5, 37.7]
        ]]
      }
    }
  ]
}
```

### Example ROI GeoJSON (Multiple ROIs - Will Be Unioned)
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-122.5, 37.7],
          [-122.3, 37.7],
          [-122.3, 37.9],
          [-122.5, 37.9],
          [-122.5, 37.7]
        ]]
      }
    },
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-122.2, 37.6],
          [-122.0, 37.6],
          [-122.0, 37.8],
          [-122.2, 37.8],
          [-122.2, 37.6]
        ]]
      }
    }
  ]
}
```
**Note**: If an image intersects both polygons, they will be unioned into a single processing region. Output will be one GeoJSON file per image per model.

---

## Multiple ROI Intersection Behavior

### Scenario: Image Intersects Multiple ROI Polygons

When a single image intersects with multiple ROI polygons from the same model's GeoJSON file:

**Processing Flow**:
1. Load all ROI polygons from GeoJSON
2. Check which ROI polygons intersect with the image bounds
3. For each intersecting ROI:
   - Calculate intersection polygon: `Image ∩ ROI_i`
4. Union all intersection polygons: `Union(Image∩ROI1, Image∩ROI2, ..., Image∩ROI_n)`
5. Convert unioned polygon to pixel bounds (bounding box)
6. Crop image to unioned region
7. Process cropped region once
8. Output single GeoJSON file with all detections

**Visual Example**:
```
Original Image:  ████████████████████████ (2000x2000 pixels)
ROI 1:              ████ (intersects at pixels 200-800, 200-800)
ROI 2:                      ████ (intersects at pixels 1200-1800, 300-900)

Union Result:      ████████████ (union of both intersections)
Pixel Bounds:      (200, 200, 1800, 900)
Cropped Region:    Process this rectangular region
Output:            Single GeoJSON with detections from unioned region
```

**Key Points**:
- ✅ **Single processing run**: Unioned region processed once, not separately per ROI
- ✅ **Single output file**: One GeoJSON per image per model (existing structure maintained)
- ✅ **Efficient**: No duplicate processing of overlapping regions
- ✅ **Coordinates preserved**: All detections in original image coordinate space
- ✅ **Simple output structure**: No change to existing output file naming/organization

**Edge Case: Non-overlapping ROIs**:
If image intersects with 2 ROIs that don't overlap each other:
- Union creates disconnected region
- Use bounding box of union for cropping (rectangular crop)
- Process entire bounding box (may include small areas outside ROIs)
- Still single output file

---

## Implementation Order

1. **Phase 1**: Create `roi_filter.py` with core functionality
2. **Phase 1**: Update `config_loader.py` to support ROI configuration
3. **Phase 2**: Modify `RasterTiler` to accept pixel bounds
4. **Phase 2**: Integrate ROI filtering in `InferenceRunner.process()`
5. **Phase 3**: Add comprehensive logging
6. **Phase 4**: Write unit tests
7. **Phase 4**: Integration testing with real images
8. **Phase 4**: Performance validation

---

## Edge Cases and Error Handling

### Edge Cases
1. **ROI in different CRS than image**: Reproject ROI to image CRS
2. **Image without projection**: Log warning, skip ROI filtering for that image
3. **ROI outside image bounds**: No intersection, skip model
4. **ROI partially overlapping**: Process only intersection region
5. **Multiple ROI polygons intersecting image**: 
   - Union all intersecting ROI polygons into single processing region
   - Process unioned region once
   - Output single GeoJSON file with all detections from unioned region
   - Example: Image intersects ROI1 and ROI2 → Union(Image∩ROI1, Image∩ROI2) → Single cropped region → Single output
6. **Multiple non-overlapping ROIs intersecting image**:
   - Union creates potentially disconnected region
   - Use bounding box of union for cropping (rectangular crop)
   - Process entire bounding box area
7. **Invalid GeoJSON**: Raise clear error with file path
8. **Empty ROI polygons**: Skip or raise error

### Error Handling Strategy
- **ROI file not found**: Log error, skip ROI filtering, process full image
- **Invalid GeoJSON**: Log error, skip ROI filtering, process full image
- **CRS transformation failure**: Log warning, try to continue with original CRS
- **Intersection calculation failure**: Log error, skip ROI filtering, process full image

**Principle**: Fail gracefully - if ROI filtering fails, fall back to processing full image rather than failing the entire job.

---

## Performance Considerations

### Memory Efficiency
- Use GDAL virtual datasets (VRT) for cropping instead of loading full image
- Only load cropped region into memory
- Maintain original dataset handle for coordinate conversion

### Computational Efficiency
- ROI intersection check is fast (Shapely operations)
- Cropping reduces tile count significantly
- Fewer tiles = less GPU inference time
- Coordinate conversion overhead is minimal

### Expected Improvements
- **Tile count reduction**: 50-90% reduction depending on ROI size
- **Processing time**: Proportional to tile count reduction
- **GPU memory**: Reduced by cropped area ratio
- **Storage**: Same output size (detections, not image data)

---

## Dependencies

### New Python Packages
- `shapely` - For spatial operations (polygon intersection, etc.)
  - Already used in `infer.py` for IoU calculations, so likely already installed

### Existing Dependencies (No Changes)
- `gdal` - Already used
- `pyproj` - Already used
- `numpy` - Already used

---

## Backward Compatibility

### Guarantees
1. **No ROI configured**: Full image processing (existing behavior)
2. **ROI file missing**: Log warning, process full image
3. **ROI filtering fails**: Log error, process full image
4. **Output format**: Unchanged (GeoJSON, CSV)
5. **Coordinate system**: Unchanged (outputs in original image coordinates)

### Migration Path
- Existing configurations continue to work without changes
- ROI is opt-in feature
- No breaking changes to API or configuration schema

---

## Success Criteria

1. ✅ ROI GeoJSON can be configured per model
2. ✅ Images are filtered based on ROI intersection
3. ✅ Only intersecting region is processed (cropped)
4. ✅ **Multiple ROI polygons are unioned into single processing region**
5. ✅ **Single output file per image per model** (even with multiple ROIs)
6. ✅ Output coordinates are in original image space
7. ✅ Detections overlay correctly on original image
8. ✅ Backward compatible (no ROI = full image processing)
9. ✅ Significant reduction in processing time for cropped regions
10. ✅ Comprehensive error handling and logging
11. ✅ Unit tests pass (including multiple ROI scenarios)
12. ✅ Integration tests pass with real images

---

## Next Steps

Once plan is approved:
1. Create detailed technical design for `roi_filter.py`
2. Implement Phase 1 (core infrastructure)
3. Implement Phase 2 (integration)
4. Add logging and monitoring
5. Write and run tests
6. Performance validation
7. Documentation updates

