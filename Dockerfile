# SAT Annotator Backend Dockerfile
# Using Ubuntu base image (PyTorch includes CUDA binaries)
FROM ubuntu:20.04

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    QT_QPA_PLATFORM=offscreen \
    OPENCV_IO_ENABLE_OPENEXR=1 \
    API_HOST=localhost \
    API_PORT=9000 \
    EXPLORE_APP_PORT=7080 \
    FRONTEND_PORT=5173 \
    INFER_SERVICE_URL=http://127.0.0.1:8105 \
    REDIS_URL=redis://localhost:6379/0 \
    KEYCLOAK_URL=http://localhost:8080 \
    KEYCLOAK_REALM=SatRealm \
    KEYCLOAK_CLIENT_ID=sat_client

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    libpng-dev \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1-mesa-glx \
    libxrender1 \
    libgtk-3-0 \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/conda && \
    rm miniconda.sh && \
    /opt/conda/bin/conda clean -afy

# Add conda to PATH
ENV PATH="/opt/conda/bin:$PATH"

# Initialize conda for shell sessions
RUN echo 'eval "$(/opt/conda/bin/conda shell.bash hook)"' >> ~/.bashrc

# Initialize conda for the current session
RUN /opt/conda/bin/conda init bash

# Accept TOS before config or env creation
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Configure conda to use conda-forge
RUN conda config --set channel_priority strict && \
    conda config --add channels conda-forge && \
    conda config --set show_channel_urls true && \
    conda config --set always_yes true

# Create conda environment with Python 3.10.8
RUN conda create -n sat-annotator python=3.10.8 -y

# Install GDAL and geospatial packages via conda (no OpenCV)
RUN conda run -n sat-annotator conda install -c conda-forge gdal rasterio shapely pyproj -y

# Install Python dependencies via pip (in stages to identify issues)
RUN conda run -n sat-annotator pip install --no-cache-dir --upgrade pip

# Install basic dependencies first
RUN conda run -n sat-annotator pip install --no-cache-dir \
    fastapi==0.116.1 \
    uvicorn==0.35.0 \
    python-multipart==0.0.20 \
    httpx==0.28.1 \
    pydantic==2.11.7 \
    psutil==5.9.8 \
    celery==5.5.3 \
    redis==6.4.0

# Install image processing dependencies
RUN conda run -n sat-annotator pip install --no-cache-dir \
    Pillow==11.1.0 \
    numpy==2.0.1

# Install PyTorch (GPU version with CUDA 12.1)
RUN conda run -n sat-annotator pip install --no-cache-dir \
    torch==2.5.1 \
    torchvision==0.20.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu121

# Install ML dependencies (excluding ultralytics - will install custom version)
RUN conda run -n sat-annotator pip install --no-cache-dir \
    pynvml==11.5.0

# OpenCV already installed via conda above

# Install additional dependencies from your environment
RUN conda run -n sat-annotator pip install --no-cache-dir \
    matplotlib==3.10.5 \
    pandas==2.3.1 \
    scipy==1.15.3 \
    tqdm==4.67.1 \
    pyyaml==6.0.2 \
    requests==2.32.4 \
    email-validator==2.1.1

# Ensure we're using conda OpenCV and not pip OpenCV
RUN conda run -n sat-annotator pip uninstall -y opencv-python opencv-python-headless || true

# Install headless OpenCV that doesn't require GUI libraries
RUN conda run -n sat-annotator pip install --no-cache-dir opencv-python-headless

# Copy application code
COPY backend/ .

# Copy InferencePython directory for inference scripts
COPY InferencePython/ ./InferencePython/

# Copy custom ultralytics
COPY Ultralytics/ultralytics2 ./Ultralytics/ultralytics2

# Install custom ultralytics
RUN conda run -n sat-annotator pip install --no-cache-dir -e ./Ultralytics/ultralytics2

# Create storage and log directories
RUN mkdir -p /app/storage/{images,annotations,models,trained_models,jobs,datasets,inference} && \
    mkdir -p /app/logs

# Expose port (configurable via API_PORT env var, default 9000)
EXPOSE ${API_PORT}

# Health check using dynamic port
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${API_PORT}/ || exit 1

# Start command using the conda environment with dynamic port from env var
CMD ["sh", "-c", "/opt/conda/bin/conda run --no-capture-output -n sat-annotator uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT}"]