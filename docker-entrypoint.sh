#!/bin/bash
# Docker entrypoint script for Satellite Inference Pipeline
# Handles config file selection and pipeline startup
# 
# Config priority:
# 1. User-mounted config/pipeline.yaml (if exists)
# 2. Default config/pipeline.yaml.default (shipped with image)

set -e

CONFIG_DIR="/app/config"
DEFAULT_CONFIG="${CONFIG_DIR}/pipeline.yaml.default"
USER_CONFIG="${CONFIG_DIR}/pipeline.yaml"

# If user has mounted their own config, use it; otherwise use default
if [ -f "$USER_CONFIG" ]; then
    echo "✓ Using user-provided config: $USER_CONFIG"
    CONFIG_FILE="$USER_CONFIG"
elif [ -f "$DEFAULT_CONFIG" ]; then
    echo "ℹ No user config found at $USER_CONFIG"
    echo "✓ Using default config: $DEFAULT_CONFIG"
    echo "  (Mount your own config/pipeline.yaml to override)"
    CONFIG_FILE="$DEFAULT_CONFIG"
else
    echo "✗ Error: No config file found"
    echo "  Expected: $USER_CONFIG (user config)"
    echo "  Or: $DEFAULT_CONFIG (default config)"
    exit 1
fi

# Validate config file exists and is readable
if [ ! -f "$CONFIG_FILE" ]; then
    echo "✗ Error: Config file does not exist: $CONFIG_FILE"
    exit 1
fi

if [ ! -r "$CONFIG_FILE" ]; then
    echo "✗ Error: Config file is not readable: $CONFIG_FILE"
    exit 1
fi

# Quick CUDA check (informational, pipeline will handle fallback)
echo ""
echo "Checking GPU/CUDA availability..."
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1 | while read line; do
        echo "  GPU detected: $line"
    done || echo "  GPU detected but nvidia-smi query failed"
else
    echo "  nvidia-smi not available"
fi

# Check PyTorch CUDA (non-blocking, just for info)
/opt/conda/bin/conda run --no-capture-output -n inference python -c "import torch; print(f'  PyTorch CUDA available: {torch.cuda.is_available()}')" 2>/dev/null || echo "  Could not check PyTorch CUDA"

echo ""
echo "Starting Satellite Inference Pipeline"
echo "Configuration: $CONFIG_FILE"
echo "Press Ctrl+C to stop"
echo ""

# Run the pipeline with the selected config
exec /opt/conda/bin/conda run --no-capture-output -n inference python /app/run_pipeline.py --config "$CONFIG_FILE"

