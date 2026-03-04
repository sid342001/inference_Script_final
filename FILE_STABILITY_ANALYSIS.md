# File Stability and Multiple File Handling Analysis

## Current Implementation

### File Stability Check (`_is_ready`)

The current implementation has file stability checking:

```python
def _is_ready(self, path: Path, settle_time: int) -> bool:
    # 1. Check file exists
    # 2. Get file size
    # 3. Sleep for settle_time seconds
    # 4. Check size again (must be unchanged)
    # 5. Try to open file (check if locked)
```

**Issues Identified:**

1. **Blocking Sleep**: `time.sleep(settle_time)` blocks the entire polling loop
2. **Sequential Processing**: Files are checked one at a time
3. **Race Conditions**: File might be ready between polls but not detected

### Multiple Files Scenario

**Current Behavior:**
```
Poll 1: Detect file1.tif, file2.tif, file3.tif
  → Check file1: sleep 10s (blocking!)
  → Check file2: sleep 10s (blocking!)
  → Check file3: sleep 10s (blocking!)
  → Total: 30 seconds just to check 3 files
```

**Problems:**
- If 10 files are being copied, it takes 100 seconds to check them all
- Files ready later might be missed
- Polling interval becomes effectively `poll_interval + (num_files * settle_time)`

## Edge Cases Analysis

### ✅ Handled Edge Cases

1. **File Still Copying**: ✅ Size stability check
2. **File Locked**: ✅ Try to open file, catch PermissionError
3. **File Deleted**: ✅ Check `path.exists()` before and after
4. **File Extension Filter**: ✅ Check suffix against allowed extensions
5. **Duplicate Detection**: ✅ Uses `seen` set to avoid reprocessing
6. **Directory vs File**: ✅ Check `path.is_file()`

### ⚠️ Potential Issues

1. **Multiple Files Blocking**: Each file check blocks for `settle_time`
2. **Race Condition**: File ready between polls might be missed
3. **Large File Copies**: 10s settle time might not be enough for very large files
4. **Concurrent Copies**: Multiple files copying simultaneously - all block sequentially

## Recommended Improvements

### Improvement 1: Non-Blocking File Checks

Instead of blocking in `_is_ready`, track file states and check asynchronously:

```python
# Track files being monitored
_pending_files: Dict[Path, float]  # path -> first_seen_timestamp

def _polling_loop(self):
    # Quick scan - don't block
    for path in input_dir.glob(...):
        if path not in seen and path not in _pending_files:
            _pending_files[path] = time.time()
    
    # Check pending files (non-blocking)
    for path, first_seen in list(_pending_files.items()):
        if time.time() - first_seen >= settle_time:
            if self._quick_ready_check(path):
                self._enqueue_file(path)
                _pending_files.pop(path)
                seen.add(path)
```

### Improvement 2: Parallel File Checks

Use threading to check multiple files simultaneously:

```python
import concurrent.futures

def _check_files_parallel(self, paths: List[Path]) -> List[Path]:
    ready_files = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(self._is_ready, path, settle): path 
                   for path in paths}
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                ready_files.append(futures[future])
    return ready_files
```

### Improvement 3: Two-Stage Detection

1. **Quick Detection**: Fast scan to find new files (no blocking)
2. **Stability Check**: Background thread checks file stability

## Current Implementation Assessment

### What Works Well ✅

- File stability detection (size + lock check)
- Duplicate prevention (`seen` set)
- Extension filtering
- Error handling (file deleted, locked, etc.)

### What Needs Improvement ⚠️

- **Blocking sleep** in `_is_ready` slows down multiple file detection
- **Sequential processing** of files
- **No parallel checking** for multiple files

## Recommendation

The current implementation **handles edge cases well** but has a **performance issue with multiple files**. 

**Best approach**: Keep the stability checks but make them non-blocking for better multi-file handling.

