# GPU Detection Debugging Guide

## Issue: GPU Not Detected in Docker

If GPUs are not being detected, it's usually **not a config file issue** - it's a Docker GPU passthrough issue. However, the config file must be correct for the pipeline to use GPUs when they are available.

## What Was Fixed

1. **Path Mismatch**: Fixed `input_dir` from `/app/data/scheduled` to `/app/data/incoming` to match Docker volume mounts
2. **Enhanced Logging**: Added detailed GPU detection diagnostics

## Config File Structure

Your `pipeline.yaml` should have this structure for GPUs:

```yaml
gpus:
  - id: "gpu0"
    device: "cuda:0"
  # Add more GPUs if you have them:
  # - id: "gpu1"
  #   device: "cuda:1"
```

**Important**: The `id` field is optional - if missing, it uses the `device` value as the key.

## Debugging Steps

### 1. Check Config File is Loaded

When the pipeline starts, you should see logs like:
```
GPU Configuration: 1 GPU(s) declared in config
  - gpu0: cuda:0
```

If you don't see this, the config file might not be loading correctly.

### 2. Check PyTorch CUDA Detection

Look for these logs:
```
PyTorch CUDA available: True/False
PyTorch detected X GPU(s)
  - GPU 0: [GPU Name]
```

- If `CUDA available: False` → Docker GPU passthrough is not working
- If `CUDA available: True` but no GPUs listed → GPU drivers not installed in container

### 3. Test GPU in Docker Container

```bash
# Enter the container
docker exec -it inference-pipeline bash

# Check if nvidia-smi works
nvidia-smi

# Check PyTorch CUDA
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"
```

### 4. Verify Docker GPU Setup

#### Linux:
```bash
# Check if nvidia-docker2 is installed
dpkg -l | grep nvidia-docker

# Check if runtime is set
docker info | grep -i runtime

# Should show: nvidia
```

#### Windows (Docker Desktop):
1. Open Docker Desktop Settings
2. Go to Resources → WSL Integration
3. Ensure WSL2 backend is enabled
4. Check if GPU support is enabled (varies by Docker Desktop version)

### 5. Check Docker Run Command

#### Linux:
```bash
# Should use: runtime: nvidia
docker-compose -f docker-compose.linux.yml up -d
```

#### Windows:
```bash
# Use the batch script for reliable GPU support
docker-run-gpu.bat

# OR manually:
docker run --gpus all ...
```

## Common Issues

### Issue 1: Config File Not Found
**Symptom**: Pipeline uses default config or fails to start
**Solution**: Ensure config is mounted at `/app/config/pipeline.yaml`

### Issue 2: CUDA Not Available
**Symptom**: Logs show "CUDA available: False"
**Causes**:
- Docker GPU passthrough not configured
- NVIDIA drivers not installed on host
- Docker runtime not set to `nvidia` (Linux)
- `--gpus all` flag not used (Windows)

**Solutions**:
- **Linux**: Install `nvidia-docker2` and use `runtime: nvidia`
- **Windows**: Use `docker-run-gpu.bat` or `docker run --gpus all`

### Issue 3: GPU Count Mismatch
**Symptom**: Config declares GPU but PyTorch doesn't see it
**Solution**: Ensure the GPU device ID in config matches actual GPU (e.g., `cuda:0` for first GPU)

### Issue 4: Models Fall Back to CPU
**Symptom**: Models load but use CPU instead of GPU
**Cause**: GPU detection failed, but pipeline continues with CPU fallback
**Solution**: Check the logs for GPU detection warnings

## Expected Log Output (Success)

```
2025-11-27 10:00:00,000 | INFO | inference_runner | GPU Configuration: 1 GPU(s) declared in config
2025-11-27 10:00:00,001 | INFO | inference_runner |   - gpu0: cuda:0
2025-11-27 10:00:00,002 | INFO | inference_runner | PyTorch CUDA available: True
2025-11-27 10:00:00,003 | INFO | inference_runner | PyTorch detected 1 GPU(s)
2025-11-27 10:00:00,004 | INFO | inference_runner |   - GPU 0: NVIDIA GeForce RTX 3090
2025-11-27 10:00:00,005 | INFO | inference_runner | Hybrid mode enabled: Loading all models on all GPUs
2025-11-27 10:00:05,000 | INFO | inference_runner | Loaded 2 models on 1 GPUs
```

## Expected Log Output (Failure - CPU Fallback)

```
2025-11-27 10:00:00,000 | INFO | inference_runner | GPU Configuration: 1 GPU(s) declared in config
2025-11-27 10:00:00,001 | INFO | inference_runner |   - gpu0: cuda:0
2025-11-27 10:00:00,002 | INFO | inference_runner | PyTorch CUDA available: False
2025-11-27 10:00:00,003 | WARNING | inference_runner | GPUs configured in config (['cuda:0']) but CUDA is not available...
2025-11-27 10:00:00,004 | INFO | inference_runner | Falling back to CPU mode
```

## Quick Test Commands

```bash
# Test GPU in container (Linux)
docker exec inference-pipeline nvidia-smi

# Test GPU in container (Windows - use docker-run-gpu.bat first)
docker exec inference-pipeline nvidia-smi

# Check container logs for GPU detection
docker logs inference-pipeline | grep -i "gpu\|cuda"

# Test PyTorch CUDA in container
docker exec inference-pipeline python -c "import torch; print(torch.cuda.is_available())"
```

## Next Steps

1. **Check the logs** - Look for the new diagnostic messages
2. **Verify Docker GPU setup** - Use the commands above
3. **Test in container** - Run `nvidia-smi` and PyTorch CUDA check
4. **Review Docker configuration** - Ensure GPU passthrough is enabled

The config file structure is correct - the issue is almost certainly Docker GPU passthrough configuration.

