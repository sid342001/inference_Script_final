# Windows GPU Support Fix

## Problem

Docker Compose on Windows doesn't reliably support GPU passthrough, even with `deploy.resources.reservations.devices`. The container falls back to CPU.

## Solution: Use `docker run` with `--gpus all`

Docker Compose on Windows has limited GPU support. The most reliable way is to use `docker run` directly with the `--gpus all` flag.

## Quick Fix

### Step 1: Stop Current Container

```bash
docker-compose -f docker-compose.windows.yml down
# OR if using default compose file:
docker stop inference-pipeline
docker rm inference-pipeline
```

### Step 2: Use GPU Script

```bash
docker-run-gpu.bat
```

This script uses `docker run --gpus all` which works reliably on Windows Docker Desktop with WSL2 backend.

### Step 3: Verify GPU Access

```bash
docker exec -it inference-pipeline bash
conda run -n inference python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, Devices: {torch.cuda.device_count()}')"
```

Should show: `CUDA: True, Devices: 1`

## Manual Command (Alternative)

If you prefer to run manually:

```bash
docker run -d --name inference-pipeline --gpus all \
  -e PYTHONUNBUFFERED=1 \
  -e CUDA_VISIBLE_DEVICES=all \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\scheduled:/app/data/incoming" \
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\artifacts:/app/artifacts" \
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\state:/app/state" \
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\logs:/app/logs" \
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\models:/app/models" \
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\config:/app/config" \
  -p 8092:8092 \
  satellite-inference-pipeline:latest
```

## Why Docker Compose Doesn't Work

1. **Docker Compose on Windows** doesn't fully support the `deploy.resources.reservations.devices` syntax for GPU
2. **WSL2 Backend** requires `--gpus all` flag, which docker-compose may not pass through correctly
3. **Direct `docker run`** with `--gpus all` is the most reliable method on Windows

## Prerequisites

1. **WSL2 Backend Enabled** in Docker Desktop
   - Settings → General → "Use the WSL 2 based engine"

2. **NVIDIA WSL Driver Installed**
   - Download from: https://www.nvidia.com/Download/index.aspx
   - Install the **WSL driver** (not the regular Windows driver)
   - Verify: `wsl nvidia-smi` should show your GPU

3. **Docker Desktop Updated**
   - Use latest version of Docker Desktop
   - Ensure WSL2 integration is enabled

## Troubleshooting

### GPU Still Not Detected

1. **Check WSL2 GPU Access:**
   ```bash
   wsl
   nvidia-smi
   ```
   Should show your GPU. If not, install NVIDIA WSL driver.

2. **Test Docker GPU:**
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu20.04 nvidia-smi
   ```
   Should show GPU. If not, Docker Desktop GPU support isn't working.

3. **Check Docker Desktop Settings:**
   - Settings → Resources → WSL Integration
   - Ensure your WSL2 distribution is enabled

### Container Falls Back to CPU

This is expected if:
- WSL2 backend not enabled
- NVIDIA WSL driver not installed
- Docker Desktop doesn't support GPU passthrough

The pipeline will continue on CPU (slower but functional).

## Summary

**For Windows with GPU:**
- ✅ Use `docker-run-gpu.bat` (recommended)
- ✅ Or use `docker run --gpus all` manually
- ❌ Don't rely on `docker-compose` for GPU on Windows

**For Windows without GPU:**
- ✅ Use `docker-compose -f docker-compose.windows.yml up -d`
- ✅ Pipeline automatically uses CPU

