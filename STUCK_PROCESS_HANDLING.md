# Stuck Process Handling - What Happens When Jobs Hang

## Overview

The pipeline has built-in timeout mechanisms to prevent jobs from hanging indefinitely. This document explains what happens when a process gets stuck.

## Timeout Configuration

**Default Timeout**: 3600 seconds (1 hour)

Configure in `pipeline.yaml`:
```yaml
workers:
  job_timeout_seconds: 3600   # Maximum time per job (1 hour)
```

**Recommendations**:
- **Small images**: `1800` seconds (30 minutes)
- **Medium images**: `3600` seconds (1 hour) - default
- **Very large images**: `7200` seconds (2 hours)

## What Happens When a Job Gets Stuck

### 1. Timeout Detection

The pipeline uses a **threading-based timeout mechanism**:

```python
# Job runs in a separate thread
# Main thread waits for completion with timeout
thread.join(timeout=timeout_seconds)
```

### 2. Timeout Behavior

When a job exceeds the timeout:

1. **Timeout Detected**: After `job_timeout_seconds`, the main thread detects the timeout
2. **TimeoutError Raised**: A `TimeoutError` exception is raised
3. **Job Marked as Failed**: The job is immediately marked as failed
4. **No Retry**: Timeout errors are **NOT retried** (they're likely to fail again)
5. **Quarantine**: After max retries, the job is moved to quarantine
6. **Worker Continues**: The worker thread may continue processing in the background (but job is considered failed)

### 3. Error Handling Flow

```
Job Starts Processing
    ↓
Timeout Timer Starts (job_timeout_seconds)
    ↓
Job Processing...
    ↓
[If timeout exceeded]
    ↓
TimeoutError Raised
    ↓
Job Marked as Failed
    ↓
Error Logged
    ↓
Image Moved to Failure Directory
    ↓
Job Moved to Quarantine (if max retries exceeded)
```

## Important Notes

### ⚠️ Thread May Continue

**Important**: The worker thread processing the job may **continue running in the background** even after the timeout. The timeout mechanism:
- ✅ Prevents the pipeline from waiting forever
- ✅ Allows other jobs to continue processing
- ⚠️ Does NOT forcefully kill the stuck thread (Python limitation)

### What This Means

- **Pipeline continues**: Other jobs can still be processed
- **Worker available**: The worker thread becomes available for new jobs after timeout
- **Background processing**: The stuck job may continue consuming resources in background
- **No data corruption**: The job is marked as failed, so outputs won't be trusted

## Monitoring Stuck Jobs

### Check Logs

Look for timeout messages in logs:
```
ERROR | job-worker-0 | orchestrator | Job abc123 timed out after 3600 seconds
```

### Check Health Status

View `artifacts/health/status.json`:
```json
{
  "queue": {
    "pending": 0,
    "processing": 1,  // Stuck job may show here
    "completed": 10,
    "failed": 1
  }
}
```

### Check Queue State

View `state/queue.json`:
```json
[
  {
    "job_id": "abc123",
    "status": "processing",  // Stuck job
    "last_error": "Job processing exceeded timeout of 3600 seconds",
    "retries": 0
  }
]
```

## Common Causes of Stuck Jobs

### 1. Very Large Images
- **Symptom**: Job takes longer than timeout
- **Solution**: Increase `job_timeout_seconds`

### 2. GPU Memory Issues
- **Symptom**: GPU runs out of memory, processing hangs
- **Solution**: Reduce `batch_size` or `max_concurrent_jobs`

### 3. Corrupted Image Files
- **Symptom**: GDAL hangs trying to read corrupted file
- **Solution**: Check image file integrity before processing

### 4. Network Issues (if using network storage)
- **Symptom**: File I/O hangs
- **Solution**: Check network connectivity, use local storage

### 5. Model Loading Issues
- **Symptom**: Model fails to load, hangs
- **Solution**: Check model file integrity, GPU availability

## How to Handle Stuck Jobs

### Option 1: Wait for Timeout (Recommended)

Let the timeout mechanism handle it:
- Job will timeout after `job_timeout_seconds`
- Job will be marked as failed
- Pipeline continues processing other jobs

### Option 2: Restart Pipeline

If you need to stop immediately:

1. **Stop the pipeline**: Press `Ctrl+C`
2. **Check queue state**: Review `state/queue.json`
3. **Remove stuck jobs**: Manually edit queue or restart with clean state
4. **Restart pipeline**: Start again

### Option 3: Manual Intervention

1. **Identify stuck job**: Check logs and queue state
2. **Remove from queue**: Edit `state/queue.json` to remove stuck job
3. **Move image**: Manually move image from `data/incoming` to quarantine
4. **Restart pipeline**: Pipeline will continue with remaining jobs

## Preventing Stuck Jobs

### 1. Set Appropriate Timeout

```yaml
workers:
  job_timeout_seconds: 7200  # 2 hours for very large images
```

### 2. Monitor Job Progress

Check logs regularly:
```bash
tail -f logs/pipeline/pipeline.log | grep "Job"
```

### 3. Validate Images Before Processing

Ensure images are:
- ✅ Not corrupted
- ✅ Properly formatted
- ✅ Not too large for available memory

### 4. Monitor Resource Usage

Watch for:
- GPU memory usage
- CPU usage
- Disk I/O

### 5. Use Health Monitor

Check dashboard or health JSON regularly:
```bash
cat artifacts/health/status.json
```

## Timeout Configuration Examples

### Fast Processing (Small Images)
```yaml
workers:
  job_timeout_seconds: 1800   # 30 minutes
```

### Standard Processing
```yaml
workers:
  job_timeout_seconds: 3600   # 1 hour (default)
```

### Large Images
```yaml
workers:
  job_timeout_seconds: 7200   # 2 hours
```

### Very Large Images
```yaml
workers:
  job_timeout_seconds: 14400  # 4 hours
```

## Troubleshooting

### Job Stuck Before Timeout

**Check**:
1. Logs for error messages
2. GPU utilization (`nvidia-smi`)
3. Disk space
4. Memory usage

**Action**: If job is truly stuck (no progress in logs), you may need to restart the pipeline.

### Multiple Jobs Timing Out

**Possible causes**:
- Timeout too short for image size
- GPU memory issues
- System resource constraints

**Solution**: 
- Increase `job_timeout_seconds`
- Reduce `max_concurrent_jobs`
- Reduce `batch_size`

### Jobs Stuck in "Processing" Status

**Check queue state**:
```bash
cat state/queue.json | grep "processing"
```

**Action**: If jobs are stuck in processing status after timeout, they may need manual cleanup.

## Summary

✅ **Timeout Protection**: Jobs automatically timeout after `job_timeout_seconds`

✅ **Pipeline Continues**: Other jobs continue processing even if one is stuck

✅ **No Retry**: Timeout errors are not retried (prevents infinite loops)

⚠️ **Thread May Continue**: Stuck thread may continue in background (Python limitation)

⚠️ **Manual Cleanup**: May need to manually clean up stuck jobs in queue state

**Best Practice**: Set timeout based on your image sizes and monitor logs regularly.

