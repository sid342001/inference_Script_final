# SAT Annotator

A comprehensive satellite image annotation and machine learning platform with YOLOv8 training capabilities for geospatial data analysis.

## 🚀 Features

- **Interactive Annotation**: Advanced polygon and rectangle annotation tools for satellite imagery
- **Dataset Management**: Support for YOLO, COCO, and Pascal VOC formats with automatic conversion
- **Model Management**: Upload, train, and deploy YOLOv8 models for object detection
- **YOLOv8 Training**: Integrated training interface with real-time monitoring and visualization
- **Auto-Detection**: YOLOv8 inference for automatic object detection and annotation
- **Task Management**: Create and manage annotation tasks with progress tracking
- **System Monitoring**: Real-time system resource monitoring and performance metrics
- **Geospatial Support**: Full support for TIFF, COG, and other geospatial formats
- **Export Functionality**: Export annotated data in multiple formats
- **Watcher-Based Inference**: Headless service that tiles new satellite imagery, runs multiple YOLO models on GPUs, and publishes per-model plus combined GeoJSON outputs with health monitoring

## 🛠️ Installation

### Prerequisites
- Python 3.8+
- Node.js 16+
- GDAL (for geospatial data processing)

### Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/sat-annotator.git
   cd sat-annotator
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Node.js dependencies**:
   ```bash
   cd frontend
   npm install
   cd ..
   ```

4. **Setup GDAL** (Windows):
   ```bash
   configure_firewall.bat
   setup_titiler_env.bat
   ```

## 🚀 Quick Start

### Option 1: Start All Services (Recommended)
```bash
start_unified_production.bat
```

### Option 2: Start Services Individually

1. **Main Backend**:
   ```bash
   start_backend.bat
   ```

2. **Frontend**:
   ```bash
   start_frontend.bat
   ```

3. **Explore App** (geospatial data exploration):
   ```bash
   start_explore_app.bat
   ```

4. **YOLOv8 Inference Service** (for autodetect):
   ```bash
   start_yolo_inference.bat
   ```

## 🌐 Services

- **Frontend**: http://localhost:5173
- **Main Backend**: http://localhost:8000
- **Explore App**: http://localhost:8002 (Geospatial data exploration and tile cutting)
- **YOLOv8 Inference**: http://localhost:8105

## 🛰️ Watcher-Based Inference Pipeline

The repository now bundles a standalone inference service that watches drop folders, splits rasters into tiles, runs multiple YOLO/YOLO-OBB models in parallel on any available GPUs, and produces per-model plus combined GeoJSON/CSV artifacts.

### Configure

- Duplicate `config/pipeline.yaml` if you need multiple environments.
- Key sections:
  - `watcher`: directories/extensions to monitor and how aggressively to enqueue jobs.
  - `queue`: persistent state file, retry/backoff policy, quarantine folder.
  - `workers`: tiler vs. GPU worker counts, batch size, cache directories.
  - `gpus`/`models`: map each `.pt` file to a target CUDA device and optional tiling overrides.
  - `artifacts` & `logging`: success/failure/combined folders, manifest format, per-image log level.
  - `health`: JSON heartbeat location + cadence for dashboards.

### Run

```bash
python scripts/run_pipeline.py --config config/pipeline.yaml
```

The process will:

1. Preload and pin each YOLO model to the configured GPU.
2. Start the directory watcher/persistent queue plus per-image structured logging.
3. Spawn workers that tile imagery, batch inference, build per-model & combined GeoJSON, CSV summaries, tile previews, and manifests.
4. Continuously publish a heartbeat JSON (queue depth, worker health, GPU utilization) for ops monitoring.

### Outputs & Failure Handling

- Successful jobs live under `artifacts/success/<image>_<job>/` with:
  - `<model>.geojson`, `<model>.csv`, optional `tiles/` PNG previews.
  - Combined GeoJSON in `artifacts/combined/<job>.geojson`.
  - Manifest JSON under `artifacts/success/manifests/<job>.json`.
- Failed jobs are copied to `artifacts/failure/<job>/` with the offending raster and stack trace.
- Repeated failures are quarantined after the configured retry budget and logged for manual triage.

## 📖 Usage

### Dashboard

The main dashboard provides access to all functionality:

1. **Explore**: View system overview, file management, and geospatial data visualization
2. **Training**: Manage YOLOv8 model training with real-time monitoring
3. **Inference**: Use trained models for automatic object detection
4. **Annotate Datasets**: Create and manage annotation tasks with interactive tools

### Geospatial Data Exploration

The Explore App provides advanced geospatial data processing capabilities:

- **Raster Upload**: Upload TIFF, COG, and other geospatial formats
- **Tile Cutting**: Cut large rasters into manageable tiles for annotation
- **COG Conversion**: Convert rasters to Cloud Optimized GeoTIFF format
- **Vector Support**: Upload and manage GeoJSON vector data
- **Interactive Visualization**: View and explore geospatial data with web-based tools
- **Export Functionality**: Export processed tiles and data in various formats

### Dataset Management

- **Upload Datasets**: Support for ZIP, TAR.GZ archives with automatic format detection
- **View Datasets**: See all registered datasets with metadata and statistics
- **Delete Datasets**: Remove datasets from the system
- **Supported Formats**: YOLO, COCO, Pascal VOC with automatic conversion
- **Geospatial Support**: TIFF, COG, and other geospatial formats

### Model Management

- **Upload Models**: Support for .pt, .pth, .onnx, .pb, .tflite files
- **View Models**: List all available models with metadata
- **Delete Models**: Remove models from the system
- **Model Classes**: View supported classes for each model
- **Model Testing**: Test models with sample images

### Training

- **Start Training**: Configure and start YOLOv8 training jobs with custom parameters
- **Monitor Progress**: Real-time training progress with logs and metrics
- **View Results**: Training graphs, loss curves, and sample predictions
- **Job Management**: List and manage all training jobs with status tracking

### Annotation Tools

- **Polygon Annotation**: Create precise polygon annotations for complex shapes
- **Rectangle Annotation**: Quick bounding box annotations
- **Auto-Detection**: Use trained models for automatic annotation
- **Export Options**: Export annotations in multiple formats

## API Endpoints

### Datasets
- `GET /datasets` - List all datasets
- `POST /datasets` - Add dataset manually
- `POST /datasets/upload` - Upload dataset file
- `DELETE /datasets/{id}` - Delete dataset

### Models
- `GET /models` - List all models
- `POST /models/upload` - Upload model file
- `DELETE /models/{name}` - Delete model
- `GET /models/{name}/classes` - Get model classes
- `POST /models/run` - Run model inference

### Training
- `POST /training/start` - Start training job
- `GET /training/jobs` - List training jobs
- `GET /training/jobs/{id}` - Get job details
- `GET /training/models` - Get available models
- `GET /training/datasets` - Get available datasets

## 📁 Project Structure

```
sat-annotator/
├── backend/                    # Main FastAPI backend server
│   ├── app/
│   │   ├── routers/           # API endpoints and routes
│   │   │   ├── annotations.py # Annotation management
│   │   │   ├── datasets.py    # Dataset operations
│   │   │   ├── models.py      # Model management
│   │   │   ├── training.py    # Training operations
│   │   │   └── ...
│   │   ├── schemas/           # Pydantic data models
│   │   └── config.py          # Application configuration
│   ├── storage/               # Data storage (excluded from git)
│   └── requirements.txt       # Python dependencies
├── frontend/                  # React frontend application
│   ├── src/
│   │   ├── api/              # API client functions
│   │   ├── components/       # Reusable UI components
│   │   ├── pages/            # Main application pages
│   │   └── context/          # React context providers
│   ├── public/               # Static assets
│   └── package.json          # Node.js dependencies
├── explore_app/              # Geospatial data exploration service
│   ├── main.py               # FastAPI app with TiTiler integration
│   ├── requirements.txt      # Geospatial dependencies
│   └── storage/              # User data storage (excluded from git)
├── InferencePython/          # YOLOv8 inference service
│   └── file/
│       └── infer.py          # Inference implementation
├── requirements.txt          # Main Python dependencies
├── .gitignore               # Git ignore rules
└── README.md                # Project documentation
```

## ⚙️ Configuration

### Supported File Formats

**Dataset Upload**:
- `.zip` - ZIP archives
- `.tar.gz` - Compressed tar archives
- `.tar` - Tar archives
- `.gz` - Gzip archives

**Model Upload**:
- `.pt` - PyTorch models
- `.pth` - PyTorch models
- `.onnx` - ONNX models
- `.pb` - TensorFlow models
- `.tflite` - TensorFlow Lite models

**Geospatial Formats**:
- `.tif/.tiff` - GeoTIFF files
- `.cog` - Cloud Optimized GeoTIFF
- `.jp2` - JPEG 2000
- `.png` - PNG with geospatial metadata

## 🔧 Troubleshooting

### Services Not Starting
1. Check if ports are available (8000, 8002, 8105, 5173)
2. Install Python dependencies: `pip install -r requirements.txt`
3. Install Node.js dependencies: `cd frontend && npm install`
4. Ensure GDAL is properly installed for geospatial processing
5. For explore_app, ensure TiTiler dependencies are installed

### Training Issues
1. Verify dataset format and structure
2. Check available system resources (GPU/CPU)
3. Ensure model files are accessible
4. Review training logs for specific errors

### Autodetect Not Working
1. Ensure YOLOv8 inference service is running on port 8105
2. Check model registry configuration
3. Verify model files are accessible and valid
4. Test with sample images first

### Geospatial Data Issues
1. Ensure GDAL is properly installed
2. Check file permissions and paths
3. Verify coordinate reference systems
4. Test with smaller files first
5. For explore_app issues, check TiTiler and rio-cogeo installation
6. Verify raster file formats are supported (TIFF, COG, etc.)

## 🚀 Development

### Adding New Features
1. **Backend**: Add endpoints to appropriate routers in `backend/app/routers/`
2. **Frontend**: Update API clients in `frontend/src/api/` and UI components
3. **Explore App**: Modify geospatial processing in `explore_app/main.py`
4. **Inference**: Modify inference logic in `InferencePython/file/infer.py`

### Testing
1. Start all services using `start_unified_production.bat`
2. Navigate to http://localhost:5173
3. Test all functionality through the web interface
4. Check backend logs for any errors

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📞 Support

For support and questions, please open an issue on GitHub.

## 🙏 Acknowledgments

- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) for the YOLO implementation
- [FastAPI](https://fastapi.tiangolo.com/) for the backend framework
- [React](https://reactjs.org/) for the frontend framework
- [GDAL](https://gdal.org/) for geospatial data processing