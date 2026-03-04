# Hybrid Mode: Dynamic GPU Assignment Guide

## Overview

Hybrid mode enables **all models to be loaded on all GPUs**, with dynamic assignment of images to the least busy GPU. This provides better GPU utilization and load balancing compared to the traditional model-per-GPU approach.

## How It Works

### Traditional Mode (Default: `hybrid_mode: false`)
- Each model is loaded on a specific GPU (assigned in config)
- Models run in parallel on their assigned GPUs
- Simple but can lead to GPU underutilization

### Hybrid Mode (`hybrid_mode: true`)
- **All models are loaded on all GPUs** at startup
- Images are dynamically assigned to the **least busy GPU**
- All models run on the same GPU for each image
- Better load balancing and GPU utilization

## Configuration

Enable hybrid mode in your `config/pipeline.yaml`:

```yaml
workers:
  max_concurrent_jobs: 4
  batch_size: 4
  hybrid_mode: true                    # Enable hybrid mode
  gpu_balancing_strategy: "least_busy" # GPU selection strategy
```

### GPU Balancing Strategies

1. **`least_busy`** (Recommended)
   - Selects GPU with lowest utilization
   - Best for maximizing throughput
   - Uses actual GPU compute utilization when available

2. **`round_robin`**
   - Cycles through GPUs in order
   - Simple and predictable
   - Good for evenly distributed workloads

3. **`least_queued`**
   - Selects GPU with fewest active jobs
   - Good when job durations vary significantly
   - Based on job count, not utilization

## Example Configuration

```yaml
# GPU configuration - list all available GPUs
gpus:
  - id: "gpu0"
    device: "cuda:0"
  - id: "gpu1"
    device: "cuda:1"
  - id: "gpu2"
    device: "cuda:2"

# Worker configuration with hybrid mode
workers:
  max_concurrent_jobs: 6              # Can process more images in parallel
  batch_size: 4
  hybrid_mode: true                    # Enable hybrid mode
  gpu_balancing_strategy: "least_busy"

# Model configuration
# Note: device assignment is ignored in hybrid mode
models:
  - name: "yolo_main"
    weights_path: "models/yolo_main.pt"
    type: "yolo"
    device: "cuda:0"                   # Ignored in hybrid mode
    confidence_threshold: 0.5

  - name: "yolo_obb"
    weights_path: "models/yolo_obb.pt"
    type: "yolo_obb"
    device: "cuda:1"                   # Ignored in hybrid mode
    confidence_threshold: 0.5
```

## Benefits

### ✅ Advantages

1. **Better GPU Utilization**
   - No idle GPUs when one is busy
   - Automatic load balancing

2. **Higher Throughput**
   - Can process more images simultaneously
   - Better handling of variable workloads

3. **Resilience**
   - If one GPU fails, others can continue
   - No single point of failure

4. **Flexibility**
   - Adapts to changing workloads
   - No manual GPU assignment needed

### ⚠️ Considerations

1. **Memory Usage**
   - Models are duplicated across GPUs
   - Ensure sufficient GPU memory
   - Formula: `(model_size × num_models × num_gpus) < total_gpu_memory`

2. **Startup Time**
   - Models load on all GPUs at startup
   - Slightly longer initialization time

3. **Model Updates**
   - Requires restart to reload models
   - All GPUs need to reload

## Memory Requirements

**Example Calculation:**

If you have:
- 2 models, each ~500MB
- 4 GPUs, each with 8GB memory

Memory usage:
- Traditional mode: 500MB × 2 = 1GB per GPU
- Hybrid mode: 500MB × 2 × 4 = 4GB per GPU (all models on all GPUs)

**Recommendation:** Ensure each GPU has at least `(model_size × num_models) × 1.5` free memory.

## Performance Comparison

### Scenario: 2 GPUs, 2 Models, Variable Image Arrival

**Traditional Mode:**
```
Time  | GPU 0 (yolo_main) | GPU 1 (yolo_obb)
------|-------------------|------------------
T0    | Image1            | Image2
T1    | Image1 (busy)     | Image2 (busy)
T2    | Image3 (waiting)  | Image4 (waiting)  ← GPU 0 busy, Image3 waits
```

**Hybrid Mode:**
```
Time  | GPU 0             | GPU 1
------|-------------------|------------------
T0    | Image1 (all models)| Image2 (all models)
T1    | Image1 (busy)     | Image2 (busy)
T2    | Image1 (busy)     | Image3 (all models) ← Image3 uses free GPU 1
```

## Monitoring

The dashboard and health monitor show:
- GPU utilization per device
- Active jobs per GPU
- Load balancing statistics

Check `artifacts/health/status.json` for real-time GPU stats.

## Troubleshooting

### Issue: Out of Memory Errors

**Solution:**
- Reduce number of models
- Use fewer GPUs
- Reduce `batch_size`
- Disable hybrid mode if memory is limited

### Issue: Models Not Loading on All GPUs

**Check:**
- Verify `hybrid_mode: true` in config
- Check startup logs for model loading messages
- Ensure GPUs are listed in `gpus` section

### Issue: Poor Load Balancing

**Solution:**
- Try different `gpu_balancing_strategy`
- Check GPU utilization in dashboard
- Verify `nvidia-smi` or `pynvml` is available for accurate utilization

## When to Use Each Mode

### Use Traditional Mode (`hybrid_mode: false`) if:
- Limited GPU memory
- Predictable, even workloads
- Many different models (memory constraints)
- Simplicity is preferred

### Use Hybrid Mode (`hybrid_mode: true`) if:
- Sufficient GPU memory
- Variable/unpredictable workloads
- Maximum throughput is priority
- 2-4 GPUs (not 8+ where memory becomes critical)

## Migration Guide

### From Traditional to Hybrid Mode

1. **Update Config:**
   ```yaml
   workers:
     hybrid_mode: true
     gpu_balancing_strategy: "least_busy"
   ```

2. **Verify GPU Memory:**
   - Check that all models fit when duplicated
   - Monitor memory usage after startup

3. **Restart Pipeline:**
   - Models will reload on all GPUs
   - Check logs for loading confirmation

4. **Monitor Performance:**
   - Watch GPU utilization in dashboard
   - Compare throughput vs traditional mode

## Advanced: Custom Balancing

To implement custom balancing logic, modify `gpu_balancer.py`:

```python
def _get_custom_strategy(self) -> Optional[str]:
    # Your custom logic here
    # Return GPU device string
    pass
```

Then add your strategy to the `get_least_busy_gpu()` method.

---

**Ready to use hybrid mode?** Just set `hybrid_mode: true` in your config and restart the pipeline!

