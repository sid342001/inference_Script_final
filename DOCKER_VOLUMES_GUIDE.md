# Docker Volumes & File Access Guide

## Overview

All directories are mounted as **read-write**, giving you full access to edit, add, and remove files from outside Docker.

---

## Volume Mounts

All directories are accessible and editable from your host machine:

| Host Directory | Container Path | Access Level | What You Can Do |
|----------------|----------------|--------------|-----------------|
| `./data/incoming` | `/app/data/incoming` | **Read-Write** | ✅ Add/remove input images<br>✅ Organize files<br>✅ Edit metadata |
| `./artifacts` | `/app/artifacts` | **Read-Write** | ✅ View outputs<br>✅ Copy/move results<br>✅ Delete old outputs<br>✅ Modify GeoJSON files |
| `./state` | `/app/state` | **Read-Write** | ✅ Inspect queue state<br>✅ Clear cache<br>✅ Manage quarantine<br>✅ Backup/restore state |
| `./logs` | `/app/logs` | **Read-Write** | ✅ View logs<br>✅ Archive old logs<br>✅ Delete logs<br>✅ Monitor in real-time |
| `./models` | `/app/models` | **Read-Write** | ✅ Add new models<br>✅ Remove models<br>✅ Update model files<br>✅ Organize models |
| `./config` | `/app/config` | **Read-Write** | ✅ Edit configuration<br>✅ Create custom configs<br>✅ Version control configs |

---

## Common Operations

### 1. **Add Input Images**

```bash
# Copy images to input directory
cp /path/to/image.tif ./data/incoming/

# Or move them
mv /path/to/image.tif ./data/incoming/

# Pipeline will automatically detect and process them
```

### 2. **Access Outputs**

```bash
# View successful outputs
ls ./artifacts/success/

# View failed outputs
ls ./artifacts/failure/

# Each image has its own folder with all outputs
ls ./artifacts/success/image_name/
# Contains:
# - Combined GeoJSON
# - Per-model GeoJSONs
# - Per-model CSVs
# - Logs
# - Original image
```

### 3. **Edit Configuration**

```bash
# Edit config file
nano ./config/pipeline.yaml

# Or use any editor
code ./config/pipeline.yaml

# Restart container to apply changes
docker-compose restart
```

### 4. **Manage Models**

```bash
# Add new model
cp /path/to/new_model.pt ./models/

# Remove model
rm ./models/old_model.pt

# Update model (replace file)
cp /path/to/updated_model.pt ./models/existing_model.pt
```

### 5. **Inspect State**

```bash
# View queue state
cat ./state/queue.json

# Clear cache
rm -rf ./state/tile_cache/*

# Check quarantine
ls ./state/quarantine/
```

### 6. **View Logs**

```bash
# View pipeline logs
tail -f ./logs/pipeline/pipeline.log

# View specific image logs
cat ./logs/pipeline/images/image_name.log

# Archive old logs
tar -czf logs_backup.tar.gz ./logs/
```

---

## File Permissions

### On Linux/Mac

Files created by the container will typically be owned by root. To fix permissions:

```bash
# Fix ownership (replace $USER with your username)
sudo chown -R $USER:$USER ./artifacts ./state ./logs

# Or set permissions
chmod -R 755 ./artifacts ./state ./logs
```

### On Windows

Permissions are usually handled automatically. If you encounter issues:

1. Ensure Docker Desktop has access to the drive
2. Check Windows file permissions
3. Run Docker Desktop as administrator if needed

---

## Best Practices

### 1. **Organize Input Images**

```bash
# Create subdirectories for organization
mkdir -p ./data/incoming/2024/01/
mkdir -p ./data/incoming/2024/02/

# Move images accordingly
mv ./data/incoming/image1.tif ./data/incoming/2024/01/
```

### 2. **Backup Important Data**

```bash
# Backup artifacts
tar -czf artifacts_backup_$(date +%Y%m%d).tar.gz ./artifacts/

# Backup state
tar -czf state_backup_$(date +%Y%m%d).tar.gz ./state/

# Backup config
cp ./config/pipeline.yaml ./config/pipeline.yaml.backup
```

### 3. **Clean Up Old Data**

```bash
# Remove old outputs (be careful!)
find ./artifacts/success -mtime +30 -type d -exec rm -rf {} \;

# Clear old logs
find ./logs -mtime +7 -type f -delete

# Clear cache
rm -rf ./state/tile_cache/*
```

### 4. **Monitor Disk Space**

```bash
# Check directory sizes
du -sh ./artifacts/* ./state/* ./logs/*

# Find large files
find ./artifacts -type f -size +100M
```

---

## Accessing Files from Container

You can also access files from inside the container:

```bash
# Enter container shell
docker exec -it inference-pipeline bash

# Navigate to directories
cd /app/artifacts
ls -la

# View files
cat /app/state/queue.json

# Exit container
exit
```

---

## Troubleshooting

### Permission Denied Errors

**Symptom**: Cannot write to mounted directories

**Solution**:
```bash
# Fix permissions (Linux/Mac)
sudo chown -R $USER:$USER ./artifacts ./state ./logs

# Or run container with your user ID
docker run --user $(id -u):$(id -g) ...
```

### Files Not Visible

**Symptom**: Files created in container not visible on host

**Solution**:
- Ensure volume mounts are correct in docker-compose.yml
- Check file permissions
- Restart container: `docker-compose restart`

### Disk Space Issues

**Symptom**: Container runs out of space

**Solution**:
```bash
# Check disk usage
docker system df

# Clean up old containers/images
docker system prune

# Clean up specific volumes
docker volume prune
```

---

## Summary

✅ **All directories are read-write** - full access from host  
✅ **Edit files directly** - no need to enter container  
✅ **Add/remove files** - manage inputs and outputs easily  
✅ **Inspect state** - view queue, cache, logs  
✅ **Backup/restore** - full control over data  

The read-write access gives you complete control over all pipeline data and configuration from your host machine.

