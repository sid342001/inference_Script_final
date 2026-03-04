# Solutions: Using Watchdog in Docker Instead of Polling

## The Problem

Docker bind mounts don't propagate inotify events from host to container, so watchdog can't detect file changes. However, there are several workarounds:

## Solution 1: Sidecar Container (Recommended)

Run a separate container that watches the **host directory** and sends notifications to the main container.

### Architecture:
```
Host Directory → Sidecar Container (watches host) → Main Container (processes files)
```

### Implementation:

**docker-compose.yml addition:**
```yaml
services:
  file-watcher:
    image: alpine:latest
    container_name: inference-file-watcher
    volumes:
      - D:\aks\sat-annotator-main\inference_Script\docker_data\scheduled:/watch:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: >
      sh -c "
      apk add --no-cache inotify-tools &&
      while true; do
        inotifywait -r -e create,moved_to /watch --format '%w%f' |
        while read file; do
          docker exec inference-pipeline touch /app/data/incoming/.trigger
        done
      done
      "
    restart: unless-stopped
```

**Limitation**: Requires Docker socket access (security consideration)

## Solution 2: Use Docker Named Volumes (May Work)

Named volumes sometimes work better with inotify than bind mounts.

### Change docker-compose.yml:
```yaml
services:
  inference-pipeline:
    volumes:
      # Instead of bind mount, use named volume
      - inference-data:/app/data/incoming
      # Copy files into volume from host
      - D:\aks\sat-annotator-main\inference_Script\docker_data\scheduled:/host-data:ro

volumes:
  inference-data:
```

**Then use a sidecar to copy files:**
```yaml
  file-copier:
    image: alpine:latest
    volumes:
      - D:\aks\sat-annotator-main\inference_Script\docker_data\scheduled:/source:ro
      - inference-data:/dest
    command: >
      sh -c "
      apk add --no-cache rsync inotify-tools &&
      while inotifywait -r -e create,moved_to /source; do
        rsync -av /source/ /dest/
      done
      "
```

## Solution 3: API/Webhook Approach

Expose an API endpoint to trigger file processing instead of watching.

### Add to orchestrator.py:
```python
# Add HTTP endpoint to manually trigger file scan
from flask import Flask, request
app = Flask(__name__)

@app.route('/trigger-scan', methods=['POST'])
def trigger_scan():
    # Force immediate directory scan
    self.watcher._polling_loop()  # or trigger watchdog scan
    return {"status": "scan triggered"}
```

### Usage:
```bash
# When file is copied, call API
curl -X POST http://localhost:8092/trigger-scan
```

## Solution 4: Message Queue (RabbitMQ/Redis)

Use a message queue where file events are published.

### Architecture:
```
Host Script → Publishes to Queue → Container subscribes → Processes file
```

## Solution 5: Hybrid: Fast Polling with Watchdog Fallback

Use very fast polling (1-2 seconds) but keep watchdog as primary when possible.

### Modify watcher.py:
```python
def _should_use_polling(self) -> bool:
    # Allow watchdog in Docker if explicitly enabled
    if os.environ.get("USE_WATCHDOG_IN_DOCKER", "").lower() in ("1", "true", "yes"):
        return False  # Try watchdog even in Docker
    
    # ... rest of detection logic
```

### Then test if it works:
```yaml
# docker-compose.yml
environment:
  - USE_WATCHDOG_IN_DOCKER=1
```

**Note**: This might work on some Linux systems but likely won't work on Windows.

## Solution 6: Host-Side Watcher Script

Run a Python script on the **host** that watches the directory and calls the container API.

### host-watcher.py (run on host):
```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import requests
import time

class Handler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(('.tif', '.tiff', '.jp2', '.img')):
            # Notify container via API
            requests.post('http://localhost:8092/trigger-scan')
            print(f"Notified container about: {event.src_path}")

observer = Observer()
observer.schedule(Handler(), 'D:\\aks\\sat-annotator-main\\inference_Script\\docker_data\\scheduled', recursive=True)
observer.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()
observer.join()
```

## Solution 7: Use PollingObserver (Watchdog's Polling Backend)

Watchdog has a `PollingObserver` that uses polling but provides the same API as watchdog.

### Modify watcher.py:
```python
from watchdog.observers import Observer, PollingObserver

def _start_watchdog(self) -> None:
    handler = _WatchdogHandler(self)
    
    # Use PollingObserver in Docker for better compatibility
    if self._should_use_polling():
        observer = PollingObserver(timeout=self.config.watcher.poll_interval_seconds)
        logger.info("Using PollingObserver (polling-based but watchdog API)")
    else:
        observer = Observer()
        logger.info("Using Observer (event-based)")
    
    observer.schedule(handler, str(self.config.watcher.input_dir), recursive=self.config.watcher.recursive)
    observer.start()
    self._observer = observer
```

**This gives you:**
- Same API as watchdog
- Works in Docker
- Still uses polling, but with watchdog's interface

## Recommended Approach

**For your use case, I recommend Solution 7 (PollingObserver)** because:
1. ✅ Uses watchdog API (consistent interface)
2. ✅ Works reliably in Docker
3. ✅ No additional containers needed
4. ✅ Easy to implement
5. ✅ Can still use event-based Observer when not in Docker

## Implementation: PollingObserver

Let me implement this for you - it's the best balance between watchdog API and Docker compatibility.

