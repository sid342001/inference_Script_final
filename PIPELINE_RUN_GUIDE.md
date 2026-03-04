# Satellite Inference Pipeline - Run Guide

## Quick Start

### 1. Prerequisites

Ensure you have:
- Python 3.8+ with required dependencies installed
- At least one GPU with CUDA support (or CPU fallback)
- Model weights files (`.pt` files) in the configured paths
- Input directory ready for satellite images

### 2. Configuration

Edit `config/pipeline.yaml` to match your setup:

```yaml
watcher:
  input_dir: "data/incoming"  # Directory to watch for new images

models:
  - name: "yolo_main"
    weights_path: "models/yolo_main.pt"  # Update to your model path
    device: "cuda:0"  # Assign to specific GPU
  - name: "yolo_obb"
    weights_path: "models/yolo_obb.pt"
    device: "cuda:1"  # Use different GPU for parallelization
```

**Key settings for parallelization:**
- `workers.max_concurrent_jobs`: Number of images processed simultaneously (default: 4)
- `workers.batch_size`: Batch size for tile inference (default: 4)
- Model `device` assignments: Distribute models across GPUs for true parallelism

### 3. Start the Pipeline

**Windows:**
```bash
python scripts/run_pipeline.py --config config/pipeline.yaml
```

**Linux/Mac:**
```bash
python3 scripts/run_pipeline.py --config config/pipeline.yaml
```

Or use the batch script:
```bash
scripts/start_pipeline.bat
```

The pipeline will:
- Start watching the input directory
- Load all models onto their assigned GPUs
- Begin processing images as they arrive
- Write outputs to `artifacts/success/` and `artifacts/combined/`

### 4. Monitor Parallelization

**Option A: Real-time Monitor (Recommended)**
```bash
python scripts/monitor_pipeline.py
```

This shows:
- Queue status (pending, processing, completed)
- Active worker threads
- GPU utilization per device
- Parallelization indicators

**Option B: Check Health JSON**
```bash
# View the latest status
cat artifacts/health/status.json
# Or on Windows:
type artifacts\health\status.json
```

**Option C: Check Logs**
```bash
# Main pipeline log
tail -f logs/pipeline/pipeline.log

# Per-image logs (detailed)
ls artifacts/logs/
```

### 5. Verify Parallelization is Working

#### ✅ Signs of Successful Parallelization:

1. **Multiple Workers Active**
   - Check monitor output: Should show `max_concurrent_jobs` workers alive
   - Example: If `max_concurrent_jobs: 4`, you should see 4 workers

2. **Multiple Jobs Processing Simultaneously**
   - Health status shows `processing > 1` when multiple images are queued
   - Logs show multiple jobs starting around the same time

3. **Multiple GPUs in Use**
   - GPU utilization > 5% on multiple devices
   - Each model assigned to different GPU shows activity

4. **Concurrent Model Inference**
   - When processing one image, all models run on their assigned GPUs
   - Check logs for timestamps showing overlapping inference runs

#### 🔍 How to Test:

1. **Prepare Test Images:**
   ```bash
   # Copy multiple satellite images to the input directory
   mkdir -p data/incoming
   cp image1.tif data/incoming/
   cp image2.tif data/incoming/
   cp image3.tif data/incoming/
   cp image4.tif data/incoming/
   ```

2. **Start Pipeline:**
   ```bash
   python scripts/run_pipeline.py --config config/pipeline.yaml
   ```

3. **In Another Terminal, Start Monitor:**
   ```bash
   python scripts/monitor_pipeline.py
   ```

4. **Watch for:**
   - Queue `processing` count increases to match `max_concurrent_jobs`
   - Multiple worker threads showing "alive" status
   - GPU utilization spikes on multiple devices
   - Logs showing concurrent job processing

#### 📊 Expected Behavior:

**Single Image Processing:**
- All models run on their assigned GPUs (parallel model inference)
- Tiles are batched and processed in parallel batches
- One worker handles the image, but models run concurrently

**Multiple Images:**
- Up to `max_concurrent_jobs` images processed simultaneously
- Each image handled by a separate worker thread
- Models run on their assigned GPUs for each image

**Example Timeline (4 workers, 2 models, 4 images):**
```
Time  | Worker 0    | Worker 1    | Worker 2    | Worker 3    | GPU 0      | GPU 1
------|-------------|-------------|-------------|-------------|------------|------------
T0    | Image1      | Image2      | Image3      | Image4      | Model1     | Model2
T1    | Tiling...   | Tiling...   | Tiling...   | Tiling...   | Model1     | Model2
T2    | Inference   | Inference   | Inference   | Inference   | 80% util   | 75% util
T3    | GeoJSON     | GeoJSON     | GeoJSON     | GeoJSON     | Model1     | Model2
```

### 6. Troubleshooting

#### Issue: Only 1 worker active
**Solution:** Check `workers.max_concurrent_jobs` in config. Increase if you have enough GPU memory.

#### Issue: GPUs not being used
**Solution:** 
- Verify CUDA is available: `python -c "import torch; print(torch.cuda.is_available())"`
- Check model device assignments in config
- Ensure models are loaded: Check startup logs for "Loading model..."

#### Issue: Queue not processing
**Solution:**
- Check if images are in the correct format (`.tif`, `.tiff`, `.jp2`, `.img`)
- Verify watcher is running: Check logs for "Watcher started"
- Check for errors in `artifacts/failure/` directories

#### Issue: Low GPU utilization
**Solution:**
- Increase `workers.batch_size` for larger tile batches
- Ensure models are on different GPUs (not all on `cuda:0`)
- Check if tiling is the bottleneck (CPU-bound)

### 7. Output Structure

```
artifacts/
├── success/
│   └── <job_id>/
│       ├── <image_name>_yolo_main.geojson
│       ├── <image_name>_yolo_obb.geojson
│       ├── summary_yolo_main.csv
│       └── summary_yolo_obb.csv
├── combined/
│   └── <job_id>/
│       └── <image_name>_combined.geojson
├── failure/
│   └── <job_id>/
│       ├── error.txt
│       └── <image_name>.tif
├── logs/
│   └── <job_id>.log
└── health/
    └── status.json
```

### 8. Performance Tuning

**For Maximum Parallelization:**

1. **Increase Concurrent Jobs:**
   ```yaml
   workers:
     max_concurrent_jobs: 8  # Process 8 images at once
   ```

2. **Distribute Models Across GPUs:**
   ```yaml
   models:
     - name: "model1"
       device: "cuda:0"
     - name: "model2"
       device: "cuda:1"
     - name: "model3"
       device: "cuda:2"
   ```

3. **Optimize Batch Size:**
   ```yaml
   workers:
     batch_size: 8  # Larger batches = better GPU utilization
   ```

4. **Adjust Tile Size:**
   ```yaml
   tiling:
     tile_size: 2048  # Larger tiles = fewer tiles = faster processing
     overlap: 512
   ```

### 9. Stopping the Pipeline

Press `Ctrl+C` in the terminal running the pipeline. The pipeline will:
- Stop accepting new jobs
- Finish processing current jobs
- Save queue state
- Shut down gracefully

---

## Advanced: Manual Testing

Create a test script to verify parallelization:

```python
# test_parallelization.py
import time
from pathlib import Path
import shutil

# Create test images directory
test_dir = Path("data/incoming")
test_dir.mkdir(parents=True, exist_ok=True)

# Copy test images (replace with your actual images)
for i in range(4):
    src = Path(f"test_images/test_{i}.tif")
    if src.exists():
        dst = test_dir / f"test_{i}_{int(time.time())}.tif"
        shutil.copy(src, dst)
        print(f"Added {dst} to queue")

print("Test images added. Monitor with: python scripts/monitor_pipeline.py")
```

Run this while the pipeline is running to add multiple jobs simultaneously and observe parallel processing.

