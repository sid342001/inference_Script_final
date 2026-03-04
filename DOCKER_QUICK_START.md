# Docker Quick Start Guide

## Prerequisites

1. **Docker** installed
2. **NVIDIA Docker** (for GPU support): `nvidia-docker2`
3. **Models** placed in `models/` directory
4. **Config** updated with Docker paths (use `/app/` prefix)

## Quick Start

### 1. Configuration (Optional)

**Option A: Use Default Config**
- No action needed! The image includes a default config with Docker paths
- Just build and run

**Option B: Customize Config**
- Create/edit `config/pipeline.yaml` on your host
- Use `/app/` prefix for all paths (Docker container paths)
- Your config will override the default

**Example paths for Docker:**
```yaml
watcher:
  input_dir: "/app/data/incoming"  # Docker path

artifacts:
  success_dir: "/app/artifacts/success"
  failure_dir: "/app/artifacts/failure"
  # ... all paths should use /app/ prefix
```

### 2. Place Models

Copy your model files to `models/`:
```bash
cp /path/to/models/*.pt models/
```

### 3. Build & Run

```bash
# Build the image
docker-compose build

# Start the pipeline
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### 4. Access Dashboard

Open: `http://localhost:8092`

## Manual Docker Run (Alternative)

```bash
# Build
docker build -f Dockerfile.inference -t inference-pipeline .

# Run with GPU (all directories read-write)
docker run -d \
  --name inference-pipeline \
  --gpus all \
  -v $(pwd)/data/incoming:/app/data/incoming \
  -v $(pwd)/artifacts:/app/artifacts \
  -v $(pwd)/state:/app/state \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/models:/app/models \
  -v $(pwd)/config:/app/config \
  -p 8092:8092 \
  inference-pipeline
```

## Verify GPU Access

```bash
# Check GPU in container
docker exec inference-pipeline conda run -n inference python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}, Devices: {torch.cuda.device_count()}')"
```

## Troubleshooting

- **GPU not working**: Install `nvidia-docker2` and restart Docker
- **Config errors**: Ensure all paths use `/app/` prefix
- **Permission errors**: Fix permissions on host directories
- **Port conflicts**: Change port in docker-compose.yml

See `DOCKER_BUILD_GUIDE.md` for detailed instructions.

