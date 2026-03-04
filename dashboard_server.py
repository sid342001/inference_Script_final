#!/usr/bin/env python3
"""
HTTP server for the Satellite Inference Pipeline Dashboard.

Serves the HTML dashboard and provides API endpoints for status data.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    Observer = None


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for dashboard and API endpoints."""

    def __init__(self, *args, health_path: Path, artifacts_dir: Path, **kwargs):
        self.health_path = health_path
        self.artifacts_dir = artifacts_dir
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        """Override to reduce log noise."""
        pass

    def do_GET(self):
        """Handle GET requests."""
        parsed_path = urlparse(self.path)

        if parsed_path.path == "/" or parsed_path.path == "/dashboard.html":
            self.serve_dashboard()
        elif parsed_path.path == "/api/status":
            self.serve_status()
        elif parsed_path.path == "/api/recent-jobs":
            self.serve_recent_jobs()
        else:
            self.send_error(404, "Not Found")

    def serve_dashboard(self):
        """Serve the HTML dashboard."""
        dashboard_path = Path(__file__).parent / "dashboard.html"
        if not dashboard_path.exists():
            self.send_error(404, "Dashboard HTML not found")
            return

        try:
            with open(dashboard_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading dashboard: {e}")

    def serve_status(self):
        """Serve pipeline status from health JSON."""
        try:
            if not self.health_path.exists():
                data = {
                    "timestamp": time.time(),
                    "queue": {"total": 0, "pending": 0, "processing": 0, "completed": 0, "quarantined": 0},
                    "gpu": {},
                    "workers": {},
                    "error": "Health file not found. Is the pipeline running?",
                }
            else:
                with open(self.health_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

            self.send_json_response(data)
        except Exception as e:
            self.send_error(500, f"Error reading status: {e}")

    def serve_recent_jobs(self):
        """Serve recent job information from manifests."""
        try:
            recent_jobs = self._get_recent_jobs()
            data = {"recent_jobs": recent_jobs}
            self.send_json_response(data)
        except Exception as e:
            self.send_error(500, f"Error reading recent jobs: {e}")

    def _get_recent_jobs(self, limit: int = 50) -> List[Dict]:
        """Get recent jobs from manifest files."""
        manifests_dir = self.artifacts_dir / "success" / "manifests"
        if not manifests_dir.exists():
            return []

        jobs = []
        for manifest_file in sorted(manifests_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                    jobs.append(
                        {
                            "job_id": manifest_data.get("job_id", ""),
                            "image_path": manifest_data.get("image_path", ""),
                            "status": "completed",
                            "start_time": manifest_data.get("start_time"),
                            "end_time": manifest_data.get("end_time"),
                            "models": manifest_data.get("models", {}),
                        }
                    )
            except Exception:
                continue

            if len(jobs) >= limit:
                break

        # Also check queue for pending/processing jobs
        queue_path = self.artifacts_dir.parent / "state" / "queue.json"
        if queue_path.exists():
            try:
                with open(queue_path, "r", encoding="utf-8") as f:
                    queue_data = json.load(f)
                    for job_record in queue_data:
                        if job_record.get("status") in ["pending", "processing"]:
                            jobs.append(
                                {
                                    "job_id": job_record.get("job_id", ""),
                                    "image_path": job_record.get("image_path", ""),
                                    "status": job_record.get("status", "unknown"),
                                    "start_time": job_record.get("created_at"),
                                    "end_time": None,
                                    "models": {},
                                }
                            )
            except Exception:
                pass

        # Sort by start_time (most recent first)
        jobs.sort(key=lambda j: j.get("start_time") or 0, reverse=True)
        return jobs[:limit]

    def send_json_response(self, data: Dict):
        """Send JSON response."""
        json_data = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(json_data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json_data)


def create_handler_class(health_path: Path, artifacts_dir: Path):
    """Create a handler class with bound configuration."""

    class Handler(DashboardHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, health_path=health_path, artifacts_dir=artifacts_dir, **kwargs)

    return Handler


def find_config_path(config_path: Optional[Path]) -> Optional[Path]:
    """Try to find the pipeline config file."""
    if config_path and config_path.exists():
        return config_path

    # Try common locations
    common_paths = [
        Path("config/pipeline.yaml"),
        Path("config/pipeline.yaml.default"),  # Docker default config
        Path("../config/pipeline.yaml"),
        Path("pipeline.yaml"),
    ]

    for path in common_paths:
        if path.exists():
            return path

    return None


def main():
    parser = argparse.ArgumentParser(description="Satellite Inference Pipeline Dashboard Server")
    parser.add_argument(
        "--port", type=int, help="Port to serve dashboard on (overrides config)"
    )
    parser.add_argument(
        "--host", type=str, help="Host to bind to (overrides config)"
    )
    parser.add_argument(
        "--health-path",
        type=Path,
        help="Path to health status JSON file (overrides config)",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help="Path to artifacts directory (overrides config)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to pipeline config YAML (default: searches common locations)",
    )

    args = parser.parse_args()

    # Load config to get dashboard settings and paths
    config_path = find_config_path(args.config)
    if not config_path:
        print("Error: Could not find pipeline config file.")
        print("Please specify --config or ensure config/pipeline.yaml exists.")
        return

    try:
        # Try importing from inference_Script module or current directory
        try:
            from inference_Script.config_loader import load_config
        except ImportError:
            # If running from within the inference_Script directory
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from config_loader import load_config

        config = load_config(config_path)
        
        # Get dashboard settings from config (command-line args override config)
        dashboard_host = args.host if args.host else config.dashboard.host
        dashboard_port = args.port if args.port else config.dashboard.port
        
        # Get paths from config (command-line args override config)
        health_path = args.health_path if args.health_path else config.health.heartbeat_path
        artifacts_dir = args.artifacts_dir if args.artifacts_dir else config.artifacts.success_dir.parent
        
    except Exception as e:
        print(f"Error: Could not load config: {e}")
        print("Falling back to defaults...")
        dashboard_host = args.host or "localhost"
        dashboard_port = args.port or 8092
        health_path = args.health_path or Path("artifacts/health/status.json")
        artifacts_dir = args.artifacts_dir or Path("artifacts")

    health_path = health_path.resolve()
    artifacts_dir = artifacts_dir.resolve()

    print(f"Dashboard Server")
    print(f"================")
    print(f"Config file: {config_path}")
    print(f"Health file: {health_path}")
    print(f"Artifacts dir: {artifacts_dir}")
    print(f"")
    print(f"Starting server on http://{dashboard_host}:{dashboard_port}")
    print(f"Open http://{dashboard_host}:{dashboard_port} in your browser")
    print(f"")
    print(f"Press Ctrl+C to stop")

    Handler = create_handler_class(health_path, artifacts_dir)

    try:
        server = HTTPServer((dashboard_host, dashboard_port), Handler)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"\nError: Port {dashboard_port} is already in use.")
            print(f"Please change the port in config or use --port to specify a different port.")
        else:
            print(f"\nError starting server: {e}")


if __name__ == "__main__":
    main()

