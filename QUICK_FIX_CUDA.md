# Quick Fix: PyTorch CUDA Not Available

## Problem
- ✅ `nvidia-smi` works
- ❌ `torch.cuda.is_available()` = False
- PyTorch version: 2.5.1+cu121 (built for CUDA 12.1)

## Root Cause
Your host system likely has **CUDA 11.8**, but PyTorch was built for **CUDA 12.1**. They need to match.

## Solution: Rebuild with CUDA 11.8

I've updated the Dockerfile to use CUDA 11.8 (most compatible). Now rebuild:

### Step 1: Rebuild the Docker Image

**Linux:**
```bash
docker-compose -f docker-compose.linux.yml build --no-cache
```

**Windows:**
```bash
docker-compose -f docker-compose.windows.yml build --no-cache
```

**Or manually:**
```bash
docker build -f Dockerfile.inference -t satellite-inference-pipeline:latest .
```

### Step 2: Restart Container

```bash
# Stop existing container
docker-compose down

# Start with new image
docker-compose -f docker-compose.linux.yml up -d
# OR for Windows
docker-compose -f docker-compose.windows.yml up -d
```

### Step 3: Verify Fix

```bash
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

Should now print: `CUDA available: True`

## If Still Not Working

### Option A: Check Your Host CUDA Version

**Linux:**
```bash
nvcc --version
cat /usr/local/cuda/version.txt
```

**Windows (WSL2):**
```bash
wsl
nvcc --version
```

### Option B: Match PyTorch to Your CUDA Version

If your host has:
- **CUDA 11.8** → Use `cu118` (already updated in Dockerfile)
- **CUDA 12.0** → Change Dockerfile to use `cu120`
- **CUDA 12.1** → Change Dockerfile to use `cu121`

Edit `Dockerfile.inference` line 82, change `cu118` to match your CUDA version.

### Option C: Use CPU (Temporary)

If you need it working immediately, edit your `pipeline.yaml`:

```yaml
gpus:
  - id: "cpu"
    device: "cpu"

models:
  - name: "Yolo_plane_x"
    device: "cpu"  # Change from cuda:0
```

## What Changed

The Dockerfile now installs PyTorch with CUDA 11.8 support instead of 12.1:

```dockerfile
# Before: --index-url https://download.pytorch.org/whl/cu121
# After:  --index-url https://download.pytorch.org/whl/cu118
```

This is more compatible with most systems.

## Expected Result

After rebuilding:
```
PyTorch: 2.5.1+cu118
CUDA available: True
GPU count: 1
```

Then your pipeline will use GPU! 🚀

