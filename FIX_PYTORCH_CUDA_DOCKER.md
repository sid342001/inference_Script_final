# Fix: PyTorch CUDA Not Available in Docker (nvidia-smi works)

## Problem

- ✅ `nvidia-smi` works in container (GPU is visible)
- ❌ `torch.cuda.is_available()` returns `False` (PyTorch can't use GPU)

This means Docker GPU passthrough is working, but PyTorch can't find the CUDA libraries.

## Root Cause

PyTorch was installed with CUDA 12.1 support, but at runtime it can't find the CUDA libraries from the host system. This happens when:

1. CUDA version mismatch between PyTorch build and host CUDA
2. CUDA libraries not properly mounted/accessible in container
3. LD_LIBRARY_PATH not set correctly

## Solution 1: Verify CUDA Version Compatibility

### Step 1: Check Host CUDA Version

On your **host machine** (outside Docker):

```bash
# Linux
nvcc --version
# OR
cat /usr/local/cuda/version.txt

# Windows (in WSL2 if using Docker Desktop)
nvcc --version
```

### Step 2: Check PyTorch CUDA Version in Container

```bash
docker exec -it inference-pipeline bash
python -c "import torch; print(torch.version.cuda)"
```

### Step 3: Compare Versions

- If host CUDA is **12.1** → Should work (PyTorch was built for 12.1)
- If host CUDA is **12.0** → Might work (backward compatible)
- If host CUDA is **11.x** → **Won't work** (need to rebuild PyTorch for 11.x)

## Solution 2: Rebuild PyTorch for Your CUDA Version

If your host CUDA is **11.8** (most common), rebuild the Docker image with CUDA 11.8:

### Update Dockerfile.inference

Change this line:
```dockerfile
# Install PyTorch (GPU version with CUDA 12.1)
RUN conda run -n inference pip install --no-cache-dir \
    torch==2.5.1 \
    torchvision==0.20.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu121
```

To (for CUDA 11.8):
```dockerfile
# Install PyTorch (GPU version with CUDA 11.8)
RUN conda run -n inference pip install --no-cache-dir \
    torch==2.5.1 \
    torchvision==0.20.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu118
```

Or (for CUDA 12.0):
```dockerfile
# Install PyTorch (GPU version with CUDA 12.0)
RUN conda run -n inference pip install --no-cache-dir \
    torch==2.5.1 \
    torchvision==0.20.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu120
```

### Rebuild Image

```bash
docker-compose -f docker-compose.linux.yml build --no-cache
# OR for Windows
docker-compose -f docker-compose.windows.yml build --no-cache
```

## Solution 3: Install CUDA Libraries in Container (Alternative)

If you can't match versions, install CUDA libraries directly in the container:

### Add to Dockerfile.inference (before PyTorch installation):

```dockerfile
# Install CUDA toolkit (matches PyTorch CUDA version)
RUN apt-get update && apt-get install -y \
    cuda-toolkit-12-1 \
    && rm -rf /var/lib/apt/lists/*

# Set CUDA paths
ENV CUDA_HOME=/usr/local/cuda-12.1
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}
```

**Note**: This increases image size significantly (~2-3 GB).

## Solution 4: Use CUDA Base Image (Recommended for Production)

Use NVIDIA's CUDA base image which already has CUDA libraries:

```dockerfile
FROM nvidia/cuda:12.1.0-runtime-ubuntu20.04 AS base
# ... rest of Dockerfile
```

This ensures CUDA libraries are always available and match the runtime.

## Quick Diagnostic

Run this inside your container:

```bash
docker exec -it inference-pipeline bash

# Copy the diagnostic script
# (or run commands manually)

# Check nvidia-smi
nvidia-smi

# Check PyTorch
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}'); print(f'Version: {torch.version.cuda}')"

# Check CUDA libraries
ls -la /usr/local/cuda*/lib64/libcudart.so* 2>/dev/null || echo "No CUDA libs found"
```

Or use the provided diagnostic script:

```bash
# Copy test_cuda.py into container first
docker cp test_cuda.py inference-pipeline:/app/
docker exec -it inference-pipeline python /app/test_cuda.py
```

## Most Likely Fix

**For most users**: Your host has CUDA 11.8, but PyTorch was built for 12.1.

**Fix**: Change the Dockerfile to install PyTorch with CUDA 11.8:

```dockerfile
RUN conda run -n inference pip install --no-cache-dir \
    torch==2.5.1 \
    torchvision==0.20.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu118
```

Then rebuild:
```bash
docker-compose build --no-cache
```

## Verify Fix

After rebuilding, test:

```bash
docker exec -it inference-pipeline python -c "import torch; print(torch.cuda.is_available())"
# Should print: True
```

## Common CUDA Versions

| Host CUDA | PyTorch Index URL | Notes |
|-----------|-------------------|-------|
| 11.8 | `cu118` | Most common |
| 12.0 | `cu120` | Newer systems |
| 12.1 | `cu121` | Latest (what Dockerfile currently uses) |
| 11.7 | `cu117` | Older systems |

## Still Not Working?

1. **Check Docker GPU setup**:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu20.04 nvidia-smi
   ```

2. **Check nvidia-container-toolkit** (Linux):
   ```bash
   docker info | grep -i runtime
   # Should show: nvidia
   ```

3. **Check Windows Docker Desktop**:
   - Settings → Resources → WSL Integration
   - Ensure GPU support is enabled

4. **Try CPU fallback** (temporary):
   - Set all `device: "cuda:0"` to `device: "cpu"` in config
   - Pipeline will work but slower

