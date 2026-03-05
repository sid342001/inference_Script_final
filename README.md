# Satellite Inference Pipeline

A production-grade, headless satellite image processing pipeline that automatically detects objects in large geospatial imagery using YOLO deep learning models. The system watches directories for new satellite images, processes them automatically with multiple AI models in parallel across GPUs, and outputs geospatial detection results in GeoJSON format.

## 🚀 Features

- **Automated Processing**: Watches directories and processes images as they arrive
- **Multi-Model Support**: Run multiple YOLO/YOLO-OBB models on the same image
- **Multi-GPU Support**: Distribute models across GPUs for parallel processing
- **Geospatial Output**: Generates GeoJSON files with precise geographic coordinates
- **Projection Support**: Handles any projection system (WGS84, UTM, custom projections)
- **Intelligent Tiling**: Automatically tiles large images for efficient processing
- **Batch Processing**: Process multiple images concurrently
- **Retry Mechanism**: Automatic retry for transient failures
- **Health Monitoring**: Real-time dashboard and health status JSON
- **Docker Support**: Full Docker containerization for easy deployment
- **Persistent Queue**: Job queue persists across restarts

## 📋 Table of Contents

- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Output Formats](#-output-formats)
- [Docker Deployment](#-docker-deployment)
- [Monitoring](#-monitoring)
- [Architecture](#-architecture)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)

## ⚡ Quick Start

### 1. Install Dependencies

```bash
pip install ultralytics torch numpy pillow pyproj pyyaml watchdog
```

### 2. Configure

Edit `config/pipeline.yaml`:
- Set `input_dir` to watch for images
- Update model paths (`weights_path`)
- Assign models to GPUs

### 3. Run

```bash
python run_pipeline.py --config config/pipeline.yaml
```

### 4. Monitor

In another terminal:
```bash
python dashboard_server.py
# Open http://localhost:8080
```

## 🛠️ Installation

### Prerequisites

- **Python 3.8+**
- **CUDA-capable GPU** (recommended) or CPU fallback
- **GDAL** (for geospatial data processing)
  - Windows: Install via OSGeo4W or conda
  - Linux: `sudo apt-get install gdal-bin python3-gdal`
  - Mac: `brew install gdal`

### Step-by-Step Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/sid342001/inference_Script_final.git
   cd inference_Script_final
   ```

2. **Install Python dependencies**:
   ```bash
   pip install ultralytics torch numpy pillow pyproj pyyaml watchdog
   ```

3. **Verify GPU support** (optional):
   ```bash
   python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
   ```

4. **Verify GDAL installation**:
   ```bash
   python -c "from osgeo import gdal; print('GDAL OK')"
   ```

5. **Create required directories**:
   ```bash
   mkdir -p data/incoming models artifacts state logs
   ```

6. **Place your model files** (`.pt` files) in the `models/` directory

## ⚙️ Configuration

The pipeline is configured via `config/pipeline.yaml`. Key sections:

### Region of Interest (ROI) per model

The ROI feature lets you restrict inference to specific geographic regions per model.

- **Per-model setting**: Add `roi_geojson_path` to any model block that should use an ROI.
- **One GeoJSON per model**: Each file can contain one or more polygons; all polygons are treated as the model’s ROI.
- **CRS**: Define ROI polygons in WGS84 (`EPSG:4326`) unless you know they match the image CRS.
- **Behavior**:
  - If an image **does not intersect** the ROI → that model is **skipped** for that image.
  - If an image **partially intersects** the ROI → only the intersecting part is processed.
  - If **no ROI is configured** → the model processes the **full image** (existing behavior).
  - If an image intersects **multiple ROI polygons** in the same file → intersections are **unioned** into a single processing region and processed once.

Update your `config/pipeline.yaml` like this:

```yaml
models:
  - name: "Yolo_plane_x"
    weights_path: "D:/aks/sat-annotator-main/inference_Script/models/Yolo_plane_x.pt"
    type: "yolo"
    device: "cuda:0"
    confidence_threshold: 0.5

    # NEW: optional ROI for this model
    roi_geojson_path: "D:/aks/sat-annotator-main/inference_Script/config/roi_Yolo_plane_x.geojson"

    all_folders: false
    folder_identities: ["qgis", "SAR", "jp2"]
    tile:
      tile_size: 256
      overlap: 128
      normalization_mode: "auto"
      allow_resample: true
      iou_threshold: 0.8
      ioma_threshold: 0.75

    outputs:
      write_tile_previews: false
      summary_csv: true

  - name: "yolo11n-obb"
    weights_path: "D:/aks/sat-annotator-main/inference_Script/models/yolo11n-obb.pt"
    type: "yolo_obb"
    device: "cuda:0"
    confidence_threshold: 0.6

    # Optional ROI for this model (can be different from above)
    roi_geojson_path: "D:/aks/sat-annotator-main/inference_Script/config/roi_yolo11n_obb.geojson"

    all_folders: false
    folder_identities: ["carto", "maxar", "jp2"]
    tile:
      tile_size: 1024
      overlap: 512
      normalization_mode: "auto"
      allow_resample: true
      iou_threshold: 0.75
      ioma_threshold: 0.7

    outputs:
      write_tile_previews: false
      summary_csv: true
```

Place the ROI GeoJSON files in `config/` (or any path you prefer) and point `roi_geojson_path` to the full path. Each GeoJSON should contain one or more rectangular (or arbitrary) polygons covering the regions where you want inference to run.

#### ROI GeoJSON structure

The ROI GeoJSON is a standard GeoJSON file. Only the **geometry** is used; any `properties` are ignored.

- **Recommended CRS**: WGS84 (`EPSG:4326`) with coordinates as `[longitude, latitude]`.
- **Supported geometries**:
  - `Polygon`
  - `MultiPolygon` (inside a Feature)
  - Multiple Features in a `FeatureCollection`

Minimal example with a single rectangular ROI:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "name": "roi_example"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [72.8000, 18.9000],
          [73.0000, 18.9000],
          [73.0000, 19.1000],
          [72.8000, 19.1000],
          [72.8000, 18.9000]
        ]]
      }
    }
  ]
}
```

You can also include **multiple polygons** in the same file; all are treated as ROI for that model. If an image intersects more than one polygon, the pipeline unions the intersections and processes that unioned region once.

### Watcher Configuration

```yaml
watcher:
  input_dir: "data/incoming"        # Directory to watch for images
  recursive: true                   # Watch subdirectories
  include_extensions: [".tif", ".tiff", ".jp2", ".img"]
  settle_time_seconds: 10           # Wait for file to finish copying
  max_inflight_jobs: 32             # Max jobs in queue
  folder_identities: ["carto", "maxar", "qgis", "SAR", "jp2"]  # Optional folder filtering
```

### Model Configuration

```yaml
models:
  - name: "yolo_main"
    weights_path: "models/yolo_main.pt"
    device: "cuda:0"                # Assign to GPU 0
    confidence_threshold: 0.25
    iou_threshold: 0.45
    # Optional: Per-model tiling overrides
    tile:
      tile_size: 512
      overlap: 256
  
  - name: "yolo_obb"
    weights_path: "models/yolo_obb.pt"
    device: "cuda:1"                # Assign to GPU 1 for parallelization
```

### Worker Configuration

```yaml
workers:
  max_concurrent_jobs: 8           # Process 8 images simultaneously
  batch_size: 12                    # Process 12 tiles per batch
  hybrid_mode: true                 # Enable dynamic GPU assignment
  gpu_balancing_strategy: "least_busy"  # Options: "least_busy", "round_robin", "least_queued"
```

### Queue Configuration

```yaml
queue:
  persistence_path: "state/queue.json"  # Queue state file
  max_retries: 3                    # Retry failed jobs 3 times
  retry_backoff_seconds: 60        # Wait between retries
  quarantine_dir: "state/quarantine"   # Permanently failed jobs
```

### Output Configuration

```yaml
artifacts:
  success_dir: "artifacts/success"      # Successful job outputs
  failure_dir: "artifacts/failure"      # Failed job outputs
  combined_dir: "artifacts/combined"    # Combined model results
  logs_dir: "artifacts/logs"            # Per-image logs
```

See `config/pipeline.yaml` for complete configuration options.

## 📖 Usage

### Basic Usage

1. **Start the pipeline**:
   ```bash
   python run_pipeline.py --config config/pipeline.yaml
   ```

2. **Add images to process**:
   - Copy satellite images (`.tif`, `.tiff`, `.jp2`, `.img`) to `data/incoming/`
   - The pipeline will automatically detect and process them

3. **View results**:
   - Successful outputs: `artifacts/success/<job_id>/`
   - Combined results: `artifacts/combined/<job_id>/`
   - Failed jobs: `artifacts/failure/<job_id>/`

### Advanced Usage

#### Folder-Based Processing

Organize images by folder to maintain identity:
```
data/incoming/
  ├── carto/
  │   └── image1.tif
  ├── maxar/
  │   └── image2.tif
  └── SAR/
      └── image3.tif
```

Configure `folder_identities` in `pipeline.yaml` to filter specific folders.

#### Multiple Models per Image

Configure multiple models in `pipeline.yaml`:
```yaml
models:
  - name: "ships"
    weights_path: "models/ship_detector.pt"
    device: "cuda:0"
  - name: "aircraft"
    weights_path: "models/aircraft_detector.pt"
    device: "cuda:1"
```

Each image will be processed by all models, with combined results in `artifacts/combined/`.

#### GPU Parallelization

Distribute models across GPUs for maximum throughput:
```yaml
models:
  - name: "model1"
    device: "cuda:0"    # GPU 0
  - name: "model2"
    device: "cuda:1"    # GPU 1
  - name: "model3"
    device: "cuda:0"    # GPU 0 (can share GPUs)
```

Enable hybrid mode for dynamic GPU assignment:
```yaml
workers:
  hybrid_mode: true
  gpu_balancing_strategy: "least_busy"
```

## 📊 Output Formats

### Per-Model Outputs

Each model produces results in `artifacts/success/<job_id>/<model_name>/`:

- **`<model_name>.geojson`**: GeoJSON file with detected objects
- **`<model_name>.csv`**: CSV summary with detection statistics
- **`tiles/`**: Optional tile preview images (if enabled)

### Combined Outputs

Combined results from all models in `artifacts/combined/<job_id>/`:

- **`combined.geojson`**: All detections from all models
- **`combined.csv`**: Summary statistics
- **`manifest.json`**: Processing metadata

### GeoJSON Format

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[lon1, lat1], [lon2, lat2], ...]]
      },
      "properties": {
        "model": "yolo_main",
        "confidence": 0.95,
        "class": "ship",
        "class_id": 0
      }
    }
  ]
}
```

### CSV Format

```csv
model,class,confidence,area_m2,centroid_lon,centroid_lat
yolo_main,ship,0.95,1234.5,-122.123,37.456
```

## 🐳 Docker Deployment

### Quick Start with Docker

1. **Build the image**:
   ```bash
   docker build -t satellite-inference .
   ```

2. **Run with docker-compose**:
   ```bash
   docker-compose up -d
   ```

3. **View logs**:
   ```bash
   docker-compose logs -f
   ```

### Docker Configuration

Edit `docker-compose.yml` to configure:
- Volume mounts for data, models, and outputs
- GPU access (nvidia-docker)
- Environment variables
- Port mappings

See `DOCKER_QUICK_START.md` for detailed Docker setup instructions.

## 📈 Monitoring

### Web Dashboard

Start the dashboard server:
```bash
python dashboard_server.py
```

Access at: **http://localhost:8080**

Features:
- Real-time pipeline status
- Queue monitoring (pending, processing, completed)
- GPU utilization across all devices
- Worker status
- Recent job history

### Health Status JSON

Real-time status available at `artifacts/health/status.json`:

```json
{
  "status": "running",
  "queue": {
    "pending": 5,
    "processing": 2,
    "completed": 100,
    "failed": 3
  },
  "gpus": [
    {
      "device": "cuda:0",
      "utilization": 85.5,
      "memory_used_mb": 8192,
      "memory_total_mb": 12288
    }
  ],
  "workers": {
    "alive": 8,
    "active": 2
  }
}
```

### Logs

- **Pipeline logs**: `logs/pipeline/`
- **Per-image logs**: `artifacts/logs/<job_id>.log`
- **Dashboard logs**: Console output from `dashboard_server.py`

## 🏗️ Architecture

### System Components

```
┌─────────────────────────────────────────────────────────┐
│                  Orchestrator (Main Controller)          │
│  - Manages workers, queue, watcher, health monitor      │
└─────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
    ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
    │ Watcher│    │ Queue  │    │Workers │    │ Health │
    │        │    │        │    │        │    │Monitor │
    └────────┘    └────────┘    └────────┘    └────────┘
         │              │              │
         ▼              ▼              ▼
    ┌──────────────────────────────────────┐
    │         Job Processing Pipeline       │
    │  1. Tile Image                        │
    │  2. Run Models (GPU)                  │
    │  3. Merge Results                     │
    │  4. Generate GeoJSON/CSV             │
    │  5. Write Artifacts                  │
    └──────────────────────────────────────┘
```

### Processing Flow

1. **File Detection**: Watcher detects new image in `input_dir`
2. **Job Enqueue**: Image added to persistent queue
3. **Tiling**: Large image split into overlapping tiles
4. **Inference**: Tiles processed by YOLO models on GPUs
5. **NMS**: Non-maximum suppression removes duplicates
6. **Reprojection**: Coordinates converted to WGS84
7. **Output**: GeoJSON and CSV files generated
8. **Cleanup**: Temporary files removed

### GPU Modes

- **Dedicated Mode**: Each model pinned to specific GPU
- **Hybrid Mode**: Models loaded on all GPUs, dynamic assignment
- **CPU Fallback**: Automatic fallback if no GPU available

## 🔧 Troubleshooting

### Common Issues

#### Pipeline Not Processing Images

1. **Check input directory**:
   ```bash
   ls data/incoming/  # Verify images are present
   ```

2. **Check file extensions**: Ensure images have supported extensions (`.tif`, `.tiff`, `.jp2`, `.img`)

3. **Check logs**: Review `logs/pipeline/` for errors

4. **Verify configuration**: Check `config/pipeline.yaml` paths are correct

#### GPU Not Detected

1. **Verify CUDA installation**:
   ```bash
   python -c "import torch; print(torch.cuda.is_available())"
   nvidia-smi
   ```

2. **Check PyTorch CUDA version**:
   ```bash
   python -c "import torch; print(torch.version.cuda)"
   ```

3. **Use CPU fallback**: Set `device: "cpu"` in model config

#### Out of Memory Errors

1. **Reduce batch size**:
   ```yaml
   workers:
     batch_size: 4  # Reduce from default
   ```

2. **Reduce concurrent jobs**:
   ```yaml
   workers:
     max_concurrent_jobs: 2  # Reduce from default
   ```

3. **Reduce tile size**:
   ```yaml
   tiling:
     tile_size: 256  # Reduce from 512
   ```

#### Projection Errors

1. **Verify GDAL installation**:
   ```bash
   python -c "from osgeo import gdal; print('GDAL OK')"
   ```

2. **Check PROJ data**: Ensure PROJ database is accessible

3. **Review logs**: Check for specific projection errors in logs

### Getting Help

- Check `HOW_TO_RUN.md` for detailed troubleshooting
- Review logs in `logs/pipeline/` and `artifacts/logs/`
- Check health status: `artifacts/health/status.json`
- Open an issue on GitHub with:
  - Error messages
  - Configuration file (sanitized)
  - Log excerpts

## 📁 Project Structure

```
inference_Script/
├── config/
│   ├── pipeline.yaml          # Main configuration file
│   └── pipeline.yaml.docker   # Docker-specific config
├── data/
│   └── incoming/              # Input directory (watched)
├── models/                    # YOLO model files (.pt)
├── artifacts/                 # Output directory
│   ├── success/              # Successful job outputs
│   ├── failure/              # Failed job outputs
│   ├── combined/             # Combined model results
│   ├── logs/                 # Per-image logs
│   └── health/               # Health status JSON
├── state/                     # State files
│   ├── queue.json            # Persistent job queue
│   └── quarantine/           # Permanently failed jobs
├── logs/                      # Pipeline logs
├── run_pipeline.py            # Main entry point
├── orchestrator.py            # Core orchestrator
├── watcher.py                 # File watcher
├── job_queue.py               # Job queue manager
├── inference_runner.py       # Inference execution
├── tiler.py                   # Image tiling
├── infer.py                   # YOLO inference
├── dashboard_server.py        # Web dashboard
└── README.md                  # This file
```

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) for the YOLO implementation
- [GDAL](https://gdal.org/) for geospatial data processing
- [PyTorch](https://pytorch.org/) for deep learning framework

## 📞 Support

For support and questions:
- Open an issue on [GitHub](https://github.com/sid342001/inference_Script_final/issues)
- Check the documentation in the `docs/` directory
- Review troubleshooting guides in the repository

---

**Ready to process satellite imagery?** Start with the [Quick Start](#-quick-start) section above! 🚀
