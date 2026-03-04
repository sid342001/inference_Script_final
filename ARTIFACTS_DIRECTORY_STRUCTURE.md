# Artifacts Directory Structure

This document explains the new centralized artifact directories that are automatically created and populated.

## Overview

The pipeline now maintains three additional centralized directories in addition to the per-image output structure:

1. **`combined_inferences_dir`**: All combined GeoJSON files from all processed images
2. **`daily_logs_dir`**: Daily logs organized by date (YYYY-MM-DD)
3. **`model_outputs_dir`**: All per-model outputs (GeoJSONs and CSVs) from all images

## Directory Structure

```
artifacts/
├── success/                          # Per-image outputs (existing)
│   └── image1_abc12345/
│       ├── image1.tif
│       ├── image1_combined.geojson
│       ├── image1_Yolo_plane_x.geojson
│       ├── image1_Yolo_plane_x.csv
│       └── image1.log
│
├── failure/                          # Failed job outputs (existing)
│   └── image2_def67890/
│       ├── image2.tif
│       └── image2.log
│
├── combined_inferences/              # NEW: All combined GeoJSON files
│   ├── image1_combined.geojson
│   ├── image2_combined.geojson
│   ├── image3_combined.geojson
│   └── ...
│
├── daily_logs/                       # NEW: Daily logs organized by date
│   ├── 2025-01-15/
│   │   ├── image1.log
│   │   ├── image2.log
│   │   └── image3.log
│   ├── 2025-01-16/
│   │   ├── image4.log
│   │   └── image5.log
│   └── ...
│
└── model_outputs/                    # NEW: All per-model outputs
    ├── image1_Yolo_plane_x.geojson
    ├── image1_Yolo_plane_x.csv
    ├── image1_yolo_obb.geojson
    ├── image1_yolo_obb.csv
    ├── image2_Yolo_plane_x.geojson
    ├── image2_Yolo_plane_x.csv
    └── ...
```

## Configuration

Add these directories to your `pipeline.yaml`:

```yaml
artifacts:
  success_dir: "artifacts/success"
  failure_dir: "artifacts/failure"
  combined_inferences_dir: "artifacts/combined_inferences"    # NEW
  daily_logs_dir: "artifacts/daily_logs"                       # NEW
  model_outputs_dir: "artifacts/model_outputs"                 # NEW
  temp_dir: "artifacts/tmp"
  manifest_format: "json"
  preview_format: "png"
```

**Note**: If not specified, these directories will be created with default paths:
- `combined_inferences_dir`: `artifacts/combined_inferences`
- `daily_logs_dir`: `artifacts/daily_logs`
- `model_outputs_dir`: `artifacts/model_outputs`

## Directory Details

### 1. Combined Inferences Directory

**Path**: `artifacts/combined_inferences/` (configurable)

**Contents**: All combined GeoJSON files from all successfully processed images.

**File Naming**: `{image_stem}_combined.geojson`

**Example Files**:
- `airport_image_combined.geojson`
- `satellite_2025_combined.geojson`
- `region_A_combined.geojson`

**Use Cases**:
- Quick access to all combined detections
- Aggregating results across multiple images
- Analysis of all detections in one place

### 2. Daily Logs Directory

**Path**: `artifacts/daily_logs/` (configurable)

**Contents**: All processing logs organized by date.

**Structure**: 
```
daily_logs/
  └── YYYY-MM-DD/          # Date folder
      └── {image_stem}.log  # Log file
```

**Example Structure**:
```
daily_logs/
  ├── 2025-01-15/
  │   ├── airport_image.log
  │   ├── satellite_2025.log
  │   └── region_A.log
  ├── 2025-01-16/
  │   ├── airport_image.log
  │   └── satellite_2025.log
  └── 2025-01-17/
      └── region_B.log
```

**Use Cases**:
- Review logs for a specific day
- Track processing history over time
- Debug issues by date
- Archive logs by date

**Note**: Logs are written in real-time to both:
- Per-image log file (in `success_dir` or `failure_dir`)
- Daily log file (in `daily_logs_dir/YYYY-MM-DD/`)

### 3. Model Outputs Directory

**Path**: `artifacts/model_outputs/` (configurable)

**Contents**: All per-model outputs (GeoJSON and CSV files) from all processed images.

**File Naming**: 
- GeoJSON: `{image_stem}_{model_name}.geojson`
- CSV: `{image_stem}_{model_name}.csv`

**Example Files**:
```
model_outputs/
  ├── airport_image_Yolo_plane_x.geojson
  ├── airport_image_Yolo_plane_x.csv
  ├── airport_image_yolo_obb.geojson
  ├── airport_image_yolo_obb.csv
  ├── satellite_2025_Yolo_plane_x.geojson
  ├── satellite_2025_Yolo_plane_x.csv
  └── ...
```

**Use Cases**:
- Compare model performance across images
- Aggregate results by model
- Analyze specific model outputs
- Generate model-specific reports

## Automatic Creation

All three directories are **automatically created** when the pipeline starts. You don't need to create them manually.

## File Copying

Files are copied (not moved) to the centralized directories. This means:
- ✅ Original files remain in per-image directories
- ✅ Centralized directories contain copies for easy access
- ✅ No data loss if centralized directories are cleaned

## Performance

- **Minimal Impact**: File copying happens after processing completes
- **Non-Blocking**: Copying failures don't affect job success
- **Efficient**: Uses `shutil.copy2()` for fast file operations

## Error Handling

If copying to centralized directories fails:
- ⚠️ Warning is logged
- ✅ Job still completes successfully
- ✅ Original files remain in per-image directories

## Best Practices

1. **Regular Cleanup**: Consider archiving old daily logs periodically
2. **Disk Space**: Monitor disk usage as centralized directories grow
3. **Backup**: Include centralized directories in backup strategy
4. **Analysis**: Use centralized directories for batch analysis scripts

## Example Usage

### Access All Combined Inferences

```python
from pathlib import Path
import json

combined_dir = Path("artifacts/combined_inferences")
for geojson_file in combined_dir.glob("*.geojson"):
    with open(geojson_file) as f:
        data = json.load(f)
        print(f"{geojson_file.name}: {len(data['features'])} detections")
```

### Get Logs for a Specific Date

```python
from pathlib import Path

date = "2025-01-15"
daily_logs_dir = Path("artifacts/daily_logs") / date

for log_file in daily_logs_dir.glob("*.log"):
    print(f"Processing log: {log_file.name}")
    # Read and analyze log
```

### Aggregate Model Outputs

```python
from pathlib import Path
import json

model_name = "Yolo_plane_x"
model_outputs_dir = Path("artifacts/model_outputs")

all_detections = []
for geojson_file in model_outputs_dir.glob(f"*_{model_name}.geojson"):
    with open(geojson_file) as f:
        data = json.load(f)
        all_detections.extend(data['features'])

print(f"Total detections from {model_name}: {len(all_detections)}")
```

## Migration

If you're upgrading from an older version:
1. New directories will be created automatically
2. Existing per-image outputs remain unchanged
3. New processing jobs will populate centralized directories
4. Old jobs won't be copied retroactively (only new jobs)

