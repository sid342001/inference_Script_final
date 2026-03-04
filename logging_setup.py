"""
Logging helpers for the inference pipeline.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config_loader import ArtifactConfig, LoggingConfig


class DailyRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """
    A rotating file handler that automatically creates date-based folders.
    
    When the date changes, it closes the current file and opens a new one
    in the new date folder. This ensures logs are always written to the
    correct date folder even if the pipeline runs across midnight.
    
    The handler uses RotatingFileHandler's rotation mechanism for file size,
    but adds date-based folder switching on top of it.
    """
    
    def __init__(
        self,
        daily_logs_dir: Path,
        filename: str = "pipeline.log",
        maxBytes: int = 5 * 1024 * 1024,
        backupCount: int = 5,
        encoding: Optional[str] = None,
    ):
        """
        Initialize the daily rotating file handler.
        
        Args:
            daily_logs_dir: Base directory for daily logs (e.g., artifacts/daily_logs)
            filename: Name of the log file (default: pipeline.log)
            maxBytes: Maximum file size before rotation (default: 5MB)
            backupCount: Number of backup files to keep (default: 5)
            encoding: File encoding (default: None, uses system default)
        """
        self.daily_logs_dir = Path(daily_logs_dir)
        self.filename = filename
        self._current_date = None
        self._lock = threading.Lock()
        
        # Initialize with today's date
        self._update_date_folder()
        
        # Initialize the base RotatingFileHandler with the current date's file
        log_file = self._get_current_log_file()
        super().__init__(
            str(log_file),
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
        )
    
    def _get_current_date(self) -> str:
        """Get current date as YYYY-MM-DD string."""
        return datetime.now().strftime("%Y-%m-%d")
    
    def _get_current_log_file(self) -> Path:
        """Get the log file path for the current date."""
        current_date = self._get_current_date()
        date_dir = self.daily_logs_dir / current_date
        date_dir.mkdir(parents=True, exist_ok=True)
        return date_dir / self.filename
    
    def _update_date_folder(self) -> None:
        """Update the current date and ensure the folder exists."""
        self._current_date = self._get_current_date()
        date_dir = self.daily_logs_dir / self._current_date
        date_dir.mkdir(parents=True, exist_ok=True)
    
    def _should_switch_date(self) -> bool:
        """Check if we need to switch to a new date folder."""
        return self._get_current_date() != self._current_date
    
    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record, switching to a new date folder if needed.
        
        This method is called for every log record. It checks if the date
        has changed and switches to the new date folder if necessary.
        """
        with self._lock:
            # Check if date has changed
            if self._should_switch_date():
                # Close the current file
                if self.stream:
                    self.stream.close()
                    self.stream = None
                
                # Update to new date
                self._update_date_folder()
                
                # Open new file in the new date folder
                new_log_file = self._get_current_log_file()
                self.baseFilename = str(new_log_file)
                self.stream = self._open()
            
            # Call parent emit to actually write the log
            super().emit(record)


def setup_logging(config: LoggingConfig, artifacts_config: Optional[ArtifactConfig] = None) -> None:
    """
    Set up main pipeline logging.
    
    Args:
        config: Logging configuration
        artifacts_config: Optional artifacts config for daily logs directory
    """
    log_dir = config.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    logfile = log_dir / "pipeline.log"
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(threadName)s | %(name)s | %(message)s"
    )

    handlers = []

    # Main pipeline log file
    file_handler = logging.handlers.RotatingFileHandler(
        logfile, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)

    # Also write to daily logs directory if configured
    # Uses DailyRotatingFileHandler which automatically switches to new date folders
    if artifacts_config:
        try:
            daily_logs_dir = artifacts_config.daily_logs_dir
            daily_logs_dir.mkdir(parents=True, exist_ok=True)
            
            # Use custom handler that automatically switches date folders
            daily_handler = DailyRotatingFileHandler(
                daily_logs_dir=daily_logs_dir,
                filename="pipeline.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            daily_handler.setFormatter(formatter)
            handlers.append(daily_handler)
            
            # Log that daily logging is set up
            setup_logger = logging.getLogger("logging_setup")
            today = datetime.now().strftime("%Y-%m-%d")
            setup_logger.info(
                "Daily logging enabled: logs will be written to %s/%s/pipeline.log",
                daily_logs_dir, today
            )
        except Exception as e:
            # Don't fail if daily log setup fails
            logging.getLogger("logging_setup").warning("Failed to set up daily log: %s", e)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    logging.basicConfig(level=getattr(logging, config.level.upper(), logging.INFO), handlers=handlers)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def create_image_logger(
    image_id: str,
    config: LoggingConfig,
    log_file: Optional[Path] = None,
    artifacts_config: Optional[ArtifactConfig] = None,
) -> logging.Logger:
    """
    Create a logger for a specific image.
    
    This logger writes to:
    - A per-image log file (in the image's output directory or logs/images/)
    - Propagates to the main pipeline logger (which writes to daily logs)
    
    Args:
        image_id: Unique identifier for the image (usually job_id)
        config: Logging configuration
        log_file: Optional path to log file. If None, uses default location.
        artifacts_config: Optional artifacts config (not used for daily logs anymore)
    """
    if log_file is None:
        per_image_dir = config.log_dir / "images"
        per_image_dir.mkdir(parents=True, exist_ok=True)
        log_file = per_image_dir / f"{image_id}.log"
    else:
        # Ensure parent directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

    logger_name = f"image.{image_id}"
    logger = logging.getLogger(logger_name)

    if not logger.handlers:
        handler = logging.FileHandler(log_file, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, config.per_image_level.upper(), logging.DEBUG))
        # Propagate to root logger so it appears in main pipeline logs (and daily logs)
        logger.propagate = True

    return logger


def log_status_snapshot(logger: logging.Logger, *, event: str, **fields) -> None:
    payload = {"event": event, **fields}
    logger.info("[status] %s", json.dumps(payload, default=str))

