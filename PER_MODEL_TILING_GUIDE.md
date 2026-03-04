# Per-Model Tiling Configuration Guide

## Overview

The pipeline now supports **per-model tiling configuration**, allowing each model to use different tile sizes, overlaps, and NMS thresholds. This is essential when models were trained on different tile sizes.

## Why Per-Model Tiling?

Different YOLO models may have been trained on:
- Different tile sizes (e.g., 512px vs 1024px)
- Different overlap requirements
- Different normalization strategies
- Different NMS thresholds

Using the same tiling configuration for all models can lead to:
- ❌ Suboptimal performance (model expects different input size)
- ❌ Reduced accuracy (wrong tile size for model)
- ❌ Inefficient processing (unnecessary tiles for some models)

## Configuration

### Global Tiling (Default)

Global tiling configuration applies to all models that don't have per-model tiling:

```yaml
tiling:
  tile_size: 512              # Default tile size
  overlap: 256                # Default overlap
  normalization_mode: "auto"
  allow_resample: true
  iou_threshold: 0.8           # Default IoU threshold for NMS
  ioma_threshold: 0.75         # Default IoMA threshold for NMS
```

### Per-Model Tiling

Override global tiling for specific models:

```yaml
models:
  - name: "Yolo_plane_x"
    weights_path: "models/Yolo_plane_x.pt"
    type: "yolo"
    device: "cuda:0"
    confidence_threshold: 0.5
    # Per-model tiling configuration (overrides global)
    tile:
      tile_size: 512           # Model-specific tile size
      overlap: 256              # Model-specific overlap
      normalization_mode: "auto"
      allow_resample: true
      iou_threshold: 0.8        # Model-specific IoU threshold
      ioma_threshold: 0.75      # Model-specific IoMA threshold
    outputs:
      write_tile_previews: false
      summary_csv: true

  - name: "yolo_obb"
    weights_path: "models/yolo11n-obb.pt"
    type: "yolo_obb"
    device: "cuda:1"
    confidence_threshold: 0.5
    # Different tiling config for this model
    tile:
      tile_size: 1024           # Larger tiles for this model
      overlap: 512              # Larger overlap
      normalization_mode: "auto"
      allow_resample: true
      iou_threshold: 0.75       # Different NMS thresholds
      ioma_threshold: 0.7
    outputs:
      write_tile_previews: false
      summary_csv: true
```

## How It Works

### Tile Generation

1. **Per-Model Tilers**: Each model gets its own `RasterTiler` instance with its tiling config
2. **Independent Processing**: Each model processes tiles generated with its own configuration
3. **Model-Specific NMS**: Cross-tile NMS uses each model's tiling config for stride calculations

### Processing Flow

```
Image Input
    ↓
For each model:
    ↓
Create RasterTiler with model's tiling config
    ↓
Generate tiles using model's tile_size and overlap
    ↓
Process tiles through model
    ↓
Apply cross-tile NMS using model's tiling config
    ↓
Convert to GeoJSON features
    ↓
Combine all model outputs
```

## Configuration Options

### Tile Size (`tile_size`)

- **Type**: Integer
- **Description**: Size of each tile in pixels (width and height)
- **Recommendations**:
  - Match the tile size used during model training
  - Common sizes: 256, 512, 640, 1024, 1280
  - Larger tiles = fewer tiles but more GPU memory

### Overlap (`overlap`)

- **Type**: Integer
- **Description**: Overlap between tiles in pixels
- **Recommendations**:
  - Typically 25-50% of tile size
  - Larger overlap = better edge detection but more processing
  - Example: For tile_size=512, use overlap=128-256

### Normalization Mode (`normalization_mode`)

- **Type**: String
- **Options**: `"auto"`, `"minmax"`, `"zscore"`, `"none"`
- **Recommendation**: Use `"auto"` for most cases

### Allow Resample (`allow_resample`)

- **Type**: Boolean
- **Description**: Whether to allow resampling if image doesn't match tile size
- **Recommendation**: Keep `true` for flexibility

### IoU Threshold (`iou_threshold`)

- **Type**: Float (0.0 to 1.0)
- **Description**: Intersection over Union threshold for cross-tile NMS
- **Purpose**: Removes duplicate detections from overlapping tiles
- **Recommendations**:
  - Strict deduplication: 0.7-0.8
  - Moderate deduplication: 0.8-0.9
  - Loose deduplication: 0.9-1.0

### IoMA Threshold (`ioma_threshold`)

- **Type**: Float (0.0 to 1.0)
- **Description**: Intersection over Minimum Area threshold for cross-tile NMS
- **Purpose**: Additional deduplication metric
- **Recommendation**: Typically 0.75

## Examples

### Example 1: Models Trained on Different Tile Sizes

```yaml
# Global default (for models without per-model config)
tiling:
  tile_size: 512
  overlap: 256

models:
  - name: "small_tile_model"
    weights_path: "models/small.pt"
    type: "yolo"
    # Model trained on 512px tiles
    tile:
      tile_size: 512
      overlap: 256

  - name: "large_tile_model"
    weights_path: "models/large.pt"
    type: "yolo"
    # Model trained on 1024px tiles
    tile:
      tile_size: 1024
      overlap: 512
```

### Example 2: Different NMS Thresholds

```yaml
models:
  - name: "high_precision_model"
    weights_path: "models/precise.pt"
    type: "yolo"
    tile:
      tile_size: 512
      overlap: 256
      iou_threshold: 0.7      # Stricter NMS
      ioma_threshold: 0.65

  - name: "general_model"
    weights_path: "models/general.pt"
    type: "yolo"
    tile:
      tile_size: 512
      overlap: 256
      iou_threshold: 0.9      # Looser NMS
      ioma_threshold: 0.8
```

### Example 3: Mixed Configuration

```yaml
# Global config for models without per-model config
tiling:
  tile_size: 512
  overlap: 256
  iou_threshold: 0.8
  ioma_threshold: 0.75

models:
  - name: "model_with_custom_tiling"
    weights_path: "models/custom.pt"
    type: "yolo"
    tile:
      tile_size: 1024         # Overrides global
      overlap: 512            # Overrides global
      # Uses global iou_threshold and ioma_threshold

  - name: "model_with_global_tiling"
    weights_path: "models/global.pt"
    type: "yolo"
    # No tile config - uses global tiling settings
```

## Best Practices

### 1. Match Training Configuration

**Always match the tile size used during training:**
- Check your model's training configuration
- Use the same tile size for inference
- This ensures optimal model performance

### 2. Optimize Overlap

**Set overlap based on your use case:**
- **High precision needed**: 50% overlap (tile_size / 2)
- **Balanced**: 25% overlap (tile_size / 4)
- **Speed priority**: 12.5% overlap (tile_size / 8)

### 3. Tune NMS Thresholds

**Adjust NMS thresholds based on model behavior:**
- Models with many false positives: Lower thresholds (0.7-0.8)
- Models with few detections: Higher thresholds (0.8-0.9)
- Test and adjust based on your results

### 4. Memory Considerations

**Balance tile size with GPU memory:**
- Larger tiles = fewer tiles but more memory per tile
- Smaller tiles = more tiles but less memory per tile
- Adjust based on your GPU memory capacity

## Performance Impact

### Processing Time

- **Per-model tiling**: Each model processes its own tiles independently
- **No shared tiles**: Tiles are generated separately for each model
- **Efficient**: Only generates tiles needed for each model's configuration

### Memory Usage

- **Tile generation**: Tiles are generated on-demand per model
- **No duplication**: Each model only holds its own tiles in memory
- **Optimized**: Memory is freed after each model processes its tiles

## Troubleshooting

### Model Performance Issues

**If a model performs poorly:**
1. Check if tile size matches training configuration
2. Verify overlap is appropriate for the model
3. Adjust NMS thresholds if needed

### Memory Errors

**If you get GPU out of memory errors:**
1. Reduce tile size for the problematic model
2. Reduce batch size for that model
3. Process models sequentially instead of in parallel

### Inconsistent Results

**If results vary between runs:**
1. Ensure tiling config is consistent
2. Check that normalization_mode is appropriate
3. Verify allow_resample is set correctly

## Migration from Global Tiling

If you're upgrading from global-only tiling:

1. **No changes needed**: Existing configs continue to work
2. **Add per-model config**: Optionally add `tile:` section to models
3. **Gradual migration**: Add per-model config one model at a time

## Summary

✅ **Per-model tiling**: Each model can have its own tiling configuration

✅ **Backward compatible**: Models without per-model config use global settings

✅ **Optimal performance**: Match training tile sizes for best results

✅ **Flexible**: Mix global and per-model configurations as needed

**Key Takeaway**: Always match the tile size used during model training for optimal inference performance!

