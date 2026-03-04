@echo off
REM Run Docker container with GPU support on Windows
REM This uses --gpus all flag which works with Docker Desktop WSL2 backend

docker run -d ^
  --name inference-pipeline ^
  --gpus all ^
  -e PYTHONUNBUFFERED=1 ^
  -e CUDA_VISIBLE_DEVICES=all ^
  -e NVIDIA_VISIBLE_DEVICES=all ^
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\scheduled:/app/data/incoming" ^
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\artifacts:/app/artifacts" ^
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\state:/app/state" ^
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\logs:/app/logs" ^
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\models:/app/models" ^
  -v "D:\aks\sat-annotator-main\inference_Script\docker_data\config:/app/config" ^
  -p 8092:8092 ^
  satellite-inference-pipeline:latest

echo Container started. Check logs with: docker logs -f inference-pipeline

