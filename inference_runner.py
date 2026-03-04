"""
Inference execution logic for per-model and combined outputs.
"""

from __future__ import annotations

import csv
import gc
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch
from pyproj import CRS, Transformer, exceptions as pyproj_exceptions
from ultralytics import YOLO
from PIL import Image

try:
    from shapely.geometry import Polygon
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    Polygon = None

from .config_loader import ModelConfig, PipelineConfig, TilingConfig
from .gpu_balancer import GPULoadBalancer
from .logging_setup import create_image_logger, get_logger, log_status_snapshot
from .manifest import ManifestEntry, ManifestWriter
from .roi_filter import ROIFilter
from .tiler import RasterTiler, Tile

logger = get_logger("inference_runner")


TARGET_CRS = CRS.from_epsg(4326)


@dataclass
class ModelHandle:
    name: str
    config: ModelConfig
    model: YOLO
    device: str


@dataclass
class TileDetection:
    """Stores a detection with its tile metadata for cross-tile NMS."""
    obb: np.ndarray  # Oriented bounding box in global coordinates (4, 2)
    confidence: float
    class_name: str
    tile_row: int
    tile_col: int
    box_type: str
    tile_metadata: TileMetadata


def _load_model(model_config: ModelConfig, device: str) -> ModelHandle:
    """Load a model on a specific device with error handling and validation."""
    weights_path = Path(model_config.weights_path)
    
    # ========================================================================
    # VALIDATION 1: File Existence
    # ========================================================================
    if not weights_path.exists():
        error_msg = (
            f"ERROR: Model weights file not found for model '{model_config.name}'\n"
            f"  Expected path: {weights_path}\n"
            f"  Please check:\n"
            f"    1. The path in pipeline.yaml is correct\n"
            f"    2. The file exists at the specified location\n"
            f"    3. The path uses forward slashes (/) or double backslashes (\\\\) on Windows\n"
            f"    4. The file has read permissions"
        )
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)
    
    # ========================================================================
    # VALIDATION 2: File Type (not a directory)
    # ========================================================================
    if not weights_path.is_file():
        error_msg = (
            f"ERROR: Model path is not a file for model '{model_config.name}'\n"
            f"  Path: {weights_path}\n"
            f"  This path exists but is not a file (might be a directory)\n"
            f"  Please check the path in pipeline.yaml"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    # ========================================================================
    # VALIDATION 3: File Extension
    # ========================================================================
    if weights_path.suffix.lower() not in ('.pt', '.pth'):
        error_msg = (
            f"ERROR: Invalid model file extension for model '{model_config.name}'\n"
            f"  Path: {weights_path}\n"
            f"  File extension: {weights_path.suffix}\n"
            f"  Expected: .pt or .pth (PyTorch model files)\n"
            f"  Please check the file extension in pipeline.yaml"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    # ========================================================================
    # VALIDATION 4: File Size (not empty)
    # ========================================================================
    try:
        file_size = weights_path.stat().st_size
        if file_size == 0:
            error_msg = (
                f"ERROR: Model file is empty (0 bytes) for model '{model_config.name}'\n"
                f"  Path: {weights_path}\n"
                f"  The file exists but contains no data\n"
                f"  Please check if the file was copied correctly"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Warn if file is suspiciously small (less than 1MB - likely corrupted)
        if file_size < 1024 * 1024:  # Less than 1MB
            logger.warning(
                "Model file '%s' is very small (%.2f MB). Most YOLO models are >10MB. "
                "This might indicate a corrupted or incomplete file.",
                weights_path, file_size / (1024 * 1024)
            )
    except OSError as e:
        error_msg = (
            f"ERROR: Cannot access model file for model '{model_config.name}'\n"
            f"  Path: {weights_path}\n"
            f"  Error: {e}\n"
            f"  Please check file permissions"
        )
        logger.error(error_msg)
        raise OSError(error_msg) from e
    
    # ========================================================================
    # VALIDATION 5: File Readability
    # ========================================================================
    try:
        # Try to check if file is readable
        with open(weights_path, 'rb') as f:
            f.read(1)  # Try to read at least 1 byte
    except PermissionError as e:
        error_msg = (
            f"ERROR: Cannot read model file for model '{model_config.name}'\n"
            f"  Path: {weights_path}\n"
            f"  Permission denied - check file permissions\n"
            f"  Please ensure the file has read permissions"
        )
        logger.error(error_msg)
        raise PermissionError(error_msg) from e
    except Exception as e:
        error_msg = (
            f"ERROR: Cannot access model file for model '{model_config.name}'\n"
            f"  Path: {weights_path}\n"
            f"  Error: {e}\n"
            f"  The file may be locked by another process"
        )
        logger.error(error_msg)
        raise
    
    # Log comprehensive model configuration
    logger.info("Loading model: %s", model_config.name)
    logger.info("  Weights Path: %s", weights_path)
    logger.info("  File Size: %.2f MB", file_size / (1024 * 1024))
    
    logger.info("  Model Type: %s", model_config.type)
    logger.info("  Target Device: %s", device)
    logger.info("  Confidence Threshold: %.2f", model_config.confidence_threshold)
    
    # Log folder filtering
    if model_config.all_folders:
        logger.info("  Folder Filter: ALL folders")
    elif model_config.folder_identities:
        logger.info("  Folder Filter: %s", ", ".join(model_config.folder_identities))
    else:
        logger.info("  Folder Filter: None (all folders)")
    
    # Log tiling configuration
    if model_config.tile:
        logger.info("  Tiling Configuration (Model-Specific):")
        logger.info("    Tile Size: %d pixels", model_config.tile.tile_size)
        logger.info("    Overlap: %d pixels", model_config.tile.overlap)
        logger.info("    Normalization: %s", model_config.tile.normalization_mode)
        logger.info("    Allow Resample: %s", model_config.tile.allow_resample)
        logger.info("    IoU Threshold: %.2f", model_config.tile.iou_threshold)
        logger.info("    IoMA Threshold: %.2f", model_config.tile.ioma_threshold)
    else:
        logger.info("  Tiling Configuration: Using global settings")
    
    # Log output settings
    logger.info("  Output Settings:")
    logger.info("    Write Tile Previews: %s", model_config.outputs.write_tile_previews)
    logger.info("    Summary CSV: %s", model_config.outputs.summary_csv)
    
    if model_config.batch_size:
        logger.info("  Batch Size: %d (model-specific)", model_config.batch_size)
    else:
        logger.info("  Batch Size: Using global setting")
    
    try:
        # Try to load the model (verbose=False to suppress YOLO logging)
        logger.debug("  Attempting to load YOLO model from: %s", weights_path)
        try:
            model = YOLO(str(weights_path), verbose=False)
        except Exception as yolo_error:
            error_msg = (
                f"ERROR: Failed to load YOLO model '{model_config.name}'\n"
                f"  Path: {weights_path}\n"
                f"  YOLO Error: {yolo_error}\n"
                f"  Possible causes:\n"
                f"    1. File is corrupted or not a valid YOLO model file\n"
                f"    2. File format is incorrect (expected .pt file)\n"
                f"    3. Model file is incomplete or truncated\n"
                f"    4. Ultralytics library version mismatch"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from yolo_error
        
        # ========================================================================
        # VALIDATION 6: Model Structure (is it a valid YOLO model?)
        # ========================================================================
        if not hasattr(model, 'model'):
            error_msg = (
                f"ERROR: File does not appear to be a valid YOLO model for model '{model_config.name}'\n"
                f"  Path: {weights_path}\n"
                f"  File exists but is missing required 'model' attribute\n"
                f"  This might not be a valid YOLO model file (.pt format)\n"
                f"  Please verify the file is a valid Ultralytics YOLO model"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # ========================================================================
        # VALIDATION 7: Model Type Detection (yolo vs yolo_obb)
        # ========================================================================
        # Detect the actual model task type
        actual_task = None
        try:
            # Method 1: Check model.task attribute (most reliable)
            if hasattr(model, 'task') and model.task:
                actual_task = model.task.lower()
                logger.debug("  Detected model task from model.task: %s", actual_task)
        except Exception as e:
            logger.debug("  Could not read model.task: %s", e)
        
        # Method 2: Try to guess from model architecture
        if not actual_task:
            try:
                from ultralytics.nn.tasks import guess_model_task
                actual_task = guess_model_task(model.model)
                logger.debug("  Detected model task from architecture: %s", actual_task)
            except (ImportError, AttributeError, Exception) as e:
                logger.debug("  Could not guess model task: %s", e)
        
        # Method 3: Check model architecture for OBB modules
        if not actual_task:
            try:
                from ultralytics.nn.modules.head import OBB
                has_obb = any(isinstance(m, OBB) for m in model.model.modules())
                if has_obb:
                    actual_task = "obb"
                else:
                    actual_task = "detect"  # Default assumption
                logger.debug("  Detected model task from architecture inspection: %s", actual_task)
            except (ImportError, AttributeError, Exception) as e:
                logger.debug("  Could not inspect model architecture: %s", e)
                actual_task = "detect"  # Safe default
        
        # Map actual task to our config type
        actual_type = None
        if actual_task == "obb":
            actual_type = "yolo_obb"
        elif actual_task in ("detect", "segment", "classify", "pose"):
            actual_type = "yolo"  # All non-OBB tasks use regular yolo type
        else:
            # Unknown task, assume regular yolo
            logger.warning(
                "  Could not determine model task type (detected: %s). Assuming 'yolo' type.",
                actual_task
            )
            actual_type = "yolo"
        
        # Compare detected type with configured type
        configured_type = model_config.type.lower()
        if configured_type not in ("yolo", "yolo_obb"):
            error_msg = (
                f"ERROR: Invalid model type specified for model '{model_config.name}'\n"
                f"  Configured type: {configured_type}\n"
                f"  Valid types: 'yolo' or 'yolo_obb'\n"
                f"  Please check the 'type' field in pipeline.yaml"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Check for type mismatch
        if actual_type != configured_type:
            error_msg = (
                f"ERROR: Model type mismatch for model '{model_config.name}'\n"
                f"  Configured type in pipeline.yaml: '{configured_type}'\n"
                f"  Actual model type (detected): '{actual_type}'\n"
                f"  Model file: {weights_path}\n"
                f"  \n"
                f"  This model is a '{actual_type}' model but you specified '{configured_type}' in the config.\n"
                f"  \n"
                f"  Solution: Update pipeline.yaml to set:\n"
                f"    type: \"{actual_type}\"\n"
                f"  \n"
                f"  Or use the correct model file that matches the configured type."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Log successful type validation
        logger.info("  ✓ Model type validated: %s (matches configuration)", actual_type)
        
        # Move to device with graceful fallback to CPU if GPU unavailable
        actual_device = device
        try:
            if device.startswith("cuda"):
                # Check if CUDA is actually available
                if not torch.cuda.is_available():
                    logger.warning(
                        "CUDA device %s requested but CUDA is not available. Falling back to CPU.",
                        device
                    )
                    actual_device = "cpu"
                elif ":" in device:
                    # Check if specific GPU exists
                    gpu_id = int(device.split(":")[1])
                    if gpu_id >= torch.cuda.device_count():
                        logger.warning(
                            "GPU %s does not exist (only %d GPUs available). Falling back to CPU.",
                            device, torch.cuda.device_count()
                        )
                        actual_device = "cpu"
            
            # Move model to device
            model.to(actual_device)
            
        except RuntimeError as e:
            error_msg = str(e).lower()
            # Check if it's a CUDA/GPU error
            if "cuda" in error_msg or "gpu" in error_msg or "no cuda" in error_msg:
                logger.warning(
                    "Failed to load model %s on GPU %s: %s. Falling back to CPU.",
                    model_config.name, device, e
                )
                actual_device = "cpu"
                try:
                    model.to(actual_device)
                except Exception as cpu_error:
                    raise RuntimeError(
                        f"Failed to load model {model_config.name} on CPU after GPU failure: {cpu_error}"
                    ) from cpu_error
            else:
                # Re-raise if it's not a GPU-related error
                raise RuntimeError(f"Failed to move model {model_config.name} to device {device}: {e}") from e
        except Exception as e:
            # For any other error, try CPU fallback
            if device != "cpu":
                logger.warning(
                    "Unexpected error loading model %s on %s: %s. Attempting CPU fallback.",
                    model_config.name, device, e
                )
                actual_device = "cpu"
                try:
                    model.to(actual_device)
                except Exception as cpu_error:
                    raise RuntimeError(
                        f"Failed to load model {model_config.name} on CPU after device error: {cpu_error}"
                    ) from cpu_error
            else:
                raise RuntimeError(f"Failed to move model {model_config.name} to device {device}: {e}") from e
        
        if actual_device != device:
            logger.info(
                "Model %s loaded on %s (requested %s was unavailable)",
                model_config.name, actual_device, device
            )
        else:
            logger.info("Successfully loaded model %s on %s", model_config.name, actual_device)
        
        # Log final validation summary
        logger.info("  ✓ All validations passed for model '%s'", model_config.name)
        logger.info("    - File exists and is readable")
        logger.info("    - File extension is valid (.pt)")
        logger.info("    - File size is valid (%.2f MB)", file_size / (1024 * 1024))
        logger.info("    - Model structure is valid (YOLO model)")
        logger.info("    - Model type matches configuration (%s)", actual_type)
        logger.info("    - Model loaded successfully on %s", actual_device)
        
        return ModelHandle(name=model_config.name, config=model_config, model=model, device=actual_device)
        
    except (FileNotFoundError, ValueError, RuntimeError, PermissionError) as e:
        # These errors already have detailed messages, just re-raise
        raise
    except Exception as e:
        error_msg = (
            f"ERROR: Unexpected error loading model '{model_config.name}'\n"
            f"  Path: {weights_path}\n"
            f"  Error Type: {type(e).__name__}\n"
            f"  Error Message: {e}\n"
            f"  Please check the model file and configuration"
        )
        logger.error(error_msg)
        logger.exception("Full error traceback:")
        raise RuntimeError(error_msg) from e


def _resolve_source_crs(dataset) -> Tuple[Optional[CRS], Optional[str]]:
    projection_wkt = dataset.GetProjection()
    if projection_wkt:
        try:
            crs = CRS.from_wkt(projection_wkt)
            return crs, "GetProjection"
        except pyproj_exceptions.CRSError:
            pass

    try:
        srs = dataset.GetSpatialRef()
        if srs:
            return CRS.from_wkt(srs.ExportToWkt()), "GetSpatialRef"
    except Exception:
        pass

    try:
        gcp_projection = dataset.GetGCPProjection()
        if gcp_projection:
            return CRS.from_wkt(gcp_projection), "GetGCPProjection"
    except Exception:
        pass

    return None, None


def _create_transformer(source_crs: Optional[CRS]) -> Optional[Transformer]:
    if not source_crs:
        return None
    if source_crs == TARGET_CRS:
        return None
    return Transformer.from_crs(source_crs, TARGET_CRS, always_xy=True)


def _validate_crs(source_crs: Optional[CRS], transformer: Optional[Transformer], image_logger) -> None:
    """
    Validate that CRS is available and transformation is possible.
    
    Raises RuntimeError if CRS is missing or invalid, preventing flawed GeoJSON output.
    """
    if source_crs is None:
        error_msg = (
            "CRITICAL: Image has no valid CRS/projection metadata. "
            "Cannot generate valid GeoJSON coordinates. "
            "Processing stopped to prevent flawed output. "
            "Please ensure the input image has proper geospatial metadata."
        )
        image_logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    # Validate CRS is valid
    try:
        crs_string = source_crs.to_string()
        image_logger.info("CRS Validation: Source CRS is valid: %s", crs_string)
    except Exception as e:
        error_msg = (
            f"CRITICAL: Source CRS is invalid or corrupted: {e}. "
            "Cannot generate valid GeoJSON coordinates. "
            "Processing stopped to prevent flawed output."
        )
        image_logger.error(error_msg)
        raise RuntimeError(error_msg) from e
    
    # If CRS is not WGS84, validate transformer is available
    if source_crs != TARGET_CRS:
        if transformer is None:
            error_msg = (
                f"CRITICAL: Cannot create coordinate transformer from {source_crs.to_string()} to WGS84 (EPSG:4326). "
                "Cannot generate valid GeoJSON coordinates. "
                "Processing stopped to prevent flawed output. "
                "Please check that the source CRS is valid and transformation is possible."
            )
            image_logger.error(error_msg)
            raise RuntimeError(error_msg)
        else:
            image_logger.info("CRS Validation: Coordinate transformer created successfully")
            image_logger.info("  Source CRS: %s", source_crs.to_string())
            image_logger.info("  Target CRS: WGS84 (EPSG:4326)")
    else:
        image_logger.info("CRS Validation: Image already in WGS84 (EPSG:4326), no transformation needed")


def _get_tile_config_key(tile_config: TilingConfig) -> Tuple[int, int, str]:
    """
    Generate hashable key for tile config comparison.
    
    Used to group models with identical tiling configurations so they can share tilers.
    
    Args:
        tile_config: TilingConfig to generate key for
        
    Returns:
        Tuple of (tile_size, overlap, normalization_mode) for use as dictionary key
    """
    return (tile_config.tile_size, tile_config.overlap, tile_config.normalization_mode)


def _tile_to_tensor(tile: Tile) -> torch.Tensor:
    """
    Convert tile data to a 3-channel tensor.

    Many satellite products include 4 bands (e.g., RGBA). YOLO models expect
    3-channel RGB inputs, so we adapt the tile accordingly:
    - If the tile has >3 bands, keep the first three (assumed RGB).
    - If the tile has 1 band, replicate it three times to form pseudo-RGB.
    - If the tile has 2 bands, duplicate the first band to reach three channels.
    """

    arr = tile.array
    channels = arr.shape[2]

    if channels > 3:
        arr = arr[:, :, :3]
    elif channels == 1:
        arr = np.repeat(arr, 3, axis=2)
    elif channels == 2:
        arr = np.concatenate([arr, arr[:, :, :1]], axis=2)

    tensor = torch.from_numpy(arr.transpose(2, 0, 1)).float()
    return tensor


def _globalize_polygon(points: np.ndarray, metadata, width: int, height: int) -> np.ndarray:
    """
    Convert tile-local polygon coordinates to global image coordinates.
    
    Args:
        points: Array of points, either:
            - Flattened: shape (8,) with [x1, y1, x2, y2, x3, y3, x4, y4]
            - 2D: shape (4, 2) with [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
        metadata: Tile metadata with offset_x and offset_y
        width: Global image width
        height: Global image height
    
    Returns:
        Array of shape (4, 2) with global coordinates
    """
    # Handle both flattened and 2D input formats
    if points.ndim == 2 and points.shape[1] == 2:
        # Already in (N, 2) format
        local_points = points
    else:
        # Flattened format: reshape to (4, 2)
        points_flat = points.flatten()
        if len(points_flat) < 8:
            raise ValueError(f"Expected at least 8 values for polygon, got {len(points_flat)}")
        local_points = points_flat[:8].reshape(4, 2)
    
    global_pts = []
    for local_x, local_y in local_points:
        # Ensure we have scalar values
        local_x = float(local_x) if isinstance(local_x, (np.ndarray, np.generic)) else float(local_x)
        local_y = float(local_y) if isinstance(local_y, (np.ndarray, np.generic)) else float(local_y)
        
        global_x = np.clip(local_x + metadata.offset_x, 0, width - 1)
        global_y = np.clip(local_y + metadata.offset_y, 0, height - 1)
        global_pts.append([float(global_x), float(global_y)])
    return np.array(global_pts)


def _axis_aligned_to_points(box: Sequence[float]) -> np.ndarray:
    x_min, y_min, x_max, y_max = box
    return np.array(
        [
            x_min,
            y_min,
            x_max,
            y_min,
            x_max,
            y_max,
            x_min,
            y_max,
        ]
    )


def _to_world_coords(points_px: np.ndarray, tiler: RasterTiler, transformer: Optional[Transformer]) -> List[List[float]]:
    coords = []
    for x_pixel, y_pixel in points_px:
        x_geo, y_geo = tiler.pixel_to_geo(x_pixel, y_pixel)
        if transformer:
            lon, lat = transformer.transform(x_geo, y_geo)
            coords.append([float(lon), float(lat)])
        else:
            coords.append([float(x_geo), float(y_geo)])
    coords.append(coords[0])
    return coords


def _intersection_over_union(obb1: np.ndarray, obb2: np.ndarray) -> float:
    """Calculate IoU between two oriented bounding boxes."""
    if not SHAPELY_AVAILABLE:
        return 0.0
    try:
        poly1 = Polygon(obb1)
        poly2 = Polygon(obb2)
        intersection = poly1.intersection(poly2).area
        union = poly1.union(poly2).area
        return intersection / union if union > 0 else 0.0
    except Exception:
        return 0.0


def _intersection_over_min_area(obb1: np.ndarray, obb2: np.ndarray) -> float:
    """Calculate IoMA (intersection over minimum area) between two OBBs."""
    if not SHAPELY_AVAILABLE:
        return 0.0
    try:
        poly1 = Polygon(obb1)
        poly2 = Polygon(obb2)
        intersection = poly1.intersection(poly2).area
        min_area = min(poly1.area, poly2.area)
        return intersection / min_area if min_area > 0 else 0.0
    except Exception:
        return 0.0


def _get_min_max_xy(obb: np.ndarray) -> Tuple[float, float, float, float]:
    """Get bounding box (min_y, min_x, max_y, max_x) from OBB."""
    min_x, min_y = np.amin(obb, axis=0)
    max_x, max_y = np.amax(obb, axis=0)
    return float(min_y), float(min_x), float(max_y), float(max_x)


def _get_object_grid(
    obb1: np.ndarray,
    obb2: np.ndarray,
    grid_lim1: Tuple[int, int, int, int],
    grid_lim2: Tuple[int, int, int, int],
    pred_score1: float,
    pred_score2: float,
) -> int:
    """
    Determine which detection to keep when two detections overlap.
    
    Returns:
        1: Keep obb1, discard obb2
        2: Keep obb2, discard obb1
    """
    bbox1 = _get_min_max_xy(obb1)
    bbox2 = _get_min_max_xy(obb2)
    
    # Check if objects are on tile edges
    obj1_edge = (
        bbox1[0] <= grid_lim1[0]
        or bbox1[1] <= grid_lim1[1]
        or bbox1[2] >= grid_lim1[2]
        or bbox1[3] >= grid_lim1[3]
    )
    obj2_edge = (
        bbox2[0] <= grid_lim2[0]
        or bbox2[1] <= grid_lim2[1]
        or bbox2[2] >= grid_lim2[2]
        or bbox2[3] >= grid_lim2[3]
    )
    
    # Prefer non-edge detections, or higher confidence if both are non-edge
    if (obj1_edge and not obj2_edge) or (not obj1_edge and not obj2_edge and pred_score2 > pred_score1):
        return 2
    return 1


class InferenceRunner:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.hybrid_mode = config.workers.hybrid_mode
        self.manifest_writer = ManifestWriter(config.artifacts)
        
        # Get list of available GPUs
        logger.info("GPU Configuration: %d GPU(s) declared in config", len(config.gpus))
        for gpu_id, gpu_cfg in config.gpus.items():
            logger.info("  - %s: %s", gpu_id, gpu_cfg.device)
        
        available_gpus = [gpu_cfg.device for gpu_cfg in config.gpus.values()]
        logger.info("PyTorch CUDA available: %s", torch.cuda.is_available())
        if torch.cuda.is_available():
            logger.info("PyTorch detected %d GPU(s)", torch.cuda.device_count())
            for i in range(torch.cuda.device_count()):
                logger.info("  - GPU %d: %s", i, torch.cuda.get_device_name(i))
        
        if not available_gpus and torch.cuda.is_available():
            # Fallback: auto-detect GPUs
            logger.info("No GPUs in config, but CUDA available. Auto-detecting GPUs...")
            available_gpus = [f"cuda:{i}" for i in range(torch.cuda.device_count())]
        
        # Check if CUDA is actually available
        if available_gpus and not torch.cuda.is_available():
            logger.warning(
                "GPUs configured in config (%s) but CUDA is not available. "
                "This may be due to: "
                "1) No NVIDIA GPU in system, "
                "2) nvidia-docker not installed (Linux) or Docker Desktop GPU not enabled (Windows), "
                "3) Docker runtime not set to 'nvidia' (Linux) or --gpus flag not used (Windows). "
                "Falling back to CPU.",
                available_gpus
            )
            available_gpus = []
        
        if self.hybrid_mode:
            # Hybrid mode: Load all models on all GPUs (or CPU if no GPUs)
            # Initialize gpu_balancer to None first
            self.gpu_balancer = None
            
            if available_gpus:
                logger.info("")
                logger.info("Hybrid mode enabled: Loading all models on all GPUs")
                logger.info("")
                self.models: Dict[str, Dict[str, ModelHandle]] = {}
                failed_models = []
                
                for model_name, model_cfg in config.models.items():
                    logger.info("Loading model '%s' on all GPUs...", model_name)
                    try:
                        self.models[model_name] = {}
                        for gpu in available_gpus:
                            logger.info("  Loading on %s...", gpu)
                            try:
                                self.models[model_name][gpu] = _load_model(model_cfg, gpu)
                            except Exception as e:
                                logger.error("  ✗ Failed to load model '%s' on %s: %s", model_name, gpu, e)
                                # Continue trying other GPUs
                                raise
                        logger.info("  ✓ Model '%s' loaded successfully on all GPUs", model_name)
                        logger.info("")
                    except Exception as e:
                        logger.error("")
                        logger.error("✗ Failed to load model '%s': %s", model_name, e)
                        logger.error("  This model will be skipped. Check the error above and fix the model path in pipeline.yaml")
                        logger.error("")
                        failed_models.append((model_name, str(e)))
                        # Don't add this model to self.models
                
                if failed_models:
                    logger.warning("=" * 80)
                    logger.warning("MODEL LOADING SUMMARY")
                    logger.warning("=" * 80)
                    logger.warning("Successfully loaded: %d model(s)", len(self.models))
                    logger.warning("Failed to load: %d model(s)", len(failed_models))
                    for model_name, error in failed_models:
                        logger.warning("  - %s: %s", model_name, error)
                    logger.warning("")
                    
                    # Only fail if ALL models failed
                    if len(self.models) == 0:
                        error_msg = (
                            "CRITICAL: All models failed to load. Cannot continue.\n"
                            "Please fix the model paths in pipeline.yaml and restart the pipeline."
                        )
                        logger.error("=" * 80)
                        logger.error(error_msg)
                        logger.error("=" * 80)
                        raise RuntimeError(error_msg)
                    else:
                        logger.warning("Pipeline will continue with successfully loaded models only.")
                        logger.warning("Images will only be processed by models that loaded successfully.")
                        logger.warning("=" * 80)
                        logger.warning("")
                else:
                    logger.info("Successfully loaded %d model(s) on %d GPU(s)", len(self.models), len(available_gpus))
                    logger.info("")
            else:
                logger.warning(
                    "Hybrid mode enabled but no GPUs available. Loading models on CPU instead."
                )
                self.models: Dict[str, ModelHandle] = {}
                failed_models = []
                
                for model_name, model_cfg in config.models.items():
                    try:
                        logger.info("Loading model '%s' on CPU...", model_name)
                        self.models[model_name] = _load_model(model_cfg, "cpu")
                        logger.info("  ✓ Model '%s' loaded successfully", model_name)
                    except Exception as e:
                        logger.error("  ✗ Failed to load model '%s': %s", model_name, e)
                        failed_models.append((model_name, str(e)))
                
                if failed_models:
                    logger.warning("=" * 80)
                    logger.warning("MODEL LOADING SUMMARY")
                    logger.warning("=" * 80)
                    logger.warning("Successfully loaded: %d model(s)", len(self.models))
                    logger.warning("Failed to load: %d model(s)", len(failed_models))
                    for model_name, error in failed_models:
                        logger.warning("  - %s: %s", model_name, error)
                    logger.warning("")
                    
                    if len(self.models) == 0:
                        error_msg = (
                            "CRITICAL: All models failed to load. Cannot continue.\n"
                            "Please fix the model paths in pipeline.yaml and restart the pipeline."
                        )
                        logger.error("=" * 80)
                        logger.error(error_msg)
                        logger.error("=" * 80)
                        raise RuntimeError(error_msg)
                    else:
                        logger.warning("Pipeline will continue with successfully loaded models only.")
                        logger.warning("=" * 80)
                        logger.warning("")
                else:
                    logger.info("Loaded %d models on CPU", len(self.models))
            
            # Initialize GPU load balancer (only if GPUs are available)
            if available_gpus:
                self.gpu_balancer = GPULoadBalancer(
                    available_gpus,
                    strategy=config.workers.gpu_balancing_strategy
                )
        else:
            # Traditional mode: Load each model on its assigned GPU
            logger.info("")
            logger.info("Traditional mode: Loading models on assigned GPUs")
            logger.info("")
            self.models: Dict[str, ModelHandle] = {}
            failed_models = []
            
            for model_name, model_cfg in config.models.items():
                device = model_cfg.device or (available_gpus[0] if available_gpus else "cpu")
                logger.info("Loading model '%s' on device '%s'...", model_name, device)
                try:
                    self.models[model_name] = _load_model(model_cfg, device)
                    logger.info("  ✓ Model '%s' loaded successfully", model_name)
                    logger.info("")
                except Exception as e:
                    logger.error("  ✗ Failed to load model '%s': %s", model_name, e)
                    logger.error("  This model will be skipped. Check the error above and fix the model path in pipeline.yaml")
                    logger.error("")
                    failed_models.append((model_name, str(e)))
            
            if failed_models:
                logger.warning("=" * 80)
                logger.warning("MODEL LOADING SUMMARY")
                logger.warning("=" * 80)
                logger.warning("Successfully loaded: %d model(s)", len(self.models))
                logger.warning("Failed to load: %d model(s)", len(failed_models))
                for model_name, error in failed_models:
                    logger.warning("  - %s: %s", model_name, error)
                logger.warning("")
                
                # Only fail if ALL models failed
                if len(self.models) == 0:
                    error_msg = (
                        "CRITICAL: All models failed to load. Cannot continue.\n"
                        "Please fix the model paths in pipeline.yaml and restart the pipeline."
                    )
                    logger.error("=" * 80)
                    logger.error(error_msg)
                    logger.error("=" * 80)
                    raise RuntimeError(error_msg)
                else:
                    logger.warning("Pipeline will continue with successfully loaded models only.")
                    logger.warning("Images will only be processed by models that loaded successfully.")
                    logger.warning("=" * 80)
                    logger.warning("")
            else:
                logger.info("Successfully loaded %d model(s) in traditional mode", len(config.models))
                logger.info("")
            self.gpu_balancer = None

    def force_memory_return_to_os(self) -> None:
        """
        Force Python to return freed memory to the OS.
        
        Python's memory allocator (pymalloc) doesn't immediately return freed memory
        to the OS - it keeps it in its own heap for reuse. This function attempts to
        force memory return using platform-specific methods.
        
        SAFETY: This function is safe to call even if processing is active because:
        - It only performs garbage collection (gc.collect()) which is thread-safe
        - It only clears PyTorch CUDA cache (torch.cuda.empty_cache()) which is safe
        - It does NOT delete or modify any active objects (models, configs, etc.)
        - Models (self.models) are intentionally kept in memory for performance
        
        However, this function should only be called when the system is idle to avoid
        unnecessary overhead during active processing.
        """
        logger.info("=" * 80)
        logger.info("FORCING MEMORY RETURN TO OS")
        logger.info("=" * 80)
        
        # Get memory before cleanup
        memory_before = None
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_before = memory_info.rss / (1024 * 1024 * 1024)  # Convert to GB
            logger.info("Memory before force cleanup: %.2f GB", memory_before)
        except Exception as e:
            logger.debug("Could not get memory usage: %s", e)
        
        # Multiple aggressive garbage collection passes
        try:
            for generation in [0, 1, 2]:
                collected = gc.collect(generation)
                logger.debug("GC generation %d: collected %d objects", generation, collected)
            
            # Final full collection
            collected = gc.collect()
            logger.info("Garbage collection: collected %d objects", collected)
        except Exception as e:
            logger.warning("Error during garbage collection: %s", e)
        
        # Clear PyTorch CUDA cache if available
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logger.info("Cleared PyTorch CUDA cache")
        except Exception as e:
            logger.debug("Could not clear CUDA cache: %s", e)
        
        # Try to force memory return to OS (Linux only)
        try:
            import ctypes
            import sys
            
            # On Linux, use malloc_trim to return freed memory to OS
            if sys.platform == 'linux' or sys.platform.startswith('linux'):
                try:
                    # Try to load libc
                    try:
                        libc = ctypes.CDLL("libc.so.6")
                    except OSError:
                        # Try alternative paths
                        try:
                            libc = ctypes.CDLL("libc.so")
                        except OSError:
                            libc = None
                    
                    if libc is not None:
                        # Define malloc_trim function signature: int malloc_trim(size_t pad)
                        libc.malloc_trim.argtypes = [ctypes.c_size_t]
                        libc.malloc_trim.restype = ctypes.c_int
                        
                        # Call malloc_trim multiple times to be more aggressive
                        # malloc_trim(0) returns freed memory to OS
                        results = []
                        for attempt in range(3):  # Try 3 times
                            result = libc.malloc_trim(0)
                            results.append(result)
                            if result == 1:
                                break
                            time.sleep(0.1)  # Small delay between attempts
                        
                        if any(r == 1 for r in results):
                            logger.info("Successfully called malloc_trim() to return memory to OS (attempts: %s)", results)
                        else:
                            logger.debug("malloc_trim() returned %s (may not have freed memory)", results)
                    else:
                        logger.debug("Could not load libc.so.6 or libc.so")
                except (OSError, AttributeError, Exception) as e:
                    logger.warning("Could not call malloc_trim(): %s", e)
            elif sys.platform == 'win32':
                # On Windows, Python uses its own allocator - no direct OS call available
                logger.debug("Windows: Python memory allocator doesn't support direct OS return")
            else:
                logger.debug("Platform %s: No known method to force memory return", sys.platform)
        except Exception as e:
            logger.warning("Error attempting to force memory return: %s", e)
        
        # Get memory after cleanup
        if memory_before is not None:
            try:
                import psutil
                process = psutil.Process()
                memory_info = process.memory_info()
                memory_after = memory_info.rss / (1024 * 1024 * 1024)  # Convert to GB
                memory_freed = memory_before - memory_after
                logger.info("Memory after force cleanup: %.2f GB", memory_after)
                if memory_freed > 0:
                    logger.info("✓ Memory returned: %.2f GB freed (%.2f GB → %.2f GB)", 
                              memory_freed, memory_before, memory_after)
                else:
                    logger.info("Memory usage: %.2f GB (Python allocator may not return memory to OS immediately)", 
                              memory_after)
                    logger.info("Note: This is normal Python behavior - memory is freed internally and available for reuse")
            except Exception as e:
                logger.debug("Could not get memory usage after cleanup: %s", e)
        
        logger.info("=" * 80)
        logger.info("")
        logger.info("IMPORTANT: PyTorch models (self.models) remain loaded in memory for performance.")
        logger.info("This is intentional - models are reused across all images.")
        logger.info("To free model memory, restart the pipeline.")
        logger.info("")

    def process(self, job_id: str, image_path: Path, folder_identity: Optional[str] = None) -> Dict[str, Path]:
        # Get image stem for file naming
        image_stem = image_path.stem
        
        # Prepare artifact directories first to get log path
        artifacts = self._prepare_artifact_dirs(job_id, image_stem, folder_identity)
        
        # Create logger with log file in the image folder (also writes to daily logs)
        image_logger = create_image_logger(
            job_id, self.config.logging, log_file=artifacts["log"], artifacts_config=self.config.artifacts
        )
        start_time = time.time()
        image_logger.info("=" * 80)
        image_logger.info("STARTING JOB: %s", job_id)
        image_logger.info("=" * 80)
        image_logger.info("Image Path: %s", image_path)
        image_logger.info("Image File: %s", image_path.name)
        image_logger.info("Folder Identity: %s", folder_identity or "root")
        image_logger.info("")

        # Initialize output variables early to prevent UnboundLocalError if exception occurs
        # These will be populated later with model names, but start empty to avoid scoping issues
        per_model_features: Dict[str, List[Dict]] = {}
        per_model_counts: Dict[str, Dict[str, int]] = {}
        detections_summary: Dict[str, List[Dict]] = {}
        per_model_paths: Dict[str, Path] = {}
        summary_paths: Dict[str, Path] = {}
        combined_path: Path = Path()
        manifest_path: Path = Path()
        return_values: Dict[str, Path] = {}  # Will be populated before cleanup

        # Select GPU for this job (hybrid mode) or use assigned GPUs (traditional mode)
        if self.hybrid_mode:
            if self.gpu_balancer is not None:
                selected_gpu = self.gpu_balancer.get_least_busy_gpu()
                if not selected_gpu:
                    logger.warning("No GPU available from balancer, falling back to CPU")
                    selected_gpu = "cpu"
                else:
                    image_logger.info("Assigned to GPU: %s (hybrid mode)", selected_gpu)
                    self.gpu_balancer.register_job_start(selected_gpu)
            else:
                # No GPUs available, use CPU
                selected_gpu = "cpu"
                image_logger.info("No GPUs available, using CPU (hybrid mode)")
        else:
            selected_gpu = None  # Not used in traditional mode

        try:
            # ========================================================================
            # STEP 1: Image File Validation
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 1: IMAGE FILE VALIDATION")
            image_logger.info("-" * 80)
            
            if not image_path.exists():
                error_msg = f"Image file not found: {image_path}"
                image_logger.error(error_msg)
                raise FileNotFoundError(error_msg)
            image_logger.info("✓ Image file exists: %s", image_path)
            
            if not image_path.is_file():
                error_msg = f"Image path is not a file: {image_path}"
                image_logger.error(error_msg)
                raise ValueError(error_msg)
            image_logger.info("✓ Image path is a valid file")
            
            # Get file size
            file_size = image_path.stat().st_size
            file_size_mb = file_size / (1024 * 1024)
            image_logger.info("  File Size: %.2f MB (%d bytes)", file_size_mb, file_size)
            
            # Try to open and validate image (use first model's tiling config for initial validation)
            # We'll create per-model tilers later
            first_model_tile_config = (
                list(self.config.models.values())[0].tile 
                if self.config.models and list(self.config.models.values())[0].tile 
                else self.config.tiling
            )
            try:
                image_logger.info("  Opening image with GDAL...")
                tiler = RasterTiler(image_path, first_model_tile_config)
                image_logger.info("✓ Image opened successfully")
                image_logger.info("  Image Dimensions: %d x %d pixels", tiler.width, tiler.height)
                image_logger.info("  Number of Bands: %d", tiler.band_count)
            except RuntimeError as e:
                error_msg = str(e)
                if "zero bands" in error_msg.lower() or "failed to open" in error_msg.lower():
                    error_msg_full = f"Image file appears corrupted or invalid: {error_msg}"
                    image_logger.error("✗ %s", error_msg_full)
                    raise RuntimeError(error_msg_full) from e
                raise
            except Exception as e:
                error_msg_full = f"Failed to read image file {image_path}: {e}"
                image_logger.error("✗ %s", error_msg_full)
                raise RuntimeError(error_msg_full) from e

            # ========================================================================
            # STEP 2: CRS Extraction and Validation
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 2: CRS EXTRACTION AND VALIDATION")
            image_logger.info("-" * 80)
            
            try:
                image_logger.info("  Extracting CRS from image metadata...")
                source_crs, method = _resolve_source_crs(tiler.dataset)
                image_logger.info("  Extraction method: %s", method or "None")
                
                if source_crs:
                    image_logger.info("✓ CRS detected via %s", method)
                    image_logger.info("  Source CRS: %s", source_crs.to_string())
                else:
                    image_logger.warning("  No CRS found in image metadata")
                
                # Create transformer
                image_logger.info("  Creating coordinate transformer...")
                transformer = _create_transformer(source_crs)
                if transformer:
                    image_logger.info("✓ Transformer created for CRS conversion")
                elif source_crs == TARGET_CRS:
                    image_logger.info("✓ Image already in target CRS (WGS84), no transformation needed")
                else:
                    image_logger.info("  No transformer needed")
                
                # Validate CRS - this will raise an error if invalid
                _validate_crs(source_crs, transformer, image_logger)
                image_logger.info("✓ CRS validation passed - processing can continue")
                
            except RuntimeError:
                # Re-raise CRS validation errors
                raise
            except Exception as e:
                error_msg = f"Failed to extract or validate CRS from image: {e}"
                image_logger.error("✗ %s", error_msg)
                image_logger.error("  This is a critical error - cannot generate valid GeoJSON without CRS")
                raise RuntimeError(error_msg) from e
            # ========================================================================
            # STEP 3: Model Selection and Configuration
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 3: MODEL SELECTION AND CONFIGURATION")
            image_logger.info("-" * 80)
            
            # Filter models based on folder identity
            image_logger.info("  Filtering models for folder identity: %s", folder_identity or "root")
            # Log all available models and their folder filtering config
            image_logger.info("  Available models in config: %s", list(self.config.models.keys()))
            for model_name, model_cfg in self.config.models.items():
                if model_cfg.all_folders:
                    image_logger.debug("    Model '%s': all_folders=True (will process)", model_name)
                elif model_cfg.folder_identities:
                    image_logger.debug("    Model '%s': folder_identities=%s", model_name, model_cfg.folder_identities)
                else:
                    image_logger.debug("    Model '%s': no folder filtering configured (will not process)", model_name)
            
            applicable_models = self._filter_models_by_folder(folder_identity)
            if not applicable_models:
                error_msg = f"No models applicable for folder identity '{folder_identity}'. Skipping processing."
                image_logger.error("✗ %s", error_msg)
                image_logger.error("  Check that at least one model has:")
                image_logger.error("    - all_folders: true, OR")
                image_logger.error("    - folder_identities containing '%s' (case-insensitive)", folder_identity)
                raise ValueError(f"No models configured for folder identity: {folder_identity}")
            
            # ========================================================================
            # STEP 3.5: ROI Filtering (if configured)
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 3.5: ROI FILTERING")
            image_logger.info("-" * 80)
            
            roi_filter = ROIFilter()
            per_model_pixel_bounds: Dict[str, Optional[Tuple[int, int, int, int]]] = {}
            models_to_skip: List[str] = []
            
            # Get image bounds once (reuse tiler.dataset)
            image_bounds = roi_filter.get_image_geographic_bounds(tiler.dataset)
            if not image_bounds:
                image_logger.warning("  Image has no geographic bounds (no geotransform/projection)")
                image_logger.warning("  ROI filtering cannot be applied - processing full image for all models")
                # Set all models to process full image
                for model_name in applicable_models.keys():
                    per_model_pixel_bounds[model_name] = None
            else:
                image_logger.info("  Image geographic bounds extracted successfully")
                
                # Get image CRS for ROI reprojection
                image_crs = roi_filter.get_image_crs(tiler.dataset)
                if image_crs:
                    image_logger.info("  Image CRS: %s", image_crs.to_string())
                else:
                    image_logger.warning("  Image CRS unknown - ROI reprojection may fail")
                
                # Check ROI for each model
                for model_name, model_config in applicable_models.items():
                    if model_config.roi_geojson_path:
                        try:
                            image_logger.info("  Checking ROI for model '%s'...", model_name)
                            image_logger.info("    ROI GeoJSON: %s", model_config.roi_geojson_path)
                            
                            # Load ROI polygons
                            roi_polygons = roi_filter.load_roi_geojson(model_config.roi_geojson_path)
                            image_logger.info("    Loaded %d ROI polygon(s)", len(roi_polygons))
                            
                            # Ensure ROI is in same CRS as image
                            # Assume ROI is in WGS84 (EPSG:4326) if not specified
                            roi_crs = CRS.from_epsg(4326)  # Default assumption
                            roi_polygons, effective_crs = roi_filter.ensure_same_crs(
                                roi_polygons, roi_crs, image_crs
                            )
                            
                            # Compute intersection
                            intersection = roi_filter.compute_intersection(image_bounds, roi_polygons)
                            
                            if not intersection:
                                image_logger.info("    ✗ Image does not intersect ROI - skipping model '%s'", model_name)
                                models_to_skip.append(model_name)
                                per_model_pixel_bounds[model_name] = None
                                continue
                            
                            # Calculate pixel bounds from intersection
                            pixel_bounds = roi_filter.geographic_to_pixel_bounds(intersection, tiler.dataset)
                            per_model_pixel_bounds[model_name] = pixel_bounds
                            
                            xmin, ymin, xmax, ymax = pixel_bounds
                            cropped_width = xmax - xmin + 1
                            cropped_height = ymax - ymin + 1
                            original_width = tiler.dataset.RasterXSize
                            original_height = tiler.dataset.RasterYSize
                            crop_ratio = (cropped_width * cropped_height) / (original_width * original_height)
                            
                            image_logger.info("    ✓ Image intersects ROI")
                            image_logger.info("    Cropped region: (%d, %d) to (%d, %d)", xmin, ymin, xmax, ymax)
                            image_logger.info("    Cropped size: %d x %d pixels (%.1f%% of original)", 
                                            cropped_width, cropped_height, crop_ratio * 100)
                            
                        except Exception as e:
                            image_logger.warning("    ✗ ROI filtering failed for model '%s': %s", model_name, e)
                            image_logger.warning("    Falling back to processing full image")
                            per_model_pixel_bounds[model_name] = None
                    else:
                        # No ROI configured - process full image
                        image_logger.debug("    Model '%s': No ROI configured - processing full image", model_name)
                        per_model_pixel_bounds[model_name] = None
            
            # Remove models that don't intersect ROI
            if models_to_skip:
                image_logger.info("")
                image_logger.info("  Removing %d model(s) that don't intersect ROI: %s", 
                               len(models_to_skip), ", ".join(models_to_skip))
                for model_name in models_to_skip:
                    applicable_models.pop(model_name, None)
                    per_model_pixel_bounds.pop(model_name, None)
            
            if not applicable_models:
                error_msg = "No models remain after ROI filtering. All models were skipped."
                image_logger.error("✗ %s", error_msg)
                raise ValueError(error_msg)
            
            model_names = list(applicable_models.keys())
            image_logger.info("")
            image_logger.info("✓ Selected %d model(s) for processing after ROI filtering:", len(applicable_models))
            for model_name in model_names:
                model_config = applicable_models[model_name]
                pixel_bounds = per_model_pixel_bounds.get(model_name)
                if pixel_bounds:
                    image_logger.info("  - %s (type: %s, confidence: %.2f, ROI cropped)", 
                                    model_name, model_config.type, model_config.confidence_threshold)
                else:
                    image_logger.info("  - %s (type: %s, confidence: %.2f, full image)", 
                                    model_name, model_config.type, model_config.confidence_threshold)
            
            preview_tracker: Dict[str, set] = {name: set() for name in model_names}

            # ========================================================================
            # STEP 4: Tiling Configuration
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 4: TILING CONFIGURATION")
            image_logger.info("-" * 80)
            
            # Group models by tile config to enable tiler sharing
            # Models with identical tile_size, overlap, and normalization_mode can share a tiler
            tile_config_to_models: Dict[Tuple[int, int, str], List[str]] = {}
            for model_name, model_config in applicable_models.items():
                # Use model-specific tiling config if available, otherwise use global
                model_tile_config = model_config.tile or self.config.tiling
                config_key = _get_tile_config_key(model_tile_config)
                if config_key not in tile_config_to_models:
                    tile_config_to_models[config_key] = []
                tile_config_to_models[config_key].append(model_name)
            
            # Create shared tilers (one per unique tile config)
            tile_config_to_tiler: Dict[Tuple[int, int, str], RasterTiler] = {}
            per_model_tilers: Dict[str, RasterTiler] = {}
            
            image_logger.info("  Creating tilers with sharing optimization...")
            for tile_config_key, models_in_group in tile_config_to_models.items():
                # Get tile config from first model (all models in this group have same config)
                first_model = applicable_models[models_in_group[0]]
                model_tile_config = first_model.tile or self.config.tiling
                
                # Check if all models in this group have the same pixel_bounds
                # If they do, we can share the tiler; otherwise, create separate tilers
                group_pixel_bounds = per_model_pixel_bounds.get(models_in_group[0])
                all_same_bounds = all(
                    per_model_pixel_bounds.get(m) == group_pixel_bounds 
                    for m in models_in_group
                )
                
                if all_same_bounds and len(models_in_group) > 1:
                    # All models share same ROI bounds - create shared tiler
                    shared_tiler = RasterTiler(image_path, model_tile_config, pixel_bounds=group_pixel_bounds)
                    tile_config_to_tiler[tile_config_key] = shared_tiler
                else:
                    # Models have different ROI bounds or only one model - create separate tilers
                    for model_name in models_in_group:
                        model_pixel_bounds = per_model_pixel_bounds.get(model_name)
                        model_tiler = RasterTiler(image_path, model_tile_config, pixel_bounds=model_pixel_bounds)
                        # Store in per_model_tilers directly (not in shared dict)
                        per_model_tilers[model_name] = model_tiler
                    # Don't create shared tiler for this group
                    continue
                
                # Calculate tile grid dimensions (using shared tiler's dimensions)
                tiles_per_row = (shared_tiler.width + model_tile_config.tile_size - model_tile_config.overlap - 1) // (model_tile_config.tile_size - model_tile_config.overlap)
                tiles_per_col = (shared_tiler.height + model_tile_config.tile_size - model_tile_config.overlap - 1) // (model_tile_config.tile_size - model_tile_config.overlap)
                total_tiles = tiles_per_row * tiles_per_col
                
                # Assign shared tiler to all models with this config
                if len(models_in_group) > 1:
                    image_logger.info("  ✓ Shared tiler created for %d models (config: %dx%d, overlap: %d)", 
                                    len(models_in_group), model_tile_config.tile_size, 
                                    model_tile_config.tile_size, model_tile_config.overlap)
                    image_logger.info("    Models sharing this tiler: %s", ", ".join(models_in_group))
                else:
                    image_logger.info("  ✓ Tiler created for model: %s", models_in_group[0])
                
                image_logger.info("    Tile Size: %d pixels", model_tile_config.tile_size)
                image_logger.info("    Overlap: %d pixels (%.1f%%)", 
                                 model_tile_config.overlap, 
                                 (model_tile_config.overlap / model_tile_config.tile_size) * 100)
                image_logger.info("    Tile Grid: %d rows x %d cols = %d total tiles", 
                                 tiles_per_row, tiles_per_col, total_tiles)
                image_logger.info("    Normalization: %s", model_tile_config.normalization_mode)
                image_logger.info("    IoU Threshold: %.2f", model_tile_config.iou_threshold)
                image_logger.info("    IoMA Threshold: %.2f", model_tile_config.ioma_threshold)
                
                # Assign shared tiler to all models in this group (only if shared tiler was created)
                if tile_config_key in tile_config_to_tiler:
                    shared_tiler = tile_config_to_tiler[tile_config_key]
                    for model_name in models_in_group:
                        per_model_tilers[model_name] = shared_tiler
            
            # Log memory savings summary
            total_models = len(applicable_models)
            unique_configs = len(tile_config_to_tiler)
            if total_models > unique_configs:
                savings = total_models - unique_configs
                image_logger.info("")
                image_logger.info("  💾 Memory Optimization: %d unique tilers for %d models (saved %d tiler instances)", 
                                unique_configs, total_models, savings)

            # ========================================================================
            # STEP 5: INFERENCE - Collecting Detections
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 5: INFERENCE - COLLECTING DETECTIONS")
            image_logger.info("-" * 80)
            
            # Collect all detections per model and per tile for cross-tile NMS
            # Structure: per_model_detections[model_name][tile_row][tile_col] = [TileDetection, ...]
            per_model_detections: Dict[str, Dict[int, Dict[int, List[TileDetection]]]] = {
                name: {} for name in model_names
            }

            # Process each model with its own tiles
            image_logger.info("  Will process %d model(s) in order: %s", len(model_names), model_names)
            for model_name in model_names:
                try:
                    model_start_time = time.time()
                    image_logger.info("")
                    image_logger.info("  Processing model: %s", model_name)
                    image_logger.info("  " + "-" * 76)
                    
                    # Verify model is available
                    if model_name not in per_model_tilers:
                        error_msg = f"Model '{model_name}' not found in per_model_tilers. Available: {list(per_model_tilers.keys())}"
                        image_logger.error("    ✗ %s", error_msg)
                        logger.error(error_msg)
                        continue
                    
                    if model_name not in applicable_models:
                        error_msg = f"Model '{model_name}' not found in applicable_models. Available: {list(applicable_models.keys())}"
                        image_logger.error("    ✗ %s", error_msg)
                        logger.error(error_msg)
                        continue
                    
                    model_tiler = per_model_tilers[model_name]
                    model_config = applicable_models[model_name]  # Use filtered models, not all config models
                    batch: List[torch.Tensor] = []
                    tiles_batch: List[Tile] = []
                    batch_size = model_config.batch_size or self.config.workers.batch_size
                    
                    image_logger.info("    Batch Size: %d tiles", batch_size)
                    image_logger.info("    Confidence Threshold: %.2f", model_config.confidence_threshold)
                    
                    # Track statistics
                    total_tiles_processed = 0
                    total_batches = 0
                    total_detections_raw = 0

                    def flush_batch():
                        nonlocal batch, tiles_batch, total_batches, total_detections_raw
                        if not batch:
                            return
                        tensor = torch.stack(batch, dim=0)
                        total_batches += 1
                        
                        try:
                            if self.hybrid_mode:
                                # In hybrid mode, run model on the selected GPU (or CPU if no GPU)
                                if isinstance(self.models[model_name], dict):
                                    # Multi-GPU structure
                                    if selected_gpu in self.models[model_name]:
                                        model_handle = self.models[model_name][selected_gpu]
                                        device = selected_gpu
                                    else:
                                        # Fallback to first available device
                                        available_devices = list(self.models[model_name].keys())
                                        if available_devices:
                                            device = available_devices[0]
                                            model_handle = self.models[model_name][device]
                                        else:
                                            raise RuntimeError(f"No model handle available for {model_name}")
                                else:
                                    # Single model handle (CPU fallback structure)
                                    model_handle = self.models[model_name]
                                    device = model_handle.device
                            else:
                                # In traditional mode, use model's assigned GPU
                                model_handle = self.models[model_name]
                                device = model_handle.device
                            
                            detections_before = total_detections_raw
                            self._collect_detections(
                                model_handle,
                                tensor.to(device),
                                tiles_batch,
                                model_tiler,
                                per_model_detections[model_name],
                                artifacts["tiles"][model_name],
                                preview_tracker[model_name],
                                image_logger,
                            )
                            # Count detections in this batch
                            for tile in tiles_batch:
                                row = tile.metadata.row
                                col = tile.metadata.col
                                if row in per_model_detections[model_name] and col in per_model_detections[model_name][row]:
                                    total_detections_raw += len(per_model_detections[model_name][row][col])
                            
                            if total_detections_raw > detections_before:
                                image_logger.debug("    Batch %d: Processed %d tiles, found %d detections", 
                                                 total_batches, len(tiles_batch), total_detections_raw - detections_before)
                        except Exception as e:
                            error_msg = f"Model {model_name} failed on batch: {e}"
                            image_logger.error("    ✗ %s", error_msg, exc_info=True)
                            logger.error(error_msg, exc_info=True)
                            # Continue with other models - don't fail entire job
                        finally:
                            # Explicitly free GPU tensors
                            if 'tensor' in locals() and tensor is not None:
                                if tensor.is_cuda:
                                    del tensor
                                    torch.cuda.empty_cache()
                            batch = []
                            tiles_batch = []

                    # First pass: collect all detections for this model using its own tiles
                    image_logger.info("    Processing tiles...")
                    for tile in model_tiler.iter_tiles():
                        batch.append(_tile_to_tensor(tile))
                        tiles_batch.append(tile)
                        total_tiles_processed += 1
                        if len(batch) >= batch_size:
                            flush_batch()

                    flush_batch()
                    
                    model_time = time.time() - model_start_time
                    image_logger.info("    ✓ Model '%s' inference complete", model_name)
                    image_logger.info("      Tiles Processed: %d", total_tiles_processed)
                    image_logger.info("      Batches: %d", total_batches)
                    image_logger.info("      Raw Detections: %d", total_detections_raw)
                    image_logger.info("      Processing Time: %.2f seconds", model_time)
                except Exception as e:
                    error_msg = f"Model {model_name} failed during inference: {e}"
                    image_logger.error("    ✗ %s", error_msg, exc_info=True)
                    logger.error(error_msg, exc_info=True)
                    # Continue with other models - don't fail entire job
                    # Initialize empty detections for failed model
                    if model_name not in per_model_detections:
                        per_model_detections[model_name] = {}
                except Exception as e:
                    error_msg = f"Model {model_name} failed during inference: {e}"
                    image_logger.error("    ✗ %s", error_msg, exc_info=True)
                    logger.error(error_msg, exc_info=True)
                    # Continue with other models - don't fail entire job
                    # Initialize empty detections for failed model
                    if model_name not in per_model_detections:
                        per_model_detections[model_name] = {}

            # ========================================================================
            # STEP 6: POST-PROCESSING - Cross-Tile NMS and Feature Conversion
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 6: POST-PROCESSING - CROSS-TILE NMS AND FEATURE CONVERSION")
            image_logger.info("-" * 80)
            
            # Initialize feature structures with model names (update existing dict to avoid scoping issues)
            for name in model_names:
                if name not in per_model_features:
                    per_model_features[name] = []
                if name not in per_model_counts:
                    per_model_counts[name] = {"axis_aligned": 0, "oriented": 0}
                if name not in detections_summary:
                    detections_summary[name] = []

            # Process each model independently - one failure doesn't stop others
            failed_models = []
            for model_name in model_names:
                nms_start_time = time.time()
                image_logger.info("")
                image_logger.info("  Processing model: %s", model_name)
                
                try:
                    model_tiler = per_model_tilers[model_name]
                    
                    # Count raw detections before NMS
                    raw_detection_count = 0
                    for row in per_model_detections[model_name]:
                        for col in per_model_detections[model_name][row]:
                            raw_detection_count += len(per_model_detections[model_name][row][col])
                    
                    image_logger.info("    Raw detections before NMS: %d", raw_detection_count)
                    
                    self._apply_cross_tile_nms_and_convert(
                        model_name,
                        per_model_detections[model_name],
                        model_tiler,
                        transformer,
                        per_model_features[model_name],
                        per_model_counts[model_name],
                        detections_summary[model_name],
                        image_logger,
                    )
                    
                    final_count = len(per_model_features[model_name])
                    duplicates_removed = raw_detection_count - final_count
                    nms_time = time.time() - nms_start_time
                    
                    image_logger.info("    ✓ NMS and conversion complete")
                    image_logger.info("      Final detections: %d", final_count)
                    image_logger.info("      Duplicates removed: %d", duplicates_removed)
                    image_logger.info("      Axis-aligned boxes: %d", per_model_counts[model_name]["axis_aligned"])
                    image_logger.info("      Oriented boxes: %d", per_model_counts[model_name]["oriented"])
                    image_logger.info("      Processing time: %.2f seconds", nms_time)
                    
                except Exception as e:
                    error_msg = f"Model {model_name} failed during NMS/feature conversion: {e}"
                    image_logger.error("    ✗ %s", error_msg, exc_info=True)
                    logger.error(error_msg, exc_info=True)
                    failed_models.append(model_name)
                    # Create empty outputs for failed model
                    per_model_features[model_name] = []
                    per_model_counts[model_name] = {"axis_aligned": 0, "oriented": 0}
                    detections_summary[model_name] = []
            
            # Log summary of model failures
            if failed_models:
                image_logger.warning("")
                image_logger.warning("⚠ Some models failed: %s. Continuing with successful models.", failed_models)
                # Check if ALL models failed
                if len(failed_models) == len(model_names):
                    error_msg = f"All models failed for image {image_path}. See logs for details."
                    image_logger.error("✗ %s", error_msg)
                    raise RuntimeError(error_msg)
        finally:
            # Always unregister job from GPU balancer
            if self.hybrid_mode and selected_gpu:
                self.gpu_balancer.register_job_end(selected_gpu)

            # ========================================================================
            # STEP 7: OUTPUT GENERATION
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 7: OUTPUT GENERATION")
            image_logger.info("-" * 80)
            
            # Validate we have valid CRS before writing GeoJSON
            _validate_crs(source_crs, transformer, image_logger)
            image_logger.info("  ✓ CRS validated - safe to write GeoJSON files")
            
            # Get image stem for file naming
            image_stem = image_path.stem
            
            image_logger.info("  Writing per-model GeoJSON files...")
            if per_model_features:  # Only write if we have features (avoid error if processing failed early)
                per_model_paths = self._write_geojsons(image_stem, per_model_features, per_model_counts, artifacts, image_logger)
            else:
                per_model_paths = {}
                image_logger.warning("  No features to write (processing may have failed early)")
            image_logger.info("  ✓ Wrote %d per-model GeoJSON file(s)", len(per_model_paths))
            for model_name, path in per_model_paths.items():
                file_size = path.stat().st_size if path.exists() else 0
                detections = len(per_model_features.get(model_name, []))
                image_logger.info("    - %s: %s (%d detections, %.2f KB)", 
                                model_name, path.name, detections, file_size / 1024)
            
            image_logger.info("  Writing combined GeoJSON file...")
            combined_path = self._write_combined_geojson(image_stem, per_model_features, artifacts, image_logger)
            combined_file_size = combined_path.stat().st_size if combined_path.exists() else 0
            total_detections = sum(len(feats) for feats in per_model_features.values())
            image_logger.info("  ✓ Wrote combined GeoJSON: %s (%d detections, %.2f KB)", 
                            combined_path.name, total_detections, combined_file_size / 1024)
            
            image_logger.info("  Writing CSV summary files...")
            summary_paths = self._write_summaries(image_stem, detections_summary, artifacts, image_logger)
            image_logger.info("  ✓ Wrote %d CSV summary file(s)", len(summary_paths))
            
            image_logger.info("  Copying files to centralized directories...")
            self._copy_to_centralized_dirs(image_stem, combined_path, per_model_paths, summary_paths, artifacts, image_logger)
            image_logger.info("  ✓ Files copied to centralized directories")

            # ========================================================================
            # STEP 7.5: MANIFEST ENTRY CREATION (before cleanup to access variables)
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 7.5: MANIFEST ENTRY CREATION")
            image_logger.info("-" * 80)
            
            # Use the model names that were actually processed (after folder filtering)
            # per_model_paths only contains models that were processed, so use its keys
            # Safely access variables - they are initialized before try block, but Python scoping
            # may treat them as local if modified inside try block
            try:
                processed_model_names = list(per_model_paths.keys())
                features_dict = per_model_features
                paths_dict = per_model_paths
                summaries_dict = summary_paths
            except UnboundLocalError:
                # If exception occurred very early, variables may not be accessible
                # Use empty defaults (initialized values)
                processed_model_names = []
                features_dict = {}
                paths_dict = {}
                summaries_dict = {}

            manifest_entry = ManifestEntry(
                image_path=str(image_path),
                job_id=job_id,
                models={
                    name: {
                        "geojson": str(paths_dict[name]),
                        "summary_csv": str(summaries_dict.get(name, "")),
                        "detections": len(features_dict.get(name, [])),
                    }
                    for name in processed_model_names
                },
                combined_geojson=str(combined_path),
                start_time=start_time,
                end_time=time.time(),
                logs=[str(artifacts["log"])],
            )

            manifest_path = self.manifest_writer.write(manifest_entry)
            image_logger.info("  ✓ Manifest written: %s", manifest_path)

            # ========================================================================
            # STEP 8: FINAL SUMMARY (before cleanup)
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 8: FINAL SUMMARY")
            image_logger.info("-" * 80)
            
            # Final summary
            total_time = time.time() - start_time
            image_logger.info("")
            image_logger.info("=" * 80)
            image_logger.info("JOB COMPLETE: %s", job_id)
            image_logger.info("=" * 80)
            image_logger.info("  Image: %s", image_path.name)
            image_logger.info("  Folder Identity: %s", folder_identity or "root")
            image_logger.info("  Source CRS: %s", source_crs.to_string() if source_crs else "None")
            image_logger.info("  Models Processed: %d", len(processed_model_names))
            image_logger.info("  Total Detections: %d", total_detections)
            image_logger.info("  Processing Time: %.2f seconds", total_time)
            image_logger.info("")
            image_logger.info("  Output Files:")
            image_logger.info("    Combined GeoJSON: %s", combined_path)
            image_logger.info("    Manifest: %s", manifest_path)
            for model_name, path in per_model_paths.items():
                image_logger.info("    %s GeoJSON: %s", model_name, path)
            image_logger.info("    Log File: %s", artifacts["log"])
            image_logger.info("")
            image_logger.info("=" * 80)
            
            log_status_snapshot(image_logger, event="job_complete", job_id=job_id, combined_geojson=str(combined_path))
            
            # Store return values before cleanup (inside try block so variables are accessible)
            return_values = {
                "manifest": manifest_path,
                "combined": combined_path,
                "base": artifacts["base"],  # Include base directory path for orchestrator
                **per_model_paths,
            }

            # ========================================================================
            # STEP 9: MEMORY CLEANUP
            # ========================================================================
            image_logger.info("")
            image_logger.info("STEP 9: MEMORY CLEANUP")
            image_logger.info("-" * 80)
            
            # Log memory usage before cleanup (if psutil available)
            memory_before = None
            try:
                import psutil
                process = psutil.Process()
                memory_info = process.memory_info()
                memory_before = memory_info.rss / (1024 * 1024 * 1024)  # Convert to GB
                image_logger.info("  Memory before cleanup: %.2f GB", memory_before)
            except ImportError:
                image_logger.debug("  psutil not available - skipping memory usage logging")
            except Exception as e:
                image_logger.debug("  Could not get memory usage: %s", e)
            
            try:
                # Clean up per-model tilers (with sharing, only close unique instances)
                if 'per_model_tilers' in locals() and per_model_tilers:
                    image_logger.info("  Closing per-model tilers...")
                    closed_tilers = set()  # Track which tilers have been closed (by id)
                    tiler_count = 0
                    for model_name, model_tiler in list(per_model_tilers.items()):
                        # Use id() to track unique tiler instances (shared tilers have same id)
                        tiler_id = id(model_tiler)
                        if tiler_id not in closed_tilers:
                            try:
                                if hasattr(model_tiler, 'close'):
                                    model_tiler.close()
                                closed_tilers.add(tiler_id)
                                tiler_count += 1
                                image_logger.debug("    Closed tiler for model: %s", model_name)
                            except Exception as e:
                                image_logger.warning("    Failed to close tiler for model %s: %s", model_name, e)
                        else:
                            image_logger.debug("    Model %s uses shared tiler (already closed)", model_name)
                    
                    if tiler_count > 0:
                        image_logger.info("  ✓ Closed %d unique tiler(s) (shared across %d models)", 
                                        tiler_count, len(per_model_tilers))
                    per_model_tilers.clear()
                    del per_model_tilers
            except Exception as e:
                image_logger.warning("  Error cleaning up per-model tilers: %s", e)
            
            try:
                # Clean up initial tiler (used for CRS extraction)
                if 'tiler' in locals() and tiler is not None:
                    image_logger.info("  Closing initial tiler...")
                    try:
                        if hasattr(tiler, 'close'):
                            tiler.close()
                        image_logger.debug("    Closed initial tiler")
                    except Exception as e:
                        image_logger.warning("    Failed to close initial tiler: %s", e)
                    del tiler
                    image_logger.info("  ✓ Initial tiler closed")
            except Exception as e:
                image_logger.warning("  Error cleaning up initial tiler: %s", e)
            
            try:
                # Clean up tiler mapping structures (hold references to tilers that are already closed)
                if 'tile_config_to_tiler' in locals() and tile_config_to_tiler:
                    image_logger.info("  Clearing tiler mapping structures...")
                    tile_config_to_tiler.clear()
                    del tile_config_to_tiler
                    image_logger.debug("    Cleared tile_config_to_tiler")
                
                if 'tile_config_to_models' in locals() and tile_config_to_models:
                    tile_config_to_models.clear()
                    del tile_config_to_models
                    image_logger.debug("    Cleared tile_config_to_models")
                    image_logger.info("  ✓ Tiler mapping structures cleared")
            except Exception as e:
                image_logger.warning("  Error cleaning up tiler mappings: %s", e)
            
            try:
                # Clean up large detection arrays
                if 'per_model_detections' in locals() and per_model_detections:
                    image_logger.info("  Freeing detection arrays...")
                    for model_name in list(per_model_detections.keys()):
                        if model_name in per_model_detections:
                            for row in list(per_model_detections[model_name].keys()):
                                if row in per_model_detections[model_name]:
                                    for col in list(per_model_detections[model_name][row].keys()):
                                        if col in per_model_detections[model_name][row]:
                                            del per_model_detections[model_name][row][col]
                                    del per_model_detections[model_name][row]
                            del per_model_detections[model_name]
                    per_model_detections.clear()
                    del per_model_detections
                    image_logger.info("  ✓ Detection arrays freed")
            except Exception as e:
                image_logger.warning("  Error cleaning up detection arrays: %s", e)
            
            try:
                # Clean up feature and summary data structures
                if 'per_model_features' in locals() and per_model_features:
                    image_logger.info("  Freeing feature arrays...")
                    for model_name in list(per_model_features.keys()):
                        if model_name in per_model_features:
                            # Clear each feature list and ensure numpy arrays are freed
                            for feature in per_model_features[model_name]:
                                # Clear any numpy arrays in feature dicts
                                if isinstance(feature, dict):
                                    for key, value in feature.items():
                                        if hasattr(value, '__array__'):  # numpy array
                                            del value
                            per_model_features[model_name].clear()
                    per_model_features.clear()
                    del per_model_features
                    image_logger.info("  ✓ Feature arrays freed")
                
                if 'detections_summary' in locals() and detections_summary:
                    image_logger.info("  Freeing summary arrays...")
                    for model_name in list(detections_summary.keys()):
                        if model_name in detections_summary:
                            # Clear any numpy arrays in summary data
                            for summary in detections_summary[model_name]:
                                if isinstance(summary, dict):
                                    for key, value in summary.items():
                                        if hasattr(value, '__array__'):  # numpy array
                                            del value
                            detections_summary[model_name].clear()
                    detections_summary.clear()
                    del detections_summary
                    image_logger.info("  ✓ Summary arrays freed")
            except Exception as e:
                image_logger.warning("  Error cleaning up features/summaries: %s", e)
            
            try:
                # Clean up preview tracker
                if 'preview_tracker' in locals() and preview_tracker:
                    image_logger.info("  Clearing preview tracker...")
                    for model_name in list(preview_tracker.keys()):
                        if model_name in preview_tracker:
                            preview_tracker[model_name].clear()
                    preview_tracker.clear()
                    del preview_tracker
                    image_logger.debug("    Cleared preview tracker")
            except Exception as e:
                image_logger.warning("  Error cleaning up preview tracker: %s", e)
            
            try:
                # Clean up other large data structures
                if 'per_model_counts' in locals() and per_model_counts:
                    per_model_counts.clear()
                    del per_model_counts
                    image_logger.debug("    Cleared per_model_counts")
                
                # Note: per_model_paths, summary_paths, combined_path, artifacts are kept
                # for return values, but they're small (just Path objects and dicts)
            except Exception as e:
                image_logger.debug("    Error cleaning up additional structures: %s", e)
            
            try:
                # Clear PyTorch CUDA cache if using GPU
                if 'selected_gpu' in locals() and selected_gpu and selected_gpu.startswith('cuda'):
                    torch.cuda.empty_cache()
                    # Also synchronize to ensure cache is actually cleared
                    torch.cuda.synchronize()
                    image_logger.debug("    Cleared CUDA cache")
            except Exception as e:
                image_logger.debug("    Failed to clear CUDA cache: %s", e)
            
            # Force aggressive garbage collection to free memory
            # Python's GC may not return memory to OS immediately, but multiple passes help
            try:
                # First pass: collect generation 0 (new objects)
                collected = gc.collect(0)
                image_logger.debug("    GC pass 1 (generation 0): collected %d objects", collected)
                
                # Second pass: collect generation 1 (older objects)
                collected = gc.collect(1)
                image_logger.debug("    GC pass 2 (generation 1): collected %d objects", collected)
                
                # Third pass: full collection (all generations)
                collected = gc.collect(2)
                image_logger.debug("    GC pass 3 (full): collected %d objects", collected)
                
                # Final pass: collect any remaining objects
                collected = gc.collect()
                image_logger.info("  ✓ Garbage collection completed (total: %d objects freed)", collected)
            except Exception as e:
                image_logger.warning("  Error during garbage collection: %s", e)
            
            # Additional cleanup: Clear any numpy/PyTorch internal caches
            try:
                import numpy as np
                # Clear numpy's internal cache (if any)
                # Note: numpy doesn't have a global cache, but this ensures arrays are freed
                pass  # No explicit numpy cache to clear
            except Exception as e:
                image_logger.debug("    Could not clear numpy cache: %s", e)
            
            # Note: We do NOT call malloc_trim() here after each image because:
            # 1. malloc_trim() is a process-wide call that affects the entire process's memory allocator
            # 2. Other worker threads may still be processing images and allocating memory
            # 3. Calling malloc_trim() while other threads are active could interfere with their memory allocations
            # 4. malloc_trim() is safely called only in force_memory_return_to_os() when the system is idle
            #
            # Python's memory allocator may not return freed memory to the OS immediately.
            # This is normal Python behavior - freed memory stays in Python's heap for reuse.
            # Docker may show high memory usage even though memory is actually available for reuse.
            # The memory will be returned to the OS under memory pressure or when the process ends.
            
            # Log memory usage after cleanup (if psutil available)
            if memory_before is not None:
                try:
                    import psutil
                    process = psutil.Process()
                    memory_info = process.memory_info()
                    memory_after = memory_info.rss / (1024 * 1024 * 1024)  # Convert to GB
                    memory_freed = memory_before - memory_after
                    image_logger.info("  Memory after cleanup: %.2f GB", memory_after)
                    if memory_freed > 0:
                        image_logger.info("  ✓ RAM cleared: %.2f GB freed (%.2f GB → %.2f GB)", 
                                        memory_freed, memory_before, memory_after)
                    else:
                        image_logger.info("  ✓ RAM cleared: Memory freed (current: %.2f GB)", memory_after)
                except Exception as e:
                    image_logger.debug("  Could not get memory usage after cleanup: %s", e)
            else:
                # If psutil not available, still log that cleanup happened
                image_logger.info("  ✓ RAM cleared: All image data and tensors freed from memory")
            
            image_logger.info("  Memory cleanup complete - Ready for next image")
            
            # Return values (stored before cleanup, or empty dict if exception occurred early)
            return return_values

    def _collect_detections(
        self,
        handle: ModelHandle,
        batch_tensor: torch.Tensor,
        tiles: List[Tile],
        tiler: RasterTiler,
        detections_store: Dict[int, Dict[int, List[TileDetection]]],
        preview_dir: Path,
        preview_tracker: set,
        image_logger,
    ) -> None:
        """Collect detections from model inference without converting to features yet."""
        tile_cfg: TilingConfig = handle.config.tile or self.config.tiling
        task_args = {"imgsz": tile_cfg.tile_size, "agnostic_nms": True, "verbose": False}
        if handle.config.type == "yolo_obb":
            task_args["task"] = "obb"

        try:
            with torch.no_grad():
                results = handle.model(batch_tensor, **task_args)
        except RuntimeError as e:
            error_msg = str(e)
            # Check for common model errors
            if "CUDA" in error_msg or "out of memory" in error_msg.lower():
                raise RuntimeError(f"GPU error in model {handle.name}: {error_msg}") from e
            elif "expected" in error_msg.lower() and "channels" in error_msg.lower():
                raise RuntimeError(f"Model {handle.name} input shape mismatch: {error_msg}") from e
            else:
                raise RuntimeError(f"Model {handle.name} inference failed: {error_msg}") from e
        except Exception as e:
            raise RuntimeError(f"Unexpected error in model {handle.name}: {e}") from e

        for idx, result in enumerate(results):
            tile_obj = tiles[idx]
            meta = tile_obj.metadata
            if handle.config.type == "yolo_obb":
                obbs = result.obb.xyxyxyxy.cpu().numpy() if hasattr(result, "obb") else []
                confs = result.obb.conf.cpu().numpy() if hasattr(result, "obb") else []
                clses = result.obb.cls.cpu().numpy() if hasattr(result, "obb") else []
                box_type = "oriented"
            else:
                boxes = result.boxes.xyxy.cpu().numpy() if result.boxes else []
                obbs = [_axis_aligned_to_points(box) for box in boxes]
                confs = result.boxes.conf.cpu().numpy() if result.boxes else []
                clses = result.boxes.cls.cpu().numpy() if result.boxes else []
                box_type = "axis_aligned"

            names_source = result.names if getattr(result, "names", None) else handle.model.names

            for obb, conf, cls in zip(obbs, confs, clses):
                if conf < handle.config.confidence_threshold:
                    continue
                
                # Convert to global coordinates
                global_points = _globalize_polygon(obb, meta, tiler.width, tiler.height)
                
                # Store detection for later NMS processing
                detection = TileDetection(
                    obb=global_points,
                    confidence=float(conf),
                    class_name=_resolve_class_name(names_source, cls),
                    tile_row=meta.row,
                    tile_col=meta.col,
                    box_type=box_type,
                    tile_metadata=meta,
                )
                
                # Initialize nested dicts if needed
                if meta.row not in detections_store:
                    detections_store[meta.row] = {}
                if meta.col not in detections_store[meta.row]:
                    detections_store[meta.row][meta.col] = []
                
                detections_store[meta.row][meta.col].append(detection)

            if handle.config.outputs.write_tile_previews:
                tile_key = f"{meta.row}-{meta.col}"
                if tile_key not in preview_tracker:
                    preview_tracker.add(tile_key)
                    self._write_tile_preview(tile_obj, preview_dir, handle.name, meta)
        
        # Clean up GPU memory: delete batch tensor and results after extracting all data
        # Results are already moved to CPU (.cpu().numpy()), so safe to delete GPU objects
        if batch_tensor.is_cuda:
            del batch_tensor
        del results
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _apply_cross_tile_nms_and_convert(
        self,
        model_name: str,
        detections_store: Dict[int, Dict[int, List[TileDetection]]],
        tiler: RasterTiler,
        transformer: Optional[Transformer],
        feature_store: List[Dict],
        counts: Dict[str, int],
        summary_store: List[Dict],
        image_logger,
    ) -> None:
        """
        Apply cross-tile NMS to remove duplicate detections from overlapping tiles,
        then convert remaining detections to GeoJSON features.
        
        Uses model-specific tiling config if available, otherwise falls back to global config.
        """
        """
        Apply cross-tile NMS to remove duplicate detections from overlapping tiles,
        then convert remaining detections to GeoJSON features.
        """
        if not detections_store:
            return

        if not SHAPELY_AVAILABLE:
            image_logger.warning(
                "shapely not available - skipping cross-tile NMS. "
                "Install shapely for duplicate detection removal: pip install shapely"
            )
            # Convert all detections to features without NMS
            for row in detections_store:
                for col in detections_store[row]:
                    detections = detections_store[row][col]
                    for detection in detections:
                        world_coords = _to_world_coords(detection.obb, tiler, transformer)
                        feature = {
                            "type": "Feature",
                            "geometry": {"type": "Polygon", "coordinates": [world_coords]},
                            "properties": {
                                "model": model_name,
                                "confidence": detection.confidence,
                                "class": detection.class_name,
                                "tile_row": detection.tile_row,
                                "tile_col": detection.tile_col,
                                "box_type": detection.box_type,
                            },
                        }
                        feature_store.append(feature)
                        counts[detection.box_type] += 1
                        summary_store.append(
                            {
                                "model": model_name,
                                "confidence": detection.confidence,
                                "class": detection.class_name,
                                "box_type": detection.box_type,
                                "tile_row": detection.tile_row,
                                "tile_col": detection.tile_col,
                            }
                        )
            return

        # Get tile grid dimensions
        max_row = max(detections_store.keys())
        max_col = max(max(cols.keys()) for cols in detections_store.values() if cols)

        # Use model-specific tiling config if available, otherwise use global
        model_config = self.config.models.get(model_name)
        tile_cfg = (model_config.tile if model_config and model_config.tile else self.config.tiling)
        stride = tile_cfg.tile_size - tile_cfg.overlap

        # Track which detections to keep (True = keep, False = discard)
        # Structure: good_detections[row][col][detection_idx] = True/False
        good_detections: Dict[int, Dict[int, List[bool]]] = {}
        
        # Initialize all detections as "good" (to keep)
        for row in detections_store:
            good_detections[row] = {}
            for col in detections_store[row]:
                if detections_store[row][col]:  # Only if there are detections
                    good_detections[row][col] = [True] * len(detections_store[row][col])

        # NMS thresholds from config
        iou_thresh = tile_cfg.iou_threshold
        ioma_thresh = tile_cfg.ioma_threshold
        
        image_logger.debug("    NMS Configuration:")
        image_logger.debug("      IoU Threshold: %.2f", iou_thresh)
        image_logger.debug("      IoMA Threshold: %.2f", ioma_thresh)
        image_logger.debug("      Tile Grid: %d rows x %d cols", max_row + 1, max_col + 1)

        # Apply NMS between adjacent tiles
        nms_comparisons = 0
        duplicates_removed = 0
        for row in range(max_row + 1):
            for col in range(max_col + 1):
                if row not in detections_store or col not in detections_store[row]:
                    continue

                detections = detections_store[row][col]
                if not detections:
                    continue

                # Get tile bounds for edge detection
                grid_lim = (
                    row * stride,
                    col * stride,
                    row * stride + tile_cfg.tile_size - 1,
                    col * stride + tile_cfg.tile_size - 1,
                )

                # Check with tile below (row+1, col)
                if row < max_row and row + 1 in detections_store and col in detections_store[row + 1]:
                    neighbor_detections = detections_store[row + 1][col]
                    # Ensure good_detections is initialized for neighbor
                    if row + 1 not in good_detections:
                        good_detections[row + 1] = {}
                    if col not in good_detections[row + 1]:
                        good_detections[row + 1][col] = [True] * len(neighbor_detections)
                    
                    neighbor_grid_lim = (
                        (row + 1) * stride,
                        col * stride,
                        (row + 1) * stride + tile_cfg.tile_size - 1,
                        col * stride + tile_cfg.tile_size - 1,
                    )
                    self._nms_between_tiles(
                        detections,
                        neighbor_detections,
                        good_detections[row][col],
                        good_detections[row + 1][col],
                        grid_lim,
                        neighbor_grid_lim,
                        iou_thresh,
                        ioma_thresh,
                    )

                # Check with tile to the right (row, col+1)
                if col < max_col and row in detections_store and col + 1 in detections_store[row]:
                    neighbor_detections = detections_store[row][col + 1]
                    # Ensure good_detections is initialized for neighbor
                    if col + 1 not in good_detections[row]:
                        good_detections[row][col + 1] = [True] * len(neighbor_detections)
                    
                    neighbor_grid_lim = (
                        row * stride,
                        (col + 1) * stride,
                        row * stride + tile_cfg.tile_size - 1,
                        (col + 1) * stride + tile_cfg.tile_size - 1,
                    )
                    self._nms_between_tiles(
                        detections,
                        neighbor_detections,
                        good_detections[row][col],
                        good_detections[row][col + 1],
                        grid_lim,
                        neighbor_grid_lim,
                        iou_thresh,
                        ioma_thresh,
                    )

                # Check with tile diagonal bottom-right (row+1, col+1)
                if (
                    row < max_row
                    and col < max_col
                    and row + 1 in detections_store
                    and col + 1 in detections_store[row + 1]
                ):
                    neighbor_detections = detections_store[row + 1][col + 1]
                    # Ensure good_detections is initialized for neighbor
                    if row + 1 not in good_detections:
                        good_detections[row + 1] = {}
                    if col + 1 not in good_detections[row + 1]:
                        good_detections[row + 1][col + 1] = [True] * len(neighbor_detections)
                    
                    neighbor_grid_lim = (
                        (row + 1) * stride,
                        (col + 1) * stride,
                        (row + 1) * stride + tile_cfg.tile_size - 1,
                        (col + 1) * stride + tile_cfg.tile_size - 1,
                    )
                    self._nms_between_tiles(
                        detections,
                        neighbor_detections,
                        good_detections[row][col],
                        good_detections[row + 1][col + 1],
                        grid_lim,
                        neighbor_grid_lim,
                        iou_thresh,
                        ioma_thresh,
                    )

                # Check with tile diagonal bottom-left (row+1, col-1)
                if (
                    row < max_row
                    and col > 0
                    and row + 1 in detections_store
                    and col - 1 in detections_store[row + 1]
                ):
                    neighbor_detections = detections_store[row + 1][col - 1]
                    # Ensure good_detections is initialized for neighbor
                    if row + 1 not in good_detections:
                        good_detections[row + 1] = {}
                    if col - 1 not in good_detections[row + 1]:
                        good_detections[row + 1][col - 1] = [True] * len(neighbor_detections)
                    
                    neighbor_grid_lim = (
                        (row + 1) * stride,
                        (col - 1) * stride,
                        (row + 1) * stride + tile_cfg.tile_size - 1,
                        (col - 1) * stride + tile_cfg.tile_size - 1,
                    )
                    self._nms_between_tiles(
                        detections,
                        neighbor_detections,
                        good_detections[row][col],
                        good_detections[row + 1][col - 1],
                        grid_lim,
                        neighbor_grid_lim,
                        iou_thresh,
                        ioma_thresh,
                    )

        # Count duplicates removed
        total_before_nms = sum(len(detections_store[row][col]) for row in detections_store for col in detections_store[row])
        total_after_nms = sum(sum(good_detections[row][col]) for row in good_detections for col in good_detections[row])
        duplicates_removed = total_before_nms - total_after_nms
        
        image_logger.debug("    NMS Results:")
        image_logger.debug("      Detections before NMS: %d", total_before_nms)
        image_logger.debug("      Detections after NMS: %d", total_after_nms)
        image_logger.debug("      Duplicates removed: %d", duplicates_removed)
        
        # Convert remaining detections to features
        image_logger.debug("    Converting detections to GeoJSON features...")
        features_converted = 0
        for row in detections_store:
            for col in detections_store[row]:
                detections = detections_store[row][col]
                for idx, detection in enumerate(detections):
                    if not good_detections[row][col][idx]:
                        continue  # Skip discarded detections

                    # Convert to world coordinates
                    world_coords = _to_world_coords(detection.obb, tiler, transformer)
                    features_converted += 1

                    feature = {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [world_coords]},
                        "properties": {
                            "model": model_name,
                            "confidence": detection.confidence,
                            "class": detection.class_name,
                            "tile_row": detection.tile_row,
                            "tile_col": detection.tile_col,
                            "box_type": detection.box_type,
                        },
                    }
                    feature_store.append(feature)
                    counts[detection.box_type] += 1
                    summary_store.append(
                        {
                            "model": model_name,
                            "confidence": detection.confidence,
                            "class": detection.class_name,
                            "box_type": detection.box_type,
                            "tile_row": detection.tile_row,
                            "tile_col": detection.tile_col,
                        }
                    )
        
        image_logger.debug("    ✓ Converted %d detections to GeoJSON features", features_converted)
        if transformer:
            image_logger.debug("    ✓ Coordinates transformed from source CRS to WGS84 (EPSG:4326)")
        else:
            image_logger.debug("    ✓ Coordinates in WGS84 (EPSG:4326) - no transformation needed")

    def _nms_between_tiles(
        self,
        detections1: List[TileDetection],
        detections2: List[TileDetection],
        good1: List[bool],
        good2: List[bool],
        grid_lim1: Tuple[int, int, int, int],
        grid_lim2: Tuple[int, int, int, int],
        iou_thresh: float,
        ioma_thresh: float,
    ) -> None:
        """Apply NMS between two adjacent tiles."""
        if not SHAPELY_AVAILABLE:
            return  # Skip NMS if shapely not available

        for i, det1 in enumerate(detections1):
            if not good1[i]:
                continue

            for j, det2 in enumerate(detections2):
                if not good2[j]:
                    continue

                # Calculate IoU and IoMA
                iou = _intersection_over_union(det1.obb, det2.obb)
                ioma = _intersection_over_min_area(det1.obb, det2.obb)

                if iou >= iou_thresh or ioma >= ioma_thresh:
                    # Detections overlap significantly, decide which to keep
                    good_grid = _get_object_grid(
                        det1.obb,
                        det2.obb,
                        grid_lim1,
                        grid_lim2,
                        det1.confidence,
                        det2.confidence,
                    )
                    if good_grid == 1:
                        good2[j] = False  # Discard det2
                    else:
                        good1[i] = False  # Discard det1
                        break  # No need to check more neighbors for det1

    def _filter_models_by_folder(self, folder_identity: Optional[str]) -> Dict[str, ModelConfig]:
        """
        Filter models based on folder identity.
        
        Returns models that:
        - Have all_folders=True, OR
        - Have folder_identities that match the given folder_identity (supports regex)
        
        If folder_identity is None, returns all models with all_folders=True or no folder filtering.
        """
        if folder_identity is None:
            # If no folder identity, only return models that process all folders
            return {
                name: cfg for name, cfg in self.config.models.items()
                if cfg.all_folders
            }
        
        applicable = {}
        for model_name, model_config in self.config.models.items():
            # If model processes all folders, include it
            if model_config.all_folders:
                applicable[model_name] = model_config
                continue
            
            # If model has no folder filtering, skip it (unless all_folders is True)
            if not model_config.folder_identities:
                continue
            
            # Check if folder_identity matches any configured pattern (supports regex)
            for pattern in model_config.folder_identities:
                try:
                    # Try regex match (case-insensitive)
                    if re.match(pattern, folder_identity, re.IGNORECASE):
                        applicable[model_name] = model_config
                        logger.debug("Model '%s' matched folder_identity '%s' with pattern '%s'", 
                                   model_name, folder_identity, pattern)
                        break
                except re.error:
                    # If not a valid regex, do case-insensitive exact match
                    if pattern.lower() == folder_identity.lower():
                        applicable[model_name] = model_config
                        logger.debug("Model '%s' matched folder_identity '%s' with exact pattern '%s'", 
                                   model_name, folder_identity, pattern)
                        break
                    else:
                        logger.debug("Model '%s' pattern '%s' did not match folder_identity '%s'", 
                                   model_name, pattern, folder_identity)
        
        return applicable
    
    def _prepare_artifact_dirs(self, job_id: str, image_stem: str, folder_identity: Optional[str] = None) -> Dict[str, Dict[str, Path] | Path]:
        """
        Prepare artifact directories for outputs.
        
        If folder_identity is provided, organizes outputs under success_dir/{folder_identity}/.
        Otherwise, uses the default structure.
        """
        # Organize by folder identity if provided
        if folder_identity:
            # Create folder structure: success_dir/{folder_identity}/{image_stem}_{job_id}/
            base_dir = self.config.artifacts.success_dir / folder_identity / f"{image_stem}_{job_id[:8]}"
        else:
            # Default structure: success_dir/{image_stem}_{job_id}/
            base_dir = self.config.artifacts.success_dir / f"{image_stem}_{job_id[:8]}"
        
        base_dir.mkdir(parents=True, exist_ok=True)
        
        # Get model names from config (works for both hybrid and traditional mode)
        model_names = list(self.config.models.keys())
        # Tile previews can still go in subdirectories if needed
        tile_dirs = {}
        for name in model_names:
            tile_dir = base_dir / "tiles" / name
            tile_dir.mkdir(parents=True, exist_ok=True)
            tile_dirs[name] = tile_dir
        # Logs go in the image folder
        log_file = base_dir / f"{image_stem}.log"
        return {
            "base": base_dir,
            "tiles": tile_dirs,
            "log": log_file,
        }

    def _write_geojsons(self, image_stem: str, features: Dict[str, List[Dict]], counts: Dict[str, Dict[str, int]], artifacts: Dict[str, Path], image_logger) -> Dict[str, Path]:
        """Write per-model GeoJSON files directly in the base directory with image name prefix."""
        outputs: Dict[str, Path] = {}
        base_dir = artifacts["base"]
        # Ensure we write files for all models in features dict (even if they have no detections)
        for name, feats in features.items():
            # Get counts for this model (default to 0 if not present)
            model_counts = counts.get(name, {"axis_aligned": 0, "oriented": 0})
            geojson = {
                "type": "FeatureCollection",
                "features": feats,
                "properties": {
                    "model": name,
                    "total_detections": len(feats),
                    "axis_aligned": model_counts.get("axis_aligned", 0),
                    "oriented": model_counts.get("oriented", 0),
                    "generated_at": time.time(),
                },
            }
            # Write with image name prefix
            path = base_dir / f"{image_stem}_{name}.geojson"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(geojson, handle, indent=2)
            outputs[name] = path
            image_logger.debug("    Wrote GeoJSON for %s: %s (%d features)", name, path.name, len(feats))
        return outputs

    def _write_combined_geojson(self, image_stem: str, features: Dict[str, List[Dict]], artifacts: Dict[str, Path], image_logger) -> Path:
        """Write combined GeoJSON file directly in the base directory with image name prefix."""
        combined_features = []
        for name, feats in features.items():
            for feature in feats:
                feature = dict(feature)
                properties = dict(feature["properties"])
                properties["source_model"] = name
                feature["properties"] = properties
                combined_features.append(feature)
        geojson = {
            "type": "FeatureCollection",
            "features": combined_features,
            "properties": {"generated_at": time.time(), "models": list(features.keys())},
        }
        # Write with image name prefix
        base_dir = artifacts["base"]
        path = base_dir / f"{image_stem}_combined.geojson"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(geojson, handle, indent=2)
        image_logger.debug("    Wrote combined GeoJSON: %s (%d features)", path.name, len(combined_features))
        return path

    def _write_summaries(self, image_stem: str, summaries: Dict[str, List[Dict]], artifacts: Dict[str, Path], image_logger) -> Dict[str, Path]:
        """Write CSV summary files directly in the base directory with image name prefix."""
        output_paths: Dict[str, Path] = {}
        base_dir = artifacts["base"]
        for name, summary in summaries.items():
            # Write with image name prefix
            path = base_dir / f"{image_stem}_{name}.csv"
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["model", "confidence", "class", "box_type", "tile_row", "tile_col"])
                writer.writeheader()
                for row in summary:
                    writer.writerow(row)
            output_paths[name] = path
            image_logger.debug("    Wrote CSV summary for %s: %s (%d rows)", name, path.name, len(summary))
        return output_paths

    def _write_tile_preview(self, tile: Tile, preview_dir: Path, model_name: str, meta) -> None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        array = tile.array
        if array.shape[2] == 1:
            array = np.repeat(array, 3, axis=2)
        elif array.shape[2] > 3:
            array = array[:, :, :3]
        image = Image.fromarray((array * 255).clip(0, 255).astype(np.uint8))
        path = preview_dir / f"tile_{meta.row:04d}_{meta.col:04d}.png"
        image.save(path)
    
    def _copy_to_centralized_dirs(
        self,
        image_stem: str,
        combined_path: Path,
        per_model_paths: Dict[str, Path],
        summary_paths: Dict[str, Path],
        artifacts: Dict[str, Path],
        image_logger,
    ) -> None:
        """
        Copy outputs to centralized directories:
        - Combined GeoJSON to combined_inferences_dir
        - Per-model GeoJSONs and CSVs to model_outputs_dir
        
        Note: Logs are automatically written to daily_logs_dir by the logger.
        """
        try:
            # 1. Copy combined GeoJSON to combined_inferences_dir
            combined_inferences_dir = self.config.artifacts.combined_inferences_dir
            combined_inferences_dir.mkdir(parents=True, exist_ok=True)
            combined_dest = combined_inferences_dir / f"{image_stem}_combined.geojson"
            shutil.copy2(combined_path, combined_dest)
            image_logger.debug("    Copied combined GeoJSON: %s", combined_dest)
            
            # 2. Copy per-model outputs to model_outputs_dir
            model_outputs_dir = self.config.artifacts.model_outputs_dir
            model_outputs_dir.mkdir(parents=True, exist_ok=True)
            
            for model_name, geojson_path in per_model_paths.items():
                # Copy GeoJSON
                geojson_dest = model_outputs_dir / f"{image_stem}_{model_name}.geojson"
                shutil.copy2(geojson_path, geojson_dest)
                image_logger.debug("    Copied model GeoJSON (%s): %s", model_name, geojson_dest)
                
                # Copy CSV if it exists
                if model_name in summary_paths:
                    csv_path = summary_paths[model_name]
                    csv_dest = model_outputs_dir / f"{image_stem}_{model_name}.csv"
                    shutil.copy2(csv_path, csv_dest)
                    image_logger.debug("    Copied model CSV (%s): %s", model_name, csv_dest)
            
            # 3. Logs are already written to daily_logs_dir by the logger (no need to copy)
            
        except Exception as e:
            # Don't fail the job if copying to centralized dirs fails
            image_logger.warning("Failed to copy files to centralized directories: %s", e)
            logger.warning("Failed to copy files to centralized directories: %s", e)


def _resolve_class_name(names_obj, cls_idx):
    cls_int = int(cls_idx)
    if isinstance(names_obj, dict):
        return names_obj.get(cls_int, str(cls_int))
    if isinstance(names_obj, (list, tuple)) and 0 <= cls_int < len(names_obj):
        return names_obj[cls_int]
    return str(cls_int)

