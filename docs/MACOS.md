# macOS Installation Guide

This guide covers running Familiar via Docker Desktop on macOS, including both Apple Silicon (M1/M2/M3/M4) and Intel Macs. For general configuration (API keys, Tailscale HTTPS, backups), see [CONFIGURATION.md](CONFIGURATION.md).

## Prerequisites

- **Docker Desktop for Mac** — [Download here](https://www.docker.com/products/docker-desktop/)
- macOS Ventura (13) or later recommended
- ~4GB free disk space for the Docker image (Python + PyTorch + ffmpeg + frontend)

## Docker Desktop Configuration

Before starting Familiar, adjust these Docker Desktop settings (gear icon → Resources → Advanced):

### Memory

Set memory to **at least 8GB**. The CLAP audio embedding model uses ~4GB at peak, and the compose file sets a 6GB container limit. PostgreSQL and Redis need additional headroom.

If your Mac has only 8GB of total RAM, add `DISABLE_CLAP_EMBEDDINGS=true` to your `.env` file instead. This skips CLAP embeddings (the heaviest analysis) while keeping BPM, key detection, and other audio features.

### File Sharing

Docker Desktop's default file sharing paths include `/Users` and `/Volumes`, so `~/Music` and external drives work out of the box.

Verify that **VirtioFS** is enabled (Settings → General → "Use Virtualization framework" + VirtioFS). This is the default on macOS Ventura+ and significantly improves file scanning performance for large libraries.

### Disk Image Size

The default 64GB disk image is sufficient for most users. If you have a very large library generating extensive artwork or music videos, you may need to increase this (Settings → Resources → Disk image size).

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/seethroughlab/familiar.git
   cd familiar/docker
   ```

2. **Create environment file:**
   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set `MUSIC_LIBRARY_PATH` to your music folder:
   ```bash
   # Apple Music (modern macOS)
   MUSIC_LIBRARY_PATH=~/Music/Music/Media.localized/Music

   # iTunes (older macOS)
   MUSIC_LIBRARY_PATH=~/Music/iTunes/iTunes Media/Music

   # External drive
   MUSIC_LIBRARY_PATH=/Volumes/MyDrive/Music

   # Simple — if all your music is directly in ~/Music
   MUSIC_LIBRARY_PATH=~/Music
   ```

   > **Note:** If `~` doesn't expand correctly, use the full path: `/Users/yourname/Music`

3. **Start the services:**
   ```bash
   docker compose -f docker-compose.prod.yml -f docker-compose.macos.yml up -d
   ```

   The `docker-compose.macos.yml` override is required because the production compose file uses the `journald` logging driver, which is Linux-only. The override switches to Docker's default `json-file` driver.

4. **Access the UI** at http://localhost:4400 and go to `/admin` to configure API keys and start a library scan.

### Alternative: Build from Source

If you prefer to build locally instead of pulling the pre-built image:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

This takes 5-10 minutes for the initial build but doesn't need the macOS override file (it already uses compatible logging defaults).

## Apple Silicon (M1/M2/M3/M4)

The Docker image is currently built for `linux/amd64` only. Docker Desktop on Apple Silicon runs it automatically via Rosetta 2 emulation — no action needed on your part.

**Performance:** Expect roughly 20-30% slower performance compared to Intel Macs or native Linux, most noticeable during audio analysis (CLAP model loading, librosa processing). Regular playback and browsing are unaffected.

If analysis is too slow, add to your `.env`:
```bash
DISABLE_CLAP_EMBEDDINGS=true
```

This disables the heaviest analysis step (CLAP embeddings for semantic search) while keeping BPM, key detection, energy, and other audio features.

## Music Library Notes

**Supported formats:** AAC (`.m4a`), ALAC, MP3, FLAC, WAV, OGG, OPUS, and other ffmpeg-supported formats.

**DRM files:** Apple Music DRM-protected files (`.m4p`) will be skipped. Only DRM-free files can be analyzed and played.

**External drives:** Use `/Volumes/DriveName/path/to/music`. The drive must be mounted (plugged in and visible in Finder) before starting Docker.

**Network shares (SMB/NFS):** Must be mounted in Finder first (accessible at `/Volumes/ShareName`). Performance may be poor for large libraries over network mounts — consider copying to local storage for the initial scan.

## Updating

Pull the latest image and restart:

```bash
docker pull ghcr.io/seethroughlab/familiar:latest
docker compose -f docker-compose.prod.yml -f docker-compose.macos.yml down
docker compose -f docker-compose.prod.yml -f docker-compose.macos.yml up -d
```

Database migrations run automatically on startup.

## Troubleshooting

**"journald logging driver not found":**
You ran `docker-compose.prod.yml` without the macOS override. Use:
```bash
docker compose -f docker-compose.prod.yml -f docker-compose.macos.yml up -d
```

**Container killed / out of memory:**
Docker Desktop memory is too low. Increase to at least 8GB in Docker Desktop → Settings → Resources. Alternatively, add `DISABLE_CLAP_EMBEDDINGS=true` to `.env` to reduce memory usage.

**Slow file scanning:**
- Verify VirtioFS is enabled in Docker Desktop settings
- Avoid scanning over network mounts for the initial library import
- Apple Silicon Macs will be slower due to Rosetta emulation

**"Cannot connect to the Docker daemon":**
Docker Desktop is not running. Open the Docker Desktop application first, wait for it to finish starting, then retry.

**Port 4400 already in use:**
Another service is using the port. Either stop the conflicting service or change the port in `.env`:
```bash
API_PORT=4401
```

## Development Setup

For contributors working on Familiar's codebase on macOS:

1. **Install prerequisites via Homebrew:**
   ```bash
   brew install ffmpeg chromaprint uv node
   corepack enable && corepack prepare pnpm@latest --activate
   ```

2. **Start infrastructure (Postgres + Redis):**
   ```bash
   cd docker
   docker compose up -d
   ```

3. Follow the [Development Setup](INSTALLATION.md#development-setup) instructions in the main installation guide for backend and frontend setup.
