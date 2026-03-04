# Fix: Watchdog Not Detecting Files in Docker Volumes

## Problem

When files are copied to the host directory (`D:\aks\sat-annotator-main\inference_Script\docker_data\scheduled`), they appear in the Docker volume (`/app/data/incoming`), but watchdog doesn't detect them.

## Root Cause

**Docker bind mounts don't propagate inotify events properly.**

- Watchdog uses `inotify` (Linux) or `ReadDirectoryChangesW` (Windows) to detect file changes
- These events are generated on the **host filesystem**
- Docker bind mounts create a **separate filesystem view** in the container
- File system events from the host **don't propagate** to the container's inotify watchers
- Result: Watchdog never sees the file creation events

## Solution Applied

Added automatic Docker detection and forced polling mode when running in Docker:

1. **Docker Detection**: Checks for:
   - `/.dockerenv` file (standard Docker indicator)
   - `container=docker` environment variable
   - Docker-style paths (`/app/`, `/mnt/`)
   - `FORCE_POLLING` environment variable

2. **Automatic Fallback**: When Docker is detected, automatically uses polling mode instead of watchdog

3. **Polling Mode**: Scans the directory periodically (every `poll_interval_seconds`) and detects new files by comparing against previously seen files

## Changes Made

### watcher.py

1. Added `os` import for environment variable checking
2. Added `_should_use_polling()` method to detect Docker environment
3. Modified `start()` to check for Docker and force polling mode

### How It Works Now

```python
def _should_use_polling(self) -> bool:
    # Check FORCE_POLLING env var
    if os.environ.get("FORCE_POLLING"):
        return True
    
    # Check if in Docker
    if os.path.exists("/.dockerenv"):
        return True
    
    # Check Docker container indicator
    if os.environ.get("container") == "docker":
        return True
    
    # Check for Docker-style paths
    if input_dir.startswith("/app/"):
        return True
```

## Testing

### Test 1: Verify Polling Mode is Active

Check logs when pipeline starts:
```
Starting watcher on /app/data/incoming
Forcing polling mode (Docker volume detected or FORCE_POLLING env var set)
```

### Test 2: Copy a File

1. Copy an image to: `D:\aks\sat-annotator-main\inference_Script\docker_data\scheduled\test.tif`
2. Wait up to `poll_interval_seconds` (default: 30 seconds)
3. Check logs for: `Detected new imagery file: /app/data/incoming/test.tif`

### Test 3: Adjust Poll Interval (If Needed)

If 30 seconds is too slow, edit your `pipeline.yaml`:

```yaml
watcher:
  poll_interval_seconds: 10  # Check every 10 seconds instead of 30
```

## Manual Override

If you want to force polling mode even outside Docker, set environment variable:

```bash
# In docker-compose.yml
environment:
  - FORCE_POLLING=1
```

Or in Dockerfile:
```dockerfile
ENV FORCE_POLLING=1
```

## Why Polling Works in Docker

- **Polling**: Actively scans the directory by listing files
- **Works with bind mounts**: Doesn't rely on file system events
- **Reliable**: Always finds files, just with a small delay (poll_interval_seconds)
- **Trade-off**: Slightly higher CPU usage, but guaranteed to work

## Performance Considerations

- **Poll Interval**: Default 30 seconds is a good balance
  - Too short (5s): Higher CPU usage
  - Too long (60s): Slower file detection
  - Recommended: 10-30 seconds for most use cases

- **Settle Time**: Default 10 seconds ensures files are fully copied
  - Large files might need more time
  - Adjust `settle_time_seconds` if files are being detected while still copying

## Expected Behavior

### Before Fix:
- File copied to host directory ✅
- File visible in container ✅
- Watchdog detects file ❌
- File never processed ❌

### After Fix:
- File copied to host directory ✅
- File visible in container ✅
- Polling detects file ✅ (within poll_interval_seconds)
- File processed ✅

## Verification Commands

```bash
# Check if polling mode is active
docker logs inference-pipeline | grep -i "polling\|watchdog"

# Check if files are being detected
docker logs inference-pipeline | grep -i "detected new imagery"

# Monitor in real-time
docker logs -f inference-pipeline | grep -i watcher
```

## Summary

The fix automatically detects Docker environments and uses polling mode instead of watchdog, ensuring files are detected reliably in Docker volume mounts. This is a known limitation of Docker bind mounts, and polling is the standard solution.

