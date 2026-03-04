# Fix: CUDA Libraries Not Found in Docker Container

## Problem

- ✅ `nvidia-smi` works (GPU visible)
- ✅ PyTorch built with CUDA 12.1 (`2.5.1+cu121`)
- ❌ `torch.cuda.is_available()` = False
- ❌ No CUDA libraries found in container (`/usr/local/cuda` empty)

## Root Cause

The container doesn't have CUDA runtime libraries installed. When using Docker with GPU passthrough, you need either:
1. CUDA libraries installed in the container, OR
2. Use NVIDIA's CUDA base image (which includes them)

## Solution Applied

Changed the base image from `ubuntu:20.04` to `nvidia/cuda:12.1.0-runtime-ubuntu20.04`:

```dockerfile
# Before
FROM ubuntu:20.04 AS base

# After
FROM nvidia/cuda:12.1.0-runtime-ubuntu20.04 AS base
```

This base image includes:
- CUDA 12.1 runtime libraries
- Proper CUDA environment variables
- All necessary CUDA libraries in `/usr/local/cuda/lib64`

## Additional Changes

Added CUDA environment variables to ensure libraries are found:

```dockerfile
ENV CUDA_HOME=/usr/local/cuda \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH}
```

## Rebuild Instructions

### Step 1: Rebuild Docker Image

```bash
# Stop current container
docker-compose down

# Rebuild with CUDA base image
docker-compose -f docker-compose.linux.yml build --no-cache
# OR for Windows:
docker-compose -f docker-compose.windows.yml build --no-cache
```

### Step 2: Start Container

```bash
docker-compose -f docker-compose.linux.yml up -d
# OR for Windows:
docker-compose -f docker-compose.windows.yml up -d
```

### Step 3: Verify CUDA Libraries

```bash
# Check CUDA libraries are present
docker exec -it inference-pipeline ls -la /usr/local/cuda/lib64/libcudart.so*

# Should show: libcudart.so.12.1.xx
```

### Step 4: Verify PyTorch CUDA

```bash
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

**Expected output:**
```
CUDA available: True
```

## Why This Works

1. **NVIDIA CUDA Base Image**: Includes all CUDA 12.1 runtime libraries
2. **Proper Paths**: Sets `CUDA_HOME` and `LD_LIBRARY_PATH` correctly
3. **Version Match**: CUDA 12.1 in base image matches PyTorch's CUDA 12.1 build

## Image Size Impact

- **Before**: ~3-4 GB (Ubuntu base)
- **After**: ~4-5 GB (NVIDIA CUDA base)
- **Increase**: ~1 GB (worth it for GPU support!)

## Alternative Solutions (If This Doesn't Work)

### Option 1: Install CUDA Toolkit in Container

If you prefer to stay on Ubuntu base:

```dockerfile
# Add after system dependencies
RUN apt-get update && apt-get install -y \
    cuda-toolkit-12-1 \
    && rm -rf /var/lib/apt/lists/*

ENV CUDA_HOME=/usr/local/cuda-12.1
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}
```

### Option 2: Use CUDA Devel Image (Larger)

For development/debugging:

```dockerfile
FROM nvidia/cuda:12.1.0-devel-ubuntu20.04 AS base
```

Includes CUDA compiler tools (larger image, ~6-7 GB).

## Verification Checklist

After rebuilding, verify:

- [ ] `nvidia-smi` works in container
- [ ] `/usr/local/cuda/lib64/libcudart.so*` exists
- [ ] `torch.cuda.is_available()` returns `True`
- [ ] Pipeline logs show "CUDA available: True"
- [ ] Models load on GPU (not CPU)

## Expected Log Output (Success)

```
2025-11-27 13:30:00,000 | INFO | inference_runner | PyTorch CUDA available: True
2025-11-27 13:30:00,001 | INFO | inference_runner | PyTorch detected 1 GPU(s)
2025-11-27 13:30:00,002 | INFO | inference_runner |   - GPU 0: NVIDIA GeForce RTX 3090
2025-11-27 13:30:00,003 | INFO | inference_runner | Hybrid mode enabled: Loading all models on all GPUs
2025-11-27 13:30:05,000 | INFO | inference_runner | Loaded 2 models on 1 GPUs
```

## Troubleshooting

### Still Not Working?

1. **Check Docker GPU Setup**:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu20.04 nvidia-smi
   ```

2. **Verify Base Image**:
   ```bash
   docker exec -it inference-pipeline cat /usr/local/cuda/version.txt
   # Should show: CUDA Version 12.1.xx
   ```

3. **Check Library Paths**:
   ```bash
   docker exec -it inference-pipeline echo $LD_LIBRARY_PATH
   docker exec -it inference-pipeline echo $CUDA_HOME
   ```

4. **Test CUDA Directly**:
   ```bash
   docker exec -it inference-pipeline /usr/local/cuda/bin/nvcc --version
   ```

The NVIDIA CUDA base image should solve the issue! 🚀

