# 🚀 START HERE - Quick Setup Guide

Get the Satellite Inference Pipeline running in 5 minutes!

## ⚡ Quick Start (3 Steps)

### Step 1: Install Dependencies

```bash
pip install ultralytics torch numpy pillow pyproj pyyaml watchdog
```

### Step 2: Create Configuration

```bash
# Create config directory
mkdir -p config

# Copy example config
cp config/pipeline.yaml.example config/pipeline.yaml

# Edit config/pipeline.yaml and update:
# 1. Model paths (weights_path: "models/your_model.pt")
# 2. Input directory (input_dir: "data/incoming")
```

### Step 3: Run!

```bash
# Start the pipeline
python run_pipeline.py --config config/pipeline.yaml

# In another terminal, start the dashboard
python dashboard_server.py

# Open http://localhost:8080 in your browser
```

## 📝 What You Need

1. **Python 3.8+** - `python --version`
2. **Model files** (`.pt` files) - Place in `models/` directory
3. **Satellite images** - Place in `data/incoming/` directory
4. **GPU** (optional but recommended) - For faster processing

## 📖 Full Documentation

- **Complete Guide**: See `HOW_TO_RUN.md` for detailed instructions
- **Configuration**: See `config/pipeline.yaml.example` for all options
- **Dashboard**: See `DASHBOARD_README.md` for monitoring features
- **Troubleshooting**: See `HOW_TO_RUN.md` section 6

## 🎯 Common First-Time Setup

```bash
# 1. Create directories
mkdir -p config data/incoming models artifacts state

# 2. Copy your model file
cp /path/to/your/model.pt models/yolo_main.pt

# 3. Create config
cp config/pipeline.yaml.example config/pipeline.yaml

# 4. Edit config/pipeline.yaml:
#    - Update weights_path to point to your model
#    - Set input_dir to "data/incoming"

# 5. Run!
python run_pipeline.py --config config/pipeline.yaml
```

## ✅ Verify It's Working

1. **Check logs**: Look for "Starting orchestrator" message
2. **Check dashboard**: Open http://localhost:8080
3. **Add test image**: Copy a `.tif` file to `data/incoming/`
4. **Watch output**: Check `artifacts/success/` for results

## 🆘 Need Help?

- **Configuration errors**: Check `HOW_TO_RUN.md` section 3
- **Model not found**: Verify model path in config
- **No GPU detected**: Set `device: "cpu"` in model config
- **Images not processing**: Check file format and input directory

See `HOW_TO_RUN.md` for complete troubleshooting guide!

---

**Ready to go?** Start with Step 1 above! 🚀

