"""
GPU Load Balancer for dynamic GPU assignment.

Supports multiple balancing strategies:
- least_busy: Assign to GPU with lowest utilization
- round_robin: Cycle through GPUs in order
- least_queued: Assign to GPU with fewest active jobs
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

import torch

from .logging_setup import get_logger

logger = get_logger("gpu_balancer")


class GPULoadBalancer:
    """Manages GPU load balancing and job assignment."""

    def __init__(self, available_gpus: List[str], strategy: str = "least_busy"):
        """
        Initialize GPU load balancer.

        Args:
            available_gpus: List of GPU device strings (e.g., ["cuda:0", "cuda:1"])
            strategy: Balancing strategy ("least_busy", "round_robin", "least_queued")
        """
        self.available_gpus = available_gpus
        self.strategy = strategy
        self._lock = threading.Lock()
        self._active_jobs: Dict[str, int] = {gpu: 0 for gpu in available_gpus}
        self._round_robin_index = 0
        self._job_start_times: Dict[str, List[float]] = {gpu: [] for gpu in available_gpus}

        logger.info("GPU Load Balancer initialized with strategy '%s' on GPUs: %s", strategy, available_gpus)

    def get_least_busy_gpu(self) -> Optional[str]:
        """
        Get the least busy GPU based on the configured strategy.

        Returns:
            GPU device string (e.g., "cuda:0") or None if no GPUs available
        """
        if not self.available_gpus:
            return None

        with self._lock:
            if self.strategy == "least_busy":
                return self._get_least_busy_by_utilization()
            elif self.strategy == "round_robin":
                return self._get_round_robin()
            elif self.strategy == "least_queued":
                return self._get_least_queued()
            else:
                logger.warning("Unknown strategy '%s', falling back to least_busy", self.strategy)
                return self._get_least_busy_by_utilization()

    def _get_least_busy_by_utilization(self) -> Optional[str]:
        """Select GPU with lowest utilization."""
        if not self.available_gpus:
            return None

        gpu_utils = {}
        for gpu in self.available_gpus:
            try:
                util = self._get_gpu_utilization(gpu)
                gpu_utils[gpu] = util
            except Exception as e:
                logger.debug("Failed to get utilization for %s: %s", gpu, e)
                gpu_utils[gpu] = float("inf")  # Prefer GPUs we can query

        if not gpu_utils:
            return self.available_gpus[0]

        # Select GPU with lowest utilization
        selected = min(gpu_utils.items(), key=lambda x: x[1])[0]
        logger.debug("Selected GPU %s (utilization: %.1f%%)", selected, gpu_utils[selected] * 100)
        return selected

    def _get_round_robin(self) -> Optional[str]:
        """Select GPU using round-robin strategy."""
        if not self.available_gpus:
            return None

        selected = self.available_gpus[self._round_robin_index]
        self._round_robin_index = (self._round_robin_index + 1) % len(self.available_gpus)
        logger.debug("Round-robin selected GPU: %s", selected)
        return selected

    def _get_least_queued(self) -> Optional[str]:
        """Select GPU with fewest active jobs."""
        if not self.available_gpus:
            return None

        # Find GPU with minimum active jobs
        min_jobs = min(self._active_jobs.values())
        candidates = [gpu for gpu, jobs in self._active_jobs.items() if jobs == min_jobs]

        # If multiple GPUs have same count, prefer the first one
        selected = candidates[0] if candidates else self.available_gpus[0]
        logger.debug("Selected GPU %s (active jobs: %d)", selected, self._active_jobs[selected])
        return selected

    def _get_gpu_utilization(self, gpu: str) -> float:
        """
        Get current GPU utilization (0.0 to 1.0).

        Tries multiple methods:
        1. pynvml (if available)
        2. nvidia-smi subprocess
        3. Memory utilization as fallback
        """
        if not torch.cuda.is_available():
            return 0.0

        # Extract GPU index
        try:
            gpu_idx = int(gpu.split(":")[-1])
        except (ValueError, IndexError):
            return 0.0

        # Try pynvml first
        try:
            import pynvml

            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_idx)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            return util.gpu / 100.0
        except Exception:
            pass

        # Try nvidia-smi
        try:
            import subprocess

            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = line.split(", ")
                    if len(parts) == 2 and int(parts[0].strip()) == gpu_idx:
                        return float(parts[1].strip()) / 100.0
        except Exception:
            pass

        # Fallback: use memory utilization
        try:
            total = torch.cuda.get_device_properties(gpu_idx).total_memory
            allocated = torch.cuda.memory_allocated(gpu_idx)
            return float(allocated / total) if total > 0 else 0.0
        except Exception:
            return 0.0

    def register_job_start(self, gpu: str) -> None:
        """Register that a job has started on a GPU."""
        with self._lock:
            if gpu in self._active_jobs:
                self._active_jobs[gpu] += 1
                self._job_start_times[gpu].append(time.time())
                logger.debug("Job started on %s (active jobs: %d)", gpu, self._active_jobs[gpu])

    def register_job_end(self, gpu: str) -> None:
        """Register that a job has ended on a GPU."""
        with self._lock:
            if gpu in self._active_jobs and self._active_jobs[gpu] > 0:
                self._active_jobs[gpu] -= 1
                # Clean up old start times (keep last 100)
                if self._job_start_times[gpu]:
                    self._job_start_times[gpu].pop(0)
                logger.debug("Job ended on %s (active jobs: %d)", gpu, self._active_jobs[gpu])

    def get_stats(self) -> Dict[str, Dict]:
        """Get current load balancing statistics."""
        with self._lock:
            stats = {}
            for gpu in self.available_gpus:
                try:
                    util = self._get_gpu_utilization(gpu)
                except Exception:
                    util = 0.0

                stats[gpu] = {
                    "active_jobs": self._active_jobs.get(gpu, 0),
                    "utilization": util,
                    "recent_jobs": len(self._job_start_times.get(gpu, [])),
                }
            return stats
