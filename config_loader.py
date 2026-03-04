"""
Pipeline configuration loader and schema validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml
import logging

logger = logging.getLogger("config_loader")


class ConfigError(Exception):
    """Raised when the pipeline configuration is invalid."""


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class WatcherConfig:
    input_dir: Path
    recursive: bool
    include_extensions: List[str]
    settle_time_seconds: int
    poll_interval_seconds: int
    max_inflight_jobs: int
    folder_identities: Optional[List[str]]
    folder_identity_regex: Optional[str]

    @classmethod
    def from_dict(cls, data: Dict, base: Path) -> "WatcherConfig":
        try:
            input_dir = base / data["input_dir"]
        except KeyError as exc:
            raise ConfigError("watcher.input_dir is required") from exc

        include_ext = data.get("include_extensions") or [".tif", ".tiff"]
        include_ext = [ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in include_ext]

        settle = int(data.get("settle_time_seconds", 10))
        poll = int(data.get("poll_interval_seconds", 15))
        inflight = int(data.get("max_inflight_jobs", 32))
        
        # Folder identity filtering (optional)
        folder_identities = data.get("folder_identities")
        if folder_identities is not None:
            folder_identities = [str(f) for f in folder_identities]
        folder_identity_regex = data.get("folder_identity_regex")

        return cls(
            input_dir=input_dir,
            recursive=bool(data.get("recursive", True)),
            include_extensions=include_ext,
            settle_time_seconds=settle,
            poll_interval_seconds=poll,
            max_inflight_jobs=inflight,
            folder_identities=folder_identities,
            folder_identity_regex=folder_identity_regex,
        )


@dataclass
class QueueConfig:
    persistence_path: Path
    max_retries: int
    retry_backoff_seconds: int
    retry_cooldown_seconds: int
    quarantine_dir: Path

    @classmethod
    def from_dict(cls, data: Dict, base: Path) -> "QueueConfig":
        required = "persistence_path"
        if required not in data:
            raise ConfigError(f"queue.{required} is required")
        persistence_path = (base / data[required]).resolve()
        _ensure_parent(persistence_path)

        quarantine = data.get("quarantine_dir")
        quarantine_dir = _ensure_dir((base / quarantine).resolve()) if quarantine else (base / "state/quarantine").resolve()
        return cls(
            persistence_path=persistence_path,
            max_retries=int(data.get("max_retries", 3)),
            retry_backoff_seconds=int(data.get("retry_backoff_seconds", 60)),
            retry_cooldown_seconds=int(data.get("retry_cooldown_seconds", 30)),
            quarantine_dir=quarantine_dir,
        )


@dataclass
class WorkerConfig:
    tiler_workers: int
    gpu_workers: int
    max_concurrent_jobs: int
    batch_size: int
    tile_cache_dir: Path
    hybrid_mode: bool
    gpu_balancing_strategy: str
    job_timeout_seconds: int

    @classmethod
    def from_dict(cls, data: Dict, base: Path) -> "WorkerConfig":
        cache_dir = data.get("tile_cache_dir")
        cache_path = _ensure_dir((base / cache_dir).resolve()) if cache_dir else _ensure_dir((base / "state/tile_cache").resolve())
        hybrid_mode = bool(data.get("hybrid_mode", False))
        balancing_strategy = data.get("gpu_balancing_strategy", "least_busy")
        if balancing_strategy not in {"least_busy", "round_robin", "least_queued"}:
            raise ConfigError(f"Invalid gpu_balancing_strategy '{balancing_strategy}'. Must be one of: least_busy, round_robin, least_queued")
        return cls(
            tiler_workers=int(data.get("tiler_workers", 2)),
            gpu_workers=int(data.get("gpu_workers", 2)),
            max_concurrent_jobs=int(data.get("max_concurrent_jobs", 4)),
            batch_size=int(data.get("batch_size", 4)),
            tile_cache_dir=cache_path,
            hybrid_mode=hybrid_mode,
            gpu_balancing_strategy=balancing_strategy,
            job_timeout_seconds=int(data.get("job_timeout_seconds", 3600)),  # Default: 1 hour
        )


@dataclass
class TilingConfig:
    tile_size: int
    overlap: int
    normalization_mode: str
    allow_resample: bool
    iou_threshold: float
    ioma_threshold: float

    @classmethod
    def from_dict(cls, data: Dict) -> "TilingConfig":
        tile_size = int(data.get("tile_size", 1024))
        overlap = int(data.get("overlap", tile_size // 4))
        normalization_mode = data.get("normalization_mode", "auto")
        allow_resample = bool(data.get("allow_resample", True))
        iou_threshold = float(data.get("iou_threshold", 0.8))
        ioma_threshold = float(data.get("ioma_threshold", 0.75))

        if tile_size <= 0:
            raise ConfigError("tiling.tile_size must be positive")
        if overlap < 0 or overlap >= tile_size:
            raise ConfigError("tiling.overlap must be between 0 and tile_size")
        if not 0.0 <= iou_threshold <= 1.0:
            raise ConfigError("tiling.iou_threshold must be between 0.0 and 1.0")
        if not 0.0 <= ioma_threshold <= 1.0:
            raise ConfigError("tiling.ioma_threshold must be between 0.0 and 1.0")
        return cls(
            tile_size=tile_size,
            overlap=overlap,
            normalization_mode=normalization_mode,
            allow_resample=allow_resample,
            iou_threshold=iou_threshold,
            ioma_threshold=ioma_threshold,
        )


@dataclass
class GPUConfig:
    id: str
    device: str

    @classmethod
    def from_dict(cls, data: Dict) -> "GPUConfig":
        if "device" not in data:
            raise ConfigError("gpus[].device is required")
        return cls(id=data.get("id", data["device"]), device=data["device"])


@dataclass
class ModelOutputConfig:
    write_tile_previews: bool = False
    summary_csv: bool = True

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "ModelOutputConfig":
        data = data or {}
        return cls(
            write_tile_previews=bool(data.get("write_tile_previews", False)),
            summary_csv=bool(data.get("summary_csv", True)),
        )


@dataclass
class ModelConfig:
    name: str
    weights_path: Path
    type: str
    device: Optional[str]
    confidence_threshold: float
    batch_size: Optional[int]
    tile: Optional[TilingConfig]
    outputs: ModelOutputConfig
    folder_identities: Optional[List[str]]
    all_folders: bool
    roi_geojson_path: Optional[Path] = None

    @classmethod
    def from_dict(cls, data: Dict, base: Path, default_tile: TilingConfig) -> "ModelConfig":
        required = ["name", "weights_path", "type"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ConfigError(f"Model config missing keys: {missing}")

        weights = (base / data["weights_path"]).resolve()
        tile_cfg = TilingConfig.from_dict(data["tile"]) if "tile" in data else default_tile
        outputs = ModelOutputConfig.from_dict(data.get("outputs"))

        model_type = data["type"].lower()
        if model_type not in {"yolo", "yolo_obb"}:
            raise ConfigError(f"Unsupported model type '{model_type}' for model '{data['name']}'")

        confidence = float(data.get("confidence_threshold", 0.5))
        if not 0 < confidence <= 1:
            raise ConfigError(f"confidence_threshold for model '{data['name']}' must be in (0, 1]")

        batch_size = data.get("batch_size")
        if batch_size is not None:
            batch_size = int(batch_size)
            if batch_size <= 0:
                raise ConfigError(f"batch_size for model '{data['name']}' must be positive")

        device = data.get("device")
        
        # Folder identity filtering for models (optional)
        folder_identities = data.get("folder_identities")
        if folder_identities is not None:
            folder_identities = [str(f) for f in folder_identities]
        all_folders = bool(data.get("all_folders", False))
        
        # ROI GeoJSON path (optional)
        roi_geojson_path = None
        if "roi_geojson_path" in data and data["roi_geojson_path"]:
            roi_path = (base / data["roi_geojson_path"]).resolve()
            if not roi_path.exists():
                raise ConfigError(f"ROI GeoJSON file not found for model '{data['name']}': {roi_path}")
            roi_geojson_path = roi_path

        return cls(
            name=data["name"],
            weights_path=weights,
            type=model_type,
            device=device,
            confidence_threshold=confidence,
            batch_size=batch_size,
            tile=tile_cfg,
            outputs=outputs,
            folder_identities=folder_identities,
            all_folders=all_folders,
            roi_geojson_path=roi_geojson_path,
        )


@dataclass
class ArtifactConfig:
    success_dir: Path
    failure_dir: Path
    combined_dir: Path
    temp_dir: Path
    per_image_log_dir: Path
    combined_inferences_dir: Path
    daily_logs_dir: Path
    model_outputs_dir: Path
    manifest_format: str
    preview_format: str

    @classmethod
    def from_dict(cls, data: Dict, base: Path) -> "ArtifactConfig":
        def path_for(key: str, default: str) -> Path:
            value = data.get(key, default)
            resolved = (base / value).resolve()
            _ensure_dir(resolved)
            return resolved

        manifest_format = (data.get("manifest_format") or "json").lower()
        if manifest_format not in {"json", "sqlite"}:
            raise ConfigError("artifacts.manifest_format must be 'json' or 'sqlite'")

        preview_format = (data.get("preview_format") or "png").lower()
        if preview_format not in {"png", "jpg"}:
            raise ConfigError("artifacts.preview_format must be 'png' or 'jpg'")

        return cls(
            success_dir=path_for("success_dir", "artifacts/success"),
            failure_dir=path_for("failure_dir", "artifacts/failure"),
            combined_dir=path_for("combined_dir", "artifacts/combined"),
            temp_dir=path_for("temp_dir", "artifacts/tmp"),
            per_image_log_dir=path_for("per_image_log_dir", "artifacts/logs"),
            combined_inferences_dir=path_for("combined_inferences_dir", "artifacts/combined_inferences"),
            daily_logs_dir=path_for("daily_logs_dir", "artifacts/daily_logs"),
            model_outputs_dir=path_for("model_outputs_dir", "artifacts/model_outputs"),
            manifest_format=manifest_format,
            preview_format=preview_format,
        )


@dataclass
class LoggingConfig:
    level: str
    log_dir: Path
    per_image_level: str

    @classmethod
    def from_dict(cls, data: Dict, base: Path) -> "LoggingConfig":
        log_dir = _ensure_dir((base / data.get("log_dir", "logs/pipeline")).resolve())
        return cls(
            level=data.get("level", "INFO"),
            log_dir=log_dir,
            per_image_level=data.get("per_image_level", "DEBUG"),
        )


@dataclass
class DashboardConfig:
    host: str
    port: int
    enabled: bool

    @classmethod
    def from_dict(cls, data: Dict) -> "DashboardConfig":
        return cls(
            host=data.get("host", "localhost"),
            port=int(data.get("port", 8092)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class HealthConfig:
    heartbeat_path: Path
    interval_seconds: int

    @classmethod
    def from_dict(cls, data: Dict, base: Path) -> "HealthConfig":
        if not data:
            heartbeat = (base / "artifacts/health/status.json").resolve()
            interval = 30
        else:
            heartbeat = (base / data.get("heartbeat_path", "artifacts/health/status.json")).resolve()
            interval = int(data.get("interval_seconds", 30))
        _ensure_parent(heartbeat)
        return cls(heartbeat_path=heartbeat, interval_seconds=interval)


@dataclass
class PipelineConfig:
    watcher: WatcherConfig
    queue: QueueConfig
    workers: WorkerConfig
    tiling: TilingConfig
    gpus: Dict[str, GPUConfig]
    models: Dict[str, ModelConfig]
    artifacts: ArtifactConfig
    logging: LoggingConfig
    health: HealthConfig
    dashboard: DashboardConfig

    @classmethod
    def from_dict(cls, data: Dict, base_path: Path) -> "PipelineConfig":
        watcher = WatcherConfig.from_dict(data.get("watcher", {}), base_path)
        queue = QueueConfig.from_dict(data.get("queue", {}), base_path)
        workers = WorkerConfig.from_dict(data.get("workers", {}), base_path)
        tiling = TilingConfig.from_dict(data.get("tiling", {}))

        gpu_list = data.get("gpus", [])
        if not gpu_list:
            raise ConfigError("At least one GPU must be declared under 'gpus'")
        gpu_configs = {gpu_data.get("id", gpu_data.get("device")): GPUConfig.from_dict(gpu_data) for gpu_data in gpu_list}

        models_data = data.get("models", [])
        if not models_data:
            raise ConfigError("At least one model must be declared")
        model_configs: Dict[str, ModelConfig] = {}
        
        # Check if hybrid mode is enabled
        hybrid_mode = data.get("workers", {}).get("hybrid_mode", False)
        
        for model in models_data:
            config = ModelConfig.from_dict(model, base_path, tiling)
            if config.name in model_configs:
                raise ConfigError(f"Model name '{config.name}' defined multiple times")
            
            # In hybrid mode, device assignment is ignored (models loaded on all GPUs)
            # In non-hybrid mode, validate device assignment
            if not hybrid_mode:
                if config.device and config.device not in {gpu.device for gpu in gpu_configs.values()}:
                    raise ConfigError(f"Model '{config.name}' references unknown device '{config.device}'")
            else:
                # In hybrid mode, log that device assignment will be ignored
                if config.device:
                    logger.warning(f"Model '{config.name}' has device '{config.device}' specified, but hybrid_mode is enabled. Device will be assigned dynamically.")
            
            model_configs[config.name] = config

        artifacts = ArtifactConfig.from_dict(data.get("artifacts", {}), base_path)
        logging_cfg = LoggingConfig.from_dict(data.get("logging", {}), base_path)
        health = HealthConfig.from_dict(data.get("health", {}), base_path)
        dashboard = DashboardConfig.from_dict(data.get("dashboard", {}))

        return cls(
            watcher=watcher,
            queue=queue,
            workers=workers,
            tiling=tiling,
            gpus=gpu_configs,
            models=model_configs,
            artifacts=artifacts,
            logging=logging_cfg,
            health=health,
            dashboard=dashboard,
        )

    def model_names(self) -> Iterable[str]:
        return self.models.keys()


def load_config(path: Path | str) -> PipelineConfig:
    """
    Load and validate the YAML configuration file.
    """
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"Configuration file '{config_path}' does not exist")

    with open(config_path, "r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}

    base_path = config_path.parent
    config = PipelineConfig.from_dict(data, base_path)
    
    # Log comprehensive configuration details
    _log_configuration_summary(config, config_path)
    
    return config


def _log_configuration_summary(config: PipelineConfig, config_path: Path) -> None:
    """Log a comprehensive summary of the loaded configuration."""
    logger.info("=" * 80)
    logger.info("PIPELINE CONFIGURATION LOADED")
    logger.info("=" * 80)
    logger.info("Configuration file: %s", config_path)
    logger.info("")
    
    # Watcher Configuration
    logger.info("📁 WATCHER CONFIGURATION:")
    logger.info("  Input Directory: %s", config.watcher.input_dir)
    logger.info("  Recursive Watch: %s", config.watcher.recursive)
    logger.info("  Supported Extensions: %s", ", ".join(config.watcher.include_extensions))
    logger.info("  Settle Time: %d seconds", config.watcher.settle_time_seconds)
    logger.info("  Poll Interval: %d seconds", config.watcher.poll_interval_seconds)
    logger.info("  Max Inflight Jobs: %d", config.watcher.max_inflight_jobs)
    if config.watcher.folder_identities:
        logger.info("  Folder Identities Filter: %s", ", ".join(config.watcher.folder_identities))
    else:
        logger.info("  Folder Identities Filter: None (all folders processed)")
    if config.watcher.folder_identity_regex:
        logger.info("  Folder Identity Regex: %s", config.watcher.folder_identity_regex)
    logger.info("")
    
    # Queue Configuration
    logger.info("📋 QUEUE CONFIGURATION:")
    logger.info("  Persistence Path: %s", config.queue.persistence_path)
    logger.info("  Max Retries: %d", config.queue.max_retries)
    logger.info("  Retry Backoff: %d seconds", config.queue.retry_backoff_seconds)
    logger.info("  Quarantine Directory: %s", config.queue.quarantine_dir)
    logger.info("")
    
    # Worker Configuration
    logger.info("👷 WORKER CONFIGURATION:")
    logger.info("  Max Concurrent Jobs: %d", config.workers.max_concurrent_jobs)
    logger.info("  Batch Size: %d", config.workers.batch_size)
    logger.info("  Tile Cache Directory: %s", config.workers.tile_cache_dir)
    logger.info("  Hybrid Mode: %s", config.workers.hybrid_mode)
    if config.workers.hybrid_mode:
        logger.info("  GPU Balancing Strategy: %s", config.workers.gpu_balancing_strategy)
    logger.info("  Job Timeout: %d seconds", config.workers.job_timeout_seconds)
    logger.info("")
    
    # Global Tiling Configuration
    logger.info("🔲 GLOBAL TILING CONFIGURATION:")
    logger.info("  Tile Size: %d pixels", config.tiling.tile_size)
    logger.info("  Overlap: %d pixels", config.tiling.overlap)
    logger.info("  Normalization Mode: %s", config.tiling.normalization_mode)
    logger.info("  Allow Resample: %s", config.tiling.allow_resample)
    logger.info("  IoU Threshold: %.2f", config.tiling.iou_threshold)
    logger.info("  IoMA Threshold: %.2f", config.tiling.ioma_threshold)
    logger.info("")
    
    # GPU Configuration
    logger.info("🎮 GPU CONFIGURATION:")
    logger.info("  Total GPUs Configured: %d", len(config.gpus))
    for gpu_id, gpu_cfg in config.gpus.items():
        logger.info("  - %s: %s", gpu_id, gpu_cfg.device)
    logger.info("")
    
    # Model Configuration
    logger.info("🤖 MODEL CONFIGURATION:")
    logger.info("  Total Models: %d", len(config.models))
    for model_name, model_cfg in config.models.items():
        logger.info("  ┌─ Model: %s", model_name)
        logger.info("  │  Type: %s", model_cfg.type)
        logger.info("  │  Weights Path: %s", model_cfg.weights_path)
        logger.info("  │  Confidence Threshold: %.2f", model_cfg.confidence_threshold)
        if model_cfg.device:
            logger.info("  │  Assigned Device: %s", model_cfg.device)
        else:
            logger.info("  │  Assigned Device: Auto (will be assigned dynamically)")
        if model_cfg.batch_size:
            logger.info("  │  Batch Size: %d", model_cfg.batch_size)
        else:
            logger.info("  │  Batch Size: Using global setting (%d)", config.workers.batch_size)
        
        # Folder filtering
        if model_cfg.all_folders:
            logger.info("  │  Folder Filter: ALL folders (all_folders=true)")
        elif model_cfg.folder_identities:
            logger.info("  │  Folder Filter: %s", ", ".join(model_cfg.folder_identities))
        else:
            logger.info("  │  Folder Filter: None (processes all folders)")
        
        # Per-model tiling configuration
        if model_cfg.tile:
            logger.info("  │  Tiling (Model-Specific Override):")
            logger.info("  │    Tile Size: %d pixels", model_cfg.tile.tile_size)
            logger.info("  │    Overlap: %d pixels", model_cfg.tile.overlap)
            logger.info("  │    Normalization: %s", model_cfg.tile.normalization_mode)
            logger.info("  │    IoU Threshold: %.2f", model_cfg.tile.iou_threshold)
            logger.info("  │    IoMA Threshold: %.2f", model_cfg.tile.ioma_threshold)
        else:
            logger.info("  │  Tiling: Using global configuration")
        
        # ROI configuration
        if model_cfg.roi_geojson_path:
            logger.info("  │  ROI: Configured from %s", model_cfg.roi_geojson_path)
        else:
            logger.info("  │  ROI: None (processes full image)")
        
        # Output settings
        logger.info("  │  Outputs:")
        logger.info("  │    Write Tile Previews: %s", model_cfg.outputs.write_tile_previews)
        logger.info("  │    Summary CSV: %s", model_cfg.outputs.summary_csv)
        logger.info("  └─")
    logger.info("")
    
    # Artifacts Configuration
    logger.info("📦 ARTIFACTS CONFIGURATION:")
    logger.info("  Success Directory: %s", config.artifacts.success_dir)
    logger.info("  Failure Directory: %s", config.artifacts.failure_dir)
    logger.info("  Combined Inferences Directory: %s", config.artifacts.combined_inferences_dir)
    logger.info("  Model Outputs Directory: %s", config.artifacts.model_outputs_dir)
    logger.info("  Temp Directory: %s", config.artifacts.temp_dir)
    logger.info("  Daily Logs Directory: %s", config.artifacts.daily_logs_dir)
    logger.info("  Manifest Format: %s", config.artifacts.manifest_format)
    logger.info("  Preview Format: %s", config.artifacts.preview_format)
    logger.info("")
    
    # Logging Configuration
    logger.info("📝 LOGGING CONFIGURATION:")
    logger.info("  Log Level: %s", config.logging.level)
    logger.info("  Log Directory: %s", config.logging.log_dir)
    logger.info("  Per-Image Log Level: %s", config.logging.per_image_level)
    logger.info("")
    
    # Health Configuration
    logger.info("💓 HEALTH MONITORING:")
    logger.info("  Heartbeat Path: %s", config.health.heartbeat_path)
    logger.info("  Update Interval: %d seconds", config.health.interval_seconds)
    logger.info("")
    
    # Dashboard Configuration
    if config.dashboard.enabled:
        logger.info("🖥️  DASHBOARD:")
        logger.info("  Status: Enabled")
        logger.info("  Host: %s", config.dashboard.host)
        logger.info("  Port: %d", config.dashboard.port)
    else:
        logger.info("🖥️  DASHBOARD: Disabled")
    logger.info("")
    
    logger.info("=" * 80)
    logger.info("Configuration loaded successfully. Pipeline ready to start.")
    logger.info("=" * 80)
    logger.info("")

