# Pipeline Configuration Guide (`pipeline.yaml`)

This guide explains every configuration option in `pipeline.yaml`, helping you customize the Satellite Inference Pipeline for your specific needs.

## Table of Contents

1. [Watcher Configuration](#watcher-configuration)
2. [Queue Configuration](#queue-configuration)
3. [Worker Configuration](#worker-configuration)
4. [Tiling Configuration](#tiling-configuration)
5. [GPU Configuration](#gpu-configuration)
6. [Model Configuration](#model-configuration)
7. [Artifacts Configuration](#artifacts-configuration)
8. [Logging Configuration](#logging-configuration)
9. [Health Monitoring](#health-monitoring)
10. [Dashboard Configuration](#dashboard-configuration)
11. [Complete Example](#complete-example)

---

## Watcher Configuration

The watcher monitors a directory for new satellite images and automatically enqueues them for processing.

```yaml
watcher:
  input_dir: "data/incoming"              # Directory to watch
  recursive: true                         # Watch subdirectories
  include_extensions: [".tif", ".tiff", ".jp2", ".img"]
  settle_time_seconds: 10                  # Wait for file to finish copying
  poll_interval_seconds: 30                # How often to scan directory
  max_inflight_jobs: 32                   # Maximum jobs in queue
```

### Options

#### `input_dir` (Required)
- **Type**: String (path)
- **Description**: Directory to watch for new satellite images
- **Example**: `"data/incoming"` or `"D:/satellite/images"`
- **Note**: Use forward slashes (`/`) even on Windows
- **Default**: None (must be specified)

#### `recursive` (Optional)
- **Type**: Boolean
- **Description**: Whether to watch subdirectories recursively
- **Options**: `true` or `false`
- **Default**: `true`
- **Recommendation**: Set to `true` if images are organized in subdirectories

#### `include_extensions` (Optional)
- **Type**: List of strings
- **Description**: File extensions to process (case-insensitive)
- **Example**: `[".tif", ".tiff", ".jp2", ".img", ".geotiff"]`
- **Default**: `[".tif", ".tiff"]`
- **Note**: Extensions should start with a dot (`.`)

#### `settle_time_seconds` (Optional)
- **Type**: Integer
- **Description**: Minimum time (in seconds) a file must exist before being checked for readiness
- **Purpose**: Ensures files are completely copied before processing
- **Default**: `10`
- **Recommendations**:
  - **Small files (<1GB)**: `5-10` seconds
  - **Medium files (1-10GB)**: `10-20` seconds
  - **Large files (>10GB)**: `20-30` seconds

#### `poll_interval_seconds` (Optional)
- **Type**: Integer
- **Description**: How often (in seconds) to scan the directory for new files
- **Purpose**: With non-blocking implementation, this determines detection latency
- **Default**: `15` (config loader), `30` (example)
- **Recommendations**:
  - **Fast detection needed**: `10-15` seconds
  - **General use**: `30` seconds
  - **Low CPU priority**: `60` seconds
- **Note**: Lower values = faster detection but slightly more CPU usage

#### `max_inflight_jobs` (Optional)
- **Type**: Integer
- **Description**: Maximum number of jobs allowed in queue (pending + processing)
- **Purpose**: Prevents queue from growing too large
- **Default**: `32`
- **Recommendations**:
  - **Low volume**: `16-32`
  - **Medium volume**: `32-64`
  - **High volume**: `64-128`

#### `folder_identities` (Optional)
- **Type**: List of strings
- **Description**: List of folder names or regex patterns to process. Only images from these folders will be enqueued.
- **Purpose**: Filter which images to process based on their parent folder
- **Example**: `["carto", "maxar", "qgis", "SAR"]` or `["project_.*", "test_.*"]` (regex patterns)
- **Default**: `None` (processes all folders)
- **Behavior**:
  - If `None` or empty: All folders are processed
  - If specified: Only images from matching folders are processed
  - Supports regex patterns for flexible matching
- **Important**: Images placed directly in `input_dir` (not in subfolders) get folder identity `"root"`

#### `folder_identity_regex` (Optional)
- **Type**: String (regex pattern)
- **Description**: Optional regex pattern to extract a custom folder identity from the file path
- **Purpose**: Extract folder identity from complex directory structures
- **Example**: `"incoming/([^/]+)/.*"` extracts the first folder name after `incoming/`
- **Default**: `None` (uses immediate parent folder name)
- **Note**: The first capturing group will be used as the identity. If no capturing groups, the entire match is used.

### Folder Identity Filtering

The watcher can filter images based on their parent folder's identity. This is useful when you want to:
- Process only specific image types
- Apply different models to different image sources
- Organize outputs by image source

#### How Folder Identity Works

1. **Extraction**: The watcher extracts a folder identity from each image's path:
   - If `folder_identity_regex` is set: Uses regex to extract identity from the path
   - Otherwise: Uses the immediate parent folder name relative to `input_dir`
   - If image is directly in `input_dir`: Returns `"root"`

2. **Matching**: The watcher checks if the extracted identity matches `folder_identities`:
   - If `folder_identities` is `None` or empty: All images are processed
   - If specified: Only images from matching folders are enqueued
   - Supports regex patterns in `folder_identities` for flexible matching

3. **Filtering**: Images that don't match are skipped (logged at DEBUG level)

#### Example: Images in Subfolders

```
incoming/
  ├── carto/
  │   └── image1.tif      # folder_identity = "carto"
  ├── maxar/
  │   └── image2.tif      # folder_identity = "maxar"
  └── qgis/
      └── image3.tif      # folder_identity = "qgis"
```

**Configuration**:
```yaml
watcher:
  folder_identities: ["carto", "maxar", "qgis"]
```

**Result**: All three images are processed (they match the folder identities).

#### Example: Images Directly in `incoming/`

```
incoming/
  ├── image1.tif          # folder_identity = "root"
  └── image2.tif          # folder_identity = "root"
```

**Configuration**:
```yaml
watcher:
  folder_identities: ["carto", "maxar", "qgis"]
```

**Result**: Images are **skipped** (not processed) because `"root"` doesn't match any configured folder identity.

#### Solutions for Processing Root-Level Images

**Option 1: Add "root" to folder identities**
```yaml
watcher:
  folder_identities: ["carto", "maxar", "qgis", "root"]
```

**Option 2: Remove folder filtering (process everything)**
```yaml
watcher:
  # folder_identities: ["carto", "maxar", "qgis"]  # Comment out or remove
```

**Option 3: Organize images in subfolders (recommended)**
```
incoming/
  ├── carto/
  │   └── image1.tif
  └── maxar/
      └── image2.tif
```

**Option 4: Use regex to extract custom identity**
```yaml
watcher:
  folder_identity_regex: "incoming/([^/]+)/.*"  # Extracts folder name
  folder_identities: ["carto", "maxar", "qgis", "root"]
```

#### Folder Identity and Model Filtering

Folder identity is also used by models to determine which images they should process. Each model can have its own `folder_identities` configuration to filter which images it processes. See [Model Configuration](#model-configuration) for details on `all_folders` and `folder_identities` options.

---

## Queue Configuration

Manages the job queue, retries, and failed job handling.

```yaml
queue:
  persistence_path: "state/queue.json"    # Queue state file
  max_retries: 3                           # Retry failed jobs 3 times
  retry_backoff_seconds: 60              # Wait 60s between retries
  quarantine_dir: "state/quarantine"      # Failed jobs go here
```

### Options

#### `persistence_path` (Required)
- **Type**: String (path)
- **Description**: File path where queue state is saved
- **Purpose**: Allows queue to persist across restarts
- **Example**: `"state/queue.json"`
- **Note**: Directory will be created automatically

#### `max_retries` (Optional)
- **Type**: Integer
- **Description**: Maximum number of retry attempts for failed jobs
- **Default**: `3`
- **Recommendations**:
  - **Transient errors expected**: `3-5` retries
  - **Stable environment**: `1-2` retries
  - **No retries**: `0` (fails immediately)

#### `retry_backoff_seconds` (Optional)
- **Type**: Integer
- **Description**: Time to wait (in seconds) before retrying a failed job
- **Default**: `60`
- **Purpose**: Gives time for transient issues to resolve
- **Recommendations**:
  - **Quick retries**: `30-60` seconds
  - **Network/file issues**: `60-120` seconds

#### `quarantine_dir` (Optional)
- **Type**: String (path)
- **Description**: Directory where permanently failed jobs are moved
- **Default**: `"state/quarantine"`
- **Purpose**: Isolates jobs that failed after all retries

---

## Worker Configuration

Controls how images are processed, including parallelism and GPU usage.

```yaml
workers:
  max_concurrent_jobs: 4                  # Process 4 images simultaneously
  batch_size: 4                            # Process 4 tiles per batch
  tile_cache_dir: "state/tile_cache"       # Tile cache directory
  hybrid_mode: true                        # Enable hybrid GPU mode
  gpu_balancing_strategy: "least_busy"     # GPU load balancing strategy
  job_timeout_seconds: 3600                # Max time per job (1 hour)
```

### Options

#### `max_concurrent_jobs` (Optional)
- **Type**: Integer
- **Description**: Maximum number of images processed simultaneously
- **Default**: `4`
- **Recommendations**:
  - **Single GPU**: `2-4` jobs
  - **Multiple GPUs**: `4-8` jobs
  - **High-end GPUs**: `8-16` jobs
- **Note**: Higher values = more parallelism but more GPU memory usage

#### `batch_size` (Optional)
- **Type**: Integer
- **Description**: Number of tiles processed in a single batch
- **Default**: `4`
- **Purpose**: Optimizes GPU utilization
- **Recommendations**:
  - **Small GPU memory**: `2-4`
  - **Medium GPU memory**: `4-8`
  - **Large GPU memory**: `8-16`
- **Note**: Higher batch size = faster processing but more memory

#### `tile_cache_dir` (Optional)
- **Type**: String (path)
- **Description**: Directory for caching processed tiles
- **Default**: `"state/tile_cache"`
- **Purpose**: Speeds up reprocessing of same images

#### `hybrid_mode` (Optional)
- **Type**: Boolean
- **Description**: Enable hybrid GPU mode (load all models on all GPUs)
- **Default**: `false`
- **Options**: `true` or `false`
- **Benefits**:
  - ✅ All models available on all GPUs
  - ✅ Dynamic job assignment to least busy GPU
  - ✅ Better GPU utilization
- **When to use**: Multiple GPUs with multiple models

#### `gpu_balancing_strategy` (Optional)
- **Type**: String
- **Description**: Strategy for assigning jobs to GPUs (only used in hybrid mode)
- **Options**:
  - `"least_busy"`: Assign to GPU with lowest utilization (recommended)
  - `"round_robin"`: Rotate through GPUs sequentially
  - `"least_queued"`: Assign to GPU with fewest queued jobs
- **Default**: `"least_busy"`
- **Recommendation**: Use `"least_busy"` for best performance

#### `job_timeout_seconds` (Optional)
- **Type**: Integer
- **Description**: Maximum time (in seconds) a job can run before being killed
- **Default**: `3600` (1 hour)
- **Purpose**: Prevents infinite hangs
- **Recommendations**:
  - **Small images**: `1800` (30 minutes)
  - **Medium images**: `3600` (1 hour)
  - **Very large images**: `7200` (2 hours)

---

## Tiling Configuration

Controls how large satellite images are split into tiles for processing.

**Note**: This is the **global default** tiling configuration. Individual models can override these settings using per-model `tile:` configuration (see [Model Configuration](#model-configuration)).

```yaml
tiling:
  tile_size: 512                           # Size of each tile in pixels
  overlap: 256                              # Overlap between tiles
  normalization_mode: "auto"                # Pixel value normalization
  allow_resample: true                      # Allow image resampling
  iou_threshold: 0.8                        # IoU threshold for NMS
  ioma_threshold: 0.75                      # IoMA threshold for NMS
```

**Per-Model Override**: Models can specify their own `tile:` configuration to override these global settings. This is essential when models were trained on different tile sizes.

### Options

#### `tile_size` (Optional)
- **Type**: Integer
- **Description**: Size of each tile in pixels (width and height)
- **Default**: `1024`
- **Recommendations**:
  - **YOLO models**: `512-1024` pixels
  - **High-resolution models**: `1024-2048` pixels
  - **Memory-constrained**: `256-512` pixels
- **Note**: Must be positive integer

#### `overlap` (Optional)
- **Type**: Integer
- **Description**: Overlap between tiles in pixels
- **Default**: `tile_size // 4` (25% of tile size)
- **Purpose**: Prevents edge artifacts and ensures objects at tile boundaries are detected
- **Recommendations**:
  - **Standard**: `tile_size // 4` (25% overlap)
  - **High precision**: `tile_size // 2` (50% overlap)
  - **Low overlap**: `tile_size // 8` (12.5% overlap)
- **Constraints**: Must be `0 <= overlap < tile_size`

#### `normalization_mode` (Optional)
- **Type**: String
- **Description**: How to normalize pixel values
- **Options**: `"auto"`, `"minmax"`, `"zscore"`, `"none"`
- **Default**: `"auto"`
- **Recommendations**: Use `"auto"` for most cases

#### `allow_resample` (Optional)
- **Type**: Boolean
- **Description**: Whether to allow resampling if image doesn't match tile size
- **Default**: `true`
- **Recommendation**: Keep `true` for flexibility

#### `iou_threshold` (Optional)
- **Type**: Float
- **Description**: Intersection over Union threshold for cross-tile Non-Maximum Suppression
- **Range**: `0.0` to `1.0`
- **Default**: `0.8`
- **Purpose**: Removes duplicate detections from overlapping tiles
- **Recommendations**:
  - **Strict deduplication**: `0.7-0.8`
  - **Moderate deduplication**: `0.8-0.9`
  - **Loose deduplication**: `0.9-1.0`

#### `ioma_threshold` (Optional)
- **Type**: Float
- **Description**: Intersection over Minimum Area threshold for cross-tile NMS
- **Range**: `0.0` to `1.0`
- **Default**: `0.75`
- **Purpose**: Additional deduplication metric for overlapping detections
- **Recommendation**: Keep at `0.75` unless you have specific needs

---

## GPU Configuration

Defines available GPUs for processing.

```yaml
gpus:
  - id: "gpu0"
    device: "cuda:0"
  - id: "gpu1"
    device: "cuda:1"
```

### Options

#### `id` (Optional)
- **Type**: String
- **Description**: Human-readable identifier for the GPU
- **Example**: `"gpu0"`, `"primary_gpu"`, `"rtx3090"`
- **Default**: Uses `device` value if not specified
- **Purpose**: Makes logs and monitoring more readable

#### `device` (Required)
- **Type**: String
- **Description**: PyTorch device identifier
- **Options**: `"cuda:0"`, `"cuda:1"`, `"cpu"`
- **Example**: `"cuda:0"` for first GPU, `"cuda:1"` for second GPU
- **Note**: Must match PyTorch's device naming

### Example: Single GPU
```yaml
gpus:
  - id: "gpu0"
    device: "cuda:0"
```

### Example: Multiple GPUs
```yaml
gpus:
  - id: "gpu0"
    device: "cuda:0"
  - id: "gpu1"
    device: "cuda:1"
  - id: "gpu2"
    device: "cuda:2"
```

### Example: CPU Fallback
```yaml
gpus:
  - id: "cpu"
    device: "cpu"
```

---

## Model Configuration

Defines YOLO models to use for inference.

```yaml
models:
  - name: "Yolo_plane_x"
    weights_path: "models/Yolo_plane_x.pt"
    type: "yolo"
    device: "cuda:0"
    confidence_threshold: 0.5
    outputs:
      write_tile_previews: false
      summary_csv: true
```

### Options

#### `name` (Required)
- **Type**: String
- **Description**: Unique name for the model
- **Example**: `"Yolo_plane_x"`, `"yolo_obb"`, `"aircraft_detector"`
- **Purpose**: Used in output filenames and logs

#### `weights_path` (Required)
- **Type**: String (path)
- **Description**: Path to model weights file (`.pt` file)
- **Example**: `"models/Yolo_plane_x.pt"`
- **Note**: Use forward slashes (`/`) even on Windows
- **Important**: Update this to your actual model path!

#### `type` (Required)
- **Type**: String
- **Description**: Model type
- **Options**:
  - `"yolo"`: Standard YOLO with axis-aligned bounding boxes
  - `"yolo_obb"`: YOLO with oriented bounding boxes (rotated boxes)
- **Example**: `"yolo"` or `"yolo_obb"`

#### `device` (Optional)
- **Type**: String
- **Description**: Which GPU to use (ignored in hybrid mode)
- **Example**: `"cuda:0"`, `"cuda:1"`, `"cpu"`
- **Default**: Uses first available GPU
- **Note**: In hybrid mode, all models are loaded on all GPUs

#### `confidence_threshold` (Optional)
- **Type**: Float
- **Description**: Minimum confidence score for detections
- **Range**: `0.0` to `1.0`
- **Default**: `0.5`
- **Recommendations**:
  - **High precision needed**: `0.6-0.8`
  - **Balanced**: `0.5`
  - **More detections**: `0.3-0.5`

#### `tile` (Optional)
- **Type**: Object (TilingConfig)
- **Description**: Per-model tiling configuration that overrides global tiling settings
- **Purpose**: Allows each model to use different tile sizes, overlaps, and NMS thresholds
- **When to use**: When models were trained on different tile sizes
- **Default**: Uses global `tiling` configuration if not specified

**Per-Model Tiling Options** (same as global tiling):
- `tile_size`: Model-specific tile size (must match training tile size)
- `overlap`: Model-specific overlap between tiles
- `normalization_mode`: Model-specific pixel normalization
- `allow_resample`: Whether to allow resampling
- `iou_threshold`: Model-specific IoU threshold for cross-tile NMS
- `ioma_threshold`: Model-specific IoMA threshold for cross-tile NMS

**Example**:
```yaml
models:
  - name: "model_512px"
    weights_path: "models/model_512.pt"
    type: "yolo"
    # Model trained on 512px tiles
    tile:
      tile_size: 512
      overlap: 256
      iou_threshold: 0.8
      ioma_threshold: 0.75

  - name: "model_1024px"
    weights_path: "models/model_1024.pt"
    type: "yolo"
    # Model trained on 1024px tiles
    tile:
      tile_size: 1024
      overlap: 512
      iou_threshold: 0.75
      ioma_threshold: 0.7
```

**Important**: Always match the tile size used during model training for optimal performance.

#### `all_folders` (Optional)
- **Type**: Boolean
- **Description**: If `true`, this model processes images from all folders, ignoring `folder_identities`
- **Default**: `false`
- **Purpose**: Allows a model to process all images regardless of folder identity
- **Example**: Set to `true` for a general-purpose model that should run on all images

#### `folder_identities` (Optional)
- **Type**: List of strings
- **Description**: List of folder names or regex patterns this model should process
- **Purpose**: Filter which images this specific model processes based on folder identity
- **Example**: `["carto", "maxar"]` or `["project_.*"]` (regex pattern)
- **Default**: `None` (no filtering if `all_folders` is `false`)
- **Behavior**:
  - If `all_folders: true`: This setting is ignored (model processes all folders)
  - If `all_folders: false` and `folder_identities` is empty/`None`: Model won't process any images
  - If `all_folders: false` and `folder_identities` is specified: Model only processes matching folders
- **Note**: Works in conjunction with watcher's `folder_identities` - both must allow the image

**Example: Model-Specific Folder Filtering**
```yaml
models:
  - name: "aircraft_model"
    weights_path: "models/aircraft.pt"
    type: "yolo"
    all_folders: false
    folder_identities: ["qgis", "SAR"]  # Only process qgis and SAR images
    confidence_threshold: 0.5

  - name: "general_model"
    weights_path: "models/general.pt"
    type: "yolo"
    all_folders: true  # Process all folders
    confidence_threshold: 0.5
```

#### `outputs` (Optional)
- **Type**: Object
- **Description**: Output configuration for this model

##### `write_tile_previews` (Optional)
- **Type**: Boolean
- **Description**: Whether to save preview images for each tile
- **Default**: `false`
- **Recommendation**: Set to `true` for debugging, `false` for production

##### `summary_csv` (Optional)
- **Type**: Boolean
- **Description**: Whether to generate CSV summary files
- **Default**: `true`
- **Recommendation**: Keep `true` for analysis

### Example: Multiple Models
```yaml
models:
  - name: "aircraft_detector"
    weights_path: "models/aircraft.pt"
    type: "yolo"
    device: "cuda:0"
    confidence_threshold: 0.5
    # Uses global tiling config (no per-model tile config)
    outputs:
      write_tile_previews: false
      summary_csv: true

  - name: "ship_detector"
    weights_path: "models/ships.pt"
    type: "yolo_obb"
    device: "cuda:1"
    confidence_threshold: 0.6
    # Per-model tiling config (overrides global)
    tile:
      tile_size: 1024        # Different tile size for this model
      overlap: 512
      iou_threshold: 0.75
      ioma_threshold: 0.7
    outputs:
      write_tile_previews: false
      summary_csv: true
```

### Example: Per-Model Tiling (Different Training Tile Sizes)
```yaml
# Global tiling (default for models without per-model config)
tiling:
  tile_size: 512
  overlap: 256

models:
  - name: "model_512px"
    weights_path: "models/model_512.pt"
    type: "yolo"
    # Uses global tiling (512px) - matches training
    confidence_threshold: 0.5

  - name: "model_1024px"
    weights_path: "models/model_1024.pt"
    type: "yolo"
    # Per-model tiling (1024px) - matches training
    tile:
      tile_size: 1024        # Must match training tile size
      overlap: 512
      iou_threshold: 0.8
      ioma_threshold: 0.75
    confidence_threshold: 0.5
```

---

## Artifacts Configuration

Defines where outputs are saved.

```yaml
artifacts:
  success_dir: "artifacts/success"         # Successful job outputs
  failure_dir: "artifacts/failure"         # Failed job outputs
  combined_dir: "artifacts/combined"       # DEPRECATED
  temp_dir: "artifacts/tmp"                # Temporary files
  per_image_log_dir: "artifacts/logs"      # DEPRECATED
  manifest_format: "json"                   # Manifest format
  preview_format: "png"                     # Preview image format
```

### Options

#### `success_dir` (Optional)
- **Type**: String (path)
- **Description**: Directory for successful job outputs
- **Default**: `"artifacts/success"`
- **Structure**: Each image gets its own folder with all outputs:
  ```
  artifacts/success/
    image1.tif/
      image1.tif              # Original image
      combined.geojson        # All detections combined
      Yolo_plane_x.geojson    # Per-model outputs
      Yolo_plane_x.csv        # Per-model summaries
      image1.log              # Processing log
  ```

#### `failure_dir` (Optional)
- **Type**: String (path)
- **Description**: Directory for failed job outputs
- **Default**: `"artifacts/failure"`
- **Structure**: Similar to success_dir, but contains error logs

#### `combined_dir` (Deprecated)
- **Type**: String (path)
- **Description**: ⚠️ **DEPRECATED** - Not used anymore
- **Note**: Combined GeoJSON files are now in `success_dir` per image

#### `temp_dir` (Optional)
- **Type**: String (path)
- **Description**: Directory for temporary files during processing
- **Default**: `"artifacts/tmp"`
- **Note**: Files are cleaned up after processing

#### `per_image_log_dir` (Deprecated)
- **Type**: String (path)
- **Description**: ⚠️ **DEPRECATED** - Not used anymore
- **Note**: Logs are now in `success_dir` or `failure_dir` per image

#### `combined_inferences_dir` (Optional)
- **Type**: String (path)
- **Description**: Directory containing all combined GeoJSON files from all processed images
- **Default**: `"artifacts/combined_inferences"`
- **Purpose**: Centralized location for all combined inference results
- **Structure**: Flat directory with `{image_stem}_combined.geojson` files

#### `daily_logs_dir` (Optional)
- **Type**: String (path)
- **Description**: Directory for daily logs organized by date
- **Default**: `"artifacts/daily_logs"`
- **Purpose**: Logs organized by date (YYYY-MM-DD) for easy review
- **Structure**: 
  ```
  daily_logs/
    YYYY-MM-DD/
      {image_stem}.log
  ```

#### `model_outputs_dir` (Optional)
- **Type**: String (path)
- **Description**: Directory containing all per-model outputs (GeoJSONs and CSVs) from all images
- **Default**: `"artifacts/model_outputs"`
- **Purpose**: Centralized location for all model-specific outputs
- **Structure**: Flat directory with `{image_stem}_{model_name}.geojson` and `{image_stem}_{model_name}.csv` files

#### `manifest_format` (Optional)
- **Type**: String
- **Description**: Format for manifest files
- **Options**: `"json"` (only option currently)
- **Default**: `"json"`

#### `preview_format` (Optional)
- **Type**: String
- **Description**: Format for preview images
- **Options**: `"png"`, `"jpg"`, `"jpeg"`
- **Default**: `"png"`
- **Recommendation**: Use `"png"` for quality, `"jpg"` for smaller files

---

## Logging Configuration

Controls logging behavior.

```yaml
logging:
  level: "INFO"                             # Main log level
  log_dir: "logs/pipeline"                  # Log directory
  per_image_level: "DEBUG"                  # Per-image log level
```

### Options

#### `level` (Optional)
- **Type**: String
- **Description**: Main pipeline log level
- **Options**: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`
- **Default**: `"INFO"`
- **Recommendations**:
  - **Production**: `"INFO"` or `"WARNING"`
  - **Debugging**: `"DEBUG"`

#### `log_dir` (Optional)
- **Type**: String (path)
- **Description**: Directory for main pipeline logs
- **Default**: `"logs/pipeline"`
- **Note**: Directory will be created automatically

#### `per_image_level` (Optional)
- **Type**: String
- **Description**: Log level for per-image logs
- **Options**: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`
- **Default**: `"DEBUG"`
- **Note**: Per-image logs are saved in `success_dir` or `failure_dir`

---

## Health Monitoring

Configures health monitoring and status reporting.

```yaml
health:
  heartbeat_path: "artifacts/health/status.json"  # Health status file
  interval_seconds: 15                              # Update interval
```

### Options

#### `heartbeat_path` (Optional)
- **Type**: String (path)
- **Description**: Path to health status JSON file
- **Default**: `"artifacts/health/status.json"`
- **Purpose**: Dashboard and monitoring tools read this file
- **Note**: Directory will be created automatically

#### `interval_seconds` (Optional)
- **Type**: Integer
- **Description**: How often (in seconds) to update health status
- **Default**: `30`
- **Recommendations**:
  - **Real-time monitoring**: `10-15` seconds
  - **General use**: `15-30` seconds
  - **Low priority**: `60` seconds

---

## Dashboard Configuration

Configures the web dashboard for monitoring.

```yaml
dashboard:
  enabled: true                              # Enable/disable dashboard
  host: "localhost"                          # Host to bind
  port: 8092                                 # Port number
```

### Options

#### `enabled` (Optional)
- **Type**: Boolean
- **Description**: Whether to enable the dashboard server
- **Default**: `true`
- **Options**: `true` or `false`

#### `host` (Optional)
- **Type**: String
- **Description**: Host to bind the dashboard server
- **Default**: `"localhost"`
- **Options**:
  - `"localhost"`: Only accessible from local machine
  - `"0.0.0.0"`: Accessible from all network interfaces
- **Recommendation**: Use `"localhost"` for security, `"0.0.0.0"` for remote access

#### `port` (Optional)
- **Type**: Integer
- **Description**: Port number for dashboard server
- **Default**: `8092`
- **Note**: Ensure port is not already in use

### Accessing the Dashboard

Once enabled, access the dashboard at:
- **Local**: `http://localhost:8092`
- **Remote**: `http://<your-ip>:8092` (if host is `0.0.0.0`)

---

## Complete Example

Here's a complete example configuration:

```yaml
# Satellite Inference Pipeline Configuration

# Directory to watch for new satellite images
watcher:
  input_dir: "data/incoming"
  recursive: true
  include_extensions: [".tif", ".tiff", ".jp2", ".img"]
  settle_time_seconds: 10
  poll_interval_seconds: 30
  max_inflight_jobs: 32

# Job queue configuration
queue:
  persistence_path: "state/queue.json"
  max_retries: 3
  retry_backoff_seconds: 60
  quarantine_dir: "state/quarantine"

# Worker configuration
workers:
  max_concurrent_jobs: 4
  batch_size: 4
  tile_cache_dir: "state/tile_cache"
  hybrid_mode: true
  gpu_balancing_strategy: "least_busy"
  job_timeout_seconds: 3600

# Tiling configuration
tiling:
  tile_size: 512
  overlap: 256
  normalization_mode: "auto"
  allow_resample: true
  iou_threshold: 0.8
  ioma_threshold: 0.75

# GPU configuration
gpus:
  - id: "gpu0"
    device: "cuda:0"
  - id: "gpu1"
    device: "cuda:1"

# Model configuration
models:
  - name: "Yolo_plane_x"
    weights_path: "models/Yolo_plane_x.pt"
    type: "yolo"
    device: "cuda:0"
    confidence_threshold: 0.5
    # Optional: Per-model tiling (overrides global if specified)
    # tile:
    #   tile_size: 512
    #   overlap: 256
    #   iou_threshold: 0.8
    #   ioma_threshold: 0.75
    outputs:
      write_tile_previews: false
      summary_csv: true

  - name: "yolo_obb"
    weights_path: "models/yolo11n-obb.pt"
    type: "yolo_obb"
    device: "cuda:1"
    confidence_threshold: 0.5
    # Optional: Per-model tiling (overrides global if specified)
    # tile:
    #   tile_size: 1024
    #   overlap: 512
    #   iou_threshold: 0.75
    #   ioma_threshold: 0.7
    outputs:
      write_tile_previews: false
      summary_csv: true

# Artifacts (output) configuration
artifacts:
  success_dir: "artifacts/success"
  failure_dir: "artifacts/failure"
  temp_dir: "artifacts/tmp"
  combined_inferences_dir: "artifacts/combined_inferences"  # All combined GeoJSON files
  daily_logs_dir: "artifacts/daily_logs"  # Daily logs organized by date
  model_outputs_dir: "artifacts/model_outputs"  # All per-model outputs
  manifest_format: "json"
  preview_format: "png"

# Logging configuration
logging:
  level: "INFO"
  log_dir: "logs/pipeline"
  per_image_level: "DEBUG"

# Health monitoring
health:
  heartbeat_path: "artifacts/health/status.json"
  interval_seconds: 15

# Dashboard configuration
dashboard:
  enabled: true
  host: "localhost"
  port: 8092
```

---

## Quick Reference: Common Configurations

### Single GPU, Single Model
```yaml
gpus:
  - id: "gpu0"
    device: "cuda:0"

models:
  - name: "my_model"
    weights_path: "models/my_model.pt"
    type: "yolo"
    device: "cuda:0"
    confidence_threshold: 0.5

workers:
  max_concurrent_jobs: 2
  hybrid_mode: false
```

### Multiple GPUs, Multiple Models (Hybrid Mode)
```yaml
gpus:
  - id: "gpu0"
    device: "cuda:0"
  - id: "gpu1"
    device: "cuda:1"

models:
  - name: "model1"
    weights_path: "models/model1.pt"
    type: "yolo"
    confidence_threshold: 0.5
  - name: "model2"
    weights_path: "models/model2.pt"
    type: "yolo_obb"
    confidence_threshold: 0.6

workers:
  max_concurrent_jobs: 8
  hybrid_mode: true
  gpu_balancing_strategy: "least_busy"
```

### High-Volume Processing
```yaml
watcher:
  poll_interval_seconds: 10
  max_inflight_jobs: 64

workers:
  max_concurrent_jobs: 8
  batch_size: 8
  job_timeout_seconds: 7200
```

### Debugging Configuration
```yaml
logging:
  level: "DEBUG"
  per_image_level: "DEBUG"

models:
  - name: "debug_model"
    outputs:
      write_tile_previews: true
      summary_csv: true
```

---

## Tips and Best Practices

1. **Paths**: Always use forward slashes (`/`) even on Windows
2. **Model Paths**: Update `weights_path` to your actual model file locations
3. **Tile Sizes**: Match tile sizes to your model's training configuration for optimal performance
4. **Per-Model Tiling**: Use per-model `tile:` config when models were trained on different tile sizes
5. **GPU Memory**: Adjust `batch_size` and `max_concurrent_jobs` based on GPU memory
6. **File Detection**: Reduce `poll_interval_seconds` for faster file detection
7. **Large Files**: Increase `settle_time_seconds` for very large files (>10GB)
8. **Hybrid Mode**: Enable `hybrid_mode: true` when using multiple GPUs
9. **Dashboard**: Set `host: "0.0.0.0"` to access dashboard from other machines
10. **Logging**: Use `DEBUG` level only when troubleshooting

---

## Troubleshooting

### Configuration Errors

**Error**: `ConfigError: watcher.input_dir is required`
- **Solution**: Add `input_dir` to `watcher` section

**Error**: `ConfigError: Model config missing keys: ['weights_path']`
- **Solution**: Add `weights_path` to model configuration

**Error**: `FileNotFoundError: models/Yolo_plane_x.pt`
- **Solution**: Update `weights_path` to correct model file location

### Performance Issues

**Slow file detection**:
- Reduce `poll_interval_seconds` to `10-15`

**High GPU memory usage**:
- Reduce `batch_size` to `2-4`
- Reduce `max_concurrent_jobs` to `2-4`

**Queue growing too large**:
- Increase `max_inflight_jobs` limit
- Increase `max_concurrent_jobs` to process faster

---

## Need Help?

- Check logs in `logs/pipeline/` directory
- Review health status in `artifacts/health/status.json`
- Access dashboard at `http://localhost:8092` (if enabled)
- See `HOW_TO_RUN.md` for setup instructions

