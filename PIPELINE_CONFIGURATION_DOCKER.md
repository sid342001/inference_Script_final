# Pipeline Configuration Guide for Docker

This guide explains how to configure the Satellite Inference Pipeline when running in Docker. All paths in this guide use Docker container paths (`/app/...`) which are automatically mapped to your host directories via volume mounts.

---

## Table of Contents

1. [Important Notes for Docker Users](#important-notes-for-docker-users)
2. [Configuration File Location](#configuration-file-location)
3. [Directory Paths (DO NOT CHANGE)](#directory-paths-do-not-change)
4. [Watcher Configuration](#watcher-configuration)
5. [Queue Configuration](#queue-configuration)
6. [Worker Configuration](#worker-configuration)
7. [Tiling Configuration](#tiling-configuration)
8. [GPU Configuration](#gpu-configuration)
9. [Model Configuration](#model-configuration)
10. [Adding New Models](#adding-new-models)
11. [Artifacts Configuration](#artifacts-configuration)
12. [Logging Configuration](#logging-configuration)
13. [Health Monitoring](#health-monitoring)
14. [Dashboard Configuration](#dashboard-configuration)
15. [Complete Example](#complete-example)

---

## Important Notes for Docker Users

### ⚠️ Directory Paths

**DO NOT CHANGE** the directory paths in `pipeline.yaml`. These paths are Docker container paths that are automatically mapped to your host directories via volume mounts in `docker-compose.windows.yml`.

**Container Path** → **Host Path Mapping**:
- `/app/data/incoming` → `docker_data/scheduled/` (on host)
- `/app/artifacts` → `docker_data/artifacts/` (on host)
- `/app/state` → `docker_data/state/` (on host)
- `/app/logs` → `docker_data/logs/` (on host)
- `/app/models` → `docker_data/models/` (on host)
- `/app/config` → `docker_data/config/` (on host)

**What You CAN Change**:
- ✅ Model names and confidence thresholds
- ✅ GPU device assignments
- ✅ Worker settings (batch size, concurrent jobs)
- ✅ Tiling parameters
- ✅ Folder identity filters
- ✅ Logging levels
- ✅ Dashboard settings

**What You CANNOT Change**:
- ❌ Directory paths (they are fixed Docker container paths)
- ❌ Volume mount mappings (change these in `docker-compose.yml` if needed)

---

## Configuration File Location

Your `pipeline.yaml` file should be located at:
```
docker_data/config/pipeline.yaml
```

This file is automatically mounted into the container at `/app/config/pipeline.yaml`.

**To edit the configuration**:
1. Edit `docker_data/config/pipeline.yaml` on your host machine
2. Restart the container:
   ```cmd
   docker-compose -f docker-compose.windows.yml restart
   ```

---

## Directory Paths (DO NOT CHANGE)

These paths are fixed and should not be modified. They are Docker container paths that map to your host directories.

### Input Directory
```yaml
watcher:
  input_dir: "/app/data/incoming"  # DO NOT CHANGE - maps to docker_data/scheduled/
```

**Host Location**: `docker_data/scheduled/`
- Place your input satellite images here
- The pipeline watches this directory for new files

### Output Directories
```yaml
artifacts:
  success_dir: "/app/artifacts/success"  # DO NOT CHANGE
  failure_dir: "/app/artifacts/failure"  # DO NOT CHANGE
  temp_dir: "/app/artifacts/tmp"  # DO NOT CHANGE
```

**Host Location**: `docker_data/artifacts/`
- Processed results appear here
- Organized by folder identity and image name

### State Directory
```yaml
queue:
  persistence_path: "/app/state/queue.json"  # DO NOT CHANGE
  quarantine_dir: "/app/state/quarantine"  # DO NOT CHANGE

workers:
  tile_cache_dir: "/app/state/tile_cache"  # DO NOT CHANGE
```

**Host Location**: `docker_data/state/`
- Queue state, cache, and quarantined jobs stored here

### Models Directory
```yaml
models:
  - weights_path: "/app/models/your-model.pt"  # DO NOT CHANGE path prefix
```

**Host Location**: `docker_data/models/`
- Place your model files (`.pt`) here
- Update only the filename in `weights_path`, keep `/app/models/` prefix

### Logs Directory
```yaml
logging:
  log_dir: "/app/logs/pipeline"  # DO NOT CHANGE
```

**Host Location**: `docker_data/logs/`
- Pipeline logs stored here

---

## Watcher Configuration

The watcher monitors the input directory for new satellite images and automatically enqueues them for processing.

```yaml
watcher:
  input_dir: "/app/data/incoming"  # DO NOT CHANGE - Docker container path
  recursive: true                  # ✅ CAN CHANGE: Watch subdirectories
  include_extensions: [".tif", ".tiff", ".jp2", ".img"]  # ✅ CAN CHANGE: File types to process
  settle_time_seconds: 10          # ✅ CAN CHANGE: Wait time before processing
  poll_interval_seconds: 30        # ✅ CAN CHANGE: How often to scan directory
  max_inflight_jobs: 32            # ✅ CAN CHANGE: Maximum jobs in queue
```

### Configurable Options

#### `recursive` (Optional)
- **Type**: Boolean
- **Description**: Whether to watch subdirectories recursively
- **Default**: `true`
- **Recommendation**: Set to `true` if images are organized in subfolders

#### `include_extensions` (Optional)
- **Type**: List of strings
- **Description**: File extensions to process (case-insensitive)
- **Example**: `[".tif", ".tiff", ".jp2", ".img", ".geotiff"]`
- **Default**: `[".tif", ".tiff"]`
- **Note**: Extensions should start with a dot (`.`)

#### `settle_time_seconds` (Optional)
- **Type**: Integer
- **Description**: Minimum time (in seconds) a file must exist before being checked
- **Purpose**: Ensures files are completely copied before processing
- **Default**: `10`
- **Recommendations**:
  - **Small files (<1GB)**: `5-10` seconds
  - **Medium files (1-10GB)**: `10-20` seconds
  - **Large files (>10GB)**: `20-30` seconds

#### `poll_interval_seconds` (Optional)
- **Type**: Integer
- **Description**: How often (in seconds) to scan the directory for new files
- **Default**: `30`
- **Recommendations**:
  - **Fast detection needed**: `10-15` seconds
  - **General use**: `30` seconds
  - **Low CPU priority**: `60` seconds

#### `max_inflight_jobs` (Optional)
- **Type**: Integer
- **Description**: Maximum number of jobs allowed in queue (pending + processing)
- **Default**: `32`
- **Recommendations**:
  - **Low volume**: `16-32`
  - **Medium volume**: `32-64`
  - **High volume**: `64-128`

#### `folder_identities` (Optional)
- **Type**: List of strings
- **Description**: List of folder names or regex patterns to process
- **Purpose**: Filter which images to process based on their parent folder
- **Example**: `["carto", "maxar", "qgis", "SAR"]` or `["project_.*", "test_.*"]`
- **Default**: `None` (processes all folders)
- **Important**: Images placed directly in `input_dir` get folder identity `"root"`

**Example**:
```yaml
watcher:
  input_dir: "/app/data/incoming"  # DO NOT CHANGE
  folder_identities: ["carto", "maxar", "qgis", "SAR"]  # ✅ CAN CHANGE
```

---

## Queue Configuration

Manages the job queue, retries, and failed job handling.

```yaml
queue:
  persistence_path: "/app/state/queue.json"  # DO NOT CHANGE
  max_retries: 3                               # ✅ CAN CHANGE: Retry attempts
  retry_backoff_seconds: 60                  # ✅ CAN CHANGE: Wait between retries
  quarantine_dir: "/app/state/quarantine"    # DO NOT CHANGE
```

### Configurable Options

#### `max_retries` (Optional)
- **Type**: Integer
- **Description**: Maximum number of retry attempts for failed jobs
- **Default**: `3`
- **Recommendations**:
  - **Transient errors expected**: `3-5` retries
  - **Stable environment**: `1-2` retries
  - **No retries**: `0`

#### `retry_backoff_seconds` (Optional)
- **Type**: Integer
- **Description**: Time to wait (in seconds) before retrying a failed job
- **Default**: `60`
- **Recommendations**:
  - **Quick retries**: `30-60` seconds
  - **Network/file issues**: `60-120` seconds

---

## Worker Configuration

Controls how images are processed, including parallelism and GPU usage.

```yaml
workers:
  max_concurrent_jobs: 4                  # ✅ CAN CHANGE: Parallel jobs
  batch_size: 4                            # ✅ CAN CHANGE: Tiles per batch
  tile_cache_dir: "/app/state/tile_cache"  # DO NOT CHANGE
  hybrid_mode: true                        # ✅ CAN CHANGE: Hybrid GPU mode
  gpu_balancing_strategy: "least_busy"     # ✅ CAN CHANGE: GPU balancing
  job_timeout_seconds: 3600                # ✅ CAN CHANGE: Max time per job
```

### Configurable Options

#### `max_concurrent_jobs` (Optional)
- **Type**: Integer
- **Description**: Maximum number of images processed simultaneously
- **Default**: `4`
- **Recommendations**:
  - **Single GPU**: `2-4` jobs
  - **Multiple GPUs**: `4-8` jobs
  - **High-end GPUs**: `8-16` jobs



#### `hybrid_mode` (Optional)
- **Type**: Boolean
- **Description**: Enable hybrid GPU mode (load all models on all GPUs)
- **Default**: `false`
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

#### `job_timeout_seconds` (Optional)
- **Type**: Integer
- **Description**: Maximum time (in seconds) a job can run before being killed


---

## Tiling Configuration

Controls how large satellite images are split into tiles for processing.

```yaml
tiling:
  tile_size: 512                           # ✅ CAN CHANGE: Tile size in pixels
  overlap: 256                             # ✅ CAN CHANGE: Overlap between tiles
  normalization_mode: "auto"               # ✅ CAN CHANGE: Pixel normalization
  allow_resample: true                     # ✅ CAN CHANGE: Allow resampling
  iou_threshold: 0.8                       # ✅ CAN CHANGE: IoU threshold for NMS
  ioma_threshold: 0.75                     # ✅ CAN CHANGE: IoMA threshold for NMS
```

**Note**: This is the **global default** tiling configuration. Individual models can override these settings using per-model `tile:` configuration (see [Model Configuration](#model-configuration)).

### Configurable Options

#

#### `iou_threshold` (Optional)
- **Type**: Float
- **Description**: Intersection over Union threshold for cross-tile Non-Maximum Suppression
- **Range**: `0.0` to `1.0`
- **Default**: `0.8`
- **Purpose**: Removes duplicate detections from overlapping tiles

#### `ioma_threshold` (Optional)
- **Type**: Float
- **Description**: Intersection over Minimum Area threshold for cross-tile NMS
- **Range**: `0.0` to `1.0`
- **Default**: `0.75`

---

## GPU Configuration

Defines available GPUs for processing.

```yaml
gpus:
  - id: "gpu0"              # ✅ CAN CHANGE: Human-readable ID
    device: "cuda:0"        # ✅ CAN CHANGE: PyTorch device
  - id: "gpu1"              # ✅ CAN CHANGE: Add more GPUs
    device: "cuda:1"        # ✅ CAN CHANGE
```

### Configurable Options

#### `id` (Optional)
- **Type**: String
- **Description**: Human-readable identifier for the GPU
- **Example**: `"gpu0"`, `"primary_gpu"`, `"rtx3090"`
- **Purpose**: Makes logs and monitoring more readable

#### `device` (Required)
- **Type**: String
- **Description**: PyTorch device identifier
- **Options**: `"cuda:0"`, `"cuda:1"`, `"cpu"`
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
  - name: "Yolo_plane_x"                    # ✅ CAN CHANGE: Model name
    weights_path: "/app/models/Yolo_plane_x.pt"  # ✅ CAN CHANGE filename only
    type: "yolo"                            # ✅ CAN CHANGE: Model type
    device: "cuda:0"                        # ✅ CAN CHANGE: GPU assignment
    confidence_threshold: 0.5                # ✅ CAN CHANGE: Confidence threshold
    outputs:
      write_tile_previews: false            # ✅ CAN CHANGE: Save previews
      summary_csv: true                     # ✅ CAN CHANGE: Generate CSV
```

### Configurable Options

#### `name` (Required)
- **Type**: String
- **Description**: Unique name for the model
- **Example**: `"Yolo_plane_x"`, `"yolo_obb"`, `"aircraft_detector"`
- **Purpose**: Used in output filenames and logs

#### `weights_path` (Required)
- **Type**: String (path)
- **Description**: Path to model weights file (`.pt` file)
- **Format**: `/app/models/your-model.pt` (keep `/app/models/` prefix, change filename)
- **Important**: 
  - Place model file in `docker_data/models/` on host
  - Update only the filename, keep `/app/models/` prefix
  - Example: If file is `docker_data/models/my_model.pt`, use `/app/models/my_model.pt`

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

**Per-Model Tiling Options**:
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
    weights_path: "/app/models/model_512.pt"
    type: "yolo"
    # Model trained on 512px tiles
    tile:
      tile_size: 512
      overlap: 256
      iou_threshold: 0.8
      ioma_threshold: 0.75

  - name: "model_1024px"
    weights_path: "/app/models/model_1024.pt"
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

#### `folder_identities` (Optional)
- **Type**: List of strings
- **Description**: List of folder names or regex patterns this model should process
- **Purpose**: Filter which images this specific model processes based on folder identity
- **Example**: `["carto", "maxar"]` or `["project_.*"]` (regex pattern)
- **Default**: `None` (no filtering if `all_folders` is `false`)

**Example: Model-Specific Folder Filtering**
```yaml
models:
  - name: "aircraft_model"
    weights_path: "/app/models/aircraft.pt"
    type: "yolo"
    all_folders: false
    folder_identities: ["qgis", "SAR"]  # Only process qgis and SAR images
    confidence_threshold: 0.5

  - name: "general_model"
    weights_path: "/app/models/general.pt"
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

---

## Adding New Models

To add a new model to the pipeline:

### Step 1: Place Model File

1. Copy your model file (`.pt`) to the models directory on your host:
   ```cmd
   copy C:\path\to\your\model.pt docker_data\models\your_model.pt
   ```

### Step 2: Add Model Configuration

1. Open `docker_data/config/pipeline.yaml` in a text editor

2. Add a new model entry to the `models:` list:

   ```yaml
   models:
     # Existing models...
     
     # New model
     - name: "your_model_name"                    # Unique name
       weights_path: "/app/models/your_model.pt"  # Path in container
       type: "yolo"                                # "yolo" or "yolo_obb"
       device: "cuda:0"                           # GPU to use (or "cpu")
       confidence_threshold: 0.5                   # Confidence threshold
       
       # Optional: Per-model tiling (if model was trained on different tile size)
       tile:
         tile_size: 512                            # Match training tile size
         overlap: 256
         iou_threshold: 0.8
         ioma_threshold: 0.75
       
       # Optional: Folder filtering
       all_folders: false                         # Process all folders?
       folder_identities: ["carto", "maxar"]       # Or specific folders
       
       outputs:
         write_tile_previews: false
         summary_csv: true
   ```

### Step 3: Configure Model Settings

**Required Settings**:
- `name`: Choose a unique name (used in output filenames)
- `weights_path`: Use `/app/models/your-filename.pt` (match the filename you copied)
- `type`: `"yolo"` for standard boxes, `"yolo_obb"` for rotated boxes

**Important Settings**:
- `tile_size`: **MUST match the tile size used during model training**
- `confidence_threshold`: Adjust based on your needs (0.3-0.8 typical range)
- `folder_identities`: Configure which image sources this model should process

### Step 4: Restart Container

After adding the model configuration, restart the container:

```cmd
docker-compose -f docker-compose.windows.yml restart
```

### Step 5: Verify Model Loaded

Check the logs to verify the model loaded successfully:

```cmd
docker-compose -f docker-compose.windows.yml logs | findstr "your_model_name"
```

You should see messages like:
```
INFO: Loading model: your_model_name
INFO: Model loaded successfully: your_model_name
```

### Example: Adding Multiple Models

```yaml
models:
  - name: "aircraft_detector"
    weights_path: "/app/models/aircraft.pt"
    type: "yolo"
    confidence_threshold: 0.5
    tile:
      tile_size: 512
      overlap: 256
    folder_identities: ["qgis", "SAR"]

  - name: "ship_detector"
    weights_path: "/app/models/ships.pt"
    type: "yolo_obb"
    confidence_threshold: 0.6
    tile:
      tile_size: 1024
      overlap: 512
    folder_identities: ["carto", "maxar"]

  - name: "general_detector"
    weights_path: "/app/models/general.pt"
    type: "yolo"
    confidence_threshold: 0.5
    all_folders: true  # Process all folders
```

---

## Artifacts Configuration

Defines where outputs are saved. **DO NOT CHANGE** the directory paths.

```yaml
artifacts:
  success_dir: "/app/artifacts/success"  # DO NOT CHANGE
  failure_dir: "/app/artifacts/failure"  # DO NOT CHANGE
  temp_dir: "/app/artifacts/tmp"  # DO NOT CHANGE
  combined_inferences_dir: "/app/artifacts/combined_inferences"  # DO NOT CHANGE
  model_outputs_dir: "/app/artifacts/model_outputs"  # DO NOT CHANGE
  daily_logs_dir: "/app/artifacts/daily_logs"  # DO NOT CHANGE
  manifest_format: "json"  # ✅ CAN CHANGE: Format (currently only "json")
  preview_format: "png"   # ✅ CAN CHANGE: "png", "jpg", "jpeg"
```

### Configurable Options

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

### Output Structure

Outputs are organized in `docker_data/artifacts/` on your host:

```
artifacts/
├── success/                    # Successful job outputs
│   └── {folder_identity}/
│       └── {image_name}_{job_id}/
│           ├── {image_name}.tif          # Original image
│           ├── combined.geojson          # All detections combined
│           ├── {model_name}.geojson      # Per-model outputs
│           ├── {model_name}.csv          # Per-model summaries
│           └── {image_name}.log          # Processing log
├── failure/                    # Failed job outputs
├── combined_inferences/        # All combined GeoJSON files (flat)
├── model_outputs/             # All per-model outputs (flat)
└── daily_logs/                # Daily logs organized by date
```

---

## Logging Configuration

Controls logging behavior.

```yaml
logging:
  level: "INFO"                             # ✅ CAN CHANGE: Main log level
  log_dir: "/app/logs/pipeline"            # DO NOT CHANGE
  per_image_level: "DEBUG"                 # ✅ CAN CHANGE: Per-image log level
```

### Configurable Options

#### `level` (Optional)
- **Type**: String
- **Description**: Main pipeline log level
- **Options**: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`
- **Default**: `"INFO"`
- **Recommendations**:
  - **Production**: `"INFO"` or `"WARNING"`
  - **Debugging**: `"DEBUG"`

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
  heartbeat_path: "/app/artifacts/health/status.json"  # DO NOT CHANGE
  interval_seconds: 15                                    # ✅ CAN CHANGE: Update interval
```

### Configurable Options

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
  enabled: true                              # ✅ CAN CHANGE: Enable/disable
  host: "0.0.0.0"                            # ✅ CAN CHANGE: Host to bind
  port: 8093                                 # ✅ CANNOT CHANGE: Port number
```

### Configurable Options

#### `enabled` (Optional)
- **Type**: Boolean
- **Description**: Whether to enable the dashboard server
- **Default**: `true`
- **Options**: `true` or `false`

#### `host` (Optional)
- **Type**: String
- **Description**: Host to bind the dashboard server
- **Default**: `"0.0.0.0"` (all interfaces) - recommended for Docker
- **Options**:
  - `"0.0.0.0"`: Accessible from all network interfaces (recommended for Docker)
  - `"localhost"`: Only accessible from container itself
- **Note**: In Docker, use `"0.0.0.0"` to access from host machine

#### `port` (Optional)
- **Type**: Integer
- **Description**: Port number for dashboard server
- **Default**: `8093`
- **Note**: Must match the port mapping in `docker-compose.windows.yml`

### Accessing the Dashboard

Once enabled, access the dashboard at:
- **Local**: `http://localhost:8093`
- **Remote**: `http://<your-ip>:8093` (if host is `0.0.0.0`)

---

## Complete Example

Here's a complete example configuration for Docker:

```yaml
# Satellite Inference Pipeline Configuration - Docker
# All paths use Docker container paths (/app/...) - DO NOT CHANGE

# Directory to watch for new satellite images
watcher:
  input_dir: "/app/data/incoming"  # DO NOT CHANGE
  recursive: true
  include_extensions: [".tif", ".tiff", ".jp2", ".img"]
  settle_time_seconds: 10
  poll_interval_seconds: 30
  max_inflight_jobs: 32
  folder_identities: ["carto", "maxar", "qgis", "SAR"]

# Job queue configuration
queue:
  persistence_path: "/app/state/queue.json"  # DO NOT CHANGE
  max_retries: 3
  retry_backoff_seconds: 60
  quarantine_dir: "/app/state/quarantine"  # DO NOT CHANGE

# Worker configuration
workers:
  max_concurrent_jobs: 4
  batch_size: 4
  tile_cache_dir: "/app/state/tile_cache"  # DO NOT CHANGE
  hybrid_mode: true
  gpu_balancing_strategy: "least_busy"
  job_timeout_seconds: 3600

# Tiling configuration (global default)
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
    weights_path: "/app/models/Yolo_plane_x.pt"  # Update filename only
    type: "yolo"
    device: "cuda:0"
    confidence_threshold: 0.5
    all_folders: false
    folder_identities: ["qgis", "SAR"]
    # Per-model tiling (overrides global if specified)
    tile:
      tile_size: 512
      overlap: 256
      iou_threshold: 0.8
      ioma_threshold: 0.75
    outputs:
      write_tile_previews: false
      summary_csv: true

  - name: "yolo_obb"
    weights_path: "/app/models/yolo11n-obb.pt"  # Update filename only
    type: "yolo_obb"
    device: "cuda:1"
    confidence_threshold: 0.5
    all_folders: false
    folder_identities: ["carto", "maxar"]
    # Per-model tiling (different tile size)
    tile:
      tile_size: 1024
      overlap: 512
      iou_threshold: 0.75
      ioma_threshold: 0.7
    outputs:
      write_tile_previews: false
      summary_csv: true

# Artifacts (output) configuration
artifacts:
  success_dir: "/app/artifacts/success"  # DO NOT CHANGE
  failure_dir: "/app/artifacts/failure"  # DO NOT CHANGE
  temp_dir: "/app/artifacts/tmp"  # DO NOT CHANGE
  combined_inferences_dir: "/app/artifacts/combined_inferences"  # DO NOT CHANGE
  daily_logs_dir: "/app/artifacts/daily_logs"  # DO NOT CHANGE
  model_outputs_dir: "/app/artifacts/model_outputs"  # DO NOT CHANGE
  manifest_format: "json"
  preview_format: "png"

# Logging configuration
logging:
  level: "INFO"
  log_dir: "/app/logs/pipeline"  # DO NOT CHANGE
  per_image_level: "DEBUG"

# Health monitoring
health:
  heartbeat_path: "/app/artifacts/health/status.json"  # DO NOT CHANGE
  interval_seconds: 15

# Dashboard configuration
dashboard:
  enabled: true
  host: "0.0.0.0"  # Recommended for Docker
  port: 8092
```

---


