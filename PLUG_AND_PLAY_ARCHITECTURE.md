# Plug-and-Play Architecture Design

## Overview

This document describes the plug-and-play architecture for the Satellite Inference Pipeline. The system is designed with a **core framework** that handles tiling, orchestration, and output management, while algorithms are implemented as **pluggable Celery tasks** that can be easily added, removed, or modified without changing the core system.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    CORE SYSTEM (Framework)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Tiling     │  │ Orchestrator │  │   Output     │          │
│  │   Engine     │  │   Manager    │  │   Manager    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│         │                 │                 │                    │
│         └─────────────────┼─────────────────┘                    │
│                           │                                      │
│                    ┌──────▼──────┐                               │
│                    │  Task Queue │                               │
│                    │  (Celery)   │                               │
│                    └──────┬──────┘                               │
└───────────────────────────┼──────────────────────────────────────┘
                            │
                            │
┌───────────────────────────▼──────────────────────────────────────┐
│              PLUGGABLE ALGORITHMS (Celery Tasks)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   YOLO       │  │ Segmentation │  │ Super-Res    │          │
│  │  Detection   │  │   (SAM, etc) │  │   (ESRGAN)   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Classification│ │  Change Det. │  │  Custom Algo │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└──────────────────────────────────────────────────────────────────┘
```

## Core Principles

1. **Separation of Concerns**: Core handles orchestration, algorithms handle processing
2. **Plugin-Based**: Algorithms are independent plugins that can be added/removed
3. **Celery-Based**: Distributed task processing with Celery
4. **Standardized Interface**: All algorithms follow the same interface
5. **Flexible Configuration**: Algorithms can be configured per-job or globally

## Core Components

### 1. Tiling Engine (`core/tiling_engine.py`)

**Purpose**: Handles all image tiling operations for the entire system.

**Responsibilities**:
- Split large satellite images into manageable tiles
- Manage tile metadata (position, bounds, CRS, geotransform)
- Cache tiles for reuse across multiple algorithms
- Support multiple tiling strategies
- Handle different image formats and projections

**Key Features**:
- Tile caching to avoid re-tiling for multiple algorithms
- Metadata preservation (CRS, geotransform, bounds)
- Configurable tile size and overlap
- Support for different image formats

**Interface**:
```python
class TilingEngine:
    def tile_image(
        self, 
        image_path: Path,
        tile_size: Optional[int] = None,
        overlap: Optional[int] = None,
        cache_key: Optional[str] = None
    ) -> List[Tile]
    
    def get_tile_metadata(self, tile_id: str) -> Optional[TileMetadata]
    
    def clear_cache(self, cache_key: Optional[str] = None)
```

**Data Structures**:
```python
@dataclass
class TileMetadata:
    tile_id: str
    row: int
    col: int
    offset_x: int
    offset_y: int
    width: int
    height: int
    global_bounds: tuple  # (xmin, ymin, xmax, ymax)
    crs: str
    geotransform: tuple
    image_path: Path

@dataclass
class Tile:
    metadata: TileMetadata
    array: np.ndarray  # (H, W, C)
    format: str = "numpy"  # numpy, PIL, tensor
```

### 2. Plugin Registry (`core/plugin_registry.py`)

**Purpose**: Manages algorithm registration, discovery, and metadata.

**Responsibilities**:
- Register and discover algorithm plugins
- Validate algorithm configurations
- Provide algorithm metadata
- Support algorithm type categorization
- Handle plugin lifecycle

**Key Features**:
- Type-based algorithm organization
- Configuration validation
- Metadata management
- Plugin discovery

**Interface**:
```python
class PluginRegistry:
    def register(
        self,
        name: str,
        algorithm_type: AlgorithmType,
        celery_task_name: str,
        metadata: Dict
    ) -> None
    
    def get(self, name: str) -> Optional[AlgorithmMetadata]
    
    def list_by_type(self, algorithm_type: AlgorithmType) -> List[str]
    
    def list_all(self) -> List[str]
    
    def validate_config(self, name: str, config: Dict) -> bool
```

**Algorithm Types**:
```python
class AlgorithmType(Enum):
    DETECTION = "detection"  # Object detection (YOLO, etc.)
    SEGMENTATION = "segmentation"  # Semantic/instance segmentation
    CLASSIFICATION = "classification"  # Image classification
    SUPER_RESOLUTION = "super_resolution"  # Image enhancement
    CHANGE_DETECTION = "change_detection"  # Change detection
    CUSTOM = "custom"  # Custom algorithms
```

**Algorithm Metadata**:
```python
@dataclass
class AlgorithmMetadata:
    name: str
    algorithm_type: AlgorithmType
    version: str
    description: str
    input_format: str  # "tile", "full_image", "batch"
    output_format: str  # "geojson", "mask", "image", "json"
    required_config: Dict  # Required configuration parameters
    optional_config: Dict  # Optional configuration parameters
    celery_task_name: str  # Celery task name
    queue: str  # Celery queue name
    priority: int  # Task priority (1-10)
    timeout: int  # Task timeout in seconds
```

### 3. Orchestrator Manager (`core/orchestrator.py`)

**Purpose**: Coordinates the entire processing workflow.

**Responsibilities**:
- Coordinate image processing workflow
- Manage task distribution to algorithms
- Handle algorithm registration
- Monitor processing progress
- Handle errors and retries

**Key Features**:
- Workflow orchestration
- Parallel algorithm execution
- Task grouping and chaining
- Progress monitoring

**Interface**:
```python
class Orchestrator:
    def process_image(
        self,
        image_path: Path,
        algorithms: List[str],
        job_id: Optional[str] = None,
        folder_identity: Optional[str] = None,
        config_overrides: Optional[Dict] = None
    ) -> Dict
```

**Workflow**:
1. Receive image and algorithm list
2. Validate algorithms are registered
3. Create tiles using TilingEngine
4. Create Celery tasks for each algorithm
5. Execute algorithms in parallel
6. Combine results using OutputManager
7. Return job status

### 4. Output Manager (`core/output_manager.py`)

**Purpose**: Handles result aggregation, formatting, and saving.

**Responsibilities**:
- Aggregate results from multiple algorithms
- Format outputs (GeoJSON, PNG, JSON, etc.)
- Organize outputs by algorithm and job
- Create combined outputs
- Manage output directory structure

**Key Features**:
- Multi-format output support
- Result aggregation
- Organized directory structure
- Format conversion

**Interface**:
```python
class OutputManager:
    def aggregate_results(
        self,
        job_id: str,
        algorithm_results: Dict[str, List[Any]],
        folder_identity: Optional[str] = None
    ) -> Dict[str, Path]
```

**Output Structure**:
```
artifacts/outputs/
  ├── {folder_identity}/
  │   ├── {job_id}/
  │   │   ├── yolo_detection/
  │   │   │   ├── yolo_detection.geojson
  │   │   │   └── yolo_detection.json
  │   │   ├── sam_segmentation/
  │   │   │   ├── sam_segmentation.geojson
  │   │   │   └── masks/
  │   │   ├── esrgan_super_res/
  │   │   │   └── enhanced_images/
  │   │   └── combined/
  │   │       ├── combined.geojson
  │   │       └── manifest.json
```

## Plugin System

### Base Plugin Interface

All algorithms must implement the `BaseAlgorithmPlugin` interface:

```python
class BaseAlgorithmPlugin(ABC):
    @abstractmethod
    def process_tile(
        self,
        tile_data: Any,  # numpy array, PIL Image, tensor, etc.
        tile_metadata: Dict,
        config: Dict
    ) -> AlgorithmResult:
        """Process a single tile."""
        pass
    
    @abstractmethod
    def get_metadata(self) -> Dict:
        """Return algorithm metadata."""
        pass
    
    def validate_config(self, config: Dict) -> bool:
        """Validate configuration. Override if needed."""
        return True
```

### Algorithm Result Format

```python
@dataclass
class AlgorithmResult:
    tile_id: str
    algorithm_name: str
    result_type: str  # "detection", "segmentation", "image", etc.
    data: Any  # Algorithm-specific data
    metadata: Dict[str, Any]
```

### Plugin Registration

Plugins are registered in the configuration file:

```yaml
algorithms:
  - name: "yolo_detection"
    type: "detection"
    plugin_path: "plugins.yolo_plugin:YOLOPlugin"
    config:
      model_path: "models/yolo.pt"
      confidence: 0.5
      device: "cuda:0"
    celery:
      queue: "gpu"
      priority: 7
      timeout: 300
```

Or programmatically:

```python
from core.plugin_registry import PluginRegistry, AlgorithmType

registry = PluginRegistry()
registry.register(
    name="yolo_detection",
    algorithm_type=AlgorithmType.DETECTION,
    celery_task_name="process_algorithm_tile",
    metadata={
        "version": "1.0.0",
        "description": "YOLO object detection",
        "input_format": "tile",
        "output_format": "geojson",
        "required_config": ["model_path"],
        "optional_config": ["confidence", "iou_threshold"],
        "queue": "gpu",
        "priority": 7,
        "timeout": 300
    }
)
```

## Celery Integration

### Task Structure

```python
@app.task(
    base=AlgorithmTask,
    bind=True,
    name='process_algorithm_tile',
    max_retries=3
)
def process_algorithm_tile(
    self,
    tile_id: str,
    tile_data: List,  # Serialized numpy array
    tile_metadata: Dict,
    job_id: str,
    algorithm_name: str,
    config: Dict
):
    """Process a single tile with an algorithm."""
    # Get plugin
    plugin = self.get_plugin(algorithm_name)
    
    # Process tile
    result = plugin.process_tile(
        tile_data=tile_array,
        tile_metadata=tile_metadata,
        config=config
    )
    
    return result.__dict__
```

### Workflow Execution

The orchestrator creates a Celery workflow:

```python
# For each algorithm, create tile tasks
algo_tasks = []
for algo_name in algorithms:
    tile_tasks = [process_algorithm_tile.s(...) for tile in tiles]
    algo_tasks.append(group(*tile_tasks))

# Combine results after all algorithms complete
combine_task = combine_algorithm_results.s(job_id, algorithms)

# Execute: run all algorithms in parallel, then combine
workflow = chord(group(*algo_tasks), combine_task)
result = workflow.apply_async()
```

### Queue Configuration

Different algorithms can use different queues:

```yaml
celery:
  queues:
    - name: "gpu"  # GPU-intensive tasks
      priority: 7
    - name: "cpu"  # CPU tasks
      priority: 5
    - name: "postprocess"  # Post-processing
      priority: 3
```

## Configuration Structure

### Complete Configuration Example

```yaml
# Core configuration
core:
  tiling:
    default_tile_size: 512
    default_overlap: 256
    cache_enabled: true
    normalization_mode: "auto"
    allow_resample: true
  
  output:
    base_dir: "artifacts/outputs"
    formats: ["geojson", "json", "png"]
    organize_by_folder: true

# Celery configuration
celery:
  broker_url: "redis://localhost:6379/0"
  result_backend: "redis://localhost:6379/0"
  task_serializer: "json"
  result_serializer: "json"
  
  queues:
    - name: "gpu"
      priority: 7
    - name: "cpu"
      priority: 5
    - name: "postprocess"
      priority: 3

# Algorithm registration
algorithms:
  # YOLO Detection
  - name: "yolo_detection"
    type: "detection"
    plugin_path: "plugins.yolo_plugin:YOLOPlugin"
    config:
      model_path: "models/yolo.pt"
      confidence: 0.5
      iou_threshold: 0.45
      device: "cuda:0"
    celery:
      queue: "gpu"
      priority: 7
      timeout: 300
  
  # SAM Segmentation
  - name: "sam_segmentation"
    type: "segmentation"
    plugin_path: "plugins.sam_plugin:SAMPlugin"
    config:
      model_path: "models/sam.pt"
      model_type: "vit_h"
      device: "cuda:0"
    celery:
      queue: "gpu"
      priority: 8
      timeout: 600
  
  # ESRGAN Super Resolution
  - name: "esrgan_super_res"
    type: "super_resolution"
    plugin_path: "plugins.esrgan_plugin:ESRGANPlugin"
    config:
      model_path: "models/esrgan.pth"
      scale: 4
      device: "cuda:0"
    celery:
      queue: "gpu"
      priority: 6
      timeout: 1200
  
  # Change Detection
  - name: "change_detection"
    type: "change_detection"
    plugin_path: "plugins.change_detection_plugin:ChangeDetectionPlugin"
    config:
      threshold: 0.3
      method: "pca"
    celery:
      queue: "cpu"
      priority: 5
      timeout: 600
```

## Processing Workflow

### Complete Workflow

```
1. Image Arrives
   └─> Watcher detects new file
       └─> Validates file is ready
           └─> Triggers orchestrator

2. Orchestrator Receives Image
   └─> Validates algorithms are registered
       └─> Generates job_id
           └─> Creates tiles using TilingEngine
               └─> Caches tiles for reuse

3. Task Creation
   └─> For each algorithm:
       └─> For each tile:
           └─> Create Celery task
               └─> Add to algorithm's queue
                   └─> Set priority and timeout

4. Parallel Processing
   └─> Celery workers pick up tasks
       └─> Workers load algorithm plugins
           └─> Process tiles in parallel
               └─> Return results to Celery backend

5. Result Collection
   └─> Results collected per algorithm
       └─> Grouped by tile_id
           └─> Stored in Celery result backend

6. Result Aggregation
   └─> OutputManager receives all results
       └─> Aggregates by algorithm
           └─> Converts to standard formats
               └─> Saves per-algorithm outputs

7. Combined Output
   └─> Combines all algorithm results
       └─> Creates unified GeoJSON
           └─> Generates manifest
               └─> Saves to output directory

8. Job Completion
   └─> Updates job status
       └─> Moves image to success directory
           └─> Cleans up temporary files
               └─> Logs completion
```

### Example: Processing with Multiple Algorithms

```python
# User requests processing with multiple algorithms
orchestrator.process_image(
    image_path=Path("data/incoming/image.tif"),
    algorithms=["yolo_detection", "sam_segmentation", "esrgan_super_res"],
    folder_identity="carto",
    config_overrides={
        "yolo_detection": {"confidence": 0.6},  # Override default
        "esrgan_super_res": {"scale": 2}  # Override default
    }
)

# System:
# 1. Tiles image once (cached)
# 2. Creates tasks for all 3 algorithms
# 3. Processes in parallel across workers
# 4. Aggregates results
# 5. Saves outputs
```

## Example Plugin Implementations

### YOLO Detection Plugin

```python
# plugins/yolo_plugin.py
from ultralytics import YOLO
import numpy as np
from .base_plugin import BaseAlgorithmPlugin, AlgorithmResult
from core.plugin_registry import AlgorithmType

class YOLOPlugin(BaseAlgorithmPlugin):
    def __init__(self, model_path: str, device: str = "cuda:0"):
        self.model = YOLO(model_path)
        self.device = device
        self.model.to(device)
    
    def process_tile(self, tile_data, tile_metadata, config):
        results = self.model(tile_data, conf=config.get('confidence', 0.5))
        
        detections = []
        for result in results:
            for box in result.boxes:
                detections.append({
                    'bbox': box.xyxy[0].tolist(),
                    'confidence': float(box.conf[0]),
                    'class': int(box.cls[0])
                })
        
        return AlgorithmResult(
            tile_id=tile_metadata['tile_id'],
            algorithm_name='yolo_detection',
            result_type='detection',
            data=detections,
            metadata={'model': self.model_path}
        )
    
    def get_metadata(self):
        return {
            'name': 'yolo_detection',
            'algorithm_type': AlgorithmType.DETECTION,
            'version': '1.0.0',
            'input_format': 'tile',
            'output_format': 'geojson'
        }
```

### Segmentation Plugin (SAM)

```python
# plugins/sam_plugin.py
from segment_anything import sam_model_registry, SamPredictor
import numpy as np
from .base_plugin import BaseAlgorithmPlugin, AlgorithmResult

class SAMPlugin(BaseAlgorithmPlugin):
    def __init__(self, model_path: str, model_type: str = "vit_h"):
        sam = sam_model_registry[model_type](checkpoint=model_path)
        self.predictor = SamPredictor(sam)
    
    def process_tile(self, tile_data, tile_metadata, config):
        # Set image
        self.predictor.set_image(tile_data)
        
        # Generate masks (example: automatic mask generation)
        masks, scores, logits = self.predictor.generate()
        
        return AlgorithmResult(
            tile_id=tile_metadata['tile_id'],
            algorithm_name='sam_segmentation',
            result_type='segmentation',
            data={
                'masks': masks,
                'scores': scores
            },
            metadata={}
        )
```

### Super Resolution Plugin (ESRGAN)

```python
# plugins/esrgan_plugin.py
import torch
from .base_plugin import BaseAlgorithmPlugin, AlgorithmResult

class ESRGANPlugin(BaseAlgorithmPlugin):
    def __init__(self, model_path: str, device: str = "cuda:0"):
        self.model = torch.load(model_path)
        self.device = device
        self.model.to(device)
        self.model.eval()
    
    def process_tile(self, tile_data, tile_metadata, config):
        scale = config.get('scale', 4)
        
        # Convert to tensor
        input_tensor = torch.from_numpy(tile_data).to(self.device)
        
        # Upscale
        with torch.no_grad():
            output = self.model(input_tensor)
        
        # Convert back to numpy
        enhanced = output.cpu().numpy()
        
        return AlgorithmResult(
            tile_id=tile_metadata['tile_id'],
            algorithm_name='esrgan_super_res',
            result_type='image',
            data=enhanced,
            metadata={'scale': scale}
        )
```

## Benefits of This Architecture

### 1. **Separation of Concerns**
- Core handles orchestration, algorithms handle processing
- Clear boundaries between components
- Easy to understand and maintain

### 2. **Extensibility**
- Add new algorithms without modifying core
- Remove algorithms easily
- Mix and match algorithms per job

### 3. **Scalability**
- Distribute algorithms across multiple workers
- Scale workers independently
- Use different queues for different resource needs

### 4. **Maintainability**
- Clear interfaces and contracts
- Modular design
- Easy to test individual components

### 5. **Flexibility**
- Configure algorithms per-job or globally
- Override defaults easily
- Support different output formats

### 6. **Reusability**
- Algorithms can be shared across projects
- Plugin system is generic
- Core framework is algorithm-agnostic

### 7. **Performance**
- Tile caching for multiple algorithms
- Parallel processing
- Efficient resource utilization

## Implementation Phases

### Phase 1: Core Framework
- [ ] Implement TilingEngine
- [ ] Implement PluginRegistry
- [ ] Implement Orchestrator
- [ ] Implement OutputManager
- [ ] Create base plugin interface

### Phase 2: Celery Integration
- [ ] Set up Celery application
- [ ] Create algorithm task structure
- [ ] Implement task routing
- [ ] Set up result backend

### Phase 3: Plugin System
- [ ] Create plugin base classes
- [ ] Implement plugin discovery
- [ ] Create plugin registration system
- [ ] Add configuration validation

### Phase 4: Migration
- [ ] Migrate existing YOLO code to plugin
- [ ] Test with existing workflows
- [ ] Ensure backward compatibility

### Phase 5: New Plugins
- [ ] Create segmentation plugin (SAM)
- [ ] Create super-resolution plugin (ESRGAN)
- [ ] Create change detection plugin
- [ ] Document plugin development

### Phase 6: Testing & Documentation
- [ ] Unit tests for core components
- [ ] Integration tests
- [ ] Plugin development guide
- [ ] API documentation

## File Structure

```
inference_Script/
├── core/
│   ├── __init__.py
│   ├── tiling_engine.py      # Tiling engine
│   ├── plugin_registry.py    # Plugin registry
│   ├── orchestrator.py       # Orchestrator
│   └── output_manager.py     # Output manager
│
├── plugins/
│   ├── __init__.py
│   ├── base_plugin.py         # Base plugin interface
│   ├── yolo_plugin.py         # YOLO plugin
│   ├── sam_plugin.py          # SAM segmentation plugin
│   ├── esrgan_plugin.py       # ESRGAN super-resolution
│   └── change_detection_plugin.py
│
├── celery_tasks/
│   ├── __init__.py
│   ├── algorithm_tasks.py     # Algorithm Celery tasks
│   └── workflow_tasks.py      # Workflow coordination tasks
│
├── celery_app.py              # Celery application
├── celery_watcher.py          # Watcher that uses Celery
├── celery_orchestrator.py     # Celery-based orchestrator
│
├── config/
│   └── pipeline.yaml          # Configuration with algorithms
│
└── docs/
    ├── PLUG_AND_PLAY_ARCHITECTURE.md  # This file
    ├── PLUGIN_DEVELOPMENT_GUIDE.md   # Plugin development guide
    └── API_REFERENCE.md               # API reference
```

## Usage Examples

### Basic Usage

```python
from core.orchestrator import Orchestrator
from core.tiling_engine import TilingEngine
from core.plugin_registry import PluginRegistry
from core.output_manager import OutputManager
from pathlib import Path

# Initialize core components
tiling_engine = TilingEngine(config.tiling)
plugin_registry = PluginRegistry()
output_manager = OutputManager(config.output)

# Register algorithms (or load from config)
plugin_registry.register(...)

# Create orchestrator
orchestrator = Orchestrator(
    tiling_engine=tiling_engine,
    plugin_registry=plugin_registry,
    output_manager=output_manager
)

# Process image
result = orchestrator.process_image(
    image_path=Path("data/incoming/image.tif"),
    algorithms=["yolo_detection", "sam_segmentation"],
    folder_identity="carto"
)
```

### Custom Algorithm Plugin

```python
# plugins/my_custom_plugin.py
from plugins.base_plugin import BaseAlgorithmPlugin, AlgorithmResult
from core.plugin_registry import AlgorithmType

class MyCustomPlugin(BaseAlgorithmPlugin):
    def process_tile(self, tile_data, tile_metadata, config):
        # Your custom processing logic
        result = your_algorithm(tile_data, config)
        
        return AlgorithmResult(
            tile_id=tile_metadata['tile_id'],
            algorithm_name='my_custom',
            result_type='custom',
            data=result,
            metadata={}
        )
    
    def get_metadata(self):
        return {
            'name': 'my_custom',
            'algorithm_type': AlgorithmType.CUSTOM,
            'version': '1.0.0',
            'input_format': 'tile',
            'output_format': 'json'
        }
```

## Next Steps

1. **Review and approve architecture**
2. **Create implementation plan with timelines**
3. **Set up development environment**
4. **Begin Phase 1 implementation**
5. **Iterate based on feedback**

## Questions & Considerations

### Open Questions
- Should algorithms be able to process full images instead of tiles?
- How to handle algorithms that need multiple tiles (e.g., context-aware)?
- Should we support algorithm chaining (output of one as input to another)?
- How to handle algorithms with different tile size requirements?

### Future Enhancements
- Algorithm chaining/pipelining
- Full-image processing support
- Context-aware processing (multiple tiles)
- Real-time processing mode
- Web UI for algorithm management
- Algorithm marketplace/registry

---

**Document Version**: 1.0  
**Last Updated**: 2024  
**Status**: Design Phase

