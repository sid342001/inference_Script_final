# Dockerfile.inference Fix Summary

## Problem Identified

The issue was caused by two things:

1. **NVIDIA CUDA Base Image Contains Stub Libraries**: 
   - `nvidia/cuda:12.1.0-base-ubuntu20.04` includes fake/stub library files at `/usr/lib/x86_64-linux-gnu/libcuda.so`
   - PyTorch finds these stub files first, sees they're empty, and gives up
   - This prevents CUDA from being detected

2. **Clean Ubuntu Works Better**:
   - `ubuntu:20.04` is a clean OS with no stub libraries
   - When Docker starts with `--gpus all`, nvidia-container-toolkit injects the real driver
   - PyTorch finds the injected driver immediately because it's the only one there

## Solution Applied

### 1. Changed Base Image
```dockerfile
# Before (BROKEN)
FROM nvidia/cuda:12.1.0-base-ubuntu20.04 AS base

# After (FIXED)
FROM ubuntu:20.04 AS base
```

### 2. Removed NVIDIA Environment Variables
```dockerfile
# Removed these (not needed, can cause conflicts):
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
```

These are automatically set by nvidia-container-toolkit when using `--gpus all` or `runtime: nvidia`.

### 3. Entrypoint Already Correct
The `docker-entrypoint.sh` already uses `conda run` correctly:
```bash
exec /opt/conda/bin/conda run --no-capture-output -n inference python /app/run_pipeline.py --config "$CONFIG_FILE"
```

This ensures the conda environment is fully "hydrated" with all library paths before the application starts.

## Why This Works

1. **Clean OS**: No stub libraries to confuse PyTorch
2. **Real Drivers Injected**: nvidia-container-toolkit mounts real CUDA libraries from host
3. **Proper Activation**: `conda run` ensures all library paths are set correctly
4. **No Conflicts**: No competing CUDA installations or environment variables

## Verification

After rebuilding, verify GPU detection:

```bash
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

Should now print: `CUDA available: True` ✅

## Key Takeaway

**For Docker GPU support:**
- ✅ Use plain `ubuntu:20.04` (clean OS)
- ✅ Let nvidia-container-toolkit inject real drivers
- ✅ Use `conda run` to ensure proper environment activation
- ❌ Don't use NVIDIA CUDA base images (they contain stub libraries)
- ❌ Don't manually set NVIDIA environment variables (toolkit handles it)

