# Complete Application Analysis: Satellite Image Inference Pipeline

## Executive Summary

This is a **production-grade satellite image processing pipeline** that automatically detects objects in large geospatial imagery using YOLO (You Only Look Once) deep learning models. The system is designed for **headless, continuous operation** - it watches a directory for new satellite images, processes them automatically with multiple AI models in parallel, and outputs geospatial detection results in GeoJSON format.

---

## What This Application Is For

### Primary Purpose
**Automated object detection in satellite imagery** for geospatial analysis applications such as:
- **Maritime surveillance**: Detecting ships, boats, and vessels
- **Infrastructure monitoring**: Identifying buildings, vehicles, aircraft
- **Agricultural analysis**: Detecting crops, fields, equipment
- **Urban planning**: Mapping structures and development
- **Defense/intelligence**: Automated reconnaissance and monitoring

### Key Use Cases
1. **Batch Processing**: Process large volumes of satellite images automatically
2. **Real-time Monitoring**: Watch a folder and process images as they arrive
3. **Multi-Model Inference**: Run multiple specialized models on the same image
4. **Geospatial Output**: Generate GeoJSON files with precise geographic coordinates
5. **Production Deployment**: Designed for Docker containers and continuous operation

### Supported Image Formats
- **GeoTIFF** (.tif, .tiff)
- **JPEG 2000** (.jp2)
- **IMG** format
- **Cloud Optimized GeoTIFF (COG)**
- Supports **any projection system** (WGS84, UTM, custom projections)

### Supported Model Types
- **YOLO** (axis-aligned bounding boxes)
- **YOLO-OBB** (oriented bounding boxes for rotated objects)
- **Multiple models per image** (e.g., one for ships, one for aircraft)

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Satellite Image Inference Pipeline            │
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │   Watcher    │───▶│  Job Queue   │───▶│ Orchestrator  │    │
│  │ (File Watch) │    │  (Persistent)│    │  (Controller)  │    │
│  └──────────────┘    └──────────────┘    └──────────────┘    │
│                                 │                                │
│                                 ▼                                │
│                    ┌──────────────────────────┐                 │
│                    │   Worker Thread Pool     │                 │
│                    │  (CPU-based parallelism) │                 │
│                    │                          │                 │
│                    │  ┌────┐ ┌────┐ ┌────┐   │                 │
│                    │  │ W0 │ │ W1 │ │ W2 │   │                 │
│                    │  └────┘ └────┘ └────┘   │                 │
│                    └──────────────────────────┘                 │
│                                 │                                │
│                                 ▼                                │
│                    ┌──────────────────────────┐                 │
│                    │   Inference Runner        │                 │
│                    │  (Per Image Processing)  │                 │
│                    └──────────────────────────┘                 │
│                                 │                                │
│         ┌───────────────────────┼───────────────────────┐     │
│         ▼                       ▼                       ▼       │
│    ┌─────────┐          ┌─────────┐          ┌─────────┐      │
│    │  Tiler   │          │  Models  │          │   NMS   │      │
│    │(Split)   │          │ (YOLO)  │          │(Dedup)  │      │
│    └─────────┘          └─────────┘          └─────────┘      │
│                                 │                                │
│                                 ▼                                │
│                    ┌──────────────────────────┐                 │
│                    │   Output Generator       │                 │
│                    │  (GeoJSON, CSV, Logs)   │                 │
│                    └──────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

#### 1. **Image Watcher** (`watcher.py`)
- **Purpose**: Monitors input directory for new satellite images
- **Mechanism**: 
  - Uses `watchdog` library (event-based) or polling fallback
  - Detects file creation, movement, and completion
  - Handles Windows file copy operations (which emit move events)
- **Features**:
  - **File stability check**: Waits for file to finish copying (settle_time)
  - **Folder identity filtering**: Process images from specific folders only
  - **Extension filtering**: Only processes configured file types (.tif, .jp2, etc.)
  - **Recursive watching**: Can watch subdirectories
- **Output**: Enqueues ready images to Job Queue

#### 2. **Job Queue** (`job_queue.py`)
- **Purpose**: Persistent job management with retry logic
- **Features**:
  - **FIFO Queue**: First-in-first-out job processing
  - **Persistent State**: Saves queue to disk (survives restarts)
  - **Job States**: pending → processing → completed/failed
  - **Retry Logic**: Automatically retries failed jobs (configurable attempts)
  - **Quarantine**: Moves permanently failed jobs to quarantine folder
  - **Exponential Backoff**: Waits between retries (prevents hammering)
- **Storage**: JSON file at `state/queue.json`

#### 3. **Orchestrator** (`orchestrator.py`)
- **Purpose**: Main controller that coordinates all components
- **Responsibilities**:
  - Spawns and manages worker threads
  - Starts/stops watcher and health monitor
  - Handles job lifecycle (success/failure)
  - Manages file movement (incoming → success/failure)
  - Implements job timeouts (prevents infinite hangs)
- **Worker Management**: Creates `max_concurrent_jobs` worker threads

#### 4. **Worker Threads** (CPU-based parallelism)
- **Purpose**: Process images in parallel (CPU threads, not GPU-bound)
- **Mechanism**:
  - Each worker is a separate Python thread
  - Workers pull jobs from queue independently
  - Each worker processes **one image at a time**
  - Workers operate **in parallel** (true parallelism)
- **Configuration**: `workers.max_concurrent_jobs = 8` means 8 images processed simultaneously

#### 5. **Inference Runner** (`inference_runner.py`)
- **Purpose**: Executes the complete inference pipeline for a single image
- **Responsibilities**:
  - Image validation and CRS extraction
  - Model selection (based on folder identity)
  - Tiling (splitting large images into manageable tiles)
  - Batch inference (running models on tile batches)
  - Cross-tile NMS (removing duplicate detections)
  - Coordinate transformation (pixel → geographic coordinates)
  - Output generation (GeoJSON, CSV, logs)

#### 6. **Raster Tiler** (`tiler.py`)
- **Purpose**: Splits large satellite images into overlapping tiles
- **Mechanism**:
  - Uses GDAL to read geospatial rasters
  - Creates overlapping tiles (prevents edge artifacts)
  - Handles different band counts (1, 3, 4 channels)
  - Normalizes pixel values (0-1 range)
  - Tracks tile metadata (position, offsets, bounds)
- **Configuration**: 
  - `tile_size`: Size of each tile (e.g., 512px)
  - `overlap`: Overlap between tiles (e.g., 256px = 50% overlap)

#### 7. **GPU Load Balancer** (`gpu_balancer.py`)
- **Purpose**: Dynamically assigns jobs to GPUs for optimal utilization
- **Strategies**:
  - **least_busy**: Selects GPU with lowest utilization (recommended)
  - **round_robin**: Cycles through GPUs in order
  - **least_queued**: Selects GPU with fewest active jobs
- **Features**:
  - Tracks active jobs per GPU
  - Monitors GPU utilization (via pynvml or nvidia-smi)
  - Thread-safe job registration

#### 8. **Health Monitor** (`health_monitor.py`)
- **Purpose**: Publishes system health status for monitoring
- **Output**: JSON file with queue stats, worker status, GPU utilization
- **Update Frequency**: Every 15 seconds (configurable)
- **Use Case**: Dashboard integration, monitoring tools

---

## How Images Are Processed in Parallel

### Multi-Level Parallelism

The application implements **three levels of parallelism**:

#### Level 1: Worker Thread Parallelism (CPU)
- **Mechanism**: Multiple worker threads process different images simultaneously
- **Configuration**: `workers.max_concurrent_jobs = 8`
- **Example**: 8 images processed at the same time by 8 worker threads

```
Worker 0 → Image 1 → Processing...
Worker 1 → Image 2 → Processing...
Worker 2 → Image 3 → Processing...
Worker 3 → Image 4 → Processing...
Worker 4 → Image 5 → Processing...
Worker 5 → Image 6 → Processing...
Worker 6 → Image 7 → Processing...
Worker 7 → Image 8 → Processing...
```

#### Level 2: GPU Parallelism (Hybrid Mode)
- **Mechanism**: Multiple GPUs process different images simultaneously
- **Configuration**: `workers.hybrid_mode = true`
- **Example**: 2 GPUs can process 2 images at the same time

```
GPU 0 → Worker 0 (Image 1) → Model1 → Model2
GPU 1 → Worker 1 (Image 2) → Model1 → Model2
```

#### Level 3: Batch Parallelism (Within Image)
- **Mechanism**: Multiple tiles processed together in a batch
- **Configuration**: `workers.batch_size = 12`
- **Example**: 12 tiles processed simultaneously on GPU

```
Batch: [Tile1, Tile2, Tile3, ..., Tile12] → GPU → All processed together
```

### Complete Parallel Processing Flow

#### Scenario: 8 Images, 4 Workers, 2 GPUs, 2 Models

**Step 1: Images Arrive**
```
Input Directory:
  ├── image1.tif (arrives first)
  ├── image2.tif
  ├── image3.tif
  ├── image4.tif
  ├── image5.tif
  ├── image6.tif
  ├── image7.tif
  └── image8.tif (arrives last)
```

**Step 2: Watcher Enqueues Jobs**
```
Job Queue (FIFO):
  [Img1] → [Img2] → [Img3] → [Img4] → [Img5] → [Img6] → [Img7] → [Img8]
```

**Step 3: Workers Grab Jobs**
```
Worker 0 → Reserves Img1 → Processing...
Worker 1 → Reserves Img2 → Processing...
Worker 2 → Reserves Img3 → Processing...
Worker 3 → Reserves Img4 → Processing...
```

**Step 4: GPU Assignment (Hybrid Mode)**
```
Worker 0 (Img1):
  → GPU Balancer → Selects GPU0 (least busy)
  → Loads image, creates tiles
  → Batch 1: [Tile1-12] → GPU0 → Model1 → Detections
  → Batch 2: [Tile13-24] → GPU0 → Model1 → Detections
  → Batch 1: [Tile1-12] → GPU0 → Model2 → Detections
  → Batch 2: [Tile13-24] → GPU0 → Model2 → Detections
  → Cross-tile NMS (removes duplicates)
  → Convert to GeoJSON
  → Write outputs

Worker 1 (Img2):
  → GPU Balancer → Selects GPU1 (least busy)
  → [Same process on GPU1]

Worker 2 (Img3):
  → GPU Balancer → Selects GPU0 (least busy now)
  → [Same process on GPU0]

Worker 3 (Img4):
  → GPU Balancer → Selects GPU1 (least busy now)
  → [Same process on GPU1]
```

**Step 5: As Workers Complete**
```
Worker 0 finishes Img1:
  → Marks job complete
  → Moves image to success_dir
  → Returns to queue
  → Reserves Img5 → Processing...

Worker 1 finishes Img2:
  → Marks job complete
  → Moves image to success_dir
  → Returns to queue
  → Reserves Img6 → Processing...
```

**Result**: Continuous parallel processing until all images are done.

### Tile Processing Parallelism

Within each image, tiles are processed in **batches** for GPU efficiency:

```
Image: 2000×2000 pixels
Tile Size: 512px
Overlap: 256px
Stride: 256px

Tile Grid: 7 rows × 7 cols = 49 tiles total

Processing:
  Batch 1: Tiles [0-11] → GPU → Model1 → 12 detections
  Batch 2: Tiles [12-23] → GPU → Model1 → 12 detections
  Batch 3: Tiles [24-35] → GPU → Model1 → 12 detections
  Batch 4: Tiles [36-47] → GPU → Model1 → 12 detections
  Batch 5: Tiles [48] → GPU → Model1 → 1 detection
  
  Repeat for Model2...
  
  Total: 49 tiles processed in 5 batches
```

### GPU Utilization in Hybrid Mode

**Hybrid Mode** (recommended):
- All models loaded on all GPUs
- Each job assigned to least busy GPU
- All models for that job run on the same GPU
- Better GPU utilization and load balancing

```
Model Loading:
  Model1: Loaded on GPU0 ✓, GPU1 ✓
  Model2: Loaded on GPU0 ✓, GPU1 ✓

Job Assignment:
  Image 1 → GPU0 → Model1 → Model2
  Image 2 → GPU1 → Model1 → Model2
  Image 3 → GPU0 → Model1 → Model2
  Image 4 → GPU1 → Model1 → Model2
```

**Traditional Mode**:
- Each model assigned to specific GPU
- Less flexible, but simpler

```
Model Loading:
  Model1: Loaded on GPU0 only
  Model2: Loaded on GPU1 only

Job Assignment:
  Image 1 → GPU0 (Model1 only)
  Image 2 → GPU1 (Model2 only)
```

---

## Complete Processing Workflow

### End-to-End Flow for a Single Image

```
1. IMAGE ARRIVAL
   └─> Watcher detects new file in input_dir
       └─> Waits for file stability (settle_time_seconds)
           └─> Extracts folder identity
               └─> Enqueues to Job Queue with metadata

2. JOB QUEUE
   └─> Job created with status="pending"
       └─> Job persisted to disk (queue.json)
           └─> Job waits in FIFO queue

3. WORKER ASSIGNMENT
   └─> Worker thread checks queue
       └─> Reserves job (status="processing")
           └─> Worker now owns this job

4. FILE VALIDATION
   └─> Check file exists and is accessible
       └─> Verify file is ready (not locked, size stable)
           └─> Proceed to inference

5. INFERENCE RUNNER - INITIALIZATION
   └─> Open image with GDAL
       └─> Extract CRS/projection metadata
           └─> Validate CRS is valid
               └─> Create coordinate transformer (if needed)
                   └─> Filter models by folder identity
                       └─> Create per-model tilers

6. TILING
   └─> For each model (with its own tile config):
       └─> Calculate tile grid dimensions
           └─> Create overlapping tiles
               └─> Normalize pixel values
                   └─> Store tile metadata (position, bounds)

7. GPU ASSIGNMENT (Hybrid Mode)
   └─> GPU Balancer selects least busy GPU
       └─> Register job start on GPU
           └─> All models will run on this GPU

8. INFERENCE - MODEL PROCESSING
   └─> For each model:
       └─> For each tile batch:
           └─> Convert tiles to PyTorch tensors
               └─> Stack into batch tensor
                   └─> Move to GPU
                       └─> Run YOLO model inference
                           └─> Extract detections (boxes, classes, confidences)
                               └─> Filter by confidence threshold
                                   └─> Convert to global coordinates
                                       └─> Store in detection grid

9. CROSS-TILE NMS (Non-Maximum Suppression)
   └─> For each model independently:
       └─> Compare detections in adjacent tiles
           └─> Calculate IoU (Intersection over Union)
               └─> Calculate IoMA (Intersection over Min Area)
                   └─> If overlap > threshold:
                       └─> Keep detection with higher confidence
                           └─> Discard duplicate
                               └─> Continue for all tile pairs

10. COORDINATE TRANSFORMATION
    └─> For each remaining detection:
        └─> Convert pixel coordinates to geographic coordinates
            └─> Use GDAL geotransform
                └─> Transform to WGS84 (EPSG:4326) if needed
                    └─> Create GeoJSON polygon feature

11. OUTPUT GENERATION
    └─> Write per-model GeoJSON files
        └─> Write combined GeoJSON file
            └─> Write CSV summary files
                └─> Write processing log
                    └─> Copy to centralized directories
                        └─> Write manifest entry

12. JOB COMPLETION
    └─> Mark job as "completed" in queue
        └─> Move image to success_dir
            └─> Unregister job from GPU balancer
                └─> Worker returns to queue for next job
```

### Detailed Processing Steps

#### Step 1: Image Tiling
```python
# Example: 2000×2000 image, 512px tiles, 256px overlap
tiles_per_row = ceil((2000 - 256) / 256) = 7
tiles_per_col = ceil((2000 - 256) / 256) = 7
total_tiles = 7 × 7 = 49 tiles

# Each tile:
tile = image[start_y:start_y+512, start_x:start_x+512]
metadata = {
    row: 0-6,
    col: 0-6,
    offset_x: 0, 256, 512, 768, 1024, 1280, 1536
    offset_y: 0, 256, 512, 768, 1024, 1280, 1536
}
```

#### Step 2: Batch Inference
```python
# Batch size = 12
batch = [tile1, tile2, ..., tile12]
tensor = stack(batch)  # Shape: (12, 3, 512, 512)
tensor = tensor.to("cuda:0")

# Run model
results = model(tensor, imgsz=512)

# Extract detections
for result in results:
    boxes = result.boxes.xyxy  # Bounding boxes
    confidences = result.boxes.conf
    classes = result.boxes.cls
```

#### Step 3: Cross-Tile NMS
```python
# For each tile's detections:
for tile_row in range(7):
    for tile_col in range(7):
        detections = tile_detections[tile_row][tile_col]
        
        # Check adjacent tiles
        if tile_row < 6:  # Check tile below
            neighbor_detections = tile_detections[tile_row+1][tile_col]
            for det1 in detections:
                for det2 in neighbor_detections:
                    iou = calculate_iou(det1, det2)
                    if iou > 0.8:  # Threshold
                        # Keep higher confidence, discard other
                        if det1.confidence > det2.confidence:
                            mark_for_removal(det2)
                        else:
                            mark_for_removal(det1)
```

#### Step 4: Coordinate Transformation
```python
# Convert pixel coordinates to geographic
for detection in final_detections:
    world_coords = []
    for pixel_x, pixel_y in detection.polygon:
        # Use GDAL geotransform
        geo_x, geo_y = tiler.pixel_to_geo(pixel_x, pixel_y)
        
        # Transform to WGS84 if needed
        if transformer:
            lon, lat = transformer.transform(geo_x, geo_y)
        else:
            lon, lat = geo_x, geo_y
        
        world_coords.append([lon, lat])
    
    # Create GeoJSON feature
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [world_coords]
        },
        "properties": {
            "model": "Model1",
            "confidence": 0.85,
            "class": "ship"
        }
    }
```

---

## Key Features & Capabilities

### 1. **Automatic File Watching**
- Monitors directory for new images
- Handles file copying operations (Windows/Linux)
- Waits for file stability before processing
- Supports recursive directory watching

### 2. **Persistent Job Queue**
- Jobs survive application restarts
- Automatic retry with exponential backoff
- Quarantine for permanently failed jobs
- Job status tracking (pending/processing/completed/failed)

### 3. **Multi-Model Support**
- Run multiple YOLO models on same image
- Per-model configuration (tile size, confidence threshold)
- Folder-based model filtering
- Per-model and combined outputs

### 4. **Advanced Tiling**
- Overlapping tiles prevent edge artifacts
- Per-model tile configuration
- Automatic normalization
- Handles different band counts (1, 3, 4 channels)

### 5. **Cross-Tile NMS**
- Removes duplicate detections from overlapping tiles
- Uses IoU and IoMA thresholds
- Prefers non-edge detections
- Keeps higher confidence detections

### 6. **Geospatial Accuracy**
- Extracts CRS from image metadata
- Transforms coordinates to WGS84 (EPSG:4326)
- Handles any projection system
- Validates CRS before processing

### 7. **GPU Load Balancing**
- Dynamic GPU assignment (hybrid mode)
- Multiple balancing strategies
- Tracks GPU utilization
- Optimizes for multi-GPU setups

### 8. **Comprehensive Outputs**
- Per-model GeoJSON files
- Combined GeoJSON file
- CSV summaries
- Processing logs
- Tile previews (optional)
- Manifest files

### 9. **Error Handling**
- File validation before processing
- CRS validation
- Model loading error handling
- Job timeouts (prevents infinite hangs)
- Automatic retry for transient errors
- Quarantine for permanent failures

### 10. **Health Monitoring**
- Real-time status JSON
- Queue statistics
- Worker health
- GPU utilization
- Dashboard integration

---

## Configuration Impact on Parallelism

### Key Parameters

| Parameter | Default | Impact on Parallelism |
|-----------|---------|----------------------|
| `workers.max_concurrent_jobs` | 8 | Number of images processed simultaneously |
| `workers.batch_size` | 12 | Number of tiles processed per GPU batch |
| `workers.hybrid_mode` | true | Enables dynamic GPU assignment |
| `workers.gpu_balancing_strategy` | "least_busy" | How GPUs are selected |
| `tiling.tile_size` | 512 | Size of each tile (affects memory) |
| `tiling.overlap` | 256 | Overlap between tiles (affects duplicate removal) |

### Performance Tuning

**For Maximum Throughput:**
- Increase `max_concurrent_jobs` to match available GPUs × 2
- Increase `batch_size` if GPU memory allows
- Use `hybrid_mode = true` with `least_busy` strategy
- Use larger `tile_size` if GPU memory is abundant

**For Memory-Constrained Systems:**
- Reduce `max_concurrent_jobs`
- Reduce `batch_size`
- Reduce `tile_size`
- Use smaller overlap

**For Single GPU:**
- Set `max_concurrent_jobs = 2-4` (prevents GPU queue buildup)
- Use `hybrid_mode = false` (simpler)
- Optimize `batch_size` for GPU memory

---

## Output Structure

### Success Case
```
artifacts/success/
  {folder_identity}/
    {image_name}_{job_id}/
      ├── {image_name}_combined.geojson    # All models combined
      ├── {image_name}_model1.geojson      # Model1 detections
      ├── {image_name}_model2.geojson      # Model2 detections
      ├── {image_name}_model1.csv          # Model1 summary
      ├── {image_name}_model2.csv          # Model2 summary
      ├── {image_name}.log                 # Processing log
      ├── {image_name}.tif                 # Original image (moved)
      └── tiles/                           # Tile previews (if enabled)
          ├── model1/
          └── model2/

artifacts/combined_inferences/
  {image_name}_combined.geojson            # Centralized combined output

artifacts/model_outputs/
  {image_name}_model1.geojson              # Centralized per-model outputs
  {image_name}_model1.csv
  {image_name}_model2.geojson
  {image_name}_model2.csv
```

### Failure Case
```
artifacts/failure/
  {folder_identity}/
    {image_name}_{job_id}/
      ├── error.txt                        # Error message
      ├── {image_name}.log                 # Processing log
      └── {image_name}.tif                 # Original image (moved)
```

### GeoJSON Format
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [lon1, lat1],
          [lon2, lat2],
          [lon3, lat3],
          [lon4, lat4],
          [lon1, lat1]
        ]]
      },
      "properties": {
        "model": "Model1",
        "confidence": 0.85,
        "class": "ship",
        "box_type": "oriented",
        "tile_row": 2,
        "tile_col": 3
      }
    }
  ],
  "properties": {
    "total_detections": 42,
    "axis_aligned": 10,
    "oriented": 32
  }
}
```

---

## Technical Details

### Dependencies
- **PyTorch**: Deep learning framework
- **Ultralytics YOLO**: Object detection models
- **GDAL**: Geospatial raster processing
- **PyProj**: Coordinate system transformations
- **Shapely**: Geometric operations (NMS)
- **Watchdog**: File system monitoring
- **NumPy**: Numerical operations

### Supported Platforms
- **Windows**: Full support (with watchdog or polling)
- **Linux**: Full support (event-based watching)
- **Docker**: Full support (with volume mounts)
- **GPU**: NVIDIA CUDA (required for GPU acceleration)

### Performance Characteristics
- **Throughput**: Depends on GPU count, model complexity, image size
- **Latency**: Per-image processing time varies (minutes for large images)
- **Scalability**: Linear scaling with number of GPUs and workers
- **Memory**: GPU memory is primary constraint

---

## Summary

This application is a **sophisticated, production-ready satellite image processing pipeline** that:

1. **Automatically processes** satellite images as they arrive
2. **Runs multiple AI models** in parallel on the same image
3. **Utilizes multiple GPUs** efficiently with dynamic load balancing
4. **Processes multiple images** simultaneously using worker threads
5. **Handles large images** by tiling and batch processing
6. **Removes duplicates** using advanced cross-tile NMS
7. **Outputs geospatial data** in standard GeoJSON format
8. **Handles errors gracefully** with retries and quarantine
9. **Monitors system health** for operational visibility
10. **Survives restarts** with persistent job queue

The architecture is designed for **maximum throughput** while maintaining **reliability** and **flexibility** across different hardware configurations, from single-GPU workstations to multi-GPU servers.

