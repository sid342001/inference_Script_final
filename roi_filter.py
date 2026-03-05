"""
Region of Interest (ROI) filtering and cropping for satellite imagery.

This module handles:
- Loading ROI polygons from GeoJSON files
- Checking spatial intersection between images and ROIs
- Converting geographic intersections to pixel bounds for cropping
- Handling CRS transformations between ROI and image coordinate systems
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

import pyproj
from osgeo import gdal
from pyproj import CRS
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .logging_setup import get_logger

logger = get_logger("roi_filter")

gdal.UseExceptions()


class ROIFilter:
    """
    Handles ROI loading, spatial intersection checks, and coordinate transformations.
    
    Supports:
    - Loading multiple ROI polygons from GeoJSON
    - Unioning intersecting ROIs into single processing region
    - CRS transformation between ROI and image coordinate systems
    - Converting geographic intersections to pixel bounds
    """

    def __init__(self):
        """Initialize ROI filter."""
        pass

    def load_roi_geojson(self, geojson_path: Path) -> List[Polygon]:
        """
        Load ROI polygons from a GeoJSON file.
        
        Args:
            geojson_path: Path to GeoJSON file containing ROI polygons
            
        Returns:
            List of Shapely Polygon objects representing ROIs
            
        Raises:
            FileNotFoundError: If GeoJSON file doesn't exist
            ValueError: If GeoJSON is invalid or contains no polygons
        """
        geojson_path = Path(geojson_path)
        
        if not geojson_path.exists():
            raise FileNotFoundError(f"ROI GeoJSON file not found: {geojson_path}")
        
        logger.info("Loading ROI from GeoJSON: %s", geojson_path)
        
        try:
            with open(geojson_path, "r", encoding="utf-8") as f:
                geojson_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in ROI file {geojson_path}: {e}") from e
        except Exception as e:
            raise ValueError(f"Failed to read ROI file {geojson_path}: {e}") from e
        
        polygons = []
        
        # Handle different GeoJSON structures
        if geojson_data.get("type") == "FeatureCollection":
            features = geojson_data.get("features", [])
            for feature in features:
                geometry = feature.get("geometry")
                if geometry and geometry.get("type") == "Polygon":
                    coords = geometry.get("coordinates", [])
                    if coords:
                        try:
                            # GeoJSON coordinates are [lon, lat] or [x, y]
                            # Shapely expects (x, y) tuples
                            polygon_coords = coords[0]  # First ring (exterior)
                            shapely_polygon = Polygon(polygon_coords)
                            if not shapely_polygon.is_valid:
                                logger.warning("Invalid polygon in ROI, attempting to fix: %s", shapely_polygon)
                                shapely_polygon = shapely_polygon.buffer(0)  # Fix self-intersections
                            polygons.append(shapely_polygon)
                        except Exception as e:
                            logger.warning("Failed to create polygon from coordinates: %s", e)
                            continue
                            
        elif geojson_data.get("type") == "Feature":
            geometry = geojson_data.get("geometry")
            if geometry and geometry.get("type") == "Polygon":
                coords = geometry.get("coordinates", [])
                if coords:
                    try:
                        polygon_coords = coords[0]
                        shapely_polygon = Polygon(polygon_coords)
                        if not shapely_polygon.is_valid:
                            shapely_polygon = shapely_polygon.buffer(0)
                        polygons.append(shapely_polygon)
                    except Exception as e:
                        logger.warning("Failed to create polygon from coordinates: %s", e)
                        
        elif geojson_data.get("type") == "Polygon":
            coords = geojson_data.get("coordinates", [])
            if coords:
                try:
                    polygon_coords = coords[0]
                    shapely_polygon = Polygon(polygon_coords)
                    if not shapely_polygon.is_valid:
                        shapely_polygon = shapely_polygon.buffer(0)
                    polygons.append(shapely_polygon)
                except Exception as e:
                    logger.warning("Failed to create polygon from coordinates: %s", e)
        
        if not polygons:
            raise ValueError(f"No valid polygons found in ROI file {geojson_path}")
        
        logger.info("Loaded %d ROI polygon(s) from %s", len(polygons), geojson_path)
        return polygons

    def get_image_geographic_bounds(self, dataset: gdal.Dataset) -> Optional[Polygon]:
        """
        Extract geographic bounds of an image as a polygon.
        
        Args:
            dataset: GDAL dataset (opened image)
            
        Returns:
            Shapely Polygon representing image bounds in geographic coordinates,
            or None if image has no geotransform/projection
        """
        try:
            geotransform = dataset.GetGeoTransform()
            if not geotransform:
                logger.warning("Image has no geotransform, cannot extract geographic bounds")
                return None
        except Exception as e:
            logger.warning("Failed to get geotransform: %s", e)
            return None
        
        width = dataset.RasterXSize
        height = dataset.RasterYSize
        
        # Calculate 4 corner points in pixel coordinates
        corners_pixel = [
            (0, 0),           # Top-left
            (width, 0),        # Top-right
            (width, height),   # Bottom-right
            (0, height),       # Bottom-left
        ]
        
        # Convert to geographic coordinates
        corners_geo = []
        for x_pixel, y_pixel in corners_pixel:
            try:
                x_geo, y_geo = gdal.ApplyGeoTransform(geotransform, x_pixel, y_pixel)
                corners_geo.append((x_geo, y_geo))
            except Exception as e:
                logger.warning("Failed to convert pixel (%d, %d) to geographic: %s", x_pixel, y_pixel, e)
                return None
        
        # Create polygon from 4 corners (close the loop)
        if len(corners_geo) == 4:
            corners_geo.append(corners_geo[0])  # Close polygon
            try:
                image_bounds = Polygon(corners_geo)
                if not image_bounds.is_valid:
                    image_bounds = image_bounds.buffer(0)
                return image_bounds
            except Exception as e:
                logger.warning("Failed to create image bounds polygon: %s", e)
                return None
        
        return None

    def reproject_polygon(
        self, polygon: Polygon, source_crs: CRS, target_crs: CRS
    ) -> Polygon:
        """
        Reproject a polygon from source CRS to target CRS.
        
        Args:
            polygon: Shapely Polygon in source CRS
            source_crs: Source coordinate reference system
            target_crs: Target coordinate reference system
            
        Returns:
            Reprojected Shapely Polygon
        """
        try:
            transformer = pyproj.Transformer.from_crs(
                source_crs, target_crs, always_xy=True
            )
            
            # Transform all coordinates
            coords = list(polygon.exterior.coords)
            transformed_coords = [
                transformer.transform(x, y) for x, y in coords
            ]
            
            reprojected = Polygon(transformed_coords)
            if not reprojected.is_valid:
                reprojected = reprojected.buffer(0)
            
            return reprojected
        except Exception as e:
            logger.warning("Failed to reproject polygon: %s", e)
            raise

    def compute_intersection(
        self, image_bounds: Polygon, roi_polygons: List[Polygon]
    ) -> Optional[Polygon]:
        """
        Compute intersection between image bounds and ROI polygons.
        
        If multiple ROI polygons intersect the image, they are unioned into
        a single polygon representing the combined region of interest.
        
        Args:
            image_bounds: Polygon representing image geographic bounds
            roi_polygons: List of ROI polygons to check against
            
        Returns:
            Unioned intersection polygon (if any intersection exists),
            or None if no intersection
        """
        if not image_bounds or not image_bounds.is_valid:
            logger.warning("Invalid image bounds polygon")
            return None
        
        intersecting_polygons = []
        
        for i, roi_poly in enumerate(roi_polygons):
            if not roi_poly.is_valid:
                logger.warning("Invalid ROI polygon at index %d, skipping", i)
                continue
            
            try:
                # Check if ROI intersects image bounds
                if roi_poly.intersects(image_bounds):
                    # Calculate intersection
                    intersection = roi_poly.intersection(image_bounds)
                    
                    # Handle different geometry types
                    if isinstance(intersection, Polygon):
                        if intersection.area > 0:
                            intersecting_polygons.append(intersection)
                            logger.debug("ROI polygon %d intersects image (area: %.6f)", i, intersection.area)
                    elif hasattr(intersection, 'geoms'):  # MultiPolygon or GeometryCollection
                        for geom in intersection.geoms:
                            if isinstance(geom, Polygon) and geom.area > 0:
                                intersecting_polygons.append(geom)
            except Exception as e:
                logger.warning("Error computing intersection with ROI polygon %d: %s", i, e)
                continue
        
        if not intersecting_polygons:
            logger.info("No ROI polygons intersect image bounds")
            return None
        
        # Union all intersecting polygons into single region
        if len(intersecting_polygons) == 1:
            unioned = intersecting_polygons[0]
            logger.debug("Single ROI polygon intersects image")
        else:
            logger.info("Unioning %d intersecting ROI regions into single processing area", len(intersecting_polygons))
            try:
                unioned = unary_union(intersecting_polygons)
                # Ensure result is a Polygon (could be MultiPolygon)
                if hasattr(unioned, 'geoms'):
                    # If MultiPolygon, get bounding box (rectangular crop)
                    bounds = unioned.bounds
                    unioned = Polygon([
                        (bounds[0], bounds[1]),  # minx, miny
                        (bounds[2], bounds[1]),  # maxx, miny
                        (bounds[2], bounds[3]),  # maxx, maxy
                        (bounds[0], bounds[3]),  # minx, maxy
                        (bounds[0], bounds[1]),  # close
                    ])
                    logger.info("Multiple non-overlapping ROIs detected, using bounding box for cropping")
                elif not isinstance(unioned, Polygon):
                    logger.warning("Union result is not a Polygon, using bounding box")
                    bounds = unioned.bounds
                    unioned = Polygon([
                        (bounds[0], bounds[1]),
                        (bounds[2], bounds[1]),
                        (bounds[2], bounds[3]),
                        (bounds[0], bounds[3]),
                        (bounds[0], bounds[1]),
                    ])
            except Exception as e:
                logger.error("Failed to union intersecting ROI polygons: %s", e)
                # Fallback: use bounding box of all intersections
                all_bounds = [p.bounds for p in intersecting_polygons]
                minx = min(b[0] for b in all_bounds)
                miny = min(b[1] for b in all_bounds)
                maxx = max(b[2] for b in all_bounds)
                maxy = max(b[3] for b in all_bounds)
                unioned = Polygon([
                    (minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)
                ])
        
        if not unioned.is_valid:
            unioned = unioned.buffer(0)
        
        logger.info("Computed intersection: polygon with %d points, area: %.6f", 
                   len(unioned.exterior.coords), unioned.area)
        return unioned

    def geographic_to_pixel_bounds(
        self, intersection_poly: Polygon, dataset: gdal.Dataset
    ) -> Tuple[int, int, int, int]:
        """
        Convert geographic intersection polygon to pixel bounds.
        
        Args:
            intersection_poly: Polygon in geographic coordinates
            dataset: GDAL dataset (for geotransform)
            
        Returns:
            Tuple of (xmin, ymin, xmax, ymax) in pixel coordinates
        """
        try:
            geotransform = dataset.GetGeoTransform()
            if not geotransform:
                raise ValueError("Dataset has no geotransform")
        except Exception as e:
            raise ValueError(f"Cannot get geotransform: {e}") from e
        
        width = dataset.RasterXSize
        height = dataset.RasterYSize
        
        # Sample points from intersection polygon boundary
        # Use exterior coordinates plus some interior points for accuracy
        sample_points = []
        
        # Add exterior ring points
        sample_points.extend(intersection_poly.exterior.coords[:-1])  # Exclude duplicate closing point
        
        # Add some interior points for better coverage (if polygon is large)
        if intersection_poly.area > 0:
            # Sample a grid of points within the polygon
            bounds = intersection_poly.bounds
            minx, miny, maxx, maxy = bounds
            # Sample 10x10 grid
            for i in range(10):
                for j in range(10):
                    x = minx + (maxx - minx) * i / 9
                    y = miny + (maxy - miny) * j / 9
                    point = (x, y)
                    if intersection_poly.contains(Polygon([point, point, point, point])) or \
                       intersection_poly.touches(Polygon([point, point, point, point])):
                        sample_points.append(point)
        
        # Convert all sample points to pixel coordinates
        pixel_coords = []
        for x_geo, y_geo in sample_points:
            try:
                # Inverse geotransform: geographic -> pixel
                # x_pixel = (x_geo - geotransform[0]) / geotransform[1]
                # y_pixel = (y_geo - geotransform[3]) / geotransform[5]
                x_pixel = (x_geo - geotransform[0]) / geotransform[1]
                y_pixel = (y_geo - geotransform[3]) / geotransform[5]
                pixel_coords.append((x_pixel, y_pixel))
            except Exception as e:
                logger.debug("Failed to convert point (%f, %f) to pixel: %s", x_geo, y_geo, e)
                continue
        
        if not pixel_coords:
            raise ValueError("No valid pixel coordinates computed from intersection polygon")
        
        # Find min/max pixel coordinates
        x_coords = [p[0] for p in pixel_coords]
        y_coords = [p[1] for p in pixel_coords]
        
        xmin = int(min(x_coords))
        ymin = int(min(y_coords))
        xmax = int(max(x_coords))
        ymax = int(max(y_coords))
        
        # Clamp to image dimensions
        xmin = max(0, min(xmin, width - 1))
        ymin = max(0, min(ymin, height - 1))
        xmax = max(0, min(xmax, width - 1))
        ymax = max(0, min(ymax, height - 1))
        
        # Ensure valid bounds (xmin < xmax, ymin < ymax)
        if xmin >= xmax:
            xmax = min(xmin + 1, width - 1)
        if ymin >= ymax:
            ymax = min(ymin + 1, height - 1)
        
        logger.info("Pixel bounds: (%d, %d, %d, %d) [xmin, ymin, xmax, ymax]", xmin, ymin, xmax, ymax)
        logger.info("Cropped region size: %d x %d pixels (original: %d x %d)", 
                   xmax - xmin + 1, ymax - ymin + 1, width, height)
        
        return (xmin, ymin, xmax, ymax)

    def get_image_crs(self, dataset: gdal.Dataset) -> Optional[CRS]:
        """
        Extract CRS from GDAL dataset.
        
        Args:
            dataset: GDAL dataset
            
        Returns:
            pyproj CRS object, or None if CRS cannot be determined
        """
        try:
            # Try GetSpatialRef() first (newer API)
            srs = dataset.GetSpatialRef()
            if srs:
                wkt = srs.ExportToWkt()
                if wkt:
                    return CRS.from_wkt(wkt)
        except Exception:
            pass
        
        try:
            # Fallback to GetProjection()
            wkt = dataset.GetProjection()
            if wkt and wkt.strip():
                return CRS.from_wkt(wkt)
        except Exception:
            pass
        
        return None

    def ensure_same_crs(
        self, roi_polygons: List[Polygon], roi_crs: Optional[CRS], image_crs: Optional[CRS]
    ) -> Tuple[List[Polygon], Optional[CRS]]:
        """
        Ensure ROI polygons are in the same CRS as the image.
        
        If CRS differ, reproject ROI polygons to image CRS.
        If image has no CRS, assume ROI is in correct CRS (WGS84 typically).
        
        Args:
            roi_polygons: List of ROI polygons
            roi_crs: CRS of ROI polygons (None if unknown)
            image_crs: CRS of image (None if unknown)
            
        Returns:
            Tuple of (reprojected_polygons, effective_crs)
        """
        # If both CRS are None, assume they're compatible (likely both WGS84)
        if not roi_crs and not image_crs:
            logger.info("Both ROI and image CRS unknown, assuming compatible (likely WGS84)")
            return roi_polygons, None
        
        # If image has no CRS, cannot reproject - use ROI as-is
        if not image_crs:
            logger.warning("Image has no CRS, using ROI polygons as-is (may cause issues)")
            return roi_polygons, roi_crs
        
        # If ROI has no CRS, assume it's in image CRS
        if not roi_crs:
            logger.info("ROI CRS unknown, assuming same as image CRS")
            return roi_polygons, image_crs
        
        # If CRS are the same, no reprojection needed
        if roi_crs == image_crs or roi_crs.to_string() == image_crs.to_string():
            logger.debug("ROI and image CRS match, no reprojection needed")
            return roi_polygons, image_crs
        
        # CRS differ - reproject ROI to image CRS
        logger.info("Reprojecting ROI from %s to %s", roi_crs, image_crs)
        try:
            reprojected_polygons = [
                self.reproject_polygon(poly, roi_crs, image_crs)
                for poly in roi_polygons
            ]
            logger.info("Successfully reprojected %d ROI polygon(s)", len(reprojected_polygons))
            return reprojected_polygons, image_crs
        except Exception as e:
            logger.error("Failed to reproject ROI polygons: %s", e)
            logger.warning("Using ROI polygons in original CRS (may cause intersection errors)")
            return roi_polygons, roi_crs

