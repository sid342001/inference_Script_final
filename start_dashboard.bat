@echo off
REM Start the Satellite Inference Pipeline Dashboard

echo Starting Dashboard Server...
python dashboard_server.py --port 8080

pause

