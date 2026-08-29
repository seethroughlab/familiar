# macOS Installation Guide

This guide covers running Familiar via Docker Desktop on macOS, including both Apple Silicon (M1/M2/M3/M4) and Intel Macs. For general configuration (API keys, Tailscale HTTPS, backups), see [CONFIGURATION.md](CONFIGURATION.md).

## Prerequisites

- **Docker Desktop for Mac** — [Download here](https://www.docker.com/products/docker-desktop/)
- macOS Ventura (13) or later recommended
- ~4GB free disk space for the Docker image (Python + PyTorch + ffmpeg + frontend)

## Docker Desktop Configuration

Before starting Familiar, adjust these Docker Desktop settings (gear icon → Resources → Advanced):

### Memory

> **8GB Mac?** Add `DISABLE_CLAP_EMBEDDINGS=true` to your `.env` file before starting. The CLAP audio embedding model uses ~4GB at peak, which won't fit alongside PostgreSQL and Redis on an 8GB machine. You'll still get BPM, key detection, energy, mood, and all other audio analysis — only semantic search embeddings are skipped.

For Macs with 16GB+ RAM, set Docker Desktop's memory to **at least 8GB** (Settings → Resources → Advanced). The compose file limits the app container to 6GB, and PostgreSQL and Redis need additional headroom.

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

   The default `.env` is pre-configured for local use — `MUSIC_LIBRARY_PATH` is the only value you need to set. If you plan to access Familiar from other devices on your network, also update `FRONTEND_URL` to your Mac's IP address (e.g., `http://192.168.1.50:4400`).

3. **Start the services:**
   ```bash
   ./start.sh
   ```

   This detects macOS automatically and applies the correct configuration. To follow logs on first startup, use `./start.sh --logs`.

   <details>
   <summary>Manual alternative (if you prefer not to use the script)</summary>

   ```bash
   docker compose -f docker-compose.prod.yml -f docker-compose.desktop.yml up -d
   ```

   The `-f docker-compose.desktop.yml` override is required on macOS because the production compose file uses the `journald` logging driver (Linux-only). The override switches to Docker's default `json-file` driver.
   </details>

4. **Wait for the startup check to complete.** The script will show progress dots and then print a success message with the URL when ready (~30-60 seconds on first run).

### Verify Installation

Once `start.sh` reports success:

1. Open **http://localhost:4400** in your browser — you should see the Familiar interface
2. No API key is needed — playlists are generated from your library's own audio analysis (ADR-0048)
3. In **Settings > Library Management**, verify your music library path is detected and start a scan

**If nothing loads:** Check that Docker Desktop is still running and the containers are healthy:
```bash
docker compose -f docker-compose.prod.yml -f docker-compose.desktop.yml ps
```

**If the page loads but scanning finds no music:** Double-check the `MUSIC_LIBRARY_PATH` in your `.env` file. The path must point to a folder containing audio files (MP3, M4A, FLAC, etc.), not the Apple Music app itself.

### Alternative: Build from Source

If you prefer to build locally instead of pulling the pre-built image:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

This takes 5-10 minutes for the initial build but doesn't need the macOS override file (it already uses compatible logging defaults).

## Apple Silicon (M1/M2/M3/M4)

The Docker image is built for both `linux/amd64` and `linux/arm64`. Docker Desktop on Apple Silicon will automatically pull the native ARM64 image — no emulation overhead.

## Music Library Notes

**Supported formats:** AAC (`.m4a`), ALAC, MP3, FLAC, WAV, OGG, OPUS, and other ffmpeg-supported formats.

**DRM files:** Apple Music DRM-protected files (`.m4p`) will be skipped. Only DRM-free files can be analyzed and played.

**External drives:** Use `/Volumes/DriveName/path/to/music`. The drive must be mounted (plugged in and visible in Finder) before starting Docker.

**Network shares (SMB/NFS):** Must be mounted in Finder first (accessible at `/Volumes/ShareName`). Performance may be poor for large libraries over network mounts — consider copying to local storage for the initial scan.

## Updating

The easiest way is to double-click **Update Familiar.command** in the `docker` folder — it opens Terminal, pulls the latest image, refreshes the scripts, and restarts Familiar automatically.

Or from Terminal:

```bash
cd ~/familiar/docker
./update.sh
```

Database migrations run automatically on startup.

## Troubleshooting

**"journald logging driver not found":**
You ran the production compose file without the macOS override. Use `./start.sh` which applies it automatically, or manually run:
```bash
docker compose -f docker-compose.prod.yml -f docker-compose.desktop.yml up -d
```

**Container killed / out of memory:**
Docker Desktop memory is too low. Increase to at least 8GB in Docker Desktop → Settings → Resources. Alternatively, add `DISABLE_CLAP_EMBEDDINGS=true` to `.env` to reduce memory usage.

**Slow file scanning:**
- Verify VirtioFS is enabled in Docker Desktop settings
- Avoid scanning over network mounts for the initial library import
- Large libraries may be slow on initial scan regardless of architecture

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
