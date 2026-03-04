# Satellite Inference Pipeline - Architecture & Work Distribution Guide

## Table of Contents
1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Work Distribution](#work-distribution)
4. [GPU Modes](#gpu-modes)
5. [Processing Flow](#processing-flow)
6. [Example Scenarios](#example-scenarios)
7. [Performance Characteristics](#performance-characteristics)
8. [Configuration Impact](#configuration-impact)

---

## Overview

This pipeline processes satellite images using YOLO models for object detection. It supports:
- **Multi-worker parallel processing** (CPU threads)
- **Multi-GPU support** with dynamic load balancing
- **Multiple models** per image
- **Automatic job queuing** and retry mechanisms
- **Cross-tile NMS** for duplicate detection removal

---

## System Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator (Main Controller)            │
│  - Manages workers, queue, watcher, health monitor          │
│  - Coordinates all components                               │
└─────────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
    ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
    │Worker 0│    │Worker 1│    │Worker 2│    │Worker 3│
    │(Thread)│    │(Thread)│    │(Thread)│    │(Thread)│
    └────────┘    └────────┘    └────────┘    └────────┘
         │              │              │              │
         └──────────────┴──────────────┴──────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │   Job Queue     │
              │  (FIFO Queue)   │
              └─────────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │ InferenceRunner │
              │  (Per Worker)   │
              └─────────────────┘
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
    ┌────────┐    ┌────────┐    ┌────────┐
    │ Model1 │    │ Model2 │    │ ModelN │
    │  GPU0  │    │  GPU0  │    │  GPU0  │
    │  GPU1  │    │  GPU1  │    │  GPU1  │
    └────────┘    └────────┘    └────────┘
```

### Component Details

#### 1. **Orchestrator**
- Main entry point that coordinates all components
- Spawns worker threads (CPU-based)
- Manages lifecycle of watcher, queue, and health monitor
- Handles job failures and success

#### 2. **Image Watcher**
- Monitors input directory for new images
- Detects file creation/movement (cross-platform)
- Enqueues new images to job queue
- Handles file readiness checks (prevents processing incomplete files)

#### 3. **Job Queue**
- Persistent FIFO queue (saved to disk)
- Tracks job status: pending → processing → completed/failed
- Implements retry logic with exponential backoff
- Quarantines permanently failed jobs

#### 4. **Worker Threads**
- CPU threads (not GPU-bound)
- Each worker processes one image at a time
- Pulls jobs from queue when idle
- Runs all models on assigned GPU for that image

#### 5. **Inference Runner**
- Executes inference for a single image
- Manages model loading and GPU assignment
- Handles tiling, batching, and NMS
- Writes outputs (GeoJSON, CSV, logs)

#### 6. **GPU Load Balancer**
- Tracks GPU utilization and active jobs
- Selects optimal GPU for each job
- Strategies: least_busy, round_robin, least_queued

---

## Work Distribution

### Worker Distribution (CPU Threads)

**Configuration**: `workers.max_concurrent_jobs = 4`

- **4 worker threads** are spawned at startup
- Each worker is a **separate CPU thread** (not GPU-bound)
- Workers operate **independently** and in **parallel**
- Each worker processes **one image at a time**

```
Worker Thread Lifecycle:
┌─────────────────────────────────────────┐
│ 1. Check queue for pending jobs         │
│ 2. Reserve a job (mark as processing)  │
│ 3. Process image (all models)          │
│ 4. Mark job as complete                 │
│ 5. Return to step 1                     │
└─────────────────────────────────────────┘
```

### Job Queue Distribution

**FIFO (First-In-First-Out) Queue**

- Images are enqueued as they arrive in the input directory
- Workers pull jobs in **chronological order** (oldest first)
- Queue state is **persisted to disk** (survives restarts)
- Maximum queue size: `watcher.max_inflight_jobs` (default: 32)

```
Queue Example:
[Img1] → [Img2] → [Img3] → [Img4] → [Img5] → [Img6] → [Img7] → [Img8]
  ↑                                                              ↑
Oldest                                                         Newest
```

### GPU Distribution

#### Hybrid Mode (Recommended)

**Configuration**: `workers.hybrid_mode = true`

**Model Loading**:
- All models are loaded on **all available GPUs**
- Example: 2 models × 2 GPUs = **4 model instances**

```
Model Distribution (Hybrid Mode):
┌─────────┬─────────┬─────────┐
│         │  GPU0   │  GPU1   │
├─────────┼─────────┼─────────┤
│ Model1  │    ✓    │    ✓    │
│ Model2  │    ✓    │    ✓    │
└─────────┴─────────┴─────────┘
```

**GPU Assignment (Per Job)**:
- When a worker picks up an image:
  1. GPU balancer selects the **least busy GPU**
  2. **All models** run on that **same GPU** for that image
  3. Models run **sequentially** (not in parallel)

```
Job Processing (Hybrid Mode):
Worker 0 picks Img1:
  → GPU Balancer selects GPU0 (least busy)
  → Run Model1 on GPU0
  → Run Model2 on GPU0
  → Complete Img1

Worker 1 picks Img2:
  → GPU Balancer selects GPU1 (least busy)
  → Run Model1 on GPU1
  → Run Model2 on GPU1
  → Complete Img2
```

#### Traditional Mode

**Configuration**: `workers.hybrid_mode = false`

**Model Loading**:
- Each model is loaded on its **assigned GPU** (from config)
- Example: Model1 → GPU0, Model2 → GPU1

```
Model Distribution (Traditional Mode):
┌─────────┬─────────┬─────────┐
│         │  GPU0   │  GPU1   │
├─────────┼─────────┼─────────┤
│ Model1  │    ✓    │    ✗    │
│ Model2  │    ✗    │    ✓    │
└─────────┴─────────┴─────────┘
```

**GPU Assignment**:
- Each model always runs on its assigned GPU
- No dynamic load balancing
- Less flexible but simpler

---

## Processing Flow

### Complete Image Processing Pipeline

```
1. Image Arrives
   └─> Watcher detects file
       └─> Enqueue to Job Queue

2. Worker Picks Job
   └─> Reserve job (mark as processing)
       └─> Check file readiness
           └─> Proceed to inference

3. Inference Runner (Per Image)
   ├─> Select GPU (hybrid mode) or use assigned GPU
   ├─> Load image with GDAL
   ├─> Extract CRS/projection
   ├─> Create tiler (split into tiles)
   │
   ├─> For each tile batch:
   │   ├─> Convert tiles to tensors
   │   ├─> Run Model1 on GPU
   │   ├─> Run Model2 on GPU
   │   └─> Collect detections
   │
   ├─> Apply cross-tile NMS
   │   ├─> Remove duplicate detections
   │   └─> Keep best detections
   │
   ├─> Convert to GeoJSON features
   ├─> Write outputs:
   │   ├─> {image}_combined.geojson
   │   ├─> {image}_model1.geojson
   │   ├─> {image}_model2.geojson
   │   ├─> {image}_model1.csv
   │   ├─> {image}_model2.csv
   │   └─> {image}.log
   │
   └─> Move image to success_dir

4. Job Complete
   └─> Mark job as completed
       └─> Worker returns to queue for next job
```

### Tile Processing Details

**Tiling Strategy**:
- Large images are split into overlapping tiles
- Tile size: `tiling.tile_size` (default: 512px)
- Overlap: `tiling.overlap` (default: 256px, prevents edge artifacts)
- Stride: `tile_size - overlap` (default: 256px)

**Batching**:
- Tiles are processed in batches
- Batch size: `workers.batch_size` (default: 4)
- All tiles in a batch are processed together on GPU

**Example**: 2000×2000 image with 512px tiles, 256px overlap
- Tiles per row: `ceil((2000 - 256) / 256) = 7`
- Tiles per column: `ceil((2000 - 256) / 256) = 7`
- Total tiles: 7 × 7 = **49 tiles**
- Batches: `ceil(49 / 4) = 13 batches`

---

## Example Scenarios

### Scenario 1: 8 Images, 4 Workers, 2 GPUs, 2 Models (Hybrid Mode)

**Initial Setup**:
```
Queue: [Img1, Img2, Img3, Img4, Img5, Img6, Img7, Img8]
Workers: [W0, W1, W2, W3] (all idle)
GPUs: [GPU0, GPU1] (both idle)
Models: [Model1, Model2] (both loaded on both GPUs)
```

**Step 1: Workers Grab First 4 Images**
```
Worker 0 → Img1 → GPU Balancer → GPU0 → [Model1, Model2] on GPU0
Worker 1 → Img2 → GPU Balancer → GPU1 → [Model1, Model2] on GPU1
Worker 2 → Img3 → GPU Balancer → GPU0 → [Model1, Model2] on GPU0
Worker 3 → Img4 → GPU Balancer → GPU1 → [Model1, Model2] on GPU1

Queue: [Img5, Img6, Img7, Img8] (waiting)
```

**Step 2: Processing Timeline**
```
Time T0:
  GPU0: W0(Img1) - Model1 → Model2
  GPU1: W1(Img2) - Model1 → Model2

Time T1 (W0 finishes Img1):
  GPU0: W2(Img3) - Model1 → Model2
  GPU1: W1(Img2) - Model1 → Model2 (still processing)
  W0 → Grabs Img5 → GPU Balancer → GPU0 → [Model1, Model2] on GPU0

Time T2 (W1 finishes Img2):
  GPU0: W0(Img5) - Model1 → Model2
  GPU1: W3(Img4) - Model1 → Model2
  W1 → Grabs Img6 → GPU Balancer → GPU1 → [Model1, Model2] on GPU1
```

**Result**:
- 4 images processed simultaneously
- GPUs dynamically balanced
- Remaining 4 images wait in queue
- As workers finish, they grab next image

### Scenario 2: 1 Image, 4 Workers, 2 GPUs, 2 Models (Hybrid Mode)

**Setup**:
```
Queue: [Img1]
Workers: [W0, W1, W2, W3]
```

**Execution**:
```
Worker 0 → Img1 → GPU0 → [Model1, Model2] on GPU0
Workers 1, 2, 3 → Idle (no jobs in queue)
```

**Result**:
- Only 1 worker active
- Other workers wait for new jobs
- GPU1 remains idle

### Scenario 3: 8 Images, 4 Workers, 1 GPU, 2 Models (Hybrid Mode)

**Setup**:
```
Queue: [Img1, Img2, Img3, Img4, Img5, Img6, Img7, Img8]
Workers: [W0, W1, W2, W3]
GPU: [GPU0] (single GPU)
```

**Execution**:
```
All workers compete for GPU0:
  Worker 0 → Img1 → GPU0 → [Model1, Model2]
  Worker 1 → Img2 → GPU0 → [Model1, Model2] (waits for GPU0)
  Worker 2 → Img3 → GPU0 → [Model1, Model2] (waits for GPU0)
  Worker 3 → Img4 → GPU0 → [Model1, Model2] (waits for GPU0)
```

**Result**:
- GPU becomes bottleneck
- Workers queue up for GPU access
- Lower throughput than multi-GPU setup

---

## Performance Characteristics

### Throughput

**Maximum Parallelism**:
- **Workers**: Up to `max_concurrent_jobs` images processed simultaneously
- **GPUs**: Each GPU processes one image at a time (per worker)
- **Models**: Run sequentially on the assigned GPU (not in parallel)

**Effective Throughput**:
```
Throughput = (Number of Images) / (Time per Image / Number of Workers)

Example:
- 8 images
- 2 minutes per image
- 4 workers
- Throughput = 8 / (2 / 4) = 16 minutes total
```

### GPU Utilization

**Hybrid Mode**:
- GPUs are dynamically assigned based on load
- Better load balancing across GPUs
- Higher GPU utilization
- Models can run on any GPU

**Traditional Mode**:
- Fixed GPU assignment per model
- May have GPU imbalance
- Lower flexibility
- Simpler configuration

### Bottlenecks

**Potential Bottlenecks**:
1. **GPU Memory**: Large images or many models may exceed GPU memory
2. **GPU Compute**: Slow models or large batches
3. **I/O**: Reading/writing large image files
4. **CPU**: Tiling and post-processing

**Optimization Tips**:
- Increase `batch_size` for better GPU utilization (if memory allows)
- Reduce `tile_size` if GPU memory is limited
- Use more workers if I/O-bound
- Use more GPUs if compute-bound

---

## Configuration Impact

### Key Configuration Parameters

#### `workers.max_concurrent_jobs`
- **Default**: 4
- **Impact**: Number of images processed simultaneously
- **Trade-off**: More workers = more parallelism, but more GPU contention

#### `workers.batch_size`
- **Default**: 4
- **Impact**: Number of tiles processed per GPU batch
- **Trade-off**: Larger batches = better GPU utilization, but more memory

#### `workers.hybrid_mode`
- **Default**: true
- **Impact**: Dynamic GPU assignment vs fixed assignment
- **Trade-off**: Hybrid = better load balancing, Traditional = simpler

#### `workers.gpu_balancing_strategy`
- **Options**: `least_busy`, `round_robin`, `least_queued`
- **Impact**: How GPUs are selected for jobs
- **Recommendation**: `least_busy` for best performance

#### `tiling.tile_size`
- **Default**: 512
- **Impact**: Size of each tile (larger = fewer tiles, more memory)
- **Trade-off**: Larger tiles = faster processing, but more GPU memory

#### `tiling.overlap`
- **Default**: 256 (tile_size / 4)
- **Impact**: Overlap between tiles (prevents edge artifacts)
- **Trade-off**: More overlap = better edge detection, but more tiles

---

## GPU Load Balancing Strategies

### 1. Least Busy (`least_busy`)
- Selects GPU with **lowest utilization**
- Uses `pynvml` or `nvidia-smi` to query GPU utilization
- **Best for**: Uneven workloads, maximizing GPU utilization

### 2. Round Robin (`round_robin`)
- Cycles through GPUs in order
- Simple and predictable
- **Best for**: Even workloads, simple distribution

### 3. Least Queued (`least_queued`)
- Selects GPU with **fewest active jobs**
- Tracks job count per GPU
- **Best for**: Balancing job distribution

---

## Memory Considerations

### GPU Memory Usage

**Per Model**:
- Model weights: ~50-500 MB (depending on model size)
- Batch processing: `batch_size × tile_size² × channels × 4 bytes`

**Example Calculation**:
```
Model: 100 MB
Batch: 4 tiles × 512² × 3 channels × 4 bytes = 12.6 MB
Total per model: ~113 MB

With 2 models on 2 GPUs (hybrid mode):
  GPU0: 2 models × 113 MB = 226 MB
  GPU1: 2 models × 113 MB = 226 MB
```

### System Memory Usage

- Image loading: Full image size in RAM
- Tile cache: `tile_cache_dir` for temporary storage
- Queue state: Minimal (JSON file)

---

## Error Handling & Retry Logic

### Job Retry Mechanism

**Configuration**: `queue.max_retries = 3`

**Retry Flow**:
```
Job Fails → Retry 1 (wait 60s) → Retry 2 (wait 60s) → Retry 3 (wait 60s) → Quarantine
```

**Failure Handling**:
- Failed images moved to `failure_dir/{image}_{job_id}/`
- Error logs saved: `error.txt` and `{image}.log`
- Quarantined jobs saved to `quarantine_dir`

### File Readiness Checks

**Before Processing**:
1. File exists
2. File size is stable (not changing)
3. File is accessible (not locked)

**Retry Logic**:
- Waits up to 30 seconds for file to be ready
- Prevents processing incomplete or locked files

---

## Output Structure

### Success Case

```
artifacts/success/
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
```

### Failure Case

```
artifacts/failure/
  {image_name}_{job_id}/
    ├── error.txt                        # Error message
    ├── {image_name}.log                 # Processing log
    └── {image_name}.tif                 # Original image (moved)
```

---

## Best Practices

### 1. Worker Configuration
- Set `max_concurrent_jobs` to match number of GPUs × 2 (for hybrid mode)
- Example: 2 GPUs → 4 workers

### 2. Batch Size
- Start with `batch_size = 4`
- Increase if GPU memory allows
- Monitor GPU memory usage

### 3. Tile Size
- Use 512px for most cases
- Use 1024px if GPU memory is abundant
- Use 256px if GPU memory is limited

### 4. GPU Strategy
- Use **hybrid mode** for best performance
- Use `least_busy` strategy for dynamic workloads
- Use `round_robin` for predictable distribution

### 5. Monitoring
- Use dashboard to monitor queue, GPU utilization, and worker status
- Check logs for errors and performance issues
- Monitor disk space for outputs

---

## Troubleshooting

### Low GPU Utilization
- **Cause**: Too many workers competing for GPUs
- **Solution**: Reduce `max_concurrent_jobs` or add more GPUs

### Out of Memory Errors
- **Cause**: Batch size or tile size too large
- **Solution**: Reduce `batch_size` or `tile_size`

### Slow Processing
- **Cause**: I/O bottleneck or too few workers
- **Solution**: Increase workers or use faster storage

### Queue Backlog
- **Cause**: Images arriving faster than processing
- **Solution**: Add more workers/GPUs or optimize models

---

## Summary

This pipeline provides:
- **Scalable parallelism** through worker threads
- **Dynamic GPU load balancing** in hybrid mode
- **Robust error handling** with retries and quarantine
- **Flexible configuration** for different hardware setups
- **Comprehensive outputs** with per-model and combined results

The architecture is designed to maximize throughput while maintaining reliability and flexibility across different hardware configurations.

