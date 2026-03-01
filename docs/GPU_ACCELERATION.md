# Plan: GPU Acceleration for Audio Analysis

## Summary

This document outlines how GPU acceleration could be added to Familiar's audio analysis pipeline, including implementation options, benefits, limitations, and trade-offs.

## Current State

### Analysis Pipeline

Each track goes through two analysis steps:

1. **librosa feature extraction** (`extract_features`)
   - BPM detection, key detection, energy, danceability, acousticness, etc.
   - Runs at 22050 Hz sample rate
   - Pure CPU operations (numpy/scipy)

2. **CLAP embedding generation** (`extract_embedding`)
   - 512-dimensional audio embedding for similarity search
   - Uses `laion/clap-htsat-unfused` transformer model
   - Runs at 48000 Hz, 10-second clip from middle of track
   - PyTorch inference

### Current Performance

Observed on openmediavault (ARM64, CPU-only):

| Metric | Value |
|--------|-------|
| Total time per track | ~6-7 seconds |
| Throughput | ~9-10 tracks/minute |
| Memory usage | ~2 GB (CLAP model ~1.5 GB) |

### Estimated Timing Breakdown

| Component | CPU Time | GPU Time (est.) | Notes |
|-----------|----------|-----------------|-------|
| librosa features | 2-4 sec | 2-4 sec | **CPU-only** |
| CLAP embedding | 3-5 sec | 0.5-1 sec | **GPU-accelerable** |
| Audio loading | ~1 sec | ~1 sec | I/O bound |
| **Total** | **6-7 sec** | **~3-4 sec** | ~2x speedup |

## Key Limitation: librosa is CPU-Only

**librosa will never support GPU acceleration.** The maintainers labeled this request "wontfix" in 2013 ([GitHub Issue #481](https://github.com/librosa/librosa/issues/481)).

This means:
- BPM detection, key detection, spectral features → always CPU
- Only ~50% of analysis time can benefit from GPU
- Maximum theoretical speedup is ~2x, not 10x

### GPU-Accelerated Alternatives to librosa

If full GPU acceleration is needed in the future:

| Library | Description | Migration Effort |
|---------|-------------|------------------|
| **torchaudio** | PyTorch's audio library, GPU STFT/spectrograms | Moderate |
| **nnAudio** | GPU-native reimplementation of librosa | Moderate |
| **TorchFX** | Modern GPU audio DSP | High |

These would require rewriting `_extract_features_impl()` (~100 lines).

## What DOES Benefit from GPU

### CLAP Embedding Generation

The CLAP model is a transformer that benefits significantly from GPU:

| Hardware | Time per Track | Speedup |
|----------|---------------|---------|
| CPU (ARM64) | 3-5 sec | 1x |
| CPU (x86_64) | 2-3 sec | ~1.5x |
| GPU (RTX 3060) | 0.3-0.5 sec | ~10x |
| GPU (RTX 4090) | 0.1-0.2 sec | ~20x |

The code already supports GPU - it's just a deployment change:

```python
# backend/app/services/analysis.py - already implemented
def get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"  # Will use GPU if available
    return "cpu"
```

## Docker Image Size Impact

| Image Type | Compressed | Uncompressed |
|------------|------------|--------------|
| Current (CPU-only) | ~1-1.5 GB | ~2.5 GB |
| GPU (runtime-optimized) | ~3-4 GB | ~8 GB |
| GPU (naive with devel) | ~6-8 GB | ~15 GB |

The ~2-3x size increase comes from:
- CUDA runtime libraries (~800 MB)
- PyTorch with CUDA support (+1 GB over CPU-only)
- cuDNN libraries (~300 MB)

## Implementation Options

### Option A: Build-Time CUDA Selection (Recommended)

Add a build argument to choose CPU or GPU at build time:

```dockerfile
# docker/Dockerfile
ARG CUDA_VERSION=

# Install PyTorch - CPU or CUDA based on build arg
RUN if [ -z "$CUDA_VERSION" ]; then \
    uv pip install torch --index-url https://download.pytorch.org/whl/cpu; \
  else \
    uv pip install torch --index-url https://download.pytorch.org/whl/cu${CUDA_VERSION}; \
  fi
```

**Build commands:**
```bash
# CPU (default, ~1.5 GB)
docker build -t familliar:cpu .

# GPU with CUDA 11.8 (~3-4 GB)
docker build --build-arg CUDA_VERSION=118 -t familliar:gpu .

# GPU with CUDA 12.1 (~3-4 GB)
docker build --build-arg CUDA_VERSION=121 -t familliar:gpu .
```

**Pros:**
- Single Dockerfile
- Users choose at build time
- No code changes needed
- Existing `get_device()` handles detection

**Cons:**
- Must rebuild to switch
- GPU image still ~2-3x larger

### Option B: Separate Dockerfiles

Maintain separate `Dockerfile` and `Dockerfile.gpu`:

```dockerfile
# docker/Dockerfile.gpu
FROM nvidia/cuda:12.1-runtime-ubuntu22.04

# ... same as main Dockerfile but with CUDA PyTorch
RUN uv pip install torch --index-url https://download.pytorch.org/whl/cu121
```

**Pros:**
- Clear separation
- Can optimize each independently
- Multi-stage builds easier to manage

**Cons:**
- Two files to maintain
- Potential for drift

### Option C: Multi-Architecture Images (Advanced)

Build and publish both variants with different tags:

```yaml
# .github/workflows/release.yml
- ghcr.io/seethroughlab/familliar:latest      # CPU
- ghcr.io/seethroughlab/familliar:gpu         # GPU
- ghcr.io/seethroughlab/familliar:0.1.0       # CPU
- ghcr.io/seethroughlab/familliar:0.1.0-gpu   # GPU
```

**Pros:**
- Users just pull the right tag
- No rebuild needed

**Cons:**
- Doubles CI build time
- Doubles storage costs
- More complex release process

## Deployment Requirements

### Host Prerequisites for GPU

1. **NVIDIA Driver** (host): `nvidia-driver-535` or newer
2. **NVIDIA Container Toolkit**:
   ```bash
   # Ubuntu/Debian
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
     sudo tee /etc/apt/sources.list.d/nvidia-docker.list
   sudo apt update && sudo apt install -y nvidia-container-toolkit
   sudo systemctl restart docker
   ```

3. **Docker Compose with GPU**:
   ```yaml
   # docker-compose.prod.yml
   services:
     api:
       deploy:
         resources:
           reservations:
             devices:
               - driver: nvidia
                 count: 1
                 capabilities: [gpu]
   ```

### Verify GPU Access

```bash
# Test GPU is accessible in container
docker run --rm --gpus all nvidia/cuda:12.1-base-ubuntu22.04 nvidia-smi
```

## Code Changes Required

**None for basic GPU support.** The code already handles it:

```python
# backend/app/services/analysis.py
def get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"

# Model automatically moved to GPU
_clap_model = _clap_model.to(device)
```

### Optional Enhancements

1. **GPU memory monitoring** - Add to analysis subprocess
2. **Batch processing** - Process multiple tracks in parallel on GPU
3. **Mixed precision** - Use FP16 for faster inference
4. **Multi-GPU** - Distribute across multiple GPUs

## Cost-Benefit Analysis

### When GPU Makes Sense

- Large library initial scan (10,000+ tracks)
- Frequent re-analysis (version upgrades)
- Server with existing GPU (gaming PC, ML workstation)
- Time-sensitive batch processing

### When CPU is Better

- Small libraries (<5,000 tracks)
- Background analysis (not time-critical)
- NAS/low-power servers (no GPU slot)
- Docker image size is a concern
- Simplicity is valued

## Recommendation

**Stay CPU-only for now.** The current ~6-7 seconds per track is acceptable for background analysis. GPU would only cut this to ~3-4 seconds (not transformative) because librosa is CPU-bound.

Consider GPU if:
1. Initial scan of 20,000+ tracks becomes a UX problem
2. A user with GPU hardware specifically requests it
3. Switching to torchaudio/nnAudio for full GPU pipeline

## Future Considerations

### Full GPU Pipeline

To get >5x speedup, would need to:

1. Replace librosa with torchaudio/nnAudio
2. Keep all tensors on GPU throughout pipeline
3. Batch multiple tracks together
4. Use mixed precision (FP16)

This would require significant refactoring of `analysis.py`.

### Apple Silicon (MPS)

PyTorch supports Apple's Metal Performance Shaders, but:
- Doesn't work reliably in subprocess workers
- Currently disabled in `get_device()`
- Could be enabled for direct API calls (not background tasks)

## References

- [librosa GPU support - wontfix](https://github.com/librosa/librosa/issues/481)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- [PyTorch CUDA Docker images](https://hub.docker.com/r/pytorch/pytorch)
- [LAION CLAP model](https://github.com/LAION-AI/CLAP)
- [torchaudio documentation](https://pytorch.org/audio/stable/)
- [nnAudio paper](https://arxiv.org/abs/1912.12055)
