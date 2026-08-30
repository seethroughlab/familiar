# Installation Guide

Familiar runs as a Docker stack (app + PostgreSQL + Redis). Choose the guide for your platform below.

> **macOS?** See the dedicated [macOS Installation Guide](MACOS.md) for Docker Desktop setup, Apple Silicon notes, and macOS-specific troubleshooting.

## Quick Start

```bash
git clone https://github.com/seethroughlab/familiar.git
cd familiar/docker
cp .env.example .env
# Edit .env: set MUSIC_LIBRARY_PATH and FRONTEND_URL
docker compose -f docker-compose.prod.yml up -d
```

> **Note:** The production compose file uses the `journald` logging driver (Linux-only). On macOS, use the [macOS guide](MACOS.md) or add the override: `docker compose -f docker-compose.prod.yml -f docker-compose.desktop.yml up -d`

Access at http://localhost:4400. API keys are configured in your `.env` file — open **Settings** (gear icon) to manage your library and start a scan.

**Music Library:** Set `MUSIC_LIBRARY_PATH` in `.env` to your music folder (e.g., `/srv/music`, `/volume1/music`, `~/Music`). It's mounted at `/music` inside the container.

## Upgrading

Run the update script from the `docker` folder:

```bash
cd ~/familiar/docker
./update.sh
```

This pulls the latest image, refreshes the scripts, and restarts Familiar. Database migrations run automatically on startup.

On macOS you can also double-click **Update Familiar.command** in the `docker` folder instead of using Terminal.

---

## Docker (Standard)

### Prerequisites
- Docker Engine 24.0+
- Docker Compose v2.0+
- 2GB+ RAM available
- Music library accessible to Docker

### Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/seethroughlab/familiar.git
   cd familiar/docker
   ```

2. **Create environment file:**
   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set:
   - `MUSIC_LIBRARY_PATH` - path to your music library on the host
   - `FRONTEND_URL` - your server's URL (e.g., `http://myserver:4400`)

3. **Start the services:**
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

4. **Access the UI** at http://localhost:4400. API keys are set in your `.env` file — open **Settings** (gear icon) to start a library scan.

---

## OpenMediaVault

Familiar works great on OpenMediaVault NAS systems. Here's how to set it up.

### Prerequisites
- OpenMediaVault 6.x or 7.x
- Docker plugin (omv-extras) installed
- Portainer or command-line access
- Shared folder with your music library

### Step-by-Step Guide

1. **Enable Docker in OMV:**
   - Install `openmediavault-compose` plugin from omv-extras
   - Go to Services → Compose → Settings and enable it

2. **Create a shared folder for app data:**

   Create a folder called `familiar` on your data disk for app data (postgres, redis, settings).

   Your music library should already exist somewhere on your NAS.

3. **Create the compose file:**

   Go to Services → Compose → Files → Add:

   **Name:** `familiar`

   **File content:** (replace `/path/to` placeholders with your actual paths)
   ```yaml
   services:
     postgres:
       image: pgvector/pgvector:pg16
       container_name: familiar-postgres
       restart: unless-stopped
       environment:
         POSTGRES_USER: familiar
         POSTGRES_PASSWORD: familiar
         POSTGRES_DB: familiar
       volumes:
         - /path/to/familiar/postgres:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U familiar"]
         interval: 10s
         timeout: 5s
         retries: 5

     redis:
       image: redis:7-alpine
       container_name: familiar-redis
       restart: unless-stopped
       volumes:
         - /path/to/familiar/redis:/data
       healthcheck:
         test: ["CMD", "redis-cli", "ping"]
         interval: 10s
         timeout: 5s
         retries: 5

     api:
       image: ghcr.io/seethroughlab/familiar:latest
       container_name: familiar-api
       restart: unless-stopped
       ports:
         - "4400:8000"
       volumes:
         - /path/to/music:/music:ro  # Your music library (read-only)
         - /path/to/familiar/data:/app/data
         - /path/to/familiar/art:/data/art
         - /path/to/familiar/videos:/data/videos
       environment:
         - DATABASE_URL=postgresql+asyncpg://familiar:familiar@postgres:5432/familiar
         - REDIS_URL=redis://redis:6379/0
         - FRONTEND_URL=http://your-omv-ip:4400
       depends_on:
         postgres:
           condition: service_healthy
         redis:
           condition: service_healthy
   ```

   **Note:** Replace `/path/to/music` with your actual music folder path (e.g., `/srv/dev-disk-by-uuid-.../music` on OpenMediaVault).

4. **Start the stack:**
   - Click the "Up" button in Compose → Files
   - Or via SSH: `docker compose -f /path/to/familiar.yml up -d`

5. **Access Familiar:**
   - Open `http://your-omv-ip:4400` in a browser
   - Open **Settings** (gear icon) to start a library scan

### Optional: HTTPS Access via nginx Proxy

If you want to access Familiar over HTTPS using OMV's SSL certificate (recommended for Tailscale HTTPS):

1. Create a proxy configuration file:
   ```bash
   nano /etc/nginx/openmediavault-webgui.d/familiar.conf
   ```

2. Add this content:
   ```nginx
   location /familiar/ {
       proxy_pass http://127.0.0.1:4400/;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

3. Reload nginx:
   ```bash
   nginx -t && systemctl reload nginx
   ```

4. Access Familiar at `https://your-omv-ip/familiar/`

### Updating on OpenMediaVault

To update to a new version, SSH in and run:

```bash
cd /path/to/familiar/docker
./update.sh
```

Or via the OMV web UI: Compose → Files → Select familiar → Down → Pull → Up.

### Troubleshooting OMV Installation

**Permission issues with music files:**
```bash
# Check container can read music
docker exec familiar-api ls -la /music

# If permission denied, ensure OMV shared folder permissions allow Docker
```

**Database connection errors:**
```bash
# Check postgres is healthy
docker logs familiar-postgres
```

**Background tasks not processing:**
```bash
# Check API logs (background tasks run in-process)
docker logs familiar-api

# Ensure Redis is running
docker exec familiar-redis redis-cli ping
```

**ARM64 audio analysis crashes (Raspberry Pi, ARM-based boards):**

If running on ARM64 hardware, add these environment variables to prevent analysis crashes:
```yaml
environment:
  - DISABLE_CLAP_EMBEDDINGS=true
  - OPENBLAS_NUM_THREADS=1
  - OMP_NUM_THREADS=1
```

---

## Synology NAS

Familiar supports Synology NAS with Container Manager (DSM 7.2+) or Docker (older DSM).

### Supported Models

**ARM64 models** (most common):
- DS218, DS220+, DS220j
- DS418, DS420+, DS420j
- DS720+, DS920+, DS923+
- RS820+, RS1221+

**x86 models** (Intel/AMD):
- DS920+, DS1621+, DS1821+
- DS3622xs+, RS3621xs+
- Any model with Intel Celeron, Atom, or Xeon

### Step-by-Step Guide

1. **Install Container Manager:**
   - Open Package Center
   - Search for "Container Manager" (DSM 7.2+) or "Docker" (older DSM)
   - Install and open it

2. **Create folders for Familiar app data:**
   ```
   /volume1/docker/familiar/          # App data
   /volume1/docker/familiar/postgres  # Database
   /volume1/docker/familiar/redis     # Cache
   /volume1/docker/familiar/art       # Album artwork
   /volume1/docker/familiar/videos    # Music videos
   ```

   Your music library should already exist somewhere on your NAS (e.g., `/volume1/music/`).

3. **Create a Project in Container Manager:**
   - Go to Project → Create
   - **Project name:** `familiar`
   - **Path:** `/volume1/docker/familiar`
   - **Source:** Create docker-compose.yml

4. **Paste this docker-compose.yml:**
   ```yaml
   services:
     postgres:
       image: pgvector/pgvector:pg16
       container_name: familiar-postgres
       restart: unless-stopped
       environment:
         POSTGRES_USER: familiar
         POSTGRES_PASSWORD: familiar
         POSTGRES_DB: familiar
       volumes:
         - /volume1/docker/familiar/postgres:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U familiar"]
         interval: 10s
         timeout: 5s
         retries: 5

     redis:
       image: redis:7-alpine
       container_name: familiar-redis
       restart: unless-stopped
       volumes:
         - /volume1/docker/familiar/redis:/data
       healthcheck:
         test: ["CMD", "redis-cli", "ping"]
         interval: 10s
         timeout: 5s
         retries: 5

     api:
       image: ghcr.io/seethroughlab/familiar:latest
       container_name: familiar-api
       restart: unless-stopped
       ports:
         - "4400:8000"
       volumes:
         - /volume1/music:/music:ro  # Your music library (read-only)
         - /volume1/docker/familiar/data:/app/data
         - /volume1/docker/familiar/art:/data/art
         - /volume1/docker/familiar/videos:/data/videos
       environment:
         - DATABASE_URL=postgresql+asyncpg://familiar:familiar@postgres:5432/familiar
         - REDIS_URL=redis://redis:6379/0
         - FRONTEND_URL=http://your-synology-ip:4400
       depends_on:
         postgres:
           condition: service_healthy
         redis:
           condition: service_healthy
   ```

   **Note:** Adjust `/volume1/music` to your music library path and `FRONTEND_URL` to your Synology's IP.

5. **Build and start:**
   - Click "Build" to pull images and start containers
   - Wait for all containers to show as "Running"

6. **Access Familiar:**
   - Open `http://your-synology-ip:4400`
   - Open **Settings** (gear icon) to start a library scan

### Updating on Synology

1. Go to Container Manager → Project → familiar
2. Click "Action" → "Build" (this pulls latest images)
3. Containers will restart automatically

### Troubleshooting Synology

**ARM64 audio analysis issues:**

Audio analysis may crash on ARM-based devices due to OpenBLAS/numpy threading issues. Add these environment variables to your api service:
```yaml
environment:
  - DISABLE_CLAP_EMBEDDINGS=true
  - OPENBLAS_NUM_THREADS=1
  - OMP_NUM_THREADS=1
```

This disables the heavy CLAP model and limits thread usage to prevent crashes. Basic audio analysis (BPM, key detection) will still work.

**Permission denied errors:**

Synology uses specific user/group IDs. If you see permission errors:
1. SSH into your Synology
2. Run: `sudo chown -R 1000:1000 /volume1/docker/familiar`

**Container won't start:**

Check logs in Container Manager → Container → familiar-api → Log

---

## Development Setup

For local development without Docker:

1. **Start infrastructure:**
   ```bash
   cd docker
   docker compose up -d  # Starts postgres and redis only
   ```

2. **Install backend:**
   ```bash
   cd backend
   uv sync --all-extras
   uv run python -m app.db.init_db
   ```

3. **Run API server:**
   ```bash
   make run
   ```

4. **Run worker (separate terminal):**
   ```bash
   make worker
   ```

5. **Run frontend (separate terminal):**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
