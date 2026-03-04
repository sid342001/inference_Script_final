# Docker Environment Matching Conda Environment

## Overview

The Dockerfile has been updated to match your conda `inference` environment exactly, using:
- **PyTorch 2.5.1 with CUDA 12.1** via conda (pytorch channel)
- **Ultralytics** from local `Ultralytics/ultralytics2` folder (not downloaded)
- Same Python 3.10 environment

## What Changed

### PyTorch Installation (Lines 77-86)

**Before:** Installed via pip with CUDA 11.8
```dockerfile
RUN conda run -n inference pip install --no-cache-dir \
    torch==2.5.1 \
    torchvision==0.20.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu118
```

**After:** Installed via conda (matching your environment)
```dockerfile
# Install PyTorch with CUDA 12.1 via conda (matching user's conda environment)
RUN conda run -n inference conda install -c pytorch \
    pytorch==2.5.1 \
    pytorch-cuda=12.1 \
    pytorch-mutex \
    -y

# Install torchvision and torchaudio via pip (as they're from pypi in user's environment)
RUN conda run -n inference pip install --no-cache-dir \
    torchvision==0.20.1 \
    torchaudio==2.5.1
```

### Conda Channels (Line 58-61)

Added `pytorch` channel before `conda-forge`:
```dockerfile
RUN conda config --set channel_priority strict && \
    conda config --add channels pytorch && \
    conda config --add channels conda-forge && \
    ...
```

### Ultralytics Installation (Lines 103-106)

**Unchanged** - Already correctly installs from local folder:
```dockerfile
# Copy custom Ultralytics package
COPY Ultralytics/ultralytics2 /app/Ultralytics/ultralytics2

# Install custom ultralytics in editable mode
RUN conda run -n inference pip install --no-cache-dir -e /app/Ultralytics/ultralytics2
```

## Package Versions (Matching Your Conda Environment)

| Package | Version | Source | Docker Installation |
|---------|---------|--------|---------------------|
| pytorch | 2.5.1 | pytorch (conda) | `conda install -c pytorch pytorch==2.5.1` |
| pytorch-cuda | 12.1 | pytorch (conda) | `conda install -c pytorch pytorch-cuda=12.1` |
| pytorch-mutex | 1.0 | pytorch (conda) | `conda install -c pytorch pytorch-mutex` |
| torchvision | 0.20.1 | pypi | `pip install torchvision==0.20.1` |
| torchaudio | 2.5.1 | pypi | `pip install torchaudio==2.5.1` |
| ultralytics | local | Ultralytics/ultralytics2 | `pip install -e /app/Ultralytics/ultralytics2` |

## Build Instructions

### 1. Rebuild Docker Image

```bash
# Linux
docker-compose -f docker-compose.linux.yml build --no-cache

# Windows
docker-compose -f docker-compose.windows.yml build --no-cache

# Or manually
docker build -f Dockerfile.inference -t satellite-inference-pipeline:latest .
```

### 2. Verify Installation

After building, test PyTorch CUDA:

```bash
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('CUDA version:', torch.version.cuda)"
```

Expected output:
```
PyTorch: 2.5.1+cu121
CUDA available: True
CUDA version: 12.1
```

### 3. Verify Ultralytics

```bash
docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import ultralytics; print('Ultralytics:', ultralytics.__version__); print('Path:', ultralytics.__file__)"
```

Should show the installed version and path pointing to `/app/Ultralytics/ultralytics2`.

## Key Differences from Previous Version

1. **PyTorch Source**: Now uses conda (pytorch channel) instead of pip
2. **CUDA Version**: Matches your environment (12.1) instead of 11.8
3. **Package Split**: 
   - PyTorch core packages (pytorch, pytorch-cuda, pytorch-mutex) from conda
   - Extension packages (torchvision, torchaudio) from pip (matching your setup)

## Why This Approach?

- **Matches your conda environment exactly** - Same packages, same versions, same sources
- **Better CUDA compatibility** - Conda PyTorch packages are better integrated with CUDA
- **Local Ultralytics** - Uses your custom Ultralytics package, not downloaded version
- **Reproducible** - Same environment every time you build

## Troubleshooting

### If CUDA still not available:

1. **Check host CUDA version**:
   ```bash
   nvidia-smi  # Check driver version
   nvcc --version  # Check CUDA toolkit version
   ```

2. **Verify Docker GPU passthrough**:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu20.04 nvidia-smi
   ```

3. **Check container CUDA**:
   ```bash
   docker exec -it inference-pipeline nvidia-smi
   docker exec -it inference-pipeline /opt/conda/bin/conda run -n inference python -c "import torch; print(torch.cuda.is_available())"
   ```

### If build fails:

- Ensure `Ultralytics/ultralytics2` folder exists and contains the package
- Check conda channel access (pytorch channel should be accessible)
- Verify Python 3.10 is available in conda

## Next Steps

1. Rebuild the Docker image with the updated Dockerfile
2. Test CUDA availability
3. Run the pipeline and verify GPU usage
4. Check logs for any CUDA-related warnings

The environment should now match your conda setup exactly! 🚀

