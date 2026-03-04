# Docker Image Export/Import Guide

## Save Docker Image

### Save to Tar File

```bash
# Save the image to a tar file
docker save satellite-inference-pipeline:latest -o satellite-inference-pipeline.tar

# Or with compression (smaller file size)
docker save satellite-inference-pipeline:latest | gzip > satellite-inference-pipeline.tar.gz
```

### Save with Specific Name

```bash
# Save with custom filename
docker save satellite-inference-pipeline:latest -o inference-pipeline-backup.tar

# Save with date stamp
docker save satellite-inference-pipeline:latest -o satellite-inference-pipeline-$(date +%Y%m%d).tar
```

## Load Docker Image

### Load from Tar File

```bash
# Load uncompressed tar
docker load -i satellite-inference-pipeline.tar

# Load compressed tar.gz
gunzip -c satellite-inference-pipeline.tar.gz | docker load
# OR
docker load < satellite-inference-pipeline.tar.gz
```

## Transfer to Another Machine

### Method 1: Save and Transfer

```bash
# On source machine: Save image
docker save satellite-inference-pipeline:latest -o inference-pipeline.tar

# Transfer file (using scp, USB, network share, etc.)
scp inference-pipeline.tar user@remote-machine:/path/to/destination/

# On destination machine: Load image
docker load -i inference-pipeline.tar
```

### Method 2: Using Docker Registry

```bash
# Tag image for registry
docker tag satellite-inference-pipeline:latest your-registry.com/inference-pipeline:latest

# Push to registry
docker push your-registry.com/inference-pipeline:latest

# On another machine: Pull from registry
docker pull your-registry.com/inference-pipeline:latest
```

## Quick Commands

### Save (Windows)
```cmd
docker save satellite-inference-pipeline:latest -o inference-pipeline.tar
```

### Save (Linux/Mac with compression)
```bash
docker save satellite-inference-pipeline:latest | gzip > inference-pipeline.tar.gz
```

### Load
```bash
docker load -i inference-pipeline.tar
```

## File Size Considerations

- **Uncompressed**: ~5-10 GB (depending on image size)
- **Compressed**: ~2-4 GB (using gzip)
- **Recommendation**: Use compression to save space and transfer time

## Example Workflow

```bash
# 1. Build image
docker-compose -f docker-compose.linux.yml build

# 2. Save image
docker save satellite-inference-pipeline:latest | gzip > inference-pipeline-$(date +%Y%m%d).tar.gz

# 3. Transfer to another machine
scp inference-pipeline-20251127.tar.gz user@remote:/path/

# 4. On remote machine: Load image
gunzip -c inference-pipeline-20251127.tar.gz | docker load
# OR
docker load < inference-pipeline-20251127.tar.gz

# 5. Verify image loaded
docker images | grep inference-pipeline
```

## Notes

- Saved images include all layers and metadata
- Can be loaded on any Docker-compatible system
- Preserves image tags and history
- Useful for offline deployments or backup

