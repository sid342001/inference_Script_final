# Docker GPU Setup for Windows

## Issue

Docker Desktop on Windows doesn't support `runtime: nvidia` (that's for Linux Docker). You need to use WSL2 backend with GPU support.

## Solution

### Option 1: Use WSL2 Backend (Recommended for Windows)

1. **Enable WSL2 in Docker Desktop:**
   - Open Docker Desktop
   - Go to Settings → General
   - Check "Use the WSL 2 based engine"
   - Apply & Restart

2. **Install NVIDIA Drivers for WSL2:**
   - Download and install: https://www.nvidia.com/Download/index.aspx
   - Install the **WSL driver** (not the regular Windows driver)
   - The driver should be version 510.47.03 or later

3. **Verify GPU in WSL2:**
   ```bash
   # Open WSL2 terminal
   wsl
   
   # Check GPU
   nvidia-smi
   ```

4. **Update docker-compose.yml:**
   The file has been updated to use `deploy.resources.reservations.devices` instead of `runtime: nvidia`.

5. **Restart Docker:**
   ```bash
   docker-compose down
   docker-compose up -d
   ```

### Option 2: Use Linux Docker (If Available)

If you have access to a Linux machine or VM:

1. Install nvidia-docker2:
   ```bash
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
   
   sudo apt-get update
   sudo apt-get install -y nvidia-docker2
   sudo systemctl restart docker
   ```

2. Use `runtime: nvidia` in docker-compose.yml (for Linux only)

### Option 3: Use CPU Mode (Fallback)

The code now automatically falls back to CPU if GPUs aren't available. You can:

1. Remove GPU configuration from docker-compose.yml
2. The pipeline will detect no GPUs and use CPU automatically
3. Processing will be slower but will work

## Verify GPU Access in Container

```bash
# Enter container
docker exec -it inference-pipeline bash

# Check CUDA
conda run -n inference python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}, Devices: {torch.cuda.device_count()}')"

# Check nvidia-smi (if available)
nvidia-smi
```

## Troubleshooting

### "No CUDA GPUs are available" in Container

**Check 1: WSL2 Backend**
```bash
# In Docker Desktop, verify WSL2 is enabled
# Settings → General → "Use the WSL 2 based engine"
```

**Check 2: NVIDIA WSL Driver**
```bash
# In WSL2 terminal
wsl
nvidia-smi
# Should show GPU, if not, install WSL driver
```

**Check 3: Docker GPU Support**
```bash
# Test GPU in container
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu20.04 nvidia-smi
```

**Check 4: docker-compose.yml**
- Make sure `deploy.resources.reservations.devices` is configured
- For Windows, don't use `runtime: nvidia`

### Container Falls Back to CPU

This is expected if:
- WSL2 backend not enabled
- NVIDIA WSL driver not installed
- GPU not accessible in WSL2

The pipeline will log:
```
WARNING: GPUs configured but CUDA is not available. Falling back to CPU.
```

Processing will continue on CPU (slower but functional).

## Windows-Specific Notes

- Docker Desktop on Windows uses WSL2 backend for GPU support
- You need NVIDIA drivers installed **in WSL2**, not just Windows
- The WSL driver is different from the regular Windows driver
- GPU passthrough works through WSL2, not directly from Windows

## Summary

For Windows:
1. ✅ Enable WSL2 backend in Docker Desktop
2. ✅ Install NVIDIA WSL driver
3. ✅ Use `deploy.resources.reservations.devices` (not `runtime: nvidia`)
4. ✅ Verify with `nvidia-smi` in WSL2
5. ✅ Restart Docker containers

The code will automatically fall back to CPU if GPUs aren't available, so the pipeline will work either way.

