#!/bin/bash
# Quick fix script to check and fix PyTorch CUDA in Docker
# Run this inside the container or as a one-liner

echo "=== PyTorch CUDA Diagnostic ==="
echo ""

# Check nvidia-smi
echo "1. NVIDIA-SMI:"
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1 || echo "  nvidia-smi failed"

# Check PyTorch
echo ""
echo "2. PyTorch:"
python -c "import torch; print(f'  Version: {torch.__version__}'); print(f'  CUDA available: {torch.cuda.is_available()}'); print(f'  Built for CUDA: {torch.version.cuda}')" 2>/dev/null || echo "  PyTorch not found"

# Check CUDA libraries
echo ""
echo "3. CUDA Libraries:"
find /usr/local -name "libcudart.so*" 2>/dev/null | head -3 || echo "  No CUDA libraries found in /usr/local"
find /usr/lib -name "libcudart.so*" 2>/dev/null | head -3 || echo "  No CUDA libraries found in /usr/lib"

# Check LD_LIBRARY_PATH
echo ""
echo "4. Environment:"
echo "  LD_LIBRARY_PATH: ${LD_LIBRARY_PATH:-NOT SET}"
echo "  CUDA_HOME: ${CUDA_HOME:-NOT SET}"
echo "  PATH: ${PATH:0:100}..."

echo ""
echo "=== Diagnostic Complete ==="

