# Docker Configuration Guide

## Overview

The Docker setup provides **maximum flexibility** for configuration management. You can edit the config from outside Docker without rebuilding the image.

---

## How It Works

### Config Priority System

The container uses a **two-tier config system**:

1. **User Config** (Highest Priority)
   - Location: `config/pipeline.yaml` (on your host)
   - Mounted into container at `/app/config/pipeline.yaml`
   - **Editable from outside Docker** - just edit the file on your host
   - Changes take effect on container restart

2. **Default Config** (Fallback)
   - Location: `config/pipeline.yaml.default` (inside image)
   - Shipped with the Docker image
   - Used if user config doesn't exist
   - **Not editable** (read-only in image)

### Entrypoint Script

The `docker-entrypoint.sh` script automatically:
- Checks for user-mounted `config/pipeline.yaml`
- Falls back to default if not found
- Validates config file exists and is readable
- Starts pipeline with selected config

---

## Usage Scenarios

### Scenario 1: Use Default Config (Quick Start)

**No action needed!**

```bash
# Just build and run
docker-compose build
docker-compose up -d
```

The default config will be used automatically. It's pre-configured with Docker paths (`/app/` prefix).

### Scenario 2: Customize Config (Recommended)

**Step 1**: Create/edit `config/pipeline.yaml` on your host:

```yaml
watcher:
  input_dir: "/app/data/incoming"

artifacts:
  success_dir: "/app/artifacts/success"
  # ... customize as needed
```

**Step 2**: Build and run (config is automatically mounted):

```bash
docker-compose build
docker-compose up -d
```

**Step 3**: Edit config anytime:

```bash
# Edit config on host
nano config/pipeline.yaml

# Restart container to apply changes
docker-compose restart
```

### Scenario 3: Multiple Configs

You can have different configs for different environments:

```bash
# Development config
cp config/pipeline.yaml config/pipeline.dev.yaml

# Production config  
cp config/pipeline.yaml config/pipeline.prod.yaml

# Use specific config by mounting it
docker run -v $(pwd)/config/pipeline.prod.yaml:/app/config/pipeline.yaml ...
```

---

## Config File Locations

### Inside Container

```
/app/config/
├── pipeline.yaml          # User config (if mounted)
└── pipeline.yaml.default  # Default config (shipped with image)
```

### On Host (Your Machine)

```
inference_Script/
└── config/
    ├── pipeline.yaml          # Your custom config (optional)
    └── pipeline.yaml.docker   # Source for default config (in repo)
```

---

## Editing Config from Outside Docker

### Method 1: Direct File Edit

```bash
# Edit config on host
vim config/pipeline.yaml
# or
nano config/pipeline.yaml
# or use any editor

# Restart container to apply
docker-compose restart
```

### Method 2: Copy from Default

```bash
# Start container to extract default config
docker run --rm satellite-inference-pipeline:latest cat /app/config/pipeline.yaml.default > config/pipeline.yaml

# Edit the copied file
vim config/pipeline.yaml

# Run with your config
docker-compose up -d
```

### Method 3: Use Environment Variables (Future Enhancement)

Currently, config is YAML-based. Environment variable support can be added if needed.

---

## Important: Path Configuration

### All paths must use `/app/` prefix (Docker container paths)

**Correct (Docker paths):**
```yaml
watcher:
  input_dir: "/app/data/incoming"

artifacts:
  success_dir: "/app/artifacts/success"
  failure_dir: "/app/artifacts/failure"
```

**Incorrect (Host paths):**
```yaml
watcher:
  input_dir: "D:/aks/sat-annotator-main/inference_Script/data/incoming"  # ❌ Wrong!
```

### Path Mapping

| Container Path | Host Path (via volume mount) |
|----------------|------------------------------|
| `/app/data/incoming` | `./data/incoming` |
| `/app/artifacts` | `./artifacts` |
| `/app/state` | `./state` |
| `/app/logs` | `./logs` |
| `/app/models` | `./models` |
| `/app/config` | `./config` |

---

## Default Config Contents

The default config (`pipeline.yaml.default`) includes:

- ✅ Docker-optimized paths (`/app/` prefix)
- ✅ Sensible defaults for all settings
- ✅ Dashboard configured to listen on `0.0.0.0:8092`
- ✅ GPU configuration template
- ✅ Model configuration template

**You can view it:**
```bash
# View default config
docker run --rm satellite-inference-pipeline:latest cat /app/config/pipeline.yaml.default

# Or extract it
docker run --rm satellite-inference-pipeline:latest cat /app/config/pipeline.yaml.default > config/pipeline.yaml.default
```

---

## Verification

### Check Which Config is Being Used

```bash
# View container logs
docker-compose logs | grep "Using"

# Should show:
# ✓ Using user-provided config: /app/config/pipeline.yaml
# OR
# ✓ Using default config: /app/config/pipeline.yaml.default
```

### Verify Config is Mounted

```bash
# Check if config exists in container
docker exec inference-pipeline ls -la /app/config/

# Should show:
# pipeline.yaml (if you mounted one)
# pipeline.yaml.default (always present)
```

### Test Config Changes

```bash
# 1. Edit config
echo "test: true" >> config/pipeline.yaml

# 2. Restart container
docker-compose restart

# 3. Check logs to see if change is detected
docker-compose logs -f
```

---

## Best Practices

### 1. **Version Control Your Config**

```bash
# Keep your custom config in git
git add config/pipeline.yaml
git commit -m "Add custom pipeline config"
```

### 2. **Use Different Configs for Environments**

```bash
# Development
config/pipeline.dev.yaml

# Production
config/pipeline.prod.yaml

# Mount specific one
docker run -v $(pwd)/config/pipeline.prod.yaml:/app/config/pipeline.yaml ...
```

### 3. **Backup Config Before Changes**

```bash
cp config/pipeline.yaml config/pipeline.yaml.backup
```

### 4. **Validate Config Syntax**

```bash
# Test config is valid YAML
python -c "import yaml; yaml.safe_load(open('config/pipeline.yaml'))"
```

---

## Troubleshooting

### Config Not Found Error

**Error**: `Error: Configuration file not found`

**Solution**:
- Ensure `config/` directory exists
- Check volume mount in docker-compose.yml
- Verify config file permissions

### Config Changes Not Applied

**Symptom**: Changes to config don't take effect

**Solution**:
- Restart container: `docker-compose restart`
- Check which config is being used in logs
- Verify file is actually mounted

### Path Errors

**Error**: `File not found` or path-related errors

**Solution**:
- Ensure all paths use `/app/` prefix
- Check volume mounts in docker-compose.yml
- Verify directories exist on host

---

## Summary

✅ **Default config** shipped with image (works out of the box)  
✅ **User config** can override default (mount `config/pipeline.yaml`)  
✅ **Editable from outside** - no rebuild needed  
✅ **Automatic selection** - entrypoint script handles it  
✅ **Flexible** - use different configs for different environments  

The config system is designed to be **user-friendly** and **flexible**, allowing you to customize the pipeline without rebuilding Docker images.

