"""
Unit tests for ROI filtering and cropping (roi_filter module).

Run from repository root (parent of inference_Script):
  python -m pytest inference_Script/test_roi_filter.py -v

Or from inference_Script directory (with parent in PYTHONPATH):
  PYTHONPATH=.. python -m pytest test_roi_filter.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure package is importable
_here = Path(__file__).resolve().parent
_root = _here.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from inference_Script.roi_filter import ROIFilter
except ImportError:
    from roi_filter import ROIFilter

from shapely.geometry import Polygon

# GDAL for in-memory dataset in geographic_to_pixel_bounds tests
try:
    from osgeo import gdal
    GDAL_AVAILABLE = True
except ImportError:
    GDAL_AVAILABLE = False


# -----------------------------------------------------------------------------
# GeoJSON loading tests
# -----------------------------------------------------------------------------

def test_load_roi_geojson_single_polygon(tmp_path):
    """Load valid GeoJSON with a single polygon."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]
                    ]]
                }
            }
        ]
    }
    path = tmp_path / "roi.geojson"
    path.write_text(json.dumps(geojson), encoding="utf-8")
    
    roi = ROIFilter()
    polygons = roi.load_roi_geojson(path)
    
    assert len(polygons) == 1
    assert isinstance(polygons[0], Polygon)
    assert polygons[0].is_valid
    assert polygons[0].area == 1.0


def test_load_roi_geojson_multiple_polygons(tmp_path):
    """Load GeoJSON with multiple polygons."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
                }
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
                }
            }
        ]
    }
    path = tmp_path / "roi.geojson"
    path.write_text(json.dumps(geojson), encoding="utf-8")
    
    roi = ROIFilter()
    polygons = roi.load_roi_geojson(path)
    
    assert len(polygons) == 2
    assert all(isinstance(p, Polygon) and p.is_valid for p in polygons)


def test_load_roi_geojson_file_not_found():
    """Missing GeoJSON file raises FileNotFoundError."""
    roi = ROIFilter()
    with pytest.raises(FileNotFoundError, match="not found"):
        roi.load_roi_geojson(Path("/nonexistent/roi.geojson"))


def test_load_roi_geojson_invalid_json(tmp_path):
    """Invalid JSON raises ValueError."""
    path = tmp_path / "bad.geojson"
    path.write_text("not valid json {", encoding="utf-8")
    
    roi = ROIFilter()
    with pytest.raises(ValueError, match="Invalid JSON"):
        roi.load_roi_geojson(path)


def test_load_roi_geojson_empty_features(tmp_path):
    """GeoJSON with no polygons raises ValueError."""
    geojson = {"type": "FeatureCollection", "features": []}
    path = tmp_path / "empty.geojson"
    path.write_text(json.dumps(geojson), encoding="utf-8")
    
    roi = ROIFilter()
    with pytest.raises(ValueError, match="No valid polygons"):
        roi.load_roi_geojson(path)


# -----------------------------------------------------------------------------
# Intersection tests (no GDAL)
# -----------------------------------------------------------------------------

def test_compute_intersection_full_overlap():
    """Image fully inside ROI."""
    roi = ROIFilter()
    # Image bounds (small box)
    image_bounds = Polygon([(0.5, 0.5), (0.8, 0.5), (0.8, 0.8), (0.5, 0.8), (0.5, 0.5)])
    # ROI (larger box containing image)
    roi_polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])]
    
    result = roi.compute_intersection(image_bounds, roi_polygons)
    
    assert result is not None
    assert result.is_valid
    assert result.area == pytest.approx(image_bounds.area, rel=1e-6)


def test_compute_intersection_partial_overlap():
    """Image partially overlaps ROI."""
    roi = ROIFilter()
    image_bounds = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    roi_polygons = [Polygon([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5), (0.5, 0.5)])]
    
    result = roi.compute_intersection(image_bounds, roi_polygons)
    
    assert result is not None
    assert result.is_valid
    assert result.area == pytest.approx(0.25, rel=1e-6)  # 0.5*0.5


def test_compute_intersection_no_overlap():
    """Image does not intersect ROI."""
    roi = ROIFilter()
    image_bounds = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    roi_polygons = [Polygon([(10, 10), (11, 10), (11, 11), (10, 11), (10, 10)])]
    
    result = roi.compute_intersection(image_bounds, roi_polygons)
    
    assert result is None


def test_compute_intersection_multiple_rois_union():
    """Image intersects two ROI polygons; result is union of intersections."""
    roi = ROIFilter()
    # Image covers area that overlaps both ROIs
    image_bounds = Polygon([(0, 0), (3, 0), (3, 1), (0, 1), (0, 0)])
    roi1 = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    roi2 = Polygon([(2, 0), (3, 0), (3, 1), (2, 1), (2, 0)])
    roi_polygons = [roi1, roi2]
    
    result = roi.compute_intersection(image_bounds, roi_polygons)
    
    assert result is not None
    assert result.is_valid
    # Union of two 1x1 boxes = 2.0
    assert result.area == pytest.approx(2.0, rel=1e-6)


def test_compute_intersection_invalid_image_bounds():
    """Invalid image bounds return None."""
    roi = ROIFilter()
    roi_polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])]
    
    result = roi.compute_intersection(None, roi_polygons)
    assert result is None


# -----------------------------------------------------------------------------
# geographic_to_pixel_bounds (requires GDAL in-memory dataset)
# -----------------------------------------------------------------------------

@pytest.mark.skipif(not GDAL_AVAILABLE, reason="GDAL not available")
def test_geographic_to_pixel_bounds():
    """Convert geographic polygon to pixel bounds using a mock dataset."""
    gdal.UseExceptions()
    driver = gdal.GetDriverByName("MEM")
    # 100x100 image, geotransform: origin (10.0, 20.0), pixel size 0.01 x -0.01
    ds = driver.Create("", 100, 100, 1, gdal.GDT_Byte)
    ds.SetGeoTransform([10.0, 0.01, 0, 20.0, 0, -0.01])
    
    # Polygon in geographic coords covering roughly pixels 10-30, 10-40
    # x_geo = 10 + x_pixel * 0.01  => x_pixel = (x_geo - 10) / 0.01
    # y_geo = 20 + y_pixel * (-0.01) => y_pixel = (20 - y_geo) / 0.01
    # So (10.1, 19.9) -> pixel (10, 10), (10.3, 19.6) -> (30, 40)
    intersection_poly = Polygon([
        (10.1, 19.9), (10.3, 19.9), (10.3, 19.6), (10.1, 19.6), (10.1, 19.9)
    ])
    
    roi = ROIFilter()
    xmin, ymin, xmax, ymax = roi.geographic_to_pixel_bounds(intersection_poly, ds)
    
    assert xmin >= 0 and ymin >= 0
    assert xmax < 100 and ymax < 100
    assert xmin <= xmax and ymin <= ymax
    assert xmin <= 11 and xmax >= 29
    assert ymin <= 11 and ymax >= 39


@pytest.mark.skipif(not GDAL_AVAILABLE, reason="GDAL not available")
def test_geographic_to_pixel_bounds_clamped():
    """Pixel bounds are clamped to image dimensions."""
    gdal.UseExceptions()
    driver = gdal.GetDriverByName("MEM")
    ds = driver.Create("", 50, 50, 1, gdal.GDT_Byte)
    ds.SetGeoTransform([0.0, 0.02, 0, 1.0, 0, -0.02])
    
    # Polygon that would extend beyond image in geo (we use a small box inside)
    intersection_poly = Polygon([
        (0.1, 0.9), (0.5, 0.9), (0.5, 0.5), (0.1, 0.5), (0.1, 0.9)
    ])
    
    roi = ROIFilter()
    xmin, ymin, xmax, ymax = roi.geographic_to_pixel_bounds(intersection_poly, ds)
    
    assert 0 <= xmin <= xmax < 50
    assert 0 <= ymin <= ymax < 50


# -----------------------------------------------------------------------------
# ensure_same_crs (no file I/O)
# -----------------------------------------------------------------------------

def test_ensure_same_crs_both_none():
    """Both CRS None returns polygons unchanged."""
    roi = ROIFilter()
    from pyproj import CRS
    polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])]
    
    out, crs = roi.ensure_same_crs(polygons, None, None)
    
    assert out is polygons
    assert crs is None


def test_ensure_same_crs_image_none():
    """Image CRS None returns polygons as-is."""
    roi = ROIFilter()
    from pyproj import CRS
    polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])]
    wgs84 = CRS.from_epsg(4326)
    
    out, crs = roi.ensure_same_crs(polygons, wgs84, None)
    
    assert out is polygons
    assert crs is wgs84


def test_ensure_same_crs_same_crs():
    """Same CRS returns polygons unchanged."""
    roi = ROIFilter()
    from pyproj import CRS
    polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])]
    wgs84 = CRS.from_epsg(4326)
    
    out, crs = roi.ensure_same_crs(polygons, wgs84, wgs84)
    
    assert out is polygons
    assert crs is wgs84


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
