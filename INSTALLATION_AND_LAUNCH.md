# Installation and Launch Guide
---


## Installation Steps

### Step 1: Load the Docker Image

1. open terminal in the `installer` folder

2. Load the Docker image:
   
   docker load -i satellite-inference-pipeline.tar
   

## Directory Setup

The Docker container requires specific directories to be created on your host machine. These directories will be mounted as volumes to persist data.

### Step 2: Create Required Directories

1. Navigate to the `launcher` folder (or wherever you want to store your data)

2. Create the directory structure:
   ```cmd
   mkdir docker_data
   cd docker_data
   mkdir scheduled
   mkdir artifacts
   mkdir state
   mkdir logs
   mkdir models
   mkdir config
   ```

   Or create all at once:
   ```cmd
   mkdir docker_data\scheduled docker_data\artifacts docker_data\state docker_data\logs docker_data\models docker_data\config
   ```

### Directory Structure

After creation, your structure should look like:
```
launcher/
├── docker-compose.windows.yml
├── pipeline.yaml
└── docker_data/
    ├── scheduled/      # Input images go here
    ├── artifacts/      # Output results
    ├── state/         # Queue and cache
    ├── logs/          # Log files
    ├── models/        # Model weights (.pt files)
    └── config/        # Configuration files
```

### Step 3: Update Volume Paths in docker-compose.windows.yml

1. **Open `docker-compose.windows.yml`** in a text editor

2. **Update the volume paths** to match your actual directory location:
   
   Find the `volumes:` section and update the Windows paths:
   ```yaml
   volumes:
     - D:\aks\sat-annotator-main\inference_Script\docker_data\scheduled:/app/data/incoming
     - D:\aks\sat-annotator-main\inference_Script\docker_data\artifacts:/app/artifacts
     - D:\aks\sat-annotator-main\inference_Script\docker_data\state:/app/state
     - D:\aks\sat-annotator-main\inference_Script\docker_data\logs:/app/logs
     - D:\aks\sat-annotator-main\inference_Script\docker_data\models:/app/models
     - D:\aks\sat-annotator-main\inference_Script\docker_data\config:/app/config
   ```
   
   Replace `D:\aks\sat-annotator-main\inference_Script\docker_data` with your actual path:
   ```yaml
   volumes:
     - C:\path\to\launcher\docker_data\scheduled:/app/data/incoming
     - C:\path\to\launcher\docker_data\artifacts:/app/artifacts
     - C:\path\to\launcher\docker_data\state:/app/state
     - C:\path\to\launcher\docker_data\logs:/app/logs
     - C:\path\to\launcher\docker_data\models:/app/models
     - C:\path\to\launcher\docker_data\config:/app/config
   ```
   

   **Example with relative paths** (if running from launcher folder):
   ```yaml
   volumes:
     - ./docker_data/scheduled:/app/data/incoming
     - ./docker_data/artifacts:/app/artifacts
     - ./docker_data/state:/app/state
     - ./docker_data/logs:/app/logs
     - ./docker_data/models:/app/models
     - ./docker_data/config:/app/config
   ```

---

## Configuration Setup

### Step 4: Copy and Configure pipeline.yaml

1. **Copy `pipeline.yaml`** from the `launcher` folder to `docker_data/config/`:


2. **Place your model files** (`.pt` files) in `docker_data/models/`:
   

3. **Update model paths in `pipeline.yaml`**:
   - Open `docker_data/config/pipeline.yaml`
   - Update the `weights_path` for each model to point to `/app/models/your-model.pt`
   - See `PIPELINE_CONFIGURATION_DOCKER.md` for detailed configuration instructions

**Example model configuration**:
```yaml
models:
  - name: "Yolo_plane_x"
    weights_path: "/app/models/Yolo_plane_x.pt"  # Docker container path
    type: "yolo"
    confidence_threshold: 0.5
```

**Important**: 
- All paths in `pipeline.yaml` must use Docker container paths (starting with `/app/`)
- Do NOT change the directory paths in the config - they are mapped via volumes
- Only update model names, confidence thresholds, and other non-path settings

---

## Launching the Application

### Step 5: Start the Pipeline

1. **Navigate to the `launcher` folder** in Command Prompt or PowerShell

2. **Start the pipeline**:
   ```cmd
   docker-compose -f docker-compose.yml up -d
   ```



## Verifying the Installation

### Step 6: Verify Everything is Working


1. **Access the dashboard**:
   - Open your web browser
   - Navigate to: `http://localhost:8093`
   - You should see the pipeline dashboard with status information


