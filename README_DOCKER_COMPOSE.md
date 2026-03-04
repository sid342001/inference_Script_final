# Docker Compose Files Guide

This project includes platform-specific Docker Compose files for different operating systems.

## Available Files

### 1. `docker-compose.linux.yml` - For Linux
- Uses `runtime: nvidia` (requires nvidia-docker2)
- Full GPU support
- **Usage**: `docker-compose -f docker-compose.linux.yml up -d`

### 2. `docker-compose.windows.yml` - For Windows
- CPU mode (GPU may not work in docker-compose on Windows)
- For GPU support, use `docker-run-gpu.bat` instead
- **Usage**: `docker-compose -f docker-compose.windows.yml up -d`

### 3. `docker-compose.yml` - Default/Reference
- Platform-agnostic template
- Use platform-specific files instead

### 4. `docker-run-gpu.bat` - Windows GPU Support
- Batch script for Windows with GPU support
- Uses `docker run --gpus all` flag
- **Usage**: Run `docker-run-gpu.bat` from command prompt

---

## Quick Start

### Linux

```bash
# 1. Install nvidia-docker2 (if not already installed)
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update
sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker

# 2. Build and run
docker-compose -f docker-compose.linux.yml build
docker-compose -f docker-compose.linux.yml up -d

# 3. Check logs
docker-compose -f docker-compose.linux.yml logs -f
```

### Windows

**Option A: CPU Mode (docker-compose)**
```bash
# Build and run (CPU mode)
docker-compose -f docker-compose.windows.yml build
docker-compose -f docker-compose.windows.yml up -d

# Check logs
docker-compose -f docker-compose.windows.yml logs -f
```

**Option B: GPU Mode (recommended)**
```bash
# Stop any existing container
docker stop inference-pipeline
docker rm inference-pipeline

# Run with GPU support
docker-run-gpu.bat

# Or manually:
docker run -d --name inference-pipeline --gpus all \
  -e PYTHONUNBUFFERED=1 \
  -e CUDA_VISIBLE_DEVICES=all \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -v "%CD%\data\incoming:/app/data/incoming" \
  -v "%CD%\artifacts:/app/artifacts" \
  -v "%CD%\state:/app/state" \
  -v "%CD%\logs:/app/logs" \
  -v "%CD%\models:/app/models" \
  -v "%CD%\config:/app/config" \
  -p 8092:8092 \
  satellite-inference-pipeline:latest

# Check logs
docker logs -f inference-pipeline
```

---

## Platform Differences

| Feature | Linux | Windows |
|---------|-------|---------|
| GPU Support | `runtime: nvidia` | `--gpus all` flag |
| Docker Compose GPU | ✅ Yes | ⚠️ Limited/Unreliable |
| Requires | nvidia-docker2 | WSL2 backend + NVIDIA WSL driver |
| Recommended Method | docker-compose | docker-run-gpu.bat |

---

## Verify GPU Access

### Linux
```bash
docker exec inference-pipeline conda run -n inference python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, Devices: {torch.cuda.device_count()}')"
```

### Windows
```bash
docker exec inference-pipeline conda run -n inference python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, Devices: {torch.cuda.device_count()}')"
```

Both should show `CUDA: True, Devices: 1` (or more) if GPU is working.

---

## Troubleshooting

### Linux: "runtime: nvidia" not found
- Install nvidia-docker2: `sudo apt-get install nvidia-docker2`
- Restart Docker: `sudo systemctl restart docker`

### Windows: GPU not detected
- Ensure WSL2 backend is enabled in Docker Desktop
- Install NVIDIA WSL driver (different from Windows driver)
- Use `docker-run-gpu.bat` instead of docker-compose
- Check: `wsl nvidia-smi` should show GPU

### Both: Falls back to CPU
- The pipeline automatically falls back to CPU if GPU unavailable
- Check logs for warnings
- Processing will continue (slower but functional)

---

## Volume Paths

### Linux
- Use relative paths: `./data/incoming`
- Or absolute Linux paths: `/home/user/data/incoming`

### Windows
- Use relative paths: `./data/incoming`
- Or absolute Windows paths: `D:\path\to\data\incoming`
- Docker Desktop handles path conversion automatically

---

## Summary

- **Linux**: Use `docker-compose.linux.yml` with `runtime: nvidia`
- **Windows**: Use `docker-run-gpu.bat` for GPU, or `docker-compose.windows.yml` for CPU
- **Both**: Pipeline automatically handles GPU/CPU fallback gracefully

