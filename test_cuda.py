#!/usr/bin/env python3
"""
Quick CUDA diagnostic script for Docker containers
Run this inside the container to diagnose CUDA/PyTorch issues
"""
import sys
import os

print("=" * 60)
print("CUDA/PyTorch Diagnostic Script")
print("=" * 60)

# Check environment variables
print("\n1. Environment Variables:")
cuda_vars = [k for k in os.environ.keys() if 'CUDA' in k.upper() or 'NVIDIA' in k.upper()]
if cuda_vars:
    for var in sorted(cuda_vars):
        print(f"  {var} = {os.environ[var]}")
else:
    print("  No CUDA/NVIDIA environment variables found")

print(f"\n  LD_LIBRARY_PATH = {os.environ.get('LD_LIBRARY_PATH', 'NOT SET')}")
print(f"  PATH = {os.environ.get('PATH', 'NOT SET')[:100]}...")

# Check if nvidia-smi works
print("\n2. NVIDIA-SMI Check:")
try:
    import subprocess
    result = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'], 
                          capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print(f"  ✓ nvidia-smi works")
        print(f"  GPU Info: {result.stdout.strip()}")
    else:
        print(f"  ✗ nvidia-smi failed: {result.stderr}")
except FileNotFoundError:
    print("  ✗ nvidia-smi not found")
except Exception as e:
    print(f"  ✗ Error running nvidia-smi: {e}")

# Check PyTorch installation
print("\n3. PyTorch Installation:")
try:
    import torch
    print(f"  PyTorch version: {torch.__version__}")
    print(f"  CUDA available: {torch.cuda.is_available()}")
    
    if torch.cuda.is_available():
        print(f"  CUDA version (PyTorch): {torch.version.cuda}")
        print(f"  cuDNN version: {torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else 'N/A'}")
        print(f"  GPU count: {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            print(f"    GPU {i}: {torch.cuda.get_device_name(i)}")
    else:
        print("  ✗ CUDA not available in PyTorch")
        print("\n  Checking CUDA library paths...")
        
        # Check common CUDA library locations
        cuda_lib_paths = [
            '/usr/local/cuda/lib64',
            '/usr/local/cuda-12.1/lib64',
            '/usr/local/cuda-12.0/lib64',
            '/usr/local/cuda-11.8/lib64',
            '/usr/lib/x86_64-linux-gnu',
        ]
        
        import os
        found_libs = []
        for lib_path in cuda_lib_paths:
            if os.path.exists(lib_path):
                libs = [f for f in os.listdir(lib_path) if 'libcudart' in f or 'libcublas' in f]
                if libs:
                    found_libs.append(f"{lib_path} ({len(libs)} CUDA libs)")
        
        if found_libs:
            print("  Found CUDA libraries at:")
            for lib in found_libs:
                print(f"    - {lib}")
        else:
            print("  ✗ No CUDA libraries found in common locations")
            
        # Check LD_LIBRARY_PATH
        ld_path = os.environ.get('LD_LIBRARY_PATH', '')
        if ld_path:
            print(f"\n  LD_LIBRARY_PATH is set to: {ld_path}")
        else:
            print("\n  ✗ LD_LIBRARY_PATH is not set")
            
except ImportError:
    print("  ✗ PyTorch not installed")
except Exception as e:
    print(f"  ✗ Error checking PyTorch: {e}")

# Check for CUDA libraries in container
print("\n4. CUDA Library Check:")
try:
    import ctypes
    import glob
    
    # Try to find libcudart
    possible_paths = [
        '/usr/local/cuda*/lib64/libcudart.so*',
        '/usr/lib/x86_64-linux-gnu/libcudart.so*',
    ]
    
    found = False
    for pattern in possible_paths:
        matches = glob.glob(pattern)
        if matches:
            print(f"  ✓ Found CUDA runtime: {matches[0]}")
            found = True
            break
    
    if not found:
        print("  ✗ libcudart.so not found")
        
except Exception as e:
    print(f"  Error checking libraries: {e}")

print("\n" + "=" * 60)
print("Diagnostic complete")
print("=" * 60)

