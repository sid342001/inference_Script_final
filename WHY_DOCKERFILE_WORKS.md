# Why Dockerfile Works But Dockerfile.inference Didn't

## Key Difference

### Dockerfile (Works ✅)
```dockerfile
FROM ubuntu:20.04
# No NVIDIA/CUDA environment variables
# No CUDA_HOME or LD_LIBRARY_PATH set
```

### Dockerfile.inference (Was Broken ❌)
```dockerfile
FROM nvidia/cuda:12.1.0-runtime-ubuntu20.04 AS base
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    CUDA_HOME=/usr/local/cuda \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH}
```

## Why This Matters

### How Docker GPU Passthrough Works

When you use `--gpus all` or `runtime: nvidia`:

1. **nvidia-container-toolkit** automatically:
   - Mounts CUDA libraries from the host into the container
   - Sets up proper library paths
   - Handles all CUDA runtime setup

2. **With plain Ubuntu base** (`ubuntu:20.04`):
   - ✅ nvidia-container-toolkit mounts host CUDA libraries
   - ✅ PyTorch finds them automatically
   - ✅ No conflicts or path issues

3. **With NVIDIA CUDA base image** (`nvidia/cuda:12.1.0-runtime-ubuntu20.04`):
   - ⚠️ Container has its own CUDA libraries
   - ⚠️ May conflict with host-mounted libraries
   - ⚠️ LD_LIBRARY_PATH might point to wrong location
   - ⚠️ Version mismatch possible

## The Solution

**Match Dockerfile approach**: Use plain Ubuntu and let nvidia-container-toolkit handle everything automatically.

### Updated Dockerfile.inference

```dockerfile
FROM ubuntu:20.04 AS base
# No CUDA-specific environment variables
# Let nvidia-container-toolkit handle CUDA setup
```

## Why This Works

1. **PyTorch includes CUDA binaries**: When you install PyTorch with `--index-url https://download.pytorch.org/whl/cu121`, it includes the CUDA binaries it needs
2. **nvidia-container-toolkit provides runtime**: The host CUDA libraries are automatically mounted
3. **No conflicts**: No competing CUDA installations
4. **Automatic path setup**: nvidia-container-toolkit sets up library paths correctly

## Key Insight

**You don't need CUDA in the Docker image** when using GPU passthrough. The host CUDA libraries are mounted automatically, and PyTorch's bundled CUDA binaries work with them.

## Verification

After rebuilding with plain Ubuntu base:

```bash
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

Should now work! ✅

## Best Practice

For Docker containers with GPU support:
- ✅ Use plain Ubuntu/Debian base
- ✅ Install PyTorch with CUDA support via pip
- ✅ Use `--gpus all` or `runtime: nvidia`
- ✅ Let nvidia-container-toolkit handle CUDA runtime
- ❌ Don't use NVIDIA CUDA base images (unless you need CUDA compiler tools)
- ❌ Don't manually set CUDA_HOME/LD_LIBRARY_PATH (unless necessary)

## Exception: When to Use NVIDIA CUDA Base Image

Only use `nvidia/cuda:*` base images if you need:
- CUDA compiler tools (nvcc)
- CUDA development libraries
- Building CUDA code in the container

For runtime-only (PyTorch inference), plain Ubuntu is better!

