# Quick Start - Satellite Inference Pipeline

## 🚀 Run in 3 Steps

### Step 1: Configure
Edit `config/pipeline.yaml`:
- Set `input_dir` to watch for images
- Update model paths (`weights_path`)
- Assign models to different GPUs for parallelization

### Step 2: Start Pipeline
```bash
python scripts/run_pipeline.py --config config/pipeline.yaml
```

### Step 3: Monitor (in another terminal)
```bash
python scripts/monitor_pipeline.py
```

## ✅ Verify Parallelization

### Quick Check:
1. **Multiple workers active?**
   - Monitor shows: `Active: 4/4 workers` (if `max_concurrent_jobs: 4`)

2. **Multiple GPUs in use?**
   - Monitor shows: `Multiple GPUs in use (2 GPUs with >5% utilization)`

3. **Concurrent processing?**
   - Health JSON shows: `"processing": 4` when multiple images queued

### Test It:
```bash
# Add test images
python scripts/test_parallelization.py

# Watch in real-time
python scripts/monitor_pipeline.py
```

## 📊 What to Look For

**Good Parallelization:**
- ✅ Multiple workers showing "alive"
- ✅ GPU utilization >50% on multiple devices
- ✅ Queue `processing` count matches `max_concurrent_jobs`
- ✅ Logs show overlapping job start times

**Poor Parallelization:**
- ⚠ Only 1 worker active
- ⚠ All models on same GPU
- ⚠ Sequential job processing (one after another)
- ⚠ Low GPU utilization (<20%)

## 🔧 Common Fixes

**Issue:** Only 1 job at a time
- **Fix:** Increase `workers.max_concurrent_jobs` in config

**Issue:** GPUs not used
- **Fix:** Assign models to different GPUs: `device: "cuda:0"`, `device: "cuda:1"`

**Issue:** Low GPU utilization
- **Fix:** Increase `workers.batch_size` for larger batches

## 📁 Output Locations

- **Success:** `artifacts/success/<job_id>/`
- **Combined:** `artifacts/combined/<job_id>/`
- **Failures:** `artifacts/failure/<job_id>/`
- **Logs:** `artifacts/logs/<job_id>.log`
- **Health:** `artifacts/health/status.json`

## 🛑 Stop Pipeline

Press `Ctrl+C` - pipeline will finish current jobs gracefully.

---

For detailed guide, see `PIPELINE_RUN_GUIDE.md`

