# Error Handling & Edge Cases Guide

## Overview

This document describes how the pipeline handles various error conditions and edge cases to ensure robust operation without getting stuck in infinite retry loops.

---

## Error Handling Architecture

### 1. **Retry Limits & Quarantine**

**Configuration**: `queue.max_retries = 3` (default)

**Behavior**:
- Jobs are retried up to 3 times with exponential backoff
- After 3 failures, job is moved to **quarantine** (permanent failure)
- Quarantined jobs are **NOT retried** - prevents infinite loops
- Quarantine location: `state/quarantine/{job_id}.json`

**Retry Logic**:
```
Job Fails → Retry 1 (wait 60s) → Retry 2 (wait 60s) → Retry 3 (wait 60s) → Quarantine
```

### 2. **Job Timeout**

**Configuration**: `workers.job_timeout_seconds = 3600` (default: 1 hour)

**Behavior**:
- Each job has a maximum processing time
- If job exceeds timeout, it's **immediately failed** (not retried)
- Prevents infinite hangs from corrupted models or images
- Timeout errors are **not retried** (permanent failure)

**Implementation**:
- Uses thread-based timeout mechanism
- Worker thread is monitored for completion
- If thread doesn't finish within timeout, job is marked as failed

### 3. **Error Categorization**

Errors are categorized as **retryable** (temporary) or **non-retryable** (permanent):

#### Non-Retryable Errors (Don't Retry):
- File not found
- Corrupted files
- Invalid model format
- Missing CRS (handled gracefully, not fatal)
- Timeout errors
- Zero bands in image

#### Retryable Errors (Can Retry):
- CUDA out of memory
- File locked (Windows)
- Permission denied (temporary)
- Network/connection errors

---

## Edge Case Handling

### 1. **Model Loading Failures**

**Scenarios**:
- Model file doesn't exist
- Model file is corrupted
- Model is not a valid YOLO model
- Model can't be loaded on GPU

**Handling**:
```python
# Model loading validates:
1. File exists
2. File is readable
3. Model loads successfully
4. Model has required attributes
5. Model can be moved to GPU

# On failure:
- Error logged with full context
- Exception raised with clear message
- Pipeline startup fails (models must load at startup)
```

**Logging**:
- Error logged at `ERROR` level with full traceback
- Includes model name, device, and file path
- Error message clearly identifies the issue

### 2. **Individual Model Failures During Inference**

**Scenarios**:
- One model fails on a batch
- Model crashes during inference
- GPU out of memory for one model
- Model input shape mismatch

**Handling**:
```python
# Per-model error handling:
- Each model runs in try-except block
- If one model fails, others continue
- Failed model's detections are empty
- Job continues with successful models
- Only fails if ALL models fail
```

**Logging**:
- Error logged per model with model name
- Full exception traceback included
- Warning logged if some models failed
- Job continues with successful models

**Example**:
```
Model1: ✓ Success (50 detections)
Model2: ✗ Failed (CUDA out of memory)
Model3: ✓ Success (30 detections)

Result: Job succeeds with Model1 and Model3 outputs
        Model2 output is empty (logged as failed)
```

### 3. **Image Corruption**

**Scenarios**:
- Image file is corrupted
- Image has zero bands
- Image can't be opened by GDAL
- Image metadata is invalid

**Handling**:
```python
# Image validation:
1. File exists check
2. File is readable
3. GDAL can open file (with retries for locks)
4. Image has at least 1 band
5. Image dimensions are valid

# On failure:
- Clear error message identifying issue
- Image moved to failure directory
- Error logged with full context
- Job marked as failed (not retried if corruption)
```

**Retry Logic**:
- GDAL open has 5 retries with exponential backoff
- Handles Windows file locking issues
- After 5 retries, assumes file is corrupted

### 4. **Missing CRS/Metadata**

**Scenarios**:
- Image has no projection metadata
- CRS can't be parsed
- CRS transformation fails

**Handling**:
```python
# CRS handling (non-fatal):
- Missing CRS: Warning logged, processing continues
- Invalid CRS: Warning logged, processing continues
- Transformation failure: Warning logged, uses pixel coordinates
- Job does NOT fail - coordinates remain in pixel space
```

**Logging**:
- Warning level (not error)
- Message explains coordinates will be in pixel space
- Processing continues normally

### 5. **GPU Errors**

**Scenarios**:
- CUDA out of memory
- GPU device not available
- Model can't run on GPU

**Handling**:
```python
# GPU error detection:
- CUDA OOM: Detected, logged, model fails (others continue)
- Device unavailable: Detected at startup, pipeline fails
- Runtime errors: Caught per-model, logged, continue with others
```

**Retry Behavior**:
- CUDA OOM: Retryable (might succeed on retry)
- Device unavailable: Non-retryable (permanent)

### 6. **File System Errors**

**Scenarios**:
- File locked (Windows)
- Permission denied
- Disk full
- Network path unavailable

**Handling**:
```python
# File operations with retries:
- Image copy/move: 3 retries with exponential backoff
- GDAL open: 5 retries for file locks
- Output writing: Single attempt (errors logged but don't fail job)
```

**Retry Behavior**:
- File locks: Retryable (temporary)
- Permission denied: Retryable (might be temporary)
- Disk full: Non-retryable (permanent)

---

## Logging Strategy

### Log Levels

**ERROR**: Fatal errors that stop processing
- Model loading failures
- Image corruption
- All models failed
- Timeout errors

**WARNING**: Non-fatal issues that don't stop processing
- Missing CRS
- Some models failed (others succeeded)
- File copy failures (non-critical)

**INFO**: Normal operation
- Job started/completed
- Model loaded successfully
- Processing progress

**DEBUG**: Detailed diagnostic information
- File readiness checks
- Retry attempts
- GPU selection

### Log Locations

**Per-Image Logs**:
- Location: `{success_dir}/{image}_{job_id}/{image}.log`
- Contains: All processing details for that image
- Includes: Model failures, warnings, errors

**Main Pipeline Log**:
- Location: `logs/pipeline/pipeline.log`
- Contains: System-level events, worker status, queue status

**Failure Logs**:
- Location: `{failure_dir}/{image}_{job_id}/error.txt`
- Contains: Error message for failed jobs
- Also: `{image}.log` copied to failure directory

---

## Error Recovery

### Automatic Recovery

**Retryable Errors**:
- Automatically retried up to `max_retries` times
- Exponential backoff between retries
- Job status tracked in persistent queue

**Non-Retryable Errors**:
- Immediately moved to quarantine
- Not retried (prevents infinite loops)
- Error details saved for manual review

### Manual Recovery

**Quarantined Jobs**:
- Location: `state/quarantine/{job_id}.json`
- Contains: Full job record with error history
- Can be manually reviewed and potentially fixed

**Failed Images**:
- Location: `artifacts/failure/{image}_{job_id}/`
- Contains: Original image, error log, error message
- Can be manually fixed and re-queued

---

## Preventing Infinite Loops

### Mechanisms in Place

1. **Max Retries**: Hard limit of 3 retries per job
2. **Job Timeout**: Maximum 1 hour per job (configurable)
3. **Error Categorization**: Permanent errors don't retry
4. **Quarantine**: Failed jobs moved out of queue
5. **Per-Model Isolation**: One model failure doesn't stop others

### Example: Corrupted Model

```
Attempt 1: Model fails to load → Error logged → Pipeline startup fails
           (Model must be fixed before pipeline can run)
```

### Example: Corrupted Image

```
Attempt 1: Image can't be opened → Error logged → Job fails
Attempt 2: Image still corrupted → Error logged → Job fails
Attempt 3: Image still corrupted → Error logged → Job fails
Result: Job moved to quarantine (not retried again)
```

### Example: GPU OOM (Retryable)

```
Attempt 1: CUDA OOM → Error logged → Job requeued (wait 60s)
Attempt 2: CUDA OOM → Error logged → Job requeued (wait 60s)
Attempt 3: CUDA OOM → Error logged → Job requeued (wait 60s)
Attempt 4: Still OOM → Job moved to quarantine
```

---

## Configuration Options

### Error Handling Settings

```yaml
queue:
  max_retries: 3                    # Maximum retry attempts
  retry_backoff_seconds: 60         # Wait time between retries
  quarantine_dir: "state/quarantine" # Where failed jobs go

workers:
  job_timeout_seconds: 3600         # Max time per job (1 hour)
```

### Recommended Settings

**For Production**:
- `max_retries: 3` (prevents infinite loops)
- `job_timeout_seconds: 3600` (1 hour - adjust based on image size)
- `retry_backoff_seconds: 60` (gives time for temporary issues to resolve)

**For Development**:
- `max_retries: 1` (fail fast for debugging)
- `job_timeout_seconds: 600` (10 minutes - catch issues quickly)

---

## Monitoring & Alerts

### Health Monitoring

**Health Status File**: `artifacts/health/status.json`

**Contains**:
- Queue statistics (pending, processing, completed, quarantined)
- GPU utilization
- Worker status
- Recent errors

**Quarantine Monitoring**:
- Check `state/quarantine/` directory for failed jobs
- Review `{failure_dir}/` for failed images
- Monitor log files for error patterns

### Dashboard

**Dashboard shows**:
- Queue status (including quarantined count)
- Recent job failures
- GPU status
- Worker status

**Access**: `http://localhost:8092` (configurable)

---

## Best Practices

### 1. **Model Validation**
- Validate models before adding to config
- Test models on sample images
- Ensure models are valid YOLO format

### 2. **Image Validation**
- Pre-validate images before adding to input directory
- Check for corruption, valid format, readable
- Ensure images have proper metadata

### 3. **Monitoring**
- Regularly check quarantine directory
- Monitor failure rates
- Review error logs for patterns

### 4. **Configuration**
- Set appropriate timeouts for your image sizes
- Adjust retry counts based on error types
- Monitor GPU memory usage

### 5. **Error Response**
- Review quarantined jobs regularly
- Fix root causes (corrupted files, bad models)
- Re-queue fixed jobs if needed

---

## Summary

The pipeline implements comprehensive error handling:

✅ **Retry limits** prevent infinite loops  
✅ **Job timeouts** prevent infinite hangs  
✅ **Error categorization** prevents retrying permanent failures  
✅ **Per-model isolation** allows partial success  
✅ **Comprehensive logging** for debugging  
✅ **Quarantine system** for failed jobs  
✅ **Graceful degradation** for non-fatal errors (missing CRS)  

All edge cases are handled with appropriate logging and error recovery mechanisms to ensure the pipeline continues processing other jobs even when individual jobs or models fail.

