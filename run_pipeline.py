#!/usr/bin/env python3
"""
Entry point for running the Satellite Inference Pipeline.

Usage:
    python run_pipeline.py --config config/pipeline.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).parent.resolve()

# Add /app to path for package imports (Docker environment)
# In Docker, files are in /app/inference_Script/, so we need /app in path
app_root = CURRENT_DIR.parent
if str(app_root) not in sys.path:
    sys.path.insert(0, str(app_root))

# Try importing from inference_Script package (Docker structure)
try:
    from inference_Script.orchestrator import run_from_config  # type: ignore
except ImportError as e:
    # Debug: print what we tried
    print(f"Failed to import from inference_Script package: {e}")
    print(f"Current directory: {CURRENT_DIR}")
    print(f"App root: {app_root}")
    print(f"Python path: {sys.path}")
    
    # Check if package directory exists
    package_dir = app_root / "inference_Script"
    if package_dir.exists():
        print(f"Package directory exists: {package_dir}")
        print(f"Contents: {list(package_dir.iterdir())}")
    else:
        print(f"Package directory does not exist: {package_dir}")
    
    # Fallback: if files are in current directory (non-Docker/local)
    if str(CURRENT_DIR) not in sys.path:
        sys.path.insert(0, str(CURRENT_DIR))
    # Try direct import (for local development)
    try:
        from orchestrator import run_from_config  # type: ignore
    except ImportError:
        print("Error: Could not import orchestrator module")
        print(f"Python path: {sys.path}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Satellite Inference Pipeline - Process satellite imagery with YOLO models"
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to pipeline configuration YAML file (e.g., config/pipeline.yaml)",
    )

    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        # Try default config if specified path doesn't exist
        default_config = config_path.parent / "pipeline.yaml.default"
        if default_config.exists():
            print(f"Warning: {config_path} not found, using default config: {default_config}")
            config_path = default_config
        else:
            print(f"Error: Configuration file not found: {config_path}")
            print(f"Please create a configuration file or check the path.")
            print(f"Default config location: {default_config}")
            sys.exit(1)

    print(f"Starting Satellite Inference Pipeline")
    print(f"Configuration: {config_path}")
    print(f"Press Ctrl+C to stop")
    print()

    try:
        run_from_config(str(config_path))
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

