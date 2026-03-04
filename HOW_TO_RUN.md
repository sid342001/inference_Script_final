# How to Run the Satellite Inference Pipeline

Complete step-by-step guide to get the application running.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running the Pipeline](#running-the-pipeline)
5. [Monitoring](#monitoring)
6. [Troubleshooting](#troubleshooting)

---

## 1. Prerequisites

### Required Software

- **Python 3.8 or higher**
  - Check version: `python --version` or `python3 --version`
  - Download: https://www.python.org/downloads/

- **CUDA-capable GPU** (recommended) or CPU fallback
  - For GPU: Install CUDA toolkit and PyTorch with CUDA support
  - Check GPU: `nvidia-smi` (if NVIDIA GPU available)

- **GDAL** (for geospatial data processing)
  - Windows: Install via OSGeo4W or conda
  - Linux: `sudo apt-get install gdal-bin python3-gdal`
  - Mac: `brew install gdal`

### Required Python Packages

The application requires:
- `ultralytics` (YOLOv8)
- `torch` (PyTorch)
- `numpy`
- `pillow` (PIL)
- `pyproj`
- `pyyaml`
- `watchdog` (optional, for file watching)

Install all dependencies:
```bash
pip install ultralytics torch numpy pillow pyproj pyyaml watchdog
```

Or if you have a `requirements.txt`:
```bash
pip install -r requirements.txt
```

### Required Files

- **Model weights** (`.pt` files) - YOLO model files
- **Configuration file** - YAML config (see Configuration section)
- **Input directory** - Directory containing satellite images to process

---

## 2. Installation

### Step 1: Navigate to the Project Directory

```bash
cd inference_Script
```

### Step 2: Verify Python Installation

```bash
python --version
# Should show Python 3.8 or higher
```

### Step 3: Install Dependencies

```bash
# Install required packages
pip install ultralytics torch numpy pillow pyproj pyyaml watchdog

# Verify PyTorch can see GPU (if available)
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

### Step 4: Verify GDAL Installation

```bash
python -c "from osgeo import gdal; print('GDAL OK')"
```

If this fails, install GDAL (see Prerequisites).

---

## 3. Configuration

### Step 1: Create Configuration File

Create a `config` directory and a `pipeline.yaml` file:

```bash
mkdir -p config
```

Create `config/pipeline.yaml` with the following structure:

```yaml
# Directory to watch for new satellite images
watcher:
  input_dir: "data/incoming"
  recursive: true
  include_extensions: [".tif", ".tiff", ".jp2", ".img"]
  settle_time_seconds: 10
  poll_interval_seconds: 15
  max_inflight_jobs: 32

# Job queue configuration
queue:
  persistence_path: "state/queue.json"
  max_retries: 3
  retry_backoff_seconds: 60
  quarantine_dir: "state/quarantine"

# Worker configuration
workers:
  max_concurrent_jobs: 4  # Number of images to process simultaneously
  batch_size: 4            # Batch size for tile inference
  tile_cache_dir: "state/tile_cache"

# Tiling configuration
tiling:
  tile_size: 1024
  overlap: 256
  normalization_mode: "auto"
  allow_resample: true

# GPU configuration
gpus:
  - id: "gpu0"
    device: "cuda:0"
  - id: "gpu1"
    device: "cuda:1"

# Model configuration
models:
  - name: "yolo_main"
    weights_path: "models/yolo_main.pt"  # Update this path!
    type: "yolo"  # or "yolo_obb" for oriented bounding boxes
    device: "cuda:0"
    confidence_threshold: 0.5
    outputs:
      write_tile_previews: false
      summary_csv: true

  - name: "yolo_obb"
    weights_path: "models/yolo_obb.pt"  # Update this path!
    type: "yolo_obb"
    device: "cuda:1"
    confidence_threshold: 0.5

# Artifacts (output) configuration
artifacts:
  success_dir: "artifacts/success"
  failure_dir: "artifacts/failure"
  combined_dir: "artifacts/combined"
  temp_dir: "artifacts/tmp"
  per_image_log_dir: "artifacts/logs"
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
  interval_seconds: 30
```

### Step 2: Update Configuration

**Important:** Update these paths in `config/pipeline.yaml`:

1. **Model paths**: Change `weights_path` to point to your actual `.pt` model files
   ```yaml
   weights_path: "models/your_model.pt"  # Update this!
   ```

2. **Input directory**: Set where to watch for images
   ```yaml
   input_dir: "data/incoming"  # Create this directory
   ```

3. **GPU devices**: Adjust based on your available GPUs
   - For CPU-only: Remove `device` or set to `"cpu"`
   - For single GPU: Use `"cuda:0"` for all models
   - For multiple GPUs: Distribute models across GPUs

### Step 3: Create Required Directories

```bash
# Create input directory for images
mkdir -p data/incoming

# Create state directory
mkdir -p state

# Create artifacts directories (will be created automatically, but you can pre-create)
mkdir -p artifacts/success artifacts/failure artifacts/combined artifacts/logs artifacts/health
```

### Step 4: Prepare Model Files

Place your YOLO model files (`.pt`) in the location specified in the config:

```bash
mkdir -p models
# Copy your .pt model files here
# Example: cp /path/to/your/model.pt models/yolo_main.pt
```

---

## 4. Running the Pipeline

### Method 1: Using the Run Script (Recommended)

**Windows:**
```bash
python run_pipeline.py --config config/pipeline.yaml
```

**Linux/Mac:**
```bash
python3 run_pipeline.py --config config/pipeline.yaml
```

### Method 2: Using Python Module

```bash
python -m inference_Script.orchestrator run_from_config config/pipeline.yaml
```

### Method 3: Direct Python Import

```python
from inference_Script.orchestrator import run_from_config
run_from_config("config/pipeline.yaml")
```

### What Happens When You Start

1. ✅ Configuration is loaded and validated
2. ✅ Models are loaded onto assigned GPUs
3. ✅ Directory watcher starts monitoring input directory
4. ✅ Worker threads are spawned (based on `max_concurrent_jobs`)
5. ✅ Health monitor starts writing status JSON
6. ✅ Pipeline is ready to process images

### Adding Images for Processing

Once the pipeline is running, simply copy satellite images to the input directory:

```bash
# Copy images to the watched directory
cp your_image.tif data/incoming/
```

The pipeline will automatically:
- Detect the new file
- Queue it for processing
- Tile the image
- Run inference with all models
- Generate GeoJSON outputs
- Write results to `artifacts/success/`

### Stopping the Pipeline

Press `Ctrl+C` in the terminal. The pipeline will:
- Stop accepting new jobs
- Finish processing current jobs
- Save queue state
- Shut down gracefully

---

## 5. Monitoring

### Option 1: Web Dashboard (Recommended)

Start the dashboard server in a separate terminal:

```bash
python dashboard_server.py
```

Then open http://localhost:8080 in your browser.

The dashboard shows:
- Real-time queue status
- GPU utilization
- Worker status
- Recent jobs

See `DASHBOARD_README.md` for more details.

### Option 2: Health JSON File

Check the health status file:

```bash
# Linux/Mac
cat artifacts/health/status.json

# Windows
type artifacts\health\status.json
```

### Option 3: Log Files

View the main pipeline log:

```bash
# Linux/Mac
tail -f logs/pipeline/pipeline.log

# Windows (PowerShell)
Get-Content logs/pipeline/pipeline.log -Wait -Tail 50
```

View per-image logs:

```bash
ls artifacts/logs/
```

### Option 4: Check Output Artifacts

```bash
# Successful jobs
ls artifacts/success/

# Combined outputs
ls artifacts/combined/

# Failed jobs
ls artifacts/failure/
```

---

## 6. Troubleshooting

### Problem: "Configuration file not found"

**Solution:**
- Check the path to your config file
- Make sure you're running from the correct directory
- Use absolute path if relative path doesn't work

### Problem: "Model file not found"

**Solution:**
- Verify model paths in `config/pipeline.yaml`
- Check that `.pt` files exist at specified locations
- Use absolute paths if relative paths don't work

### Problem: "CUDA not available" or "No GPU detected"

**Solution:**
- Install PyTorch with CUDA: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118`
- Check GPU: `nvidia-smi`
- For CPU-only: Remove `device` from model config or set to `"cpu"`

### Problem: "GDAL error" or "Cannot open dataset"

**Solution:**
- Install GDAL (see Prerequisites)
- Verify image file is not corrupted
- Check file permissions
- Try with a different image file

### Problem: "No images being processed"

**Solution:**
- Check that images are in the correct format (`.tif`, `.tiff`, `.jp2`, `.img`)
- Verify `input_dir` path in config
- Check watcher logs for errors
- Ensure files are fully written before being detected (increase `settle_time_seconds`)

### Problem: "Low GPU utilization"

**Solution:**
- Increase `workers.batch_size` in config
- Distribute models across multiple GPUs
- Increase `max_concurrent_jobs` if you have enough GPU memory

### Problem: "Out of memory" errors

**Solution:**
- Reduce `max_concurrent_jobs`
- Reduce `batch_size`
- Reduce `tile_size` in tiling config
- Process fewer models simultaneously

### Problem: Dashboard shows "Error loading status"

**Solution:**
- Make sure pipeline is running
- Check that `artifacts/health/status.json` exists
- Verify dashboard server can read the health file
- Check file permissions

---

## Quick Reference

### Start Pipeline
```bash
python run_pipeline.py --config config/pipeline.yaml
```

### Start Dashboard
```bash
python dashboard_server.py
```

### Check Status
```bash
cat artifacts/health/status.json
```

### View Logs
```bash
tail -f logs/pipeline/pipeline.log
```

### Stop Pipeline
Press `Ctrl+C`

---

## Next Steps

- Read `PIPELINE_RUN_GUIDE.md` for detailed parallelization tuning
- Read `DASHBOARD_README.md` for dashboard features
- Check `QUICK_START.md` for a condensed guide

---

## Getting Help

If you encounter issues:

1. Check the logs: `logs/pipeline/pipeline.log`
2. Check error files: `artifacts/failure/`
3. Verify configuration: Check `config/pipeline.yaml`
4. Check system resources: GPU memory, disk space
5. Review this guide's troubleshooting section

For more information, see the other documentation files in this directory.

