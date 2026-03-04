"""
Directory watcher that enqueues new imagery files.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from .config_loader import PipelineConfig, WatcherConfig
from .job_queue import JobQueue

logger = logging.getLogger("watcher")

try:
    from watchdog.events import FileMovedEvent, FileSystemEventHandler
    from watchdog.observers import Observer, PollingObserver

    WATCHDOG_AVAILABLE = True
except Exception:  # pragma: no cover - watchdog optional
    WATCHDOG_AVAILABLE = False

    class FileSystemEventHandler:  # type: ignore
        """Fallback no-op handler when watchdog isn't available."""

        pass

    class FileMovedEvent:  # type: ignore
        dest_path: str = ""
    
    class PollingObserver:  # type: ignore
        """Fallback when watchdog not available."""
        pass


def _normalize_suffixes(extensions: Iterable[str]) -> set[str]:
    return {ext.lower() for ext in extensions}


class ImageWatcher:
    def __init__(self, config: PipelineConfig, queue: JobQueue):
        self.config = config
        self.queue = queue
        self._stop_event = threading.Event()
        self._observer: Optional[Observer] = None
        self._extensions = _normalize_suffixes(config.watcher.include_extensions)
        self.config.watcher.input_dir.mkdir(parents=True, exist_ok=True)
        
        # Compile folder identity regex if provided
        self._folder_identity_regex = None
        if config.watcher.folder_identity_regex:
            try:
                self._folder_identity_regex = re.compile(config.watcher.folder_identity_regex)
            except re.error as e:
                logger.warning("Invalid folder_identity_regex pattern: %s. Error: %s", config.watcher.folder_identity_regex, e)
        
        # Store folder identities for matching
        self._folder_identities = config.watcher.folder_identities
        if self._folder_identities:
            logger.info("Watcher configured to process folders: %s", self._folder_identities)

    def start(self) -> None:
        logger.info("Starting watcher on %s", self.config.watcher.input_dir)
        self._stop_event.clear()
        
        # Check if we should use PollingObserver (Docker volumes don't propagate inotify events)
        use_polling_observer = self._should_use_polling()
        
        if WATCHDOG_AVAILABLE:
            # Use watchdog, but with PollingObserver in Docker for compatibility
            self._start_watchdog(use_polling_observer=use_polling_observer)
        else:
            logger.warning("watchdog not available; falling back to polling mode")
            thread = threading.Thread(target=self._polling_loop, name="watcher-poll", daemon=True)
            thread.start()
    
    def _should_use_polling(self) -> bool:
        """
        Determine if we should use PollingObserver instead of event-based Observer.
        
        PollingObserver is used when:
        1. FORCE_POLLING environment variable is set
        2. USE_WATCHDOG_IN_DOCKER is NOT set (allows override)
        3. Running in Docker (detected via /.dockerenv or container environment)
        4. Input directory is a Docker volume mount (common paths)
        
        Returns True to use PollingObserver (polling-based but watchdog API)
        Returns False to use Observer (event-based inotify)
        """
        # Allow explicit override to use event-based Observer even in Docker
        if os.environ.get("USE_WATCHDOG_IN_DOCKER", "").lower() in ("1", "true", "yes"):
            logger.info("USE_WATCHDOG_IN_DOCKER enabled: attempting event-based Observer in Docker")
            return False
        
        # Check environment variable to force polling
        if os.environ.get("FORCE_POLLING", "").lower() in ("1", "true", "yes"):
            return True
        
        # Check if running in Docker
        if os.path.exists("/.dockerenv"):
            logger.debug("Docker environment detected (/.dockerenv exists), using PollingObserver")
            return True
        
        # Check for Docker container indicators
        if os.environ.get("container") == "docker":
            logger.debug("Docker container detected (container=docker), using PollingObserver")
            return True
        
        # Check if input_dir is a common Docker mount path
        input_dir_str = str(self.config.watcher.input_dir)
        if input_dir_str.startswith("/app/") or input_dir_str.startswith("/mnt/"):
            logger.debug("Docker-style path detected, using PollingObserver for better reliability")
            return True
        
        return False

    def stop(self) -> None:
        self._stop_event.set()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

    def _start_watchdog(self, use_polling_observer: bool = False) -> None:
        handler = _WatchdogHandler(self)
        
        # Use PollingObserver in Docker (works with bind mounts) or if explicitly requested
        if use_polling_observer:
            poll_interval = self.config.watcher.poll_interval_seconds
            observer = PollingObserver(timeout=poll_interval)
            logger.info("Using PollingObserver (polling-based, works in Docker) with %ds interval", poll_interval)
        else:
            observer = Observer()
            logger.info("Using Observer (event-based inotify)")
        
        observer.schedule(handler, str(self.config.watcher.input_dir), recursive=self.config.watcher.recursive)
        observer.start()
        self._observer = observer
        
        # Log platform-specific information for debugging
        system = platform.system()
        observer_type = type(observer).__name__
        logger.info("Watchdog observer started: %s on %s", observer_type, system)
        
        # Log Windows-specific note
        if system == "Windows" and not use_polling_observer:
            logger.info("Windows detected: will handle both 'on_created' and 'on_moved' events for file copies")

    def _polling_loop(self) -> None:
        seen: set[Path] = set()
        pending_files: dict[Path, float] = {}  # path -> first_seen_timestamp
        settle = self.config.watcher.settle_time_seconds
        poll_interval = self.config.watcher.poll_interval_seconds
        input_dir = self.config.watcher.input_dir

        while not self._stop_event.is_set():
            current_time = time.time()
            
            # Quick scan for new files (non-blocking)
            for path in input_dir.glob("**/*" if self.config.watcher.recursive else "*"):
                if path in seen:
                    continue
                if not path.is_file():
                    continue
                if path.suffix.lower() not in self._extensions:
                    continue
                
                # Check folder identity filtering
                folder_identity = self._extract_folder_identity(path)
                if not self._matches_folder_identity(folder_identity):
                    logger.debug("File %s skipped (folder identity '%s' not in configured list)", path, folder_identity)
                    continue
                
                # Add to pending if not already being tracked
                if path not in pending_files:
                    pending_files[path] = current_time
                    logger.debug("Found new file (pending stability check): %s (folder: %s)", path, folder_identity)
            
            # Check pending files for stability (non-blocking quick check)
            ready_files = []
            for path, first_seen in list(pending_files.items()):
                # File must have been seen for at least settle_time seconds
                if current_time - first_seen >= settle:
                    # Quick non-blocking check
                    if self._quick_ready_check(path):
                        ready_files.append(path)
                    else:
                        # File still not ready, keep waiting (but don't block)
                        logger.debug("File %s still not ready (seen for %.1fs)", path, current_time - first_seen)
            
            # Process ready files
            for path in ready_files:
                self._enqueue_file(path)
                seen.add(path)
                pending_files.pop(path, None)
                logger.info("File ready and enqueued: %s", path)
            
            # Clean up stale pending files (files that disappeared)
            for path in list(pending_files.keys()):
                if not path.exists():
                    logger.debug("Pending file %s no longer exists, removing from tracking", path)
                    pending_files.pop(path)
            
            time.sleep(poll_interval)

    def _quick_ready_check(self, path: Path) -> bool:
        """
        Quick non-blocking check if file is ready.
        
        This is used in polling mode to check file stability without blocking.
        Assumes file has already been observed for settle_time seconds.
        
        Returns True if:
        - File exists
        - File is accessible (not locked)
        - File size is reasonable (not 0 bytes)
        """
        if not path.exists():
            return False
        
        try:
            # Check file size (should not be 0 for valid images)
            file_size = path.stat().st_size
            if file_size == 0:
                logger.debug("File %s is 0 bytes, not ready", path)
                return False
            
            # Try to open the file to check if it's accessible and not locked
            try:
                with open(path, "rb") as test_file:
                    test_file.read(1)  # Read one byte to verify access
                return True
            except (PermissionError, OSError, IOError) as e:
                # File is locked or inaccessible
                logger.debug("File %s is locked or inaccessible: %s", path, e)
                return False
                
        except (OSError, IOError) as e:
            # Error accessing file
            logger.debug("Error accessing file %s: %s", path, e)
            return False
    
    def _is_ready(self, path: Path, settle_time: int) -> bool:
        """
        Check if file is ready (completely copied and stable).
        
        This method includes a blocking sleep to check size stability.
        Used by watchdog handlers where blocking is acceptable.
        
        Returns True if:
        - File exists
        - File size is stable (unchanged for settle_time seconds)
        - File is accessible (not locked)
        """
        if not path.exists():
            return False
        
        try:
            # Check file size stability
            first_size = path.stat().st_size
            time.sleep(settle_time)
            
            if not path.exists():
                return False
            
            second_size = path.stat().st_size
            if second_size != first_size:
                # File size changed, still being copied
                return False
            
            # File size is stable, check if it's accessible
            try:
                # Try to open the file to check if it's locked
                with open(path, "rb") as test_file:
                    test_file.read(1)  # Read one byte to verify access
                return True
            except (PermissionError, OSError, IOError):
                # File is locked, not ready yet
                return False
                
        except (OSError, IOError):
            # Error accessing file
            return False

    def _extract_folder_identity(self, file_path: Path) -> str:
        """
        Extract folder identity from file path.
        
        If folder_identity_regex is configured, uses regex to extract identity.
        Otherwise, uses the immediate parent folder name relative to input_dir.
        
        Returns the folder identity string.
        """
        input_dir = self.config.watcher.input_dir.resolve()
        file_path_resolved = file_path.resolve()
        
        try:
            # Get relative path from input_dir
            relative_path = file_path_resolved.relative_to(input_dir)
            
            # If using regex, match against the full relative path
            if self._folder_identity_regex:
                match = self._folder_identity_regex.search(str(relative_path))
                if match:
                    # Return the first captured group, or the entire match
                    return match.group(1) if match.groups() else match.group(0)
            
            # Default: use immediate parent folder name
            if len(relative_path.parts) > 1:
                return relative_path.parts[0]  # First folder in path
            else:
                # File is directly in input_dir, use "root" or input_dir name
                return "root"
        except ValueError:
            # File is not under input_dir (shouldn't happen, but handle gracefully)
            logger.warning("File %s is not under input_dir %s", file_path, input_dir)
            return "unknown"
    
    def _matches_folder_identity(self, folder_identity: str) -> bool:
        """
        Check if folder identity matches configured folder_identities.
        
        If folder_identities is None or empty, all folders are allowed.
        Otherwise, checks if folder_identity matches any configured identity
        (supports regex patterns).
        """
        if not self._folder_identities:
            # No filtering configured - allow all
            return True
        
        # Check if folder_identity matches any configured identity (supports regex)
        for pattern in self._folder_identities:
            try:
                # Try regex match first
                if re.match(pattern, folder_identity):
                    return True
            except re.error:
                # If not a valid regex, do exact match
                if pattern == folder_identity:
                    return True
        
        return False
    
    def _enqueue_file(self, path: Path) -> None:
        self._wait_for_capacity()
        folder_identity = self._extract_folder_identity(path)
        logger.info("")
        logger.info("📥 NEW IMAGE DETECTED")
        logger.info("  File Path: %s", path)
        logger.info("  File Name: %s", path.name)
        logger.info("  Folder Identity: %s", folder_identity)
        logger.info("  Source Directory: %s", path.parent)
        logger.info("  File Size: %s bytes", path.stat().st_size if path.exists() else "unknown")
        logger.info("  Enqueuing for processing...")
        logger.info("")
        # Store folder identity in job payload
        self.queue.enqueue(str(path), payload={"folder_identity": folder_identity})

    def _wait_for_capacity(self) -> None:
        max_inflight = self.config.watcher.max_inflight_jobs
        poll = max(5, self.config.watcher.poll_interval_seconds)
        while True:
            stats = self.queue.stats()
            inflight = stats["pending"] + stats["processing"]
            if inflight < max_inflight:
                return
            logger.debug("Watcher waiting for capacity (inflight=%s, limit=%s)", inflight, max_inflight)
            time.sleep(poll)


class _WatchdogHandler(FileSystemEventHandler):
    def __init__(self, watcher: ImageWatcher):
        super().__init__()
        self._watcher = watcher
        self._watched_dir = Path(watcher.config.watcher.input_dir).resolve()

    def _process_file(self, file_path: Path) -> None:
        """Common logic to process a detected file."""
        if not file_path.is_file():
            return
        if file_path.suffix.lower() not in self._watcher._extensions:
            return
        
        # Check folder identity filtering
        folder_identity = self._watcher._extract_folder_identity(file_path)
        if not self._watcher._matches_folder_identity(folder_identity):
            logger.debug("File %s skipped (folder identity '%s' not in configured list)", file_path, folder_identity)
            return
        
        # Normalize path for cross-platform compatibility
        normalized_path = file_path.resolve()
        if self._watcher._is_ready(normalized_path, self._watcher.config.watcher.settle_time_seconds):
            self._watcher._enqueue_file(normalized_path)

    def on_created(self, event):  # pragma: no cover - requires filesystem events
        """Handle file creation events (Linux/Unix and some Windows operations)."""
        if event.is_directory:
            return
        path = Path(event.src_path).resolve()
        self._process_file(path)

    def on_moved(self, event):  # pragma: no cover - requires filesystem events
        """
        Handle file move/copy events.
        
        On Windows, file copy operations often emit 'on_moved' events instead of 'on_created'.
        The dest_path is the new location (where the file was moved/copied to).
        We only process files moved INTO the watched directory.
        """
        if event.is_directory:
            return
        
        # FileMovedEvent has both src_path and dest_path attributes
        # On Windows, file copies emit on_moved with dest_path as the new file location
        # On Linux, on_moved is typically for actual moves/renames
        if isinstance(event, FileMovedEvent) and hasattr(event, "dest_path") and event.dest_path:
            dest_path = Path(event.dest_path).resolve()
            # Check if the destination is within the watched directory
            try:
                dest_path.relative_to(self._watched_dir)
                # File was moved/copied into the watched directory
                self._process_file(dest_path)
            except ValueError:
                # File was moved out of the watched directory, ignore
                pass
        else:
            # Fallback: use src_path if dest_path is not available (shouldn't happen with FileMovedEvent)
            src_path = Path(event.src_path).resolve()
            try:
                src_path.relative_to(self._watched_dir)
                self._process_file(src_path)
            except ValueError:
                pass

