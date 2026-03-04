# Deep Analysis: Why torch.cuda.is_available() Returns False

## Problem Summary
- ✅ `nvidia-smi` works (GPU is visible to container)
- ❌ `torch.cuda.is_available()` returns `False`
- ✅ Working: `Dockerfile` + `docker-compose copy.yml`
- ❌ Not Working: `Dockerfile.inference` + `docker-compose.windows.yml`

## Critical Differences Found

### 1. Docker Compose Configuration Differences

#### Working (`docker-compose copy.yml`):
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
# NO CUDA_VISIBLE_DEVICES or NVIDIA_VISIBLE_DEVICES environment variables!
```

#### Not Working (`docker-compose.windows.yml`):
```yaml
environment:
  - CUDA_VISIBLE_DEVICES=all      # ⚠️ POTENTIAL ISSUE
  - NVIDIA_VISIBLE_DEVICES=all    # ⚠️ POTENTIAL ISSUE

deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

**KEY FINDING**: The working compose file does NOT set `CUDA_VISIBLE_DEVICES` or `NVIDIA_VISIBLE_DEVICES`. These environment variables might be interfering with PyTorch's CUDA detection!

### 2. Dockerfile Differences

#### Both Dockerfiles are nearly identical:
- ✅ Both use `ubuntu:20.04`
- ✅ Both use `conda run`
- ✅ Both install PyTorch the same way
- ✅ Both use Python 3.10.8

**No significant differences in Dockerfiles that would affect CUDA detection.**

## Root Cause Analysis

### Possible Reasons (Ranked by Likelihood)

#### 1. **Environment Variables Interference** (MOST LIKELY)
**Problem**: Setting `CUDA_VISIBLE_DEVICES=all` and `NVIDIA_VISIBLE_DEVICES=all` manually might conflict with nvidia-container-toolkit's automatic setup.

**Evidence**:
- Working compose file: NO CUDA environment variables
- Non-working compose file: HAS CUDA environment variables
- nvidia-container-toolkit automatically sets these when using `--gpus all`

**Solution**: Remove these environment variables and let nvidia-container-toolkit handle it.

#### 2. **Library Path Issues**
**Problem**: PyTorch can't find CUDA libraries even though they're mounted.

**Possible causes**:
- LD_LIBRARY_PATH not set correctly
- CUDA libraries in wrong location
- PyTorch looking in wrong place

**Check**: 
```bash
docker exec -it inference-pipeline find /usr -name "libcudart.so*" 2>/dev/null
docker exec -it inference-pipeline echo $LD_LIBRARY_PATH
```

#### 3. **PyTorch Installation Issue**
**Problem**: PyTorch was installed but CUDA support wasn't properly linked.

**Check**:
```bash
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print(torch.__version__); print(torch.version.cuda)"
```

Should show: `2.5.1+cu121` and `12.1`

#### 4. **Conda Environment Activation**
**Problem**: `conda run` might not be setting up library paths correctly.

**Check**: Compare working vs non-working container:
```bash
# Working container
docker exec -it sat-annotator-backend /opt/conda/bin/conda run -n sat-annotator python -c "import torch; print(torch.cuda.is_available())"

# Non-working container  
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print(torch.cuda.is_available())"
```

#### 5. **Docker Compose GPU Passthrough on Windows**
**Problem**: `deploy.resources.reservations.devices` might not work reliably on Windows Docker Desktop.

**Evidence**: The working `docker-compose copy.yml` uses the same approach, but it's running on a different system (possibly Linux).

**Solution**: Use `docker run --gpus all` instead (as recommended in `docker-run-gpu.bat`).

## Recommended Fixes (In Order)

### Fix 1: Remove CUDA Environment Variables (HIGHEST PRIORITY)

**In `docker-compose.windows.yml`**, remove these lines:
```yaml
environment:
  - CUDA_VISIBLE_DEVICES=all      # REMOVE THIS
  - NVIDIA_VISIBLE_DEVICES=all    # REMOVE THIS
```

**Why**: nvidia-container-toolkit automatically sets these when using `deploy.resources.reservations.devices`. Manually setting them can cause conflicts.

### Fix 2: Verify PyTorch Installation

Check if PyTorch was built with CUDA:
```bash
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print('Version:', torch.__version__); print('CUDA compiled:', torch.version.cuda); print('CUDA available:', torch.cuda.is_available())"
```

Expected:
- Version: `2.5.1+cu121`
- CUDA compiled: `12.1`
- CUDA available: `True` (after fix)

### Fix 3: Check Library Paths

```bash
# Check if CUDA libraries are accessible
docker exec -it inference-pipeline ls -la /usr/local/cuda*/lib64/libcudart.so* 2>/dev/null
docker exec -it inference-pipeline find /usr -name "libcudart.so*" 2>/dev/null

# Check LD_LIBRARY_PATH
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference bash -c "echo \$LD_LIBRARY_PATH"
```

### Fix 4: Use docker run Instead of docker-compose (Windows)

On Windows, `docker-compose` GPU passthrough is unreliable. Use:
```bash
docker run --gpus all ...
```

Or use the provided `docker-run-gpu.bat` script.

## Testing Steps

### Step 1: Remove Environment Variables
Edit `docker-compose.windows.yml` and remove `CUDA_VISIBLE_DEVICES` and `NVIDIA_VISIBLE_DEVICES`.

### Step 2: Rebuild and Test
```bash
docker-compose -f docker-compose.windows.yml down
docker-compose -f docker-compose.windows.yml build --no-cache
docker-compose -f docker-compose.windows.yml up -d
```

### Step 3: Verify
```bash
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

## Expected Result After Fix

```
CUDA available: True
```

## Why This Should Work

1. **No Environment Variable Conflicts**: Let nvidia-container-toolkit handle CUDA setup automatically
2. **Matches Working Configuration**: Same approach as `docker-compose copy.yml`
3. **Clean Setup**: No manual overrides that could interfere

## Additional Debugging Commands

If still not working after removing environment variables:

```bash
# 1. Check nvidia-smi
docker exec -it inference-pipeline nvidia-smi

# 2. Check PyTorch installation
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print(torch.__version__); print(torch.version.cuda)"

# 3. Check CUDA libraries
docker exec -it inference-pipeline find /usr -name "libcudart.so*" 2>/dev/null

# 4. Check environment in conda
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference env | grep -i cuda

# 5. Compare with working container
docker exec -it sat-annotator-backend /opt/conda/bin/conda run -n sat-annotator env | grep -i cuda
```

## Summary

**Most Likely Cause**: Environment variables `CUDA_VISIBLE_DEVICES=all` and `NVIDIA_VISIBLE_DEVICES=all` in `docker-compose.windows.yml` are interfering with PyTorch's CUDA detection.

**Solution**: Remove these environment variables and let nvidia-container-toolkit handle GPU setup automatically (matching the working `docker-compose copy.yml`).

