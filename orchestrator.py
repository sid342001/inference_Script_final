"""
Worker orchestrator that ties watcher, queue, and inference runners together.
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from .config_loader import PipelineConfig, load_config
from .health_monitor import HealthMonitor
from .inference_runner import InferenceRunner
from .job_queue import JobQueue
from .logging_setup import get_logger, setup_logging
from .watcher import ImageWatcher

logger = get_logger("orchestrator")


class Orchestrator:
    def __init__(self, config: PipelineConfig):
        self.config = config
        setup_logging(config.logging, artifacts_config=config.artifacts)
        self.queue = JobQueue(config.queue)
        self.runner = InferenceRunner(config)
        self.watcher = ImageWatcher(config, self.queue)
        self.health_monitor = HealthMonitor(
            config.health,
            self.queue,
            status_supplier=self._worker_snapshot,
            gpu_balancer_supplier=self._gpu_balancer_snapshot,
        )
        self._stop = threading.Event()
        self._workers: Dict[int, threading.Thread] = {}

    def start(self) -> None:
        logger.info("=" * 80)
        logger.info("STARTING PIPELINE ORCHESTRATOR")
        logger.info("=" * 80)
        logger.info("Initializing pipeline components...")
        logger.info("")
        
        # Log worker configuration
        logger.info("Worker Configuration:")
        logger.info("  Max Concurrent Workers: %d", self.config.workers.max_concurrent_jobs)
        logger.info("  Batch Size: %d", self.config.workers.batch_size)
        logger.info("  Hybrid Mode: %s", self.config.workers.hybrid_mode)
        if self.config.workers.hybrid_mode:
            logger.info("  GPU Balancing Strategy: %s", self.config.workers.gpu_balancing_strategy)
        logger.info("  Job Timeout: %d seconds", self.config.workers.job_timeout_seconds)
        logger.info("")
        
        logger.info("Starting watcher on: %s", self.config.watcher.input_dir)
        self.watcher.start()
        
        logger.info("Starting health monitor (updates every %d seconds)", self.config.health.interval_seconds)
        self.health_monitor.start()
        
        logger.info("Spawning %d worker thread(s)...", self.config.workers.max_concurrent_jobs)
        self._spawn_workers()
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("PIPELINE IS RUNNING - Waiting for images in: %s", self.config.watcher.input_dir)
        logger.info("=" * 80)
        logger.info("")
        self._main_loop()

    def _spawn_workers(self) -> None:
        for idx in range(self.config.workers.max_concurrent_jobs):
            thread = threading.Thread(target=self._worker_loop, args=(idx,), name=f"job-worker-{idx}", daemon=True)
            self._workers[idx] = thread
            thread.start()

    def _main_loop(self) -> None:
        # Track when queue was last empty for periodic memory cleanup
        last_empty_check = time.time()
        idle_cleanup_interval = 240 # 1 minute - force memory return when idle
        
        try:
            while not self._stop.is_set():
                time.sleep(1)
                
                # Periodically check if queue is empty and force memory cleanup
                current_time = time.time()
                if current_time - last_empty_check >= idle_cleanup_interval:
                    # First check: Verify queue is truly empty
                    stats = self.queue.stats()
                    in_progress = self.queue.in_progress()
                    
                    # Check if any jobs are pending or processing
                    has_pending = stats["pending"] > 0
                    has_processing = stats["processing"] > 0
                    has_in_progress = len(in_progress) > 0
                    
                    # Check GPU balancer for active jobs (if available)
                    has_active_gpu_jobs = False
                    if self.runner.gpu_balancer is not None:
                        gpu_stats = self.runner.gpu_balancer.get_stats()
                        total_active = sum(gpu_info.get("active_jobs", 0) for gpu_info in gpu_stats.values())
                        has_active_gpu_jobs = total_active > 0
                    
                    # Log current state for debugging
                    if has_pending or has_processing or has_in_progress or has_active_gpu_jobs:
                        logger.debug(
                            "Skipping memory cleanup - system is active: "
                            "pending=%d, processing=%d, in_progress=%d, active_gpu_jobs=%s",
                            stats["pending"], stats["processing"], len(in_progress), has_active_gpu_jobs
                        )
                        last_empty_check = current_time
                        continue
                    
                    # Double-check: Wait a moment and verify again to avoid race conditions
                    # This ensures no job started between the first check and now
                    time.sleep(2)  # Small delay to catch any jobs that just started
                    
                    # Second check: Verify still idle
                    stats2 = self.queue.stats()
                    in_progress2 = self.queue.in_progress()
                    has_pending2 = stats2["pending"] > 0
                    has_processing2 = stats2["processing"] > 0
                    has_in_progress2 = len(in_progress2) > 0
                    
                    has_active_gpu_jobs2 = False
                    if self.runner.gpu_balancer is not None:
                        gpu_stats2 = self.runner.gpu_balancer.get_stats()
                        total_active2 = sum(gpu_info.get("active_jobs", 0) for gpu_info in gpu_stats2.values())
                        has_active_gpu_jobs2 = total_active2 > 0
                    
                    # Only proceed if still idle after double-check
                    if has_pending2 or has_processing2 or has_in_progress2 or has_active_gpu_jobs2:
                        logger.debug(
                            "Skipping memory cleanup - system became active during double-check: "
                            "pending=%d, processing=%d, in_progress=%d, active_gpu_jobs=%s",
                            stats2["pending"], stats2["processing"], len(in_progress2), has_active_gpu_jobs2
                        )
                        last_empty_check = current_time
                        continue
                    
                    # All checks passed - system is truly idle
                    logger.info("")
                    logger.info("=" * 80)
                    logger.info("SYSTEM IDLE DETECTED - Forcing memory return to OS")
                    logger.info("=" * 80)
                    logger.info("Queue Status: pending=0, processing=0, in_progress=0")
                    if self.runner.gpu_balancer is not None:
                        logger.info("GPU Status: all GPUs idle (no active jobs)")
                    logger.info("")
                    logger.info("Performing safe memory cleanup (will not interfere with active processing)...")
                    logger.info("")
                    
                    # Force memory return - this is safe because we've verified no active processing
                    self.runner.force_memory_return_to_os()
                    last_empty_check = current_time
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received; shutting down.")
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        self.watcher.stop()
        self.health_monitor.stop()
        logger.info("Waiting for worker threads to finish")
        for thread in self._workers.values():
            thread.join(timeout=5)

    def _ensure_file_ready(self, image_path: Path, max_wait_seconds: int = 30) -> bool:
        """
        Ensure the image file is completely copied and ready for processing.
        
        Checks:
        1. File exists
        2. File size is stable (not changing)
        3. File is accessible (not locked)
        
        Returns True if file is ready, False otherwise.
        """
        if not image_path.exists():
            logger.warning("Image file does not exist: %s", image_path)
            return False
        
        check_interval = 0.5  # Check every 0.5 seconds
        settle_time = 2.0  # File must be stable for 2 seconds
        max_checks = int(max_wait_seconds / check_interval)
        
        last_size = None
        stable_count = 0
        required_stable_checks = int(settle_time / check_interval)
        
        for check_num in range(max_checks):
            try:
                current_size = image_path.stat().st_size
                
                # Check if file size is stable
                if last_size is not None and current_size == last_size:
                    stable_count += 1
                    if stable_count >= required_stable_checks:
                        # File size is stable, now check if it's accessible
                        try:
                            # Try to open the file in read mode to check if it's locked
                            with open(image_path, "rb") as test_file:
                                test_file.read(1)  # Read one byte
                            logger.debug("File %s is ready for processing (size: %d bytes, stable for %.1fs)", 
                                       image_path, current_size, settle_time)
                            return True
                        except (PermissionError, OSError, IOError) as e:
                            logger.debug("File %s exists but is locked (check %d/%d): %s", 
                                       image_path, check_num + 1, max_checks, e)
                            stable_count = 0  # Reset stable count if file is locked
                else:
                    stable_count = 0  # Reset if size changed
                
                last_size = current_size
                time.sleep(check_interval)
                
            except (OSError, IOError) as e:
                logger.debug("Error checking file %s (check %d/%d): %s", 
                           image_path, check_num + 1, max_checks, e)
                time.sleep(check_interval)
        
        logger.warning("File %s did not become ready within %d seconds", image_path, max_wait_seconds)
        return False

    def _worker_loop(self, worker_idx: int) -> None:
        logger.info("Worker %s online", worker_idx)
        while not self._stop.is_set():
            job = self.queue.reserve()
            if not job:
                time.sleep(1)
                continue
            path = Path(job.image_path)
            
            # Extract folder identity from job payload
            folder_identity = job.payload.get("folder_identity") if job.payload else None
            
            # Log job start with paths
            logger.info("=" * 80)
            logger.info("Worker %s: Starting job %s", worker_idx, job.job_id)
            logger.info("  Source Image Path: %s", path)
            logger.info("  Folder Identity: %s", folder_identity or "root")
            logger.info("  Image File: %s", path.name)
            logger.info("")
            
            # Ensure file is completely copied and ready before processing
            if not self._ensure_file_ready(path):
                logger.error("Job %s: File %s is not ready for processing. Marking as failed.", job.job_id, path)
                self._handle_failure(job.job_id, path, "File not ready for processing (may still be copying)", folder_identity=folder_identity)
                self.queue.mark_failed(job.job_id, "File not ready for processing", requeue=False)
                continue
            
            try:
                # Process with timeout to prevent infinite hangs
                timeout = self.config.workers.job_timeout_seconds
                logger.info("Worker %s: Processing job %s (timeout: %d seconds)", worker_idx, job.job_id, timeout)
                outputs = self._process_with_timeout(job.job_id, path, timeout, folder_identity=folder_identity)
                self.queue.mark_complete(job.job_id)
                
                # Log completion with output paths
                logger.info("Worker %s: Job %s completed successfully", worker_idx, job.job_id)
                logger.info("  Output Directories:")
                for output_type, output_path in outputs.items():
                    if isinstance(output_path, Path):
                        logger.info("    %s: %s", output_type, output_path)
                logger.info("")
                
                # Move image to success directory
                self._handle_success(job.job_id, path, outputs)
            except TimeoutError as exc:
                error_msg = f"Job timed out after {timeout} seconds"
                logger.error("Job %s %s", job.job_id, error_msg)
                self._handle_failure(job.job_id, path, error_msg, folder_identity=folder_identity)
                # Don't requeue timeout errors - they're likely to fail again
                self.queue.mark_failed(job.job_id, error_msg, requeue=False)
            except Exception as exc:
                error_msg = str(exc)
                logger.exception("Job %s failed: %s", job.job_id, error_msg)
                self._handle_failure(job.job_id, path, error_msg, folder_identity=folder_identity)
                # Determine if error is retryable
                is_retryable = self._is_retryable_error(exc)
                self.queue.mark_failed(job.job_id, error_msg, requeue=is_retryable)

    def _handle_success(self, job_id: str, image_path: Path, outputs: Dict[str, Path]) -> None:
        """Move successfully processed image to success directory."""
        image_stem = image_path.stem
        # Extract folder identity from outputs (it's in the base directory path)
        # Outputs are already organized by folder identity in inference_runner
        # We just need to get the base directory from outputs
        if outputs and "base" in outputs:
            success_dir = outputs["base"]
        else:
            # Fallback: try to extract from combined path or any output path
            # Check if any output path contains a folder identity subdirectory
            folder_identity = None
            for output_path in outputs.values():
                if isinstance(output_path, Path):
                    # Check if path contains a folder identity (e.g., success/carto/image_name/)
                    parts = output_path.parts
                    success_idx = None
                    for i, part in enumerate(parts):
                        if part == "success" or "success" in str(part):
                            success_idx = i
                            break
                    if success_idx is not None and success_idx + 1 < len(parts):
                        # Next part after "success" might be folder identity
                        potential_folder = parts[success_idx + 1]
                        # Check if it's not the image folder (doesn't contain underscore with job_id)
                        if "_" not in potential_folder or len(potential_folder.split("_")) < 2:
                            folder_identity = potential_folder
                            break
            
            if folder_identity:
                success_dir = self.config.artifacts.success_dir / folder_identity / f"{image_stem}_{job_id[:8]}"
            else:
                # Fallback to default structure
                success_dir = self.config.artifacts.success_dir / f"{image_stem}_{job_id[:8]}"
        
        # Ensure the directory exists
        success_dir.mkdir(parents=True, exist_ok=True)
        
        # Image should already be in the success directory (created by inference_runner)
        # But we need to move it from incoming if it's still there
        if image_path.exists() and str(self.config.watcher.input_dir) in str(image_path.parent):
            target_image_path = success_dir / image_path.name
            try:
                # Try to move the file
                shutil.move(str(image_path), str(target_image_path))
                logger.info("  Image moved from source to success directory:")
                logger.info("    Source: %s", image_path)
                logger.info("    Destination: %s", target_image_path)
            except Exception as e:
                logger.warning("Could not move image to success directory: %s. Copying instead.", e)
                try:
                    shutil.copy(str(image_path), str(target_image_path))
                    logger.info("  Image copied to success directory:")
                    logger.info("    Source: %s", image_path)
                    logger.info("    Destination: %s", target_image_path)
                    # Try to remove original after successful copy
                    try:
                        image_path.unlink()
                    except Exception:
                        pass
                except Exception as copy_err:
                    logger.error("Could not copy image to success directory: %s", copy_err)

    def _handle_failure(self, job_id: str, image_path: Path, message: str, folder_identity: Optional[str] = None) -> None:
        """Move failed image to failure directory with logs."""
        image_stem = image_path.stem
        # Organize by folder identity if provided
        if folder_identity:
            failure_dir = self.config.artifacts.failure_dir / folder_identity / f"{image_stem}_{job_id[:8]}"
        else:
            failure_dir = self.config.artifacts.failure_dir / f"{image_stem}_{job_id[:8]}"
        failure_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("  Moving failed image to failure directory:")
        logger.info("    Source: %s", image_path)
        logger.info("    Destination: %s", failure_dir)
        
        # Write error message
        failure_log = failure_dir / "error.txt"
        failure_log.write_text(message, encoding="utf-8")
        
        # Copy log file if it exists
        log_file = self.config.logging.log_dir / "images" / f"{job_id}.log"
        if log_file.exists():
            try:
                target_log = failure_dir / f"{image_stem}.log"
                shutil.copy(str(log_file), str(target_log))
            except Exception as e:
                logger.warning("Could not copy log file to failure directory: %s", e)
        
        # Try to move/copy the failed image file
        if image_path.exists():
            target_image_path = failure_dir / image_path.name
            max_copy_retries = 3
            retry_delay = 1.0
            moved = False
            
            for attempt in range(max_copy_retries):
                try:
                    # Try to move first (preferred)
                    if attempt == 0:
                        shutil.move(str(image_path), str(target_image_path))
                        moved = True
                        logger.info("Moved failed image %s to failure directory", image_path.name)
                        break
                    else:
                        # Fall back to copy on retry
                        shutil.copy(str(image_path), str(target_image_path))
                        moved = True
                        logger.info("Copied failed image %s to failure directory", image_path.name)
                        # Try to remove original after copy
                        try:
                            image_path.unlink()
                        except Exception:
                            pass
                        break
                except (PermissionError, OSError) as e:
                    if attempt < max_copy_retries - 1:
                        logger.debug(
                            "Failed to move/copy failed image (attempt %d/%d): %s. Retrying in %.1fs...",
                            attempt + 1,
                            max_copy_retries,
                            e,
                            retry_delay,
                        )
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        logger.warning(
                            "Could not move/copy failed image %s to failure directory after %d attempts: %s",
                            image_path,
                            max_copy_retries,
                            e,
                        )
                        # Write a note about the failed copy
                        copy_note = failure_dir / "image_copy_failed.txt"
                        copy_note.write_text(
                            f"Original image path: {image_path}\n"
                            f"Copy failed due to: {e}\n"
                            f"The file may be locked by another process.",
                            encoding="utf-8",
                        )
                except Exception as e:
                    logger.warning("Unexpected error moving/copying failed image: %s", e)
                    break

    def _worker_snapshot(self) -> Dict[str, Dict]:
        return {f"worker_{idx}": {"alive": thread.is_alive()} for idx, thread in self._workers.items()}

    def _process_with_timeout(self, job_id: str, image_path: Path, timeout_seconds: int, folder_identity: Optional[str] = None) -> Dict[str, Path]:
        """Process a job with timeout to prevent infinite hangs."""
        result_container = {"result": None, "exception": None}
        
        def target():
            try:
                result_container["result"] = self.runner.process(job_id, image_path, folder_identity=folder_identity)
            except Exception as e:
                result_container["exception"] = e
        
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=timeout_seconds)
        
        if thread.is_alive():
            # Thread is still running - job timed out
            logger.error("Job %s exceeded timeout of %d seconds. Worker thread may continue in background.", job_id, timeout_seconds)
            raise TimeoutError(f"Job processing exceeded timeout of {timeout_seconds} seconds")
        
        if result_container["exception"]:
            raise result_container["exception"]
        
        if result_container["result"] is None:
            raise RuntimeError("Job processing returned None (unknown error)")
        
        return result_container["result"]
    
    def _is_retryable_error(self, exc: Exception) -> bool:
        """Determine if an error is retryable (temporary) or permanent."""
        error_msg = str(exc).lower()
        error_type = type(exc).__name__
        
        # Permanent errors - don't retry
        permanent_indicators = [
            "file not found",
            "not found",
            "corrupted",
            "invalid",
            "not a valid",
            "zero bands",
            "timeout",
            "filenotfounderror",
            "valueerror",
        ]
        
        if any(indicator in error_msg for indicator in permanent_indicators):
            return False
        
        # Temporary errors - can retry
        temporary_indicators = [
            "cuda out of memory",
            "out of memory",
            "file locked",
            "permission denied",
            "connection",
            "network",
            "temporary",
        ]
        
        if any(indicator in error_msg for indicator in temporary_indicators):
            return True
        
        # Default: retry for unknown errors (might be temporary)
        return True
    
    def _gpu_balancer_snapshot(self) -> Optional[Dict[str, Dict]]:
        """Get GPU balancer statistics if available."""
        if hasattr(self.runner, "gpu_balancer") and self.runner.gpu_balancer:
            return self.runner.gpu_balancer.get_stats()
        return None


def run_from_config(config_path: str) -> None:
    config = load_config(config_path)
    orchestrator = Orchestrator(config)
    orchestrator.start()

