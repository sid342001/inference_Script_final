# Satellite Inference Pipeline Dashboard

A real-time web dashboard for monitoring the Satellite Inference Pipeline status, queue, GPU utilization, workers, and recent jobs.

## Features

- **Real-time Status**: Auto-refreshing dashboard with live pipeline metrics
- **Queue Monitoring**: View pending, processing, completed, and quarantined jobs
- **GPU Utilization**: Monitor GPU usage across all devices with visual progress bars
- **Worker Status**: See which worker threads are alive and active
- **Recent Jobs**: Browse the most recent job completions with details
- **Auto-refresh**: Configurable automatic updates (default: every 5 seconds)

## Quick Start

### Option 1: Simple Start (Default Paths)

```bash
# Windows
python dashboard_server.py

# Linux/Mac
python3 dashboard_server.py
```

Or use the convenience scripts:
```bash
# Windows
start_dashboard.bat

# Linux/Mac
chmod +x start_dashboard.sh
./start_dashboard.sh
```

The dashboard will be available at: **http://localhost:8080**

### Option 2: Custom Configuration

If your pipeline is running with custom paths, specify them:

```bash
python dashboard_server.py \
    --health-path artifacts/health/status.json \
    --artifacts-dir artifacts \
    --port 8080
```

### Option 3: Auto-detect from Config

If you have a pipeline config file:

```bash
python dashboard_server.py \
    --config config/pipeline.yaml \
    --port 8080
```

The server will automatically read the health path and artifacts directory from the config.

## Usage

1. **Start the Pipeline**: Make sure your inference pipeline is running
   ```bash
   python scripts/run_pipeline.py --config config/pipeline.yaml
   ```

2. **Start the Dashboard**: In another terminal
   ```bash
   python dashboard_server.py
   ```

3. **Open in Browser**: Navigate to http://localhost:8080

## Dashboard Sections

### Queue Status
- **Total Jobs**: Total number of jobs processed
- **Completed**: Successfully finished jobs
- **Processing**: Currently active jobs
- **Pending**: Jobs waiting in queue
- **Quarantined**: Jobs that failed after retries
- **Completion Rate**: Visual progress bar showing overall completion percentage

### GPU Utilization
- Real-time GPU usage percentage for each CUDA device
- Color-coded indicators:
  - Green (>70%): High utilization
  - Yellow (30-70%): Moderate utilization
  - Gray (<30%): Low utilization

### Workers
- List of all worker threads
- Status indicators (Alive/Dead)
- Shows which workers are actively processing jobs

### Recent Jobs
- Last 20 completed or active jobs
- Job ID, image path, status, duration
- Processing time and model information

## API Endpoints

The dashboard server provides REST API endpoints:

- `GET /` or `GET /dashboard.html` - Serves the HTML dashboard
- `GET /api/status` - Returns current pipeline status (queue, GPU, workers)
- `GET /api/recent-jobs` - Returns list of recent jobs from manifests

### Example: Get Status via API

```bash
curl http://localhost:8080/api/status
```

Response:
```json
{
  "timestamp": 1234567890.123,
  "queue": {
    "total": 100,
    "pending": 5,
    "processing": 2,
    "completed": 90,
    "quarantined": 3
  },
  "gpu": {
    "cuda:0": 0.75,
    "cuda:1": 0.82
  },
  "workers": {
    "worker_0": {"alive": true},
    "worker_1": {"alive": true}
  }
}
```

## Configuration

### Command Line Options

```
--port PORT          Port to serve dashboard on (default: 8080)
--host HOST          Host to bind to (default: localhost)
--health-path PATH   Path to health status JSON file
--artifacts-dir DIR  Path to artifacts directory
--config PATH        Path to pipeline config YAML
```

### Changing Refresh Interval

Edit `dashboard.html` and modify the `REFRESH_INTERVAL` constant:

```javascript
const REFRESH_INTERVAL = 5000; // Change to desired milliseconds
```

## Troubleshooting

### Dashboard shows "Error loading status"

- **Check if pipeline is running**: The dashboard needs the health JSON file to be updated
- **Verify health path**: Make sure `--health-path` points to the correct location
- **Check file permissions**: Ensure the dashboard server can read the health file

### No recent jobs shown

- **Check manifests directory**: Recent jobs are read from `artifacts/success/manifests/`
- **Verify artifacts path**: Ensure `--artifacts-dir` is correct
- **Jobs may not have completed yet**: Only completed jobs appear in recent jobs

### GPU utilization shows 0%

- **GPU may not be in use**: If no jobs are processing, GPU will be idle
- **CUDA not available**: Check if PyTorch can access CUDA devices
- **Models not loaded**: Ensure models are assigned to GPUs in config

### Dashboard doesn't auto-refresh

- **Check browser console**: Look for JavaScript errors
- **Verify auto-refresh toggle**: Make sure it's enabled (should be on by default)
- **Check network tab**: Ensure API requests are succeeding

## Advanced Usage

### Custom Port

```bash
python dashboard_server.py --port 9000
```

### Access from Remote Machine

```bash
python dashboard_server.py --host 0.0.0.0 --port 8080
```

Then access from any machine on the network: `http://<server-ip>:8080`

### Integration with Monitoring Tools

The API endpoints can be consumed by external monitoring tools:

```bash
# Prometheus-style metrics
watch -n 5 'curl -s http://localhost:8080/api/status | jq .queue'

# Grafana data source
# Use JSON API data source pointing to http://localhost:8080/api/status
```

## Requirements

- Python 3.8+
- Running Satellite Inference Pipeline
- Modern web browser (Chrome, Firefox, Safari, Edge)

No additional Python packages required - uses only standard library!

