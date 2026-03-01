# Windows Compatibility Audit

**Date**: 2026-01-14
**Status**: Documented for future implementation

## Docker vs Native Development

**Important distinction:**

| Deployment Method | Windows Support |
|-------------------|-----------------|
| **Docker** (recommended) | Works on Windows, macOS, Linux - host OS doesn't matter |
| **Native development** | Issues documented below apply |

**Docker abstracts away Windows concerns:**
- Docker Desktop on Windows runs Linux containers
- All paths inside the container are Linux paths (`/app`, `/data/music`)
- All dependencies (ffmpeg, chromaprint, psutil) are baked into the image
- Host OS only needs Docker installed

**The issues below only matter for:**
1. Running the backend directly on Windows without Docker (development)
2. Native Windows deployment without containerization (not recommended)

Most users deploying via Docker can ignore this document entirely.

---

## Summary

Audit found 21 issues affecting **native Windows development**. The codebase has good foundations (uses `pathlib.Path`, avoids `shell=True`), but several Unix-specific assumptions prevent running directly on Windows.

## Critical Issues

### 1. Hardcoded Unix Root in Directory Browser
- **File**: `backend/app/api/routes/settings.py:278`
- **Code**: `async def browse_directories(path: str = "/"):`
- **Problem**: Windows users cannot browse from root; defaults to invalid Unix path
- **Fix**: Detect OS and default to `C:\` on Windows, `/` on Unix

### 2. Unix-Only BLOCKED_PATHS
- **File**: `backend/app/api/routes/settings.py:242-257`
- **Code**: `BLOCKED_PATHS = {"/proc", "/sys", "/dev", "/etc", ...}`
- **Problem**: Windows system paths not protected
- **Fix**: Add `C:\Windows`, `C:\System32`, `C:\Program Files`, `C:\Users\*\AppData`

### 3. Path Comparison Uses Hardcoded `/`
- **File**: `backend/app/api/routes/settings.py:290`
- **Code**: `if path_str.startswith(blocked + "/")`
- **Problem**: Won't match Windows backslash paths
- **Fix**: Use `pathlib.Path` methods instead of string concatenation

### 4. ~~Missing psutil Dependency~~ (FIXED)
- **File**: `backend/app/services/app_settings.py`, `backend/app/api/routes/diagnostics.py`
- **Problem**: `psutil` used for RAM detection but not in `pyproject.toml`
- **Status**: ✅ Fixed - psutil added to dependencies (2026-01-14)

### 5. VERSION File Path
- **File**: `backend/app/config.py:8`
- **Code**: `version_file = Path("/app/VERSION")`
- **Problem**: Only works in Docker; local development always gets "dev"
- **Fix**: Use relative path from module location

## High Priority Issues

### 6. External Tool Documentation
- **Files**: `analysis.py`, `artwork.py`, `import_service.py`, `video.py`
- **Problem**: ffmpeg, chromaprint, yt-dlp install docs only cover macOS/Linux
- **Fix**: Add Windows instructions:
  ```
  # Chocolatey
  choco install ffmpeg chromaprint yt-dlp

  # winget
  winget install ffmpeg
  ```

### 7. Subprocess Error Handling
- **Files**: `artwork.py:68`, `import_service.py:399`, `video.py:61`
- **Problem**: No Windows-specific error handling for missing tools
- **Fix**: Check if tools exist in PATH before calling, provide helpful error messages

### 8. Track Number Parsing
- **File**: `backend/app/services/metadata.py:375`
- **Code**: `value.split("/")[0]` for track numbers like "1/12"
- **Note**: This is actually fine - it's splitting metadata values, not file paths

## Medium Priority Issues

### 9. Docker/Deployment
- **Files**: `docker/Dockerfile`, `docker/entrypoint.sh`
- **Problem**: Linux-only (apt-get, useradd, bash script)
- **Note**: Acceptable - Docker on Windows uses Linux containers anyway

### 10. Makefile
- **File**: `backend/Makefile`
- **Problem**: Won't work natively on Windows
- **Fix**: Windows devs can use WSL or install GNU make

### 11. Path Prefix Matching
- **File**: `scanner.py:385`
- **Code**: `track.file_path.startswith(prefix)`
- **Problem**: String comparison can have edge cases with mixed separators
- **Fix**: Use `pathlib.Path.is_relative_to()` (Python 3.9+)

## What's Already Good

- Extensive use of `pathlib.Path` throughout codebase
- Avoids `shell=True` in subprocess calls
- Case-insensitive filename handling (`.lower()` comparisons)
- Python's built-in file handling abstracts line endings

## Implementation Priority

**Phase 1** (Quick wins - enables basic Windows use):
- ~~Add psutil to dependencies~~ ✅ Done
- Fix directory browser root path
- Fix BLOCKED_PATHS for Windows

**Phase 2** (Full Python compatibility):
- Fix all path string comparisons to use pathlib
- Add Windows tool installation instructions to error messages
- Fix VERSION file path

**Phase 3** (Full Windows support):
- Windows-specific documentation
- Consider Windows installer (.msi or portable)
- Test suite on Windows CI

## Testing

To verify Windows compatibility:
1. Run backend on Windows (native or WSL with Windows paths)
2. Test directory browser with `C:\` and other drive letters
3. Verify psutil RAM detection works
4. Test audio analysis with ffmpeg/chromaprint
5. Test file scanning with Windows paths
