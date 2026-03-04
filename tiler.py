"""
Reusable tiling utilities for satellite imagery.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Generator, Iterable, List, Optional, Tuple

import numpy as np
from osgeo import gdal

from .config_loader import TilingConfig

logger = logging.getLogger("tiler")


gdal.UseExceptions()


@dataclass
class TileMetadata:
    row: int
    col: int
    width: int
    height: int
    offset_x: int
    offset_y: int
    global_bounds: Tuple[int, int, int, int]  # (ymin, xmin, ymax, xmax)


@dataclass
class Tile:
    metadata: TileMetadata
    array: np.ndarray  # shape: (H, W, C)


class RasterTiler:
    def __init__(self, image_path: Path, config: TilingConfig, pixel_bounds: Optional[Tuple[int, int, int, int]] = None):
        """
        Initialize RasterTiler.
        
        Args:
            image_path: Path to image file
            config: Tiling configuration
            pixel_bounds: Optional (xmin, ymin, xmax, ymax) in original image coordinates.
                        If provided, only tiles within these bounds will be generated.
                        Tile offsets will still reference original image coordinates.
        """
        self.image_path = Path(image_path)
        self.config = config
        self.dataset = self._open_dataset()
        
        # Store original dimensions
        self.original_width = self.dataset.RasterXSize
        self.original_height = self.dataset.RasterYSize
        
        # Handle pixel bounds (ROI cropping)
        self.pixel_bounds = pixel_bounds
        if pixel_bounds:
            xmin, ymin, xmax, ymax = pixel_bounds
            # Validate bounds
            if xmin < 0 or ymin < 0 or xmax >= self.original_width or ymax >= self.original_height:
                raise ValueError(f"Pixel bounds {pixel_bounds} are outside image dimensions ({self.original_width}x{self.original_height})")
            if xmin >= xmax or ymin >= ymax:
                raise ValueError(f"Invalid pixel bounds: {pixel_bounds}")
            
            # Set effective dimensions to cropped region
            self.width = xmax - xmin + 1
            self.height = ymax - ymin + 1
            self.crop_offset_x = xmin
            self.crop_offset_y = ymin
            logger.info("ROI cropping enabled: processing region (%d, %d) to (%d, %d) = %dx%d pixels (original: %dx%d)",
                      xmin, ymin, xmax, ymax, self.width, self.height, self.original_width, self.original_height)
        else:
            # No cropping - use full image
            self.width = self.original_width
            self.height = self.original_height
            self.crop_offset_x = 0
            self.crop_offset_y = 0
        
        self.band_count = min(self.dataset.RasterCount, 4)
        self._validate()
        # Compute global min/max for normalization (without loading full image)
        self.min_pixel, self.max_pixel = self._compute_global_minmax()

    def _open_dataset(self):
        """Open GDAL dataset with retry logic for Windows file locking issues."""
        logger.debug("Opening dataset %s", self.image_path)
        max_retries = 5
        retry_delay = 0.5  # Start with 0.5 seconds
        
        for attempt in range(max_retries):
            try:
                # On Windows, use GA_ReadOnly to avoid exclusive locks
                ds = gdal.Open(str(self.image_path), gdal.GA_ReadOnly)
                if ds is not None:
                    return ds
                
                # If ds is None, it might be a temporary lock issue
                if attempt < max_retries - 1:
                    logger.debug(
                        "Failed to open dataset (attempt %d/%d), retrying in %.1fs...",
                        attempt + 1,
                        max_retries,
                        retry_delay,
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
            except RuntimeError as e:
                error_msg = str(e).lower()
                # Check if it's a file locking error
                if "file used by other process" in error_msg or "permission denied" in error_msg:
                    if attempt < max_retries - 1:
                        logger.debug(
                            "File locked (attempt %d/%d), retrying in %.1fs...",
                            attempt + 1,
                            max_retries,
                            retry_delay,
                        )
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                # Re-raise if it's a different error or last attempt
                raise
        
        raise RuntimeError(f"Failed to open dataset {self.image_path} after {max_retries} attempts (file may be locked)")

    def _validate(self) -> None:
        if self.dataset.RasterCount == 0:
            raise RuntimeError(f"Raster {self.image_path} has zero bands")

    def _compute_global_minmax(self) -> Tuple[float, float]:
        """
        Compute global min/max pixel values across all bands using GDAL without loading full image.
        
        Uses GDAL's ComputeStatistics or ComputeRasterMinMax for efficiency.
        Returns (min_pixel, max_pixel) aggregated across all bands.
        """
        min_values = []
        max_values = []
        
        for idx in range(1, self.band_count + 1):
            band = self.dataset.GetRasterBand(idx)
            
            # Try ComputeStatistics first (more accurate, may be slower)
            # If that fails, fall back to ComputeRasterMinMax (faster, less accurate)
            try:
                stats = band.ComputeStatistics(False)  # False = don't force recomputation
                if stats and len(stats) >= 4:
                    # stats = [min, max, mean, stddev]
                    min_values.append(float(stats[0]))
                    max_values.append(float(stats[1]))
                else:
                    # Fallback to ComputeRasterMinMax
                    min_max = band.ComputeRasterMinMax(False)
                    if min_max and len(min_max) == 2:
                        min_values.append(float(min_max[0]))
                        max_values.append(float(min_max[1]))
                    else:
                        # Last resort: read a sample to estimate
                        logger.warning("Could not compute statistics for band %d, using sample", idx)
                        sample = band.ReadAsArray(0, 0, min(1000, self.width), min(1000, self.height))
                        min_values.append(float(np.min(sample)))
                        max_values.append(float(np.max(sample)))
            except Exception as e:
                # If ComputeStatistics fails, try ComputeRasterMinMax
                try:
                    min_max = band.ComputeRasterMinMax(False)
                    if min_max and len(min_max) == 2:
                        min_values.append(float(min_max[0]))
                        max_values.append(float(min_max[1]))
                    else:
                        raise ValueError("Could not compute min/max")
                except Exception:
                    # Last resort: read a sample
                    logger.warning("Statistics computation failed for band %d: %s. Using sample.", idx, e)
                    sample = band.ReadAsArray(0, 0, min(1000, self.width), min(1000, self.height))
                    min_values.append(float(np.min(sample)))
                    max_values.append(float(np.max(sample)))
        
        if not min_values or not max_values:
            raise RuntimeError("Failed to compute min/max values for any band")
        
        global_min = float(min(min_values))
        global_max = float(max(max_values))
        
        logger.debug("Computed global min/max: %.2f / %.2f (across %d bands)", 
                    global_min, global_max, self.band_count)
        
        return global_min, global_max

    def _normalize_tile(self, tile_array: np.ndarray) -> np.ndarray:
        """
        Normalize a single tile array using global min/max values.
        
        Args:
            tile_array: Raw tile array (H, W, C) from ReadAsArray
            
        Returns:
            Normalized array as float32, same shape
        """
        if self.max_pixel == self.min_pixel:
            return np.zeros_like(tile_array, dtype=np.float32)
        
        normalized = (tile_array.astype(np.float32) - self.min_pixel) / (self.max_pixel - self.min_pixel)
        return normalized.astype(np.float32)

    def iter_tiles(self, tile_size: Optional[int] = None, overlap: Optional[int] = None) -> Generator[Tile, None, None]:
        """
        Generate tiles using windowed reading (reads only needed portions from disk).
        
        This method reads tiles on-demand instead of loading the entire image into memory,
        dramatically reducing RAM usage while preserving exact tile positions and normalization.
        """
        cfg_tile_size = tile_size or self.config.tile_size
        cfg_overlap = overlap if overlap is not None else self.config.overlap

        stride = cfg_tile_size - cfg_overlap
        if stride <= 0:
            raise ValueError("Overlap must be smaller than tile size")

        # Calculate padding needed (same as before, but we'll handle it per-tile)
        pad_x = ceil((self.width - cfg_overlap) / stride) * stride + cfg_overlap - self.width
        pad_y = ceil((self.height - cfg_overlap) / stride) * stride + cfg_overlap - self.height

        # Calculate tile grid dimensions (same as before)
        h_iter = ceil((self.height - cfg_overlap) / stride)
        w_iter = ceil((self.width - cfg_overlap) / stride)

        for row in range(h_iter):
            for col in range(w_iter):
                # Calculate tile position in cropped coordinate space
                start_y_cropped = row * stride
                start_x_cropped = col * stride
                
                # Convert to original image coordinates (for reading from dataset)
                start_y = start_y_cropped + self.crop_offset_y
                start_x = start_x_cropped + self.crop_offset_x
                
                # Calculate actual read window (may extend beyond cropped bounds on right/bottom)
                read_x = start_x
                read_y = start_y
                read_width = cfg_tile_size
                read_height = cfg_tile_size
                
                # Clamp read window to cropped region bounds
                max_read_x = self.crop_offset_x + self.width
                max_read_y = self.crop_offset_y + self.height
                
                if read_x + read_width > max_read_x:
                    read_width = max_read_x - read_x
                if read_y + read_height > max_read_y:
                    read_height = max_read_y - read_y
                
                # Skip if tile is completely outside cropped region
                if read_x < self.crop_offset_x or read_y < self.crop_offset_y:
                    continue
                if read_width <= 0 or read_height <= 0:
                    continue
                
                # Calculate padding needed if tile extends beyond image bounds
                pad_top = 0
                pad_bottom = 0
                pad_left = 0
                pad_right = 0
                
                # Check if tile extends beyond bottom edge
                if read_y + read_height > self.height:
                    pad_bottom = (read_y + read_height) - self.height
                    read_height = self.height - read_y
                
                # Check if tile extends beyond right edge
                if read_x + read_width > self.width:
                    pad_right = (read_x + read_width) - self.width
                    read_width = self.width - read_x
                
                # Read tile window directly from file (windowed reading)
                bands = []
                for idx in range(1, self.band_count + 1):
                    band = self.dataset.GetRasterBand(idx)
                    # Read only the needed window
                    # GDAL ReadAsArray signature: ReadAsArray(xoff, yoff, xsize, ysize)
                    if read_width > 0 and read_height > 0:
                        band_data = band.ReadAsArray(
                            read_x,
                            read_y,
                            read_width,
                            read_height
                        )
                    else:
                        # Empty tile (shouldn't happen with valid tile positions, but handle gracefully)
                        # Use same dtype as band would return (typically uint8, uint16, or float32)
                        band_data = np.zeros((max(0, read_height), max(0, read_width)), dtype=np.float32)
                    
                    # Pad if necessary (edge tiles extending beyond image)
                    if pad_top > 0 or pad_bottom > 0 or pad_left > 0 or pad_right > 0:
                        band_data = np.pad(
                            band_data,
                            ((pad_top, pad_bottom), (pad_left, pad_right)),
                            mode="constant",
                            constant_values=0
                        )
                    
                    bands.append(band_data)
                
                # Stack bands into (H, W, C) array
                tile_array = np.stack(bands, axis=-1)
                
                # Normalize using global min/max
                tile_array = self._normalize_tile(tile_array)
                
                # Calculate global bounds in original image coordinates
                # These offsets reference the original image, not the cropped region
                global_bounds = (
                    start_y,  # ymin in original image
                    start_x,  # xmin in original image
                    min(start_y + cfg_tile_size, self.crop_offset_y + self.height),  # ymax in original image
                    min(start_x + cfg_tile_size, self.crop_offset_x + self.width),   # xmax in original image
                )
                
                metadata = TileMetadata(
                    row=row,
                    col=col,
                    width=cfg_tile_size,
                    height=cfg_tile_size,
                    offset_x=start_x,  # In original image coordinates
                    offset_y=start_y,  # In original image coordinates
                    global_bounds=global_bounds,  # In original image coordinates
                )
                
                yield Tile(metadata=metadata, array=tile_array)

    def pixel_to_geo(self, x_pixel: float, y_pixel: float) -> Tuple[float, float]:
        gt = self.dataset.GetGeoTransform()
        if not gt:
            raise RuntimeError("Dataset lacks geotransform metadata.")
        x_geo, y_geo = gdal.ApplyGeoTransform(gt, x_pixel, y_pixel)
        return x_geo, y_geo

    def close(self) -> None:
        """
        Explicitly free memory and close GDAL dataset.
        
        This method should be called after processing is complete to close
        the GDAL dataset handle. With windowed reading, there's no large
        image array to free (tiles are read on-demand).
        """
        # Close GDAL dataset explicitly
        if hasattr(self, 'dataset') and self.dataset is not None:
            try:
                # GDAL datasets need explicit closing to free file handles and memory
                # Setting to None is not enough - GDAL uses reference counting
                dataset = self.dataset
                self.dataset = None
                # Explicitly delete the dataset reference
                del dataset
            except Exception as e:
                logger.warning("Error closing GDAL dataset: %s", e)
        
        # Clear other references
        if hasattr(self, 'min_pixel'):
            delattr(self, 'min_pixel')
        if hasattr(self, 'max_pixel'):
            delattr(self, 'max_pixel')
        
        # Force garbage collection to immediately free any remaining references
        import gc
        gc.collect()
        
        logger.debug("RasterTiler memory freed for %s", self.image_path)

