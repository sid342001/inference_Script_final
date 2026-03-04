"""
Heartbeat and GPU utilization monitoring.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

try:
    import torch
except Exception:  # pragma: no cover - optional at runtime
    torch = None

try:
    import pynvml
    PYNVML_AVAILABLE = True
except Exception:  # pragma: no cover - optional at runtime
    PYNVML_AVAILABLE = False
    pynvml = None

from .config_loader import HealthConfig
from .job_queue import JobQueue
from .logging_setup import get_logger

logger = get_logger("health_monitor")

# Initialize pynvml once if available
_pynvml_initialized = False
if PYNVML_AVAILABLE:
    try:
        pynvml.nvmlInit()
        _pynvml_initialized = True
    except Exception:
        _pynvml_initialized = False


def _gpu_utilization_pynvml() -> Dict[str, float]:
    """Get GPU utilization using pynvml (nvidia-ml-py)."""
    stats = {}
    if not _pynvml_initialized:
        return stats
    
    try:
        device_count = pynvml.nvmlDeviceGetCount()
        for idx in range(device_count):
            device_id = f"cuda:{idx}"
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                # util.gpu is the GPU utilization percentage (0-100)
                stats[device_id] = util.gpu / 100.0  # Convert to 0.0-1.0 range
            except Exception as e:
                logger.debug(f"Failed to get utilization for GPU {idx}: {e}")
                stats[device_id] = 0.0
    except Exception as e:
        logger.debug(f"pynvml GPU utilization query failed: {e}")
    
    return stats


def _gpu_utilization_nvidia_smi() -> Dict[str, float]:
    """Get GPU utilization using nvidia-smi subprocess call."""
    stats = {}
    try:
        # Query nvidia-smi for GPU utilization
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    parts = line.split(", ")
                    if len(parts) == 2:
                        try:
                            gpu_idx = int(parts[0].strip())
                            util_percent = float(parts[1].strip())
                            device_id = f"cuda:{gpu_idx}"
                            stats[device_id] = util_percent / 100.0  # Convert to 0.0-1.0 range
                        except (ValueError, IndexError):
                            continue
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug(f"nvidia-smi GPU utilization query failed: {e}")
    
    return stats


def _gpu_utilization_memory_fallback() -> Dict[str, float]:
    """Fallback: Use memory utilization as a proxy for GPU activity."""
    stats = {}
    if torch is None or not torch.cuda.is_available():
        return stats
    
    try:
        for idx in range(torch.cuda.device_count()):
            device_id = f"cuda:{idx}"
            try:
                total = torch.cuda.get_device_properties(idx).total_memory
                allocated = torch.cuda.memory_allocated(idx)
                reserved = torch.cuda.memory_reserved(idx)
                # Use the higher of allocated or reserved as a proxy
                memory_util = max(allocated, reserved) / total if total > 0 else 0.0
                stats[device_id] = float(memory_util)
            except Exception:
                stats[device_id] = 0.0
    except Exception:
        pass
    
    return stats


def _gpu_utilization() -> Dict[str, float]:
    """
    Get GPU utilization using the best available method.
    
    Priority:
    1. pynvml (nvidia-ml-py) - most accurate
    2. nvidia-smi subprocess - reliable fallback
    3. Memory utilization - last resort proxy
    """
    # Try pynvml first (most accurate)
    stats = _gpu_utilization_pynvml()
    if stats:
        return stats
    
    # Try nvidia-smi subprocess
    stats = _gpu_utilization_nvidia_smi()
    if stats:
        return stats
    
    # Fallback to memory utilization (not ideal but better than nothing)
    return _gpu_utilization_memory_fallback()


class HealthMonitor:
    def __init__(self, config: HealthConfig, queue: JobQueue, status_supplier: Optional[Callable[[], Dict]] = None, gpu_balancer_supplier: Optional[Callable[[], Dict]] = None):
        self.config = config
        self.queue = queue
        self.status_supplier = status_supplier
        self.gpu_balancer_supplier = gpu_balancer_supplier
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="health-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        logger.info("Health monitor writing to %s", self.config.heartbeat_path)
        while not self._stop.is_set():
            snapshot = {
                "timestamp": time.time(),
                "queue": self.queue.stats(),
                "gpu": _gpu_utilization(),
            }
            if self.status_supplier:
                snapshot["workers"] = self.status_supplier()
            if self.gpu_balancer_supplier:
                snapshot["gpu_load"] = self.gpu_balancer_supplier()
            self._write(snapshot)
            self._stop.wait(timeout=self.config.interval_seconds)

    def _write(self, snapshot: Dict) -> None:
        path = self.config.heartbeat_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2)

