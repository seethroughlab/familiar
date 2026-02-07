# Familiar

[![CI](https://github.com/seethroughlab/familiar/actions/workflows/ci.yml/badge.svg)](https://github.com/seethroughlab/familiar/actions/workflows/ci.yml)
[![Release](https://github.com/seethroughlab/familiar/actions/workflows/release.yml/badge.svg?event=push)](https://github.com/seethroughlab/familiar/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Describe what you want to hear.** Familiar is a local music player that understands the *sound* of your music, not just its metadata. Ask for "something that sounds like rain on a window" and it actually works.

**Your music, your server, your data.** Runs entirely on your hardware - no cloud dependency, no subscriptions, no data leaving your network.

**Community-powered analysis.** Share anonymized audio fingerprints with other users. New installations benefit instantly from pre-computed analysis, skipping hours of processing.

## Why Familiar?

Most music players search by artist, album, or genre. Familiar searches by *how music sounds*.

- **Semantic audio search** - "Find me something melancholy with piano" searches the actual audio, not just tags
- **CLAP embeddings** - AI model that understands the sound of your music, trained on millions of audio-text pairs
- **AI that knows YOUR library** - Not generic recommendations. Claude searches, filters, and creates playlists from tracks you actually own
- **Community cache** - Analysis results shared anonymously via hashed fingerprints. New users benefit instantly from the community's processing
- **Privacy-first** - Runs on your NAS or home server. Your listening data stays yours

## Screenshots

| Library Track List | AI Chat |
|:--:|:--:|
| ![Library](screenshots/01-library-tracks.png) | ![Chat](screenshots/08-chat-panel.png) |

| Music Map | Mood Grid |
|:--:|:--:|
| ![Music Map](screenshots/03-library-music-map.png) | ![Mood Grid](screenshots/02-library-mood-grid.png) |

| Full Player | Visualizer |
|:--:|:--:|
| ![Full Player](screenshots/14-mobile-full-player.png) | ![Visualizer](screenshots/06-visualizer.png) |

<details>
<summary><strong>More screenshots</strong></summary>

| Albums | Playlists |
|:--:|:--:|
| ![Albums](screenshots/04-library-albums.png) | ![Playlists](screenshots/05-playlists.png) |

| Settings | Admin Setup |
|:--:|:--:|
| ![Settings](screenshots/07-settings.png) | ![Admin Setup](screenshots/11-admin-setup.png) |

### Mobile Interface

| Library (Mobile) | Settings (Mobile) |
|:--:|:--:|
| ![Mobile Library](screenshots/12-mobile-library.png) | ![Mobile Settings](screenshots/13-mobile-settings.png) |

</details>

## Features

### Discovery & Search
- **Semantic audio search** - Describe the sound you want: "upbeat with synths", "acoustic and melancholy"
- **AI chat assistant** - 25 tools for search, playback, metadata correction, and playlist creation
- **Find similar tracks** - Click any track to find sonically similar music via CLAP embeddings
- **Mood Grid** - 2D scatter plot by energy and valence (happy/sad × calm/energetic)
- **Music Map** - Ego-centric similarity map. Click any artist to center the view
- **3D Explorer** - Navigate a 3D space of artists with hover-to-preview audio

<details>
<summary><strong>Available AI Tools (25)</strong></summary>

| Tool | Description |
|------|-------------|
| **Search & Discovery** | |
| `search_library` | Text search across title, artist, album, genre |
| `semantic_search` | Natural language search by mood/style via CLAP embeddings |
| `find_similar_tracks` | Find sonically similar tracks using audio embeddings |
| `filter_tracks_by_features` | Filter by BPM, energy, key, danceability, valence |
| `get_similar_artists_in_library` | Find similar artists (via Last.fm) that exist in your library |
| **Library Info** | |
| `get_library_stats` | Total tracks, artists, albums, top genres |
| `get_library_genres` | List all genres with track counts |
| `get_visible_tracks` | Get tracks currently shown in the UI |
| `get_track_details` | Detailed track info including audio features |
| **Playback** | |
| `queue_tracks` | Add tracks to the playback queue |
| `control_playback` | Play, pause, next, previous, shuffle |
| `select_diverse_tracks` | Ensure variety across artists/albums |
| **Spotify Integration** | |
| `get_spotify_status` | Check if Spotify is connected |
| `get_spotify_favorites` | Get Spotify likes matched to local library |
| `unmatched_spotify_favorites` | Spotify likes you don't have locally |
| `get_spotify_sync_stats` | Match rate and sync statistics |
| **Discovery** | |
| `search_bandcamp` | Search Bandcamp for albums/tracks to purchase |
| `recommend_bandcamp_purchases` | Suggest albums based on unmatched Spotify favorites |
| **Metadata Correction** | |
| `lookup_correct_metadata` | Look up correct metadata from MusicBrainz |
| `propose_metadata_change` | Propose a metadata fix for user review |
| `get_album_tracks` | Get all tracks from a specific album |
| `mark_album_as_compilation` | Set album_artist for compilation albums |
| `propose_album_artwork` | Search and propose album artwork from Cover Art Archive |
| `find_duplicate_artists` | Find artists with variant spellings |
| `merge_duplicate_artists` | Propose merging duplicate artist names |

</details>

### Playback & Experience
- **Synced lyrics** - Auto-scrolling lyrics display fetched from LRCLIB.net
- **6 audio visualizers** - Cosmic Orb, Frequency Bars, Album Kaleidoscope, Color Flow, Lyric Storm, Typography Wave
- **Visualizer plugins** - Open API for community visualizers ([create your own](docs/VISUALIZER_API.md))
- **Music video playback** - Download and match music videos from YouTube
- **Keyboard shortcuts** - Full keyboard control (press `?` for help)
- **Multi-profile support** - Each household member gets their own favorites and history

### Library Management
- **Fast scanning with community cache** - Pre-computed analysis from other users speeds up initial scan
- **Audio analysis** - BPM, key detection, energy, danceability, and more via librosa
- **CLAP embeddings** - Semantic audio search powered by LAION's CLAP model
- **Smart playlists** - Dynamic playlists with rules for BPM, key, energy, genre, and more
- **Metadata editing** - Right-click to edit, AI-assisted corrections, duplicate artist detection
- **AcoustID fingerprinting** - Identify unknown tracks
- **Cloud backup** - S3 Glacier Deep Archive backup (~$1/TB/month) with scheduled backups and restore

### Mobile & Offline
- **PWA support** - Install on mobile or desktop, works offline
- **Download tracks** - Cache music for offline playback
- **Lock screen controls** - Media notifications and controls
- **Works over Tailscale** - Access your library anywhere with HTTPS

### Integrations
- **Spotify sync** - Import your Spotify favorites, see what you're missing locally
- **Last.fm scrobbling** - Automatic scrobbling, love/unlove tracks
- **Bandcamp discovery** - Search and get purchase recommendations

## Keyboard Shortcuts

Press `?` anytime to see all shortcuts.

| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `←` / `→` | Previous / Next track |
| `↑` / `↓` | Volume up / down |
| `J` / `L` | Seek backward / forward 10s |
| `S` | Toggle shuffle |
| `R` | Cycle repeat mode |
| `M` | Mute / Unmute |
| `F` | Toggle full player |
| `Esc` | Close overlay |
| `?` | Show shortcuts help |

## Community Cache

Familiar includes an optional community cache that shares pre-computed audio analysis between users.

**How it works:**
1. When you scan a track, Familiar generates an AcoustID fingerprint
2. The fingerprint is hashed (SHA256) - one-way, anonymous, not reversible
3. The hash is used to look up pre-computed CLAP embeddings and audio features
4. If found, analysis is instant. If not, Familiar computes locally and optionally contributes back

**Privacy guarantees:**
- Only hashed fingerprints are transmitted - no track names, artists, or file paths
- Fingerprint hashes are one-way - your library contents cannot be determined
- Contribution is opt-in (lookup is enabled by default)

**Benefits:**
- New installations can skip hours of audio analysis
- Popular tracks are analyzed once across the community
- Your processing helps future users

Configure in Admin (`/admin`) under Community Cache.

## Cloud Backup

Familiar can back up your entire music library and configuration to Amazon S3 Glacier Deep Archive for long-term archival storage at ~$1/TB/month.

**What gets backed up:**
- Audio files from all configured library paths
- Database (tracks, playlists, analysis data)
- Settings and configuration
- Album artwork and music videos
- User profiles and favorites

**Setup:**

1. **Set S3 credentials** in your `docker/.env` file:
   ```bash
   S3_BACKUP_ACCESS_KEY_ID=your-access-key
   S3_BACKUP_SECRET_ACCESS_KEY=your-secret-key
   S3_BACKUP_BUCKET=your-bucket-name
   S3_BACKUP_REGION=us-east-1
   S3_BACKUP_PREFIX=familiar/   # optional, organizes files in bucket
   ```

2. **Enable and configure** in Settings > Cloud Backup:
   - Click "Validate Credentials" to verify your S3 access
   - Enable scheduled backups (daily/weekly/monthly)
   - Or run a manual backup immediately

3. **Restore** from the same Settings panel - select a backup snapshot and restore specific components (database, settings, audio files, etc.)

**Note:** Glacier Deep Archive has a 12-hour retrieval time for restores. Standard retrieval fees apply (~$0.02/GB).

## Quick Start

```bash
git clone https://github.com/seethroughlab/familiar.git
cd familiar/docker
cp .env.example .env
# Edit .env: set MUSIC_LIBRARY_PATH and FRONTEND_URL
docker compose -f docker-compose.prod.yml up -d
```

Access at http://localhost:4400, then go to `/admin` to configure API keys and start a library scan.

**Music Library:** Set `MUSIC_LIBRARY_PATH` in `.env` to your music folder (e.g., `/srv/music`, `/volume1/music`, `~/Music`). It's mounted at `/music` inside the container.

## Upgrading

Pull the latest image and restart:

```bash
docker pull ghcr.io/seethroughlab/familiar:latest
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
```

Database migrations run automatically on startup.

## Installation

### Docker (Recommended)

#### Prerequisites
- Docker Engine 24.0+
- Docker Compose v2.0+
- 2GB+ RAM available
- Music library accessible to Docker

#### Standard Installation

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

4. **Access the UI** at http://localhost:4400 and go to `/admin` to configure API keys.

### OpenMediaVault Installation

Familiar works great on OpenMediaVault NAS systems. Here's how to set it up:

#### Prerequisites
- OpenMediaVault 6.x or 7.x
- Docker plugin (omv-extras) installed
- Portainer or command-line access
- Shared folder with your music library

#### Step-by-Step Guide

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
         - /path/to/music:/music:rw  # Your music library (rw allows imports)
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
   - Go to `/admin` to configure API keys and start a scan

#### Optional: HTTPS Access via nginx Proxy

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

#### Updating on OpenMediaVault

To update to a new version:

```bash
# Pull the latest image
docker pull ghcr.io/seethroughlab/familiar:latest

# Restart the containers
cd /path/to/familiar
docker compose down && docker compose up -d

# Or via OMV web UI:
# Compose → Files → Select familiar → Down → Pull → Up
```

#### Troubleshooting OMV Installation

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

### Synology NAS Installation

Familiar supports Synology NAS with Container Manager (DSM 7.2+) or Docker (older DSM).

#### Supported Models

**ARM64 models** (most common):
- DS218, DS220+, DS220j
- DS418, DS420+, DS420j
- DS720+, DS920+, DS923+
- RS820+, RS1221+

**x86 models** (Intel/AMD):
- DS920+, DS1621+, DS1821+
- DS3622xs+, RS3621xs+
- Any model with Intel Celeron, Atom, or Xeon

#### Step-by-Step Guide

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
         - /volume1/music:/music:rw  # Your music library (rw allows imports)
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
   - Go to `/admin` to configure API keys and start a library scan

#### Updating on Synology

1. Go to Container Manager → Project → familiar
2. Click "Action" → "Build" (this pulls latest images)
3. Containers will restart automatically

#### Troubleshooting Synology

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

### Development Setup

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

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and customize for your deployment:

```bash
cp .env.example .env
# Edit .env with your settings
```

| Variable | Description | Default |
|----------|-------------|---------|
| `MUSIC_LIBRARY_PATH` | Host path to your music folder (mounted at `/music`) | `/data/music` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `FRONTEND_URL` | Base URL for OAuth callbacks | `http://localhost:4400` |
| `S3_BACKUP_ACCESS_KEY_ID` | AWS access key for S3 backup | *(none)* |
| `S3_BACKUP_SECRET_ACCESS_KEY` | AWS secret key for S3 backup | *(none)* |
| `S3_BACKUP_BUCKET` | S3 bucket name for backups | *(none)* |
| `S3_BACKUP_REGION` | AWS region for S3 bucket | `us-east-1` |
| `S3_BACKUP_PREFIX` | Key prefix for backup objects in bucket | *(none)* |

**Important:** If accessing Familiar from a remote machine (not localhost), update `FRONTEND_URL` to use your server's hostname or IP address:
```
FRONTEND_URL=http://myserver:4400
```

All other settings (API keys, community cache) are configured via the Admin UI at `/admin`.

### Getting API Keys

**Anthropic (Claude AI):**

The Anthropic API powers the AI chat feature, allowing you to ask questions about your music library and get intelligent recommendations.

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Sign up or log in to your account
3. Navigate to **Settings** → **API Keys**
4. Click **Create Key** and give it a name (e.g., "Familiar")
5. Copy the key (starts with `sk-ant-...`)
6. Add it in Familiar's Admin UI at `/admin`

**Pricing note:** Anthropic charges per token. Typical music library queries cost fractions of a cent. See [anthropic.com/pricing](https://www.anthropic.com/pricing) for current rates.

**Spotify:**
1. Go to https://developer.spotify.com/dashboard
2. Create a new app
3. Set redirect URI to `{FRONTEND_URL}/api/v1/spotify/callback` (e.g., `http://localhost:4400/api/v1/spotify/callback`)
4. Copy Client ID and Client Secret
5. Add them in Familiar's Admin UI at `/admin`

**Last.fm:**
1. Go to https://www.last.fm/api/account/create
2. Create a new application
3. Copy API Key and API Secret
4. Add them in Familiar's Admin UI at `/admin`

### Tailscale HTTPS

If you access Familiar over [Tailscale](https://tailscale.com/), you can enable HTTPS for full PWA support (install prompts, background sync, etc.).

1. **Enable HTTPS certificates** in your Tailscale admin console:
   - Go to [DNS settings](https://login.tailscale.com/admin/dns)
   - Enable "HTTPS Certificates"

2. **Use `tailscale serve`** on your server (easiest method):
   ```bash
   # Proxy HTTPS to Familiar on port 4400
   tailscale serve --bg https / http://localhost:4400
   ```

3. **Access via HTTPS:**
   ```
   https://your-server.<tailnet-name>.ts.net
   ```

This automatically provisions a Let's Encrypt certificate and handles renewal.

**Alternative: Manual certificates**

If you need cert files for nginx/caddy:
```bash
tailscale cert your-server.<tailnet-name>.ts.net
```

This creates `.crt` and `.key` files (you're responsible for renewal every 90 days).

See [Tailscale HTTPS docs](https://tailscale.com/kb/1153/enabling-https) for more details.

## Coming Soon

Features planned for future releases:

### Listening Sessions (WebRTC)
Share what you're listening to with friends in real-time. Host a session, share a link, and guests hear synchronized audio - no account required. Requires public signaling server deployment.

### Multi-Room Audio
Play to Sonos speakers and AirPlay devices in addition to browser audio. Control playback across multiple rooms with per-room volume controls.

### Additional LLM Providers
Support for more AI providers beyond Claude and Ollama, including OpenAI (ChatGPT), Google Gemini, and other compatible APIs.

## Documentation

- **[Visualizer API](docs/VISUALIZER_API.md)** - Create custom audio visualizers with full metadata access
- **[Library Browser API](docs/LIBRARY_BROWSERS.md)** - Create custom 2D/3D library visualizations
- **[REST API Reference](docs/REST-API.md)** - Backend REST API documentation

## Community Plugins

Extend Familiar with community-created visualizers:
- **[Lyric Pulse](https://github.com/seethroughlab/familiar-plugin-lyric-pulse)** - BPM-synced lyric display with glowing pulse effects
- **[Timeline](https://github.com/seethroughlab/familiar-plugin-timeline)** - Visual timeline showing track position and upcoming lyrics

## Beta Feedback

Familiar is in active development and we'd love your feedback!

**What's most helpful:**
- Bug reports with steps to reproduce
- Feature requests with use cases
- Performance issues (especially on NAS devices)
- UI/UX suggestions

**How to report:**
- [GitHub Issues](https://github.com/seethroughlab/familiar/issues) - Bugs and feature requests
- Include your platform, Docker version, and relevant logs (`docker logs familiar-api`)

## Project Structure

```
familiar/
├── backend/          # Python FastAPI backend
│   ├── app/
│   │   ├── api/      # API routes
│   │   ├── db/       # Database models
│   │   ├── services/ # Business logic
│   │   └── workers/  # Background tasks
│   └── tests/
├── frontend/         # React + TypeScript PWA
│   ├── src/
│   │   ├── api/      # API client
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── services/ # Offline, sync services
│   │   └── stores/   # Zustand state
├── docker/           # Docker configuration
└── data/             # Runtime data (gitignored)
    ├── art/          # Extracted album art
    └── videos/       # Downloaded music videos
```

## Open Questions

We'd love your feedback on these potential features:

### Should Familiar support GPU acceleration for audio analysis?

Currently, audio analysis runs on CPU only (~6-7 seconds per track). GPU acceleration could speed up the CLAP embedding generation by 3-5x, but comes with trade-offs:

**Pros:**
- Faster initial library scan (important for large libraries)
- CLAP embeddings ~3-5x faster on GPU

**Cons:**
- Docker image size increases from ~1.5GB to ~3-4GB
- Requires nvidia-docker and CUDA drivers on host
- Most NAS devices don't have GPUs
- librosa (BPM, key detection) is CPU-only regardless

**Would GPU support be useful for your setup?** [Open an issue](https://github.com/seethroughlab/familiar/issues) to share your thoughts!

## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting PRs.

## License

MIT License - see [LICENSE](LICENSE) for details.
