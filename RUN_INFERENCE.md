# Running the Inference Script

## Basic Command Format

```bash
python InferencePython/file/infer.py <model_path> <image_path> <output_json> <tile_size> <model_type> <batch_size> <conf_thresh> <is_8bit> [device]
```

## Arguments

1. **model_path** - Path to YOLO model file (`.pt` file)
2. **img_tif** - Path to input GeoTIFF image
3. **json_output_path** - Path where output GeoJSON will be saved
4. **tile_size** - Size of tiles for sliding window inference (e.g., 640, 1024)
5. **model_type** - Type of model: `"yolo"` or `"yolo_obb"` (oriented bounding boxes)
6. **batch_size** - Number of tiles to process in parallel (e.g., 4, 8, 16)
7. **conf_thresh** - Confidence threshold (0.0 to 1.0, e.g., 0.25, 0.5)
8. **is_8bit** - Model bit depth: `"8_bit"` for 8-bit models, any other string for 16-bit
9. **device** (optional) - Device to use: `"auto"`, `"cpu"`, `"cuda"`, or `"cuda:0"` (default: `"auto"`)

## Example Commands

### Example 1: Basic YOLO Model (8-bit, CPU)
```bash
python InferencePython/file/infer.py \
    models/yolo_model.pt \
    data/input_image.tif \
    output/detections.geojson \
    640 \
    yolo \
    4 \
    0.25 \
    8_bit \
    cpu
```

### Example 2: YOLO OBB Model (16-bit, GPU)
```bash
python InferencePython/file/infer.py \
    models/yolo_obb_model.pt \
    data/satellite_image.tif \
    output/obb_detections.geojson \
    1024 \
    yolo_obb \
    8 \
    0.5 \
    16_bit \
    cuda:0
```

### Example 3: Auto Device Detection (Recommended)
```bash
python InferencePython/file/infer.py \
    models/my_model.pt \
    images/test.tif \
    results/output.geojson \
    640 \
    yolo \
    4 \
    0.3 \
    8_bit \
    auto
```

### Example 4: Windows Command (Single Line)
```cmd
python InferencePython\file\infer.py models\model.pt images\image.tif output\result.geojson 640 yolo 4 0.25 8_bit auto
```

### Example 5: High-Resolution Processing (Large Tiles, GPU)
```bash
python InferencePython/file/infer.py \
    models/high_res_model.pt \
    data/large_image.tif \
    output/high_res_detections.geojson \
    2048 \
    yolo_obb \
    2 \
    0.4 \
    16_bit \
    cuda
```

## Using with Conda Environment

If using a conda environment (e.g., `titiler`):

```bash
conda activate titiler
python InferencePython/file/infer.py \
    models/model.pt \
    data/image.tif \
    output/result.geojson \
    640 \
    yolo \
    4 \
    0.25 \
    8_bit \
    auto
```

## Parameter Recommendations

### Tile Size
- **640**: Fast, good for small objects, lower memory
- **1024**: Balanced, good for medium objects
- **2048**: High resolution, slower, higher memory, good for large objects

### Batch Size
- **CPU**: 1-4 (depends on CPU cores)
- **GPU**: 4-16 (depends on GPU memory)
- **Large images**: Use smaller batch size (2-4)

### Confidence Threshold
- **0.25**: More detections, may include false positives
- **0.5**: Balanced
- **0.7**: Fewer detections, higher precision

### Model Type
- **yolo**: Standard axis-aligned bounding boxes
- **yolo_obb**: Oriented bounding boxes (rotated rectangles)

## Output

The script generates a GeoJSON file with:
- **CRS**: Always WGS84 (EPSG:4326)
- **Coordinates**: Reprojected to WGS84 if source image is in different CRS
- **Features**: Detection polygons with properties:
  - `name`: Class name
  - `confidence`: Detection confidence score
  - `box_type`: "oriented" or "axis_aligned"
  - `detection_method`: Model type used

## Troubleshooting

### If you get PROJ errors:
- The script automatically sets up PROJ environment
- Check that conda/pip environment has pyproj installed
- Verify PROJ database exists in environment

### If reprojection fails:
- Check logs for CRS identification messages
- Ensure input image has valid projection metadata
- Script will warn if coordinates cannot be reprojected

### If GPU not detected:
- Script will automatically fall back to CPU
- Use `device=cpu` explicitly if needed
- Check CUDA installation if using GPU

## Quick Test Command

```bash
python InferencePython/file/infer.py \
    path/to/model.pt \
    path/to/test_image.tif \
    test_output.geojson \
    640 \
    yolo \
    1 \
    0.5 \
    8_bit \
    auto
```




