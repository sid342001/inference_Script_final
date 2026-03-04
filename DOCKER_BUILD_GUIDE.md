# Docker Build & Deployment Guide

## Overview

This guide explains how to build and run the Satellite Inference Pipeline using Docker.

---

## Prerequisites

### 1. **Docker & Docker Compose**
```bash
# Install Docker (if not already installed)
# Ubuntu/Debian:
sudo apt-get update
sudo apt-get install docker.io docker-compose

# Verify installation
docker --version
docker-compose --version
```

### 2. **NVIDIA Docker (for GPU support)**
```bash
# Install nvidia-docker2
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker

# Verify GPU access
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu20.04 nvidia-smi
```

### 3. **Directory Structure**
Ensure you have the following directories (they should exist from .gitkeep files):
```
inference_Script/
├── config/
│   └── pipeline.yaml
├── data/
│   └── incoming/        # Place input images here
├── models/              # Place model weights here (.pt files)
├── artifacts/           # Outputs will be written here
├── state/               # Queue and cache
└── logs/                # Logs
```

---

## Build Instructions

### Option 1: Build Using Dockerfile

```bash
# Navigate to the inference_Script directory
cd inference_Script

# Build the Docker image
docker build -f Dockerfile.inference -t satellite-inference-pipeline:latest .

# Build with specific tag
docker build -f Dockerfile.inference -t satellite-inference-pipeline:v1.0 .
```

### Option 2: Build Using Docker Compose

```bash
# Build and start services
docker-compose up --build -d

# Or build only
docker-compose build
```

---

## Configuration

### 1. **Config File Management**

The Docker image includes a **default config** (`pipeline.yaml.default`) with Docker-optimized paths.

**Option A: Use Default Config (Quick Start)**
- No action needed - default config will be used automatically
- Default config uses `/app/` paths (Docker container paths)

**Option B: Override with Your Own Config (Recommended)**
- Create/edit `config/pipeline.yaml` on your host
- Mount it into container (already configured in docker-compose.yml)
- Your config will override the default
- **Important**: All paths in your config should use `/app/` prefix (Docker container paths)

**Example config paths for Docker:**
```yaml
watcher:
  input_dir: "/app/data/incoming"  # Docker path

artifacts:
  success_dir: "/app/artifacts/success"
  failure_dir: "/app/artifacts/failure"
  # ... all paths should use /app/ prefix
```

**Config Priority:**
1. User-mounted `config/pipeline.yaml` (if exists) ← **Highest priority**
2. Default `config/pipeline.yaml.default` (shipped with image) ← **Fallback**

### 2. **Place Models**

Copy your model files (`.pt`) to the `models/` directory:
```bash
cp /path/to/your/models/*.pt models/
```

---

## Running the Container

### Option 1: Docker Run (Manual)

```bash
# Basic run (CPU only) - all directories read-write
docker run -d \
  --name inference-pipeline \
  -v $(pwd)/data/incoming:/app/data/incoming \
  -v $(pwd)/artifacts:/app/artifacts \
  -v $(pwd)/state:/app/state \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/models:/app/models \
  -v $(pwd)/config:/app/config \
  -p 8092:8092 \
  satellite-inference-pipeline:latest

# With GPU support - all directories read-write
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
  satellite-inference-pipeline:latest
```

### Option 2: Docker Compose (Recommended)

```bash
# Start the pipeline
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the pipeline
docker-compose down

# Restart
docker-compose restart
```

---

## Volume Mounts Explained

| Host Path | Container Path | Purpose | Mode |
|-----------|----------------|---------|------|
| `./data/incoming` | `/app/data/incoming` | Input images | Read-write |
| `./artifacts` | `/app/artifacts` | Output results | Read-write |
| `./state` | `/app/state` | Queue & cache | Read-write |
| `./logs` | `/app/logs` | Log files | Read-write |
| `./models` | `/app/models` | Model weights | Read-write |
| `./config` | `/app/config` | Configuration | Read-write |

**Note**: All directories are mounted as read-write, allowing you to:
- Add/remove input images
- Access and modify outputs
- Inspect and modify state files
- View and manage logs
- Add/remove/update models
- Edit configuration files

---

## Accessing the Dashboard

Once the container is running:

1. **Open browser**: `http://localhost:8092`
2. **Or from another machine**: `http://<server-ip>:8092`

The dashboard shows:
- Queue status
- GPU utilization
- Worker status
- Recent jobs

---

## Monitoring & Logs

### View Container Logs

```bash
# All logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Specific service
docker logs -f inference-pipeline
```

### Check Container Status

```bash
# Container status
docker ps

# Resource usage
docker stats inference-pipeline

# Health check status
docker inspect --format='{{.State.Health.Status}}' inference-pipeline
```

### Access Container Shell

```bash
# Interactive shell
docker exec -it inference-pipeline bash

# Run commands
docker exec inference-pipeline conda run -n inference python -c "import torch; print(torch.cuda.is_available())"
```

---

## Troubleshooting

### 1. **GPU Not Available**

**Symptoms**: Models run on CPU, slow performance

**Solution**:
```bash
# Verify nvidia-docker is installed
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu20.04 nvidia-smi

# Check container has GPU access
docker exec inference-pipeline conda run -n inference python -c "import torch; print(torch.cuda.device_count())"
```

### 2. **Permission Denied Errors**

**Symptoms**: Cannot write to mounted volumes

**Solution**:
```bash
# Fix permissions on host
sudo chown -R $USER:$USER artifacts/ state/ logs/

# Or run container with user mapping
docker run --user $(id -u):$(id -g) ...
```

### 3. **Config File Not Found**

**Symptoms**: Container exits immediately with config error

**Solution**:
- Ensure `config/pipeline.yaml` exists
- Check volume mount: `-v $(pwd)/config:/app/config`
- Verify paths in config use `/app/` prefix

### 4. **Models Not Found**

**Symptoms**: Model loading errors

**Solution**:
- Place model files in `models/` directory
- Check volume mount: `-v $(pwd)/models:/app/models`
- Verify model paths in `config/pipeline.yaml` use `/app/models/`

### 5. **Port Already in Use**

**Symptoms**: Cannot bind to port 8092

**Solution**:
```bash
# Change port in docker-compose.yml or use different port
docker run -p 8093:8092 ...

# Or stop conflicting service
sudo lsof -i :8092
```

### 6. **Out of Memory**

**Symptoms**: Container killed, OOM errors

**Solution**:
- Increase Docker memory limit
- Reduce `batch_size` in config
- Reduce `max_concurrent_jobs` in config
- Use fewer GPUs

---

## Production Deployment

### 1. **Use Docker Compose with Resource Limits**

```yaml
# docker-compose.yml
services:
  inference-pipeline:
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 16G
```

### 2. **Set Up Log Rotation**

```yaml
# Add to docker-compose.yml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

### 3. **Use Health Checks**

Health check is already configured in Dockerfile. Monitor with:
```bash
docker inspect --format='{{json .State.Health}}' inference-pipeline | jq
```

### 4. **Backup Important Data**

```bash
# Backup queue state
docker cp inference-pipeline:/app/state/queue.json ./backup/

# Backup artifacts
tar -czf artifacts-backup-$(date +%Y%m%d).tar.gz artifacts/
```

---

## Multi-GPU Setup

If you have multiple GPUs:

```yaml
# docker-compose.yml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          device_ids: ['0', '1']  # Specific GPUs
          capabilities: [gpu]
```

Or use all GPUs:
```yaml
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

---

## Environment Variables

You can override config via environment variables:

```bash
docker run -e DASHBOARD_PORT=9000 \
  -e JOB_TIMEOUT_SECONDS=7200 \
  ...
```

(Note: Currently, config is read from YAML. Environment variable support can be added if needed.)

---

## Building for Different Platforms

### CPU-Only Build

```dockerfile
# In Dockerfile.inference, change PyTorch installation:
RUN conda run -n inference pip install --no-cache-dir \
    torch==2.5.1 \
    torchvision==0.20.1 \
    torchaudio==2.5.1
# Remove --index-url flag for CPU version
```

### Different CUDA Versions

```dockerfile
# For CUDA 11.8:
--index-url https://download.pytorch.org/whl/cu118

# For CUDA 12.4:
--index-url https://download.pytorch.org/whl/cu124
```

---

## Quick Start Commands

```bash
# 1. Build
docker-compose build

# 2. Start
docker-compose up -d

# 3. Check status
docker-compose ps

# 4. View logs
docker-compose logs -f

# 5. Stop
docker-compose down

# 6. Rebuild after code changes
docker-compose up --build -d
```

---

## Summary

The Docker setup provides:
- ✅ Isolated environment with all dependencies
- ✅ GPU support via nvidia-docker
- ✅ Persistent data via volume mounts
- ✅ Easy deployment and scaling
- ✅ Health monitoring
- ✅ Dashboard access

All data, outputs, and state are persisted on the host via volume mounts, so container restarts don't lose progress.

