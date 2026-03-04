"""
YOLO Inference Script with Enhanced Projection Support

This script handles projection extraction and reprojection for all types of images,
including those with non-WGS84 projections. It includes PROJ database setup to
avoid conflicts with PostgreSQL or other installations.
"""

import sys
import os
import re
from pathlib import Path

# ============================================================================
# PROJ Environment Setup - MUST be done BEFORE importing pyproj/gdal
# ============================================================================
def setup_proj_environment():
    """
    Configure PROJ environment to avoid conflicts with PostgreSQL or other installations.
    This must be called before importing pyproj, rasterio, or any geo libraries.
    """
    # Try to find the correct PROJ data directory
    proj_data_paths = []
    
    # Method 1: Check conda environment
    if hasattr(sys, 'prefix'):
        # Windows conda
        conda_proj1 = Path(sys.prefix) / 'Library' / 'share' / 'proj'
        if conda_proj1.exists() and (conda_proj1 / 'proj.db').exists():
            proj_data_paths.append(str(conda_proj1))
        
        # Linux/Mac conda
        conda_proj2 = Path(sys.prefix) / 'share' / 'proj'
        if conda_proj2.exists() and (conda_proj2 / 'proj.db').exists():
            proj_data_paths.append(str(conda_proj2))
    
    # Method 2: Try pyproj's data directory (check common locations without importing)
    # We'll verify pyproj works after imports
    
    # Method 3: Check common pip installation locations
    python_dir = Path(sys.executable).parent
    pip_paths = [
        python_dir / 'Lib' / 'site-packages' / 'pyproj' / 'proj_dir' / 'share' / 'proj',
        python_dir / 'lib' / 'site-packages' / 'pyproj' / 'proj_dir' / 'share' / 'proj',
    ]
    for path in pip_paths:
        if path.exists() and (path / 'proj.db').exists():
            proj_data_paths.append(str(path))
    
    # Set PROJ environment variables
    if proj_data_paths:
        proj_lib = proj_data_paths[0]
        os.environ['PROJ_LIB'] = proj_lib
        os.environ['PROJ_DATA'] = proj_lib
        
        # Remove PostgreSQL from PATH to avoid conflicts
        path = os.environ.get('PATH', '')
        filtered_paths = [
            p for p in path.split(os.pathsep) 
            if 'PostgreSQL' not in p and 'postgis' not in p.lower()
        ]
        os.environ['PATH'] = os.pathsep.join(filtered_paths)
        
        return proj_lib
    else:
        # If we can't find PROJ, try to use system default
        # pyproj will handle it, but we warn the user
        return None

# Setup PROJ environment before any geo imports
_proj_dir = setup_proj_environment()

# Now safe to import geo libraries
from ultralytics import YOLO
import numpy as np
import xml.etree.ElementTree as gfg
from math import ceil,floor
import json
from datetime import datetime
from osgeo import gdal
import torch
from shapely.geometry import Polygon
import pyproj
from pyproj import CRS, Transformer
from pyproj import exceptions as pyproj_exceptions
import traceback


def verify_proj_setup():
    """
    Verify that PROJ is set up correctly and working.
    Returns True if PROJ is working, False otherwise.
    """
    try:
        import pyproj
        # Test a simple transformation to verify PROJ works
        transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        test_result = transformer.transform(0, 0)
        if _proj_dir:
            log_info(f"PROJ environment configured: {_proj_dir}")
        return True
    except Exception as e:
        log_warning(f"PROJ verification failed: {e}")
        log_warning("CRS operations may fail. Check PROJ_LIB environment variable.")
        return False


def log_info(message):
    print(f"[INFO] {message}")


def log_warning(message):
    print(f"[WARN] {message}")


def exit_with_error(stage, error):
    print(f"[ERROR] {stage}: {error}")
    traceback.print_exc()
    sys.exit(1)


def reproject_point(transformer, point, label):
    try:
        return list(transformer.transform(point[0], point[1]))
    except Exception as exc:
        exit_with_error(f"Reprojecting {label}", exc)


def resolve_class_name(names_obj, cls_idx):
    cls_int = int(cls_idx)
    if isinstance(names_obj, dict):
        return names_obj.get(cls_int, str(cls_int))
    if isinstance(names_obj, (list, tuple)):
        if 0 <= cls_int < len(names_obj):
            return names_obj[cls_int]
    return str(cls_int)

def intersection_over_union(obb1,obb2):#obb is in the [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] format
    #print(obb1.shape)
    poly1 = Polygon(obb1)
    poly2 = Polygon(obb2)
    intersection = poly1.intersection(poly2).area
    union = poly1.union(poly2).area
    if(union == 0):
        iou = 0
    else:
        iou = intersection/union
    return iou

def intersection_over_min_area(obb1,obb2):#obb is in the [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] format
    poly1 = Polygon(obb1)
    poly2 = Polygon(obb2)
    intersection = poly1.intersection(poly2).area
    min_area = min(poly1.area,poly2.area)
    return (intersection/min_area)

def get_min_max_xy(obb):#obb is in the [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] format
    min_x,min_y = np.amin(obb,axis = 0)
    max_x,max_y = np.amax(obb,axis = 0)
    return [min_y,min_x,max_y,max_x]
    
def get_object_grid(obb1,obb2,grid_lim1,grid_lim2,pred_score1,pred_score2):
    #obb1 and obb2 are in the [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] format
    obj1_edge = False
    obj2_edge = False
    bbox1 = get_min_max_xy(obb1)
    bbox2 = get_min_max_xy(obb2)
    if(bbox1[0] <= grid_lim1[0] or bbox1[1] <= grid_lim1[1] or bbox1[2] >= grid_lim1[2] or bbox1[3] >= grid_lim1[3]):
        obj1_edge = True 
    if(bbox2[0] <= grid_lim2[0] or bbox2[1] <= grid_lim2[1] or bbox2[2] >= grid_lim2[2] or bbox2[3] >= grid_lim2[3]):
        obj2_edge = True
    object_grid = 1
    if((obj1_edge and not obj2_edge) or
       (not obj1_edge and not obj2_edge and pred_score2 > pred_score1)):
        object_grid = 2
    return object_grid

def pixel_to_geo(ds, x_pixel, y_pixel):
    """
    Convert pixel coordinates to geospatial coordinates using GDAL's affine transform.
    """
    gt = ds.GetGeoTransform()
    x_geo, y_geo = gdal.ApplyGeoTransform(gt, x_pixel, y_pixel)

    # Optional debug logging for the first sample to verify correctness
    if os.environ.get("DEBUG_COORD_LOG", "0") == "1" and not getattr(pixel_to_geo, "_sample_logged", False):
        log_info(
            f"pixel_to_geo sample -> px: {x_pixel}, py: {y_pixel} "
            f"maps to source CRS coords: ({x_geo:.6f}, {y_geo:.6f})"
        )
        pixel_to_geo._sample_logged = True

    return float(x_geo), float(y_geo)


def compute_global_obb(obb, tile_row, tile_col, stride_length, width, height):
    """
    Convert a local OBB (tile-relative) to global pixel coordinates referencing the original raster.
    """
    global_points = []
    for x_local, y_local in obb:
        global_px = tile_col * stride_length + x_local
        global_py = tile_row * stride_length + y_local
        global_px = min(max(global_px, 0), width - 1)
        global_py = min(max(global_py, 0), height - 1)
        global_points.append([global_px, global_py])
    return np.array(global_points, dtype=float)

def get_model_input_channels(model):
    py_model = model.model
    first_conv_layer = None
    for module in py_model.modules():
        if isinstance(module,torch.nn.Conv2d):
            first_conv_layer = module
            break
    if(first_conv_layer):
        num_ch = first_conv_layer.in_channels
    else:
        num_ch = 0
    return num_ch

#boxes = np.round(result[i].boxes.xyxy.tolist())
def boxes_to_obbs(boxes):
    obbs = []
    for box in boxes:
        x_min, y_min, x_max, y_max = box
        obbs.append(np.array([x_min,y_min,x_max,y_min,x_max,y_max,x_min,y_max]))
    return obbs
    
if __name__=="__main__":
    start_time = datetime.now()
    model_path = sys.argv[1]
    img_tif = sys.argv[2]
    json_output_path = sys.argv[3]
    tile_size = int(sys.argv[4])
    model_type = sys.argv[5]
    batch_size = int(sys.argv[6])
    conf_thresh = float(sys.argv[7])
    is_model_8bit = (sys.argv[8] == "8_bit")
    device_arg = sys.argv[9] if len(sys.argv) > 9 else "auto"
    
    # Device detection and configuration
    device_arg_lower = device_arg.lower()
    if device_arg_lower == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    elif device_arg_lower.startswith("cuda"):
        requested_device = device_arg_lower
        if requested_device == "cuda":
            requested_device = "cuda:0"
        if torch.cuda.is_available():
            available_cuda_devices = [f"cuda:{idx}" for idx in range(torch.cuda.device_count())]
            if requested_device in available_cuda_devices:
                device = requested_device
            else:
                fallback = available_cuda_devices[0] if available_cuda_devices else "cpu"
                log_warning(f"Requested CUDA device '{device_arg}' not available. Falling back to {fallback}.")
                device = available_cuda_devices[0] if available_cuda_devices else "cpu"
        else:
            log_warning("CUDA requested but no GPU detected. Falling back to CPU.")
            device = "cpu"
    else:
        device = "cpu"
    
    log_info("Starting inference with parameters:")
    log_info(f"  Model path: {model_path}")
    log_info(f"  Image path: {img_tif}")
    log_info(f"  Output path: {json_output_path}")
    log_info(f"  Tile size: {tile_size}")
    log_info(f"  Model type: {model_type}")
    log_info(f"  Batch size: {batch_size}")
    log_info(f"  Confidence threshold: {conf_thresh}")
    log_info(f"  Model bit depth flag: {'8-bit' if is_model_8bit else '16-bit'}")
    log_info(f"  Requested device: {device}")
    
    # Verify PROJ setup
    verify_proj_setup()
    
    overlap_length = tile_size//4
    
    if model_type not in ("yolo", "yolo_obb"):
        exit_with_error("Model type", f"Unsupported model type '{model_type}'. Expected 'yolo' or 'yolo_obb'.")

    log_info("Loading YOLO model...")
    try:
        model = YOLO(model_path)
    except Exception as e:
        exit_with_error("Loading YOLO model", e)

    log_info(f"Moving model to device '{device}'")
    try:
        model.to(device)
    except Exception as e:
        exit_with_error(f"Moving model to device '{device}'", e)

    class_names = getattr(model, "names", {}) or {}
    if not class_names:
        log_warning("Model did not expose class names; outputs will use numeric indices.")

    is_hbb = (model_type == "yolo")
    
    num_ch = get_model_input_channels(model)
    if num_ch == 0:
        exit_with_error("Inspecting model architecture", "Unable to determine input channel count. Verify the model file.")
    log_info(f"Model expects {num_ch} channel(s).")

    gdal.UseExceptions()
    log_info("Opening input raster with GDAL...")
    try:
        ds = gdal.Open(img_tif)
    except RuntimeError as e:
        exit_with_error("Opening input raster", e)

    if ds is None:
        exit_with_error("Opening input raster", "GDAL returned None. Check file path, permissions, or file format.")

    raster_count = ds.RasterCount
    if raster_count == 0:
        exit_with_error("Reading raster bands", "Raster has zero bands.")
    log_info(f"Raster opened successfully with {raster_count} band(s).")
    if raster_count > 4:
        log_warning(f"Raster has {raster_count} bands. Only the first 4 will be used by this script.")

    try:
        geotransform = ds.GetGeoTransform()
    except Exception as e:
        exit_with_error("Reading geotransform", e)

    if geotransform is None:
        exit_with_error("Reading geotransform", "GeoTIFF is missing geotransform metadata.")

    # Get projection - try multiple methods as GetProjection() can return None
    # even when gdalinfo shows correct projection
    projection_wkt = None
    
    # Method 1: Try GetProjection() (standard method)
    projection_wkt_temp = ds.GetProjection()
    if projection_wkt_temp and projection_wkt_temp.strip():
        projection_wkt = projection_wkt_temp
        log_info("Got projection from GetProjection()")
    
    # Method 2: Try GetSpatialRef() (newer GDAL API, more reliable)
    if not projection_wkt:
        try:
            srs_obj = ds.GetSpatialRef()
            if srs_obj:
                projection_wkt = srs_obj.ExportToWkt()
                log_info("Got projection from GetSpatialRef()")
        except (AttributeError, Exception) as e:
            log_warning(f"GetSpatialRef() not available or failed: {e}")
    
    # Method 3: Try GetGCPProjection() (for files with GCPs)
    if not projection_wkt:
        try:
            gcp_projection = ds.GetGCPProjection()
            if gcp_projection and gcp_projection.strip():
                projection_wkt = gcp_projection
                log_info("Got projection from GetGCPProjection()")
        except Exception as e:
            log_warning(f"GetGCPProjection() failed: {e}")
    
    if not projection_wkt:
        log_warning("Input image has no projection metadata. GeoJSON will default to CRS84 coordinates.")

    if(raster_count == 1):
        r = ds.GetRasterBand(1)
        ra = r.ReadAsArray()
        if(num_ch == 1):
            img_np = np.expand_dims(ra,axis = 2)
        elif(num_ch == 3):
            img_np = np.stack((ra,ra,ra),axis = 2)
        else:
            img_np = np.stack((ra,ra,ra,ra),axis = 2)
    elif(raster_count == 3):
        r = ds.GetRasterBand(1)
        ra = r.ReadAsArray()
        g = ds.GetRasterBand(2)
        ga = g.ReadAsArray()
        b = ds.GetRasterBand(3)
        ba = b.ReadAsArray()
        if(num_ch == 1):
            img_np = np.expand_dims(ra,axis = 2)
        elif(num_ch == 3):
            img_np = np.stack((ra,ga,ba),axis = 2)
        else:
            exit_with_error(
                "Preparing image data",
                f"Model expects {num_ch} channels but the raster has only 3. Consider updating the model or preprocessing the imagery."
            )
    else:
        r = ds.GetRasterBand(1)
        ra = r.ReadAsArray()
        g = ds.GetRasterBand(2)
        ga = g.ReadAsArray()
        b = ds.GetRasterBand(3)
        ba = b.ReadAsArray()
        a = ds.GetRasterBand(4)
        aa = a.ReadAsArray()
        if(num_ch == 1):
            img_np = np.expand_dims(ra,axis = 2)
        elif(num_ch == 3):
            img_np = np.stack((ra,ga,ba),axis = 2)
        else:
            img_np = np.stack((ra,ga,ba,aa),axis = 2)
            
    log_info(f"Prepared image array with shape {img_np.shape} and dtype {img_np.dtype}.")

    max_pixel = np.max(img_np)
    min_pixel = np.min(img_np)
    log_info(f"Image pixel range before normalization: min={min_pixel}, max={max_pixel}")
    if(is_model_8bit):
        if(max_pixel > 255):
            #print("min_pixel",min_pixel,min_pixel.dtype)
            #beta = -1*min_pixel
            if max_pixel == min_pixel:
                log_warning("Image has flat pixel values; scaling may result in zeros.")
                alpha = 1.0
            else:
                alpha = 1/(max_pixel-min_pixel)
            alpha = 1/(max_pixel-min_pixel)
            img_np = (img_np-min_pixel)*alpha #scale image into full range of 0 to 1.0
        else:
            img_np = img_np/255.0
    else:
        img_np = img_np/65535.0
    log_info("Image normalization complete.")
        
    (h,w) = img_np.shape[:2]
    stride_length = tile_size-overlap_length
    iou_thresh = 0.8
    ioma_thresh = 0.75
    
    w_pad = ceil((w-overlap_length)/stride_length)*stride_length+overlap_length-w
    h_pad = ceil((h-overlap_length)/stride_length)*stride_length+overlap_length-h
    img_np_pad = np.pad(img_np,((0,h_pad),(0,w_pad),(0,0)),constant_values = 0.0)
    h_iter = ceil((h-overlap_length)/stride_length)
    w_iter = ceil((w-overlap_length)/stride_length)
    

    obbs_tif = []      #detected obbs for each sliding window grid
    names_tif = []    #detected object class for each sliding window grid
    scores_tif = []     #detected object score for each sliding window grid
    good_obb = []       #same detected object may also be detected in adjacent grid. True if detection belongs to this grid
    N_og = []           #number of detected object in a particular grid
    grid_lim = []
    for r in range(h_iter):
        obbs_tif.append([])
        names_tif.append([])
        scores_tif.append([])
        good_obb.append([])
        N_og.append([])
        grid_lim.append([])
        for c in range(w_iter):
            obbs_tif[r].append([])
            names_tif[r].append([])
            scores_tif[r].append([])
            good_obb[r].append([])     #here element would be True or False corresponding to whether obb should be taken or not due to intersection with other obb 
            N_og[r].append(0)
            grid_lim[r].append([r*stride_length,c*stride_length,r*stride_length+tile_size-1,c*stride_length+tile_size-1])
    
    model_input = []
    b_rem = batch_size
    b_start_h_i = 0
    b_start_w_i = 0
    for r in range(h_iter):
        for c in range(w_iter):
            crop_img = img_np_pad[stride_length*r:stride_length*r+tile_size,stride_length*c:stride_length*c+tile_size]
            model_input.append(torch.from_numpy(crop_img.transpose(2,0,1)))
            b_rem -= 1
            if(b_rem == 0):
                input_tensor = torch.stack(model_input,dim = 0).to(device)
                log_info(f"Running batch inference on tensor with shape {input_tensor.shape}.")
                if model_type == "yolo_obb":
                    result = model(input_tensor, imgsz=tile_size, agnostic_nms=True, task="obb")
                else:
                    result = model(input_tensor, imgsz=tile_size, agnostic_nms=True)
                model_input = []
                b_rem = batch_size
                for i in range(batch_size):
                    if(is_hbb):
                        boxes = np.round(result[i].boxes.xyxy.tolist())
                        obbs = boxes_to_obbs(boxes)
                        classes = np.round(result[i].boxes.cls.tolist())
                        confidences = result[i].boxes.conf.tolist()
                    else:
                        obbs = np.round(result[i].obb.xyxyxyxy.tolist())
                        classes = np.round(result[i].obb.cls.tolist())
                        confidences = result[i].obb.conf.tolist()
                    names_source = result[i].names if getattr(result[i], "names", None) else class_names
                    
                    cur_c = b_start_w_i+i
                    cur_r = b_start_h_i+int(cur_c/w_iter)
                    cur_c = cur_c%w_iter
                    for obb, cls, conf in zip(obbs, classes, confidences):
                        #print("obb",obb,obb.shape)
                        x1,y1,x2,y2,x3,y3,x4,y4 = obb.flatten()
                        name = resolve_class_name(names_source, cls)
                        if(conf >= conf_thresh):
                            obbs_tif[cur_r][cur_c].append(
                                np.array([[x1, y1], [x2, y2], [x3, y3], [x4, y4]], dtype=float)
                            )
                            #obbs_tif[cur_r][cur_c].append(np.array([x1,y1,x2,y2,x3,y3,x4,y4]))
                            names_tif[cur_r][cur_c].append(name)
                            scores_tif[cur_r][cur_c].append(conf)
                            good_obb[cur_r][cur_c].append(True)
                            N_og[cur_r][cur_c] += 1
                b_start_h_i = r
                b_start_w_i = c+1
                if(b_start_w_i == w_iter):
                    b_start_w_i = 0
                    b_start_h_i = b_start_h_i+1

    if(len(model_input) > 0):
        input_tensor = torch.stack(model_input,dim = 0).to(device)
        if model_type == "yolo_obb":
            result = model(input_tensor, imgsz=tile_size, agnostic_nms=True, task="obb")
        else:
            result = model(input_tensor, imgsz=tile_size, agnostic_nms=True)
        N_rem = len(model_input)
        for i in range(N_rem):
            if(is_hbb):
                boxes = np.round(result[i].boxes.xyxy.tolist())
                obbs = boxes_to_obbs(boxes)
                classes = np.round(result[i].boxes.cls.tolist())
                confidences = result[i].boxes.conf.tolist()
            else:
                obbs = np.round(result[i].obb.xyxyxyxy.tolist())
                classes = np.round(result[i].obb.cls.tolist())
                confidences = result[i].obb.conf.tolist()
            names_source = result[i].names if getattr(result[i], "names", None) else class_names
                 
            cur_c = b_start_w_i+i
            cur_r = b_start_h_i+int(cur_c/w_iter)
            cur_c = cur_c%w_iter
            
            for obb, cls, conf in zip(obbs, classes, confidences):
                #print(obb.shape)
                x1,y1,x2,y2,x3,y3,x4,y4 = obb.flatten()
                name = resolve_class_name(names_source, cls)
                if(conf >= conf_thresh):
                    obbs_tif[cur_r][cur_c].append(
                        np.array([[x1, y1], [x2, y2], [x3, y3], [x4, y4]], dtype=float)
                    )
                    names_tif[cur_r][cur_c].append(name)
                    scores_tif[cur_r][cur_c].append(conf)
                    good_obb[cur_r][cur_c].append(True)
                    N_og[cur_r][cur_c] += 1 

    for r in range(h_iter):
        for c in range(w_iter):
            N = N_og[r][c]
            if(r < h_iter-1):
                N1 = N_og[r+1][c]
                for i in range(N):
                    current_global = compute_global_obb(obbs_tif[r][c][i], r, c, stride_length, w, h)
                    j = 0
                    while(j < N1 and good_obb[r][c][i]):
                        if(good_obb[r+1][c][j]):
                            neighbor_global = compute_global_obb(obbs_tif[r+1][c][j], r+1, c, stride_length, w, h)
                            iou = intersection_over_union(current_global, neighbor_global)
                            ioma = intersection_over_min_area(current_global, neighbor_global)
                            if(iou >= iou_thresh or ioma >= ioma_thresh):
                                good_grid = get_object_grid(
                                    current_global,
                                    neighbor_global,
                                    grid_lim[r][c],
                                    grid_lim[r+1][c],
                                    scores_tif[r][c][i],
                                    scores_tif[r+1][c][j]
                                )
                                if(good_grid == 1):
                                    good_obb[r+1][c][j] = False
                                else:
                                    good_obb[r][c][i] = False
                        j += 1
            if(c < w_iter-1):
                N1 = N_og[r][c+1]
                for i in range(N):
                    current_global = compute_global_obb(obbs_tif[r][c][i], r, c, stride_length, w, h)
                    j = 0
                    while(j < N1 and good_obb[r][c][i]):
                        if(good_obb[r][c+1][j]):
                            neighbor_global = compute_global_obb(obbs_tif[r][c+1][j], r, c+1, stride_length, w, h)
                            iou = intersection_over_union(current_global, neighbor_global)
                            ioma = intersection_over_min_area(current_global, neighbor_global)
                            if(iou >= iou_thresh or ioma >= ioma_thresh):
                                good_grid = get_object_grid(
                                    current_global,
                                    neighbor_global,
                                    grid_lim[r][c],
                                    grid_lim[r][c+1],
                                    scores_tif[r][c][i],
                                    scores_tif[r][c+1][j]
                                )
                                if(good_grid == 1):
                                    good_obb[r][c+1][j] = False
                                else:
                                    good_obb[r][c][i] = False
                        j += 1
            if(r < h_iter-1 and c < w_iter-1):
                N1 = N_og[r+1][c+1]
                for i in range(N):
                    current_global = compute_global_obb(obbs_tif[r][c][i], r, c, stride_length, w, h)
                    j = 0
                    while(j < N1 and good_obb[r][c][i]):
                        if(good_obb[r+1][c+1][j]):
                            neighbor_global = compute_global_obb(obbs_tif[r+1][c+1][j], r+1, c+1, stride_length, w, h)
                            iou = intersection_over_union(current_global, neighbor_global)
                            ioma = intersection_over_min_area(current_global, neighbor_global)
                            if(iou >= iou_thresh or ioma >= ioma_thresh):
                                good_grid = get_object_grid(
                                    current_global,
                                    neighbor_global,
                                    grid_lim[r][c],
                                    grid_lim[r+1][c+1],
                                    scores_tif[r][c][i],
                                    scores_tif[r+1][c+1][j]
                                )
                                if(good_grid == 1):
                                    good_obb[r+1][c+1][j] = False
                                else:
                                    good_obb[r][c][i] = False
                        j += 1
            if(r < h_iter-1 and c > 0):
                N1 = N_og[r+1][c-1]
                for i in range(N):
                    current_global = compute_global_obb(obbs_tif[r][c][i], r, c, stride_length, w, h)
                    j = 0
                    while(j < N1 and good_obb[r][c][i]):
                        if(good_obb[r+1][c-1][j]):
                            neighbor_global = compute_global_obb(obbs_tif[r+1][c-1][j], r+1, c-1, stride_length, w, h)
                            iou = intersection_over_union(current_global, neighbor_global)
                            ioma = intersection_over_min_area(current_global, neighbor_global)
                            if(iou >= iou_thresh or ioma >= ioma_thresh):
                                good_grid = get_object_grid(
                                    current_global,
                                    neighbor_global,
                                    grid_lim[r][c],
                                    grid_lim[r+1][c-1],
                                    scores_tif[r][c][i],
                                    scores_tif[r+1][c-1][j]
                                )
                                if(good_grid == 1):
                                    good_obb[r+1][c-1][j] = False
                                else:
                                    good_obb[r][c][i] = False
                        j += 1
                    
    #Till here detected objects has been assigned to specific grid
    features = []
    crs_name = f"urn:ogc:def:crs:OGC:1.3:CRS84"
    
    # Determine source CRS with multiple fallback methods
    source_crs = None
    if projection_wkt:
        # Method 1: Try pyproj CRS.from_wkt() (most reliable)
        try:
            source_crs = CRS.from_wkt(projection_wkt)
            log_info(f"Detected source CRS via pyproj: {source_crs.to_string()}")
            if source_crs.to_epsg():
                log_info(f"  EPSG code: {source_crs.to_epsg()}")
        except (pyproj_exceptions.CRSError, Exception) as exc:
            log_warning(f"pyproj CRS.from_wkt() failed: {exc}")
            
            # Method 2: Try GDAL/OSR to identify EPSG code
            try:
                from osgeo import osr
                sr = osr.SpatialReference()
                sr.ImportFromWkt(projection_wkt)
                sr.AutoIdentifyEPSG()
                authority = sr.GetAuthorityName(None)
                code = sr.GetAuthorityCode(None)
                
                if authority and code:
                    try:
                        source_crs = CRS.from_authority(authority, int(code))
                        log_info(f"GDAL identified CRS: {authority}:{code} -> {source_crs.to_string()}")
                    except Exception as e:
                        log_warning(f"Failed to create CRS from authority {authority}:{code}: {e}")
                        # Try direct EPSG if authority is EPSG
                        if authority.upper() == 'EPSG':
                            try:
                                source_crs = CRS.from_epsg(int(code))
                                log_info(f"Created CRS from EPSG code: {code}")
                            except Exception:
                                pass
            except Exception as exc:
                log_warning(f"GDAL/OSR CRS identification failed: {exc}")
            
            # Method 3: Try to extract EPSG code from WKT string directly
            if not source_crs:
                epsg_match = re.search(r'EPSG["\']?\s*[:\s]+(\d+)', projection_wkt, re.IGNORECASE)
                if epsg_match:
                    try:
                        epsg_code = int(epsg_match.group(1))
                        source_crs = CRS.from_epsg(epsg_code)
                        log_info(f"Extracted EPSG code from WKT: {epsg_code}")
                    except Exception as e:
                        log_warning(f"Failed to create CRS from extracted EPSG {epsg_code}: {e}")
            
            # Method 4: Last resort - try to use WKT directly (may not work for all operations)
            if not source_crs:
                try:
                    source_crs = CRS.from_wkt(projection_wkt)
                    log_info("Using WKT directly (may have limitations)")
                except Exception:
                    log_warning("All CRS identification methods failed")
                source_crs = None

    target_crs = CRS.from_epsg(4326)  # WGS84 - always use for GeoJSON output
    transformer = None
    reprojection_available = False

    # Always convert to WGS84 (EPSG:4326) for GeoJSON output
    crs_name = f"urn:ogc:def:crs:EPSG::{target_crs.to_epsg()}"  # Always WGS84 for GeoJSON

    if source_crs:
        try:
            pyproj.datadir.set_use_proj4_api(True)
            source_crs_fixed = CRS.from_proj4(source_crs.to_proj4())
            transformer = Transformer.from_crs(
                source_crs_fixed,
                target_crs,
                always_xy=True
            )
            reprojection_available = True
            log_info(f"Reprojecting coordinates from {source_crs.to_string()} to EPSG:4326 (WGS84) for GeoJSON output.")
            
            # Test the transformer with a sample point to verify it works
            try:
                test_point_x = geotransform[0]  # Top-left X (easting or lon)
                test_point_y = geotransform[3]   # Top-left Y (northing or lat)
                test_result = transformer.transform(test_point_x, test_point_y)
                log_info(f"Transformer test successful:")
                log_info(f"  Source CRS ({source_crs_fixed.to_string()}): [{test_point_x:.6f}, {test_point_y:.6f}]")
                log_info(f"  WGS84 (EPSG:4326): [{test_result[0]:.6f}, {test_result[1]:.6f}]")
                log_info(f"  Coordinate order: [longitude, latitude] for GeoJSON")
                
                # Validate test result
                test_lon, test_lat = test_result[0], test_result[1]
                if not (-180 <= test_lon <= 180) or not (-90 <= test_lat <= 90):
                    log_warning(f"Transformer test result is outside WGS84 bounds!")
                    log_warning(f"  This suggests the transformation may be incorrect.")
            except Exception as test_exc:
                log_warning(f"Transformer test failed: {test_exc}")
                log_warning(f"  Reprojection may not work correctly.")
                import traceback
                log_warning(f"  Traceback: {traceback.format_exc()}")
        except Exception as trans_exc:
            log_warning(f"Failed to create transformer: {trans_exc}")
            reprojection_available = False
            transformer = None
        except Exception as exc:
            log_warning(f"CRS reprojection setup failed: {exc}. Coordinates will remain in native CRS.")
            log_warning(f"ERROR: GeoJSON will be labeled as WGS84 but coordinates are in source CRS: {source_crs.to_string() if source_crs else 'Unknown'}")
            source_crs = None
            transformer = None
            reprojection_available = False
    else:
        log_warning("Unable to determine source CRS from projection metadata.")
        log_warning("ERROR: Cannot reproject to WGS84. GeoJSON coordinates will be in native CRS but labeled as WGS84.")
        log_warning("This may cause incorrect coordinate display. Please ensure the input image has valid projection metadata.")
        reprojection_available = False
                        
    for r in range(h_iter):
        for c in range(w_iter):
            N = N_og[r][c]
            for i in range(N):
                if(good_obb[r][c][i]):
                    global_obb_pixels = compute_global_obb(obbs_tif[r][c][i], r, c, stride_length, w, h)

                    world_coords = []
                    for global_px, global_py in global_obb_pixels:
                        x_geo, y_geo = pixel_to_geo(ds, global_px, global_py)
                        if transformer and reprojection_available:
                            try:
                                lon, lat = transformer.transform(x_geo, y_geo)
                                world_coords.append([float(lon), float(lat)])
                            except Exception as e:
                                log_warning(f"Failed to reproject point ({x_geo}, {y_geo}): {e}")
                                world_coords.append([float(x_geo), float(y_geo)])
                        else:
                            world_coords.append([float(x_geo), float(y_geo)])

                    if len(world_coords) != 4:
                        continue

                    p1, p2, p3, p4 = world_coords
                    #top_left = pixel_to_geo(geotransform, xmin, ymin)
                    #top_right = pixel_to_geo(geotransform, xmax, ymin)
                    #bottom_right = pixel_to_geo(geotransform, xmax, ymax)
                    #bottom_left = pixel_to_geo(geotransform, xmin, ymax)
                    polygon_coords = [p1, p2, p3, p4, p1.copy()]  # Closing the loop
                    feature = {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [polygon_coords]
                                },
                                "properties": {
                                    "name": names_tif[r][c][i],
                                    "confidence": scores_tif[r][c][i],
                                    "box_type": "oriented" if not is_hbb else "axis_aligned",
                                    "detection_method": model_type
                                }
                            }
                    features.append(feature)
    
    # Log reprojection summary
    if reprojection_available:
        if transformer:
            log_info(f"✓ Successfully reprojected {len(features)} features from source CRS to WGS84 (EPSG:4326)")
        else:
            log_info(f"✓ Source CRS is already WGS84 - {len(features)} features are in WGS84 coordinates")
    else:
        log_warning(f"⚠ WARNING: {len(features)} features were NOT reprojected to WGS84")
        log_warning("  GeoJSON declares WGS84 but coordinates are in source CRS - this will cause display issues!")
                        
    # Count detection types for metadata
    oriented_count = sum(1 for f in features if f["properties"].get("box_type") == "oriented")
    axis_aligned_count = sum(1 for f in features if f["properties"].get("box_type") == "axis_aligned")
    
    geojson_collection = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {
                "name": crs_name
            }
        },
        "properties": {
            "total_detections": len(features),
            "oriented_detections": oriented_count,
            "axis_aligned_detections": axis_aligned_count,
            "model_type": model_type,
            "detection_method": "mixed" if (oriented_count > 0 and axis_aligned_count > 0) else ("obb" if oriented_count > 0 else "regular"),
            "generated_by": "YOLO Inference Script",
            "version": "2.0_with_obb_support",
            "confidence_threshold": conf_thresh,
            "model_bit_depth": "8-bit" if is_model_8bit else "16-bit"
        },
        "features": features
    }

    log_info(f"GeoJSON will be written with CRS identifier: {crs_name}")

    try:
        with open(json_output_path, 'w') as f:
            json.dump(geojson_collection, f, indent=2)
        log_info(f"Successfully created GeoJSON file at {json_output_path}")
        log_info("Detection summary:")
        log_info(f"  - Total detections: {len(features)}")
        log_info(f"  - Oriented bounding boxes: {oriented_count}")
        log_info(f"  - Axis-aligned bounding boxes: {axis_aligned_count}")
        log_info(f"  - Model type: {model_type}")
        log_info(f"  - Detection method: {geojson_collection['properties']['detection_method']}")
        log_info(f"  - Confidence threshold: {conf_thresh}")
        log_info(f"  - Model bit depth: {'8-bit' if is_model_8bit else '16-bit'}")
    except IOError as e:
        exit_with_error("Writing GeoJSON output", e)
