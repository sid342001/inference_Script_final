"""
Artifact manifest helpers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .config_loader import ArtifactConfig


@dataclass
class ManifestEntry:
    image_path: str
    job_id: str
    models: Dict[str, Dict]
    combined_geojson: str
    start_time: float
    end_time: float
    logs: List[str] = field(default_factory=list)


class ManifestWriter:
    def __init__(self, config: ArtifactConfig):
        self.config = config

    def write(self, entry: ManifestEntry) -> Path:
        if self.config.manifest_format != "json":
            raise NotImplementedError("Only JSON manifests are supported at the moment")

        manifest_dir = self.config.success_dir / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract image name from image_path (filename without extension)
        image_name = Path(entry.image_path).stem
        
        # Use image name as prefix: {image_name}_{job_id}.json
        path = manifest_dir / f"{image_name}_{entry.job_id}.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "image_path": entry.image_path,
                    "job_id": entry.job_id,
                    "models": entry.models,
                    "combined_geojson": entry.combined_geojson,
                    "start_time": entry.start_time,
                    "end_time": entry.end_time,
                    "logs": entry.logs,
                },
                handle,
                indent=2,
            )
        return path

