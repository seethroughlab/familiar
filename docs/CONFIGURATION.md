# Configuration

Most settings are configured via the admin UI (Settings panel). This document covers environment variables, API key setup, and optional integrations.

## Environment Variables

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

API keys are configured via environment variables in your `.env` file (see below). Other settings (community cache, library paths) are in the **Settings** panel (gear icon).

## Getting API Keys

### Anthropic (Claude AI)

The Anthropic API powers the AI chat feature, allowing you to ask questions about your music library and get intelligent recommendations.

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Sign up or log in to your account
3. Navigate to **Settings** → **API Keys**
4. Click **Create Key** and give it a name (e.g., "Familiar")
5. Copy the key (starts with `sk-ant-...`)
6. Add it to your `.env` file as `ANTHROPIC_API_KEY=sk-ant-...` and restart Docker

**Pricing note:** Anthropic charges per token. Typical music library queries cost fractions of a cent. See [anthropic.com/pricing](https://www.anthropic.com/pricing) for current rates.

### Spotify

1. Go to https://developer.spotify.com/dashboard
2. Create a new app
3. Set redirect URI to `{FRONTEND_URL}/api/v1/spotify/callback` (e.g., `http://localhost:4400/api/v1/spotify/callback`)
4. Copy Client ID and Client Secret
5. Add them to your `.env` file as `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`, then restart Docker

### Last.fm

1. Go to https://www.last.fm/api/account/create
2. Create a new application
3. Copy API Key and API Secret
4. Add them to your `.env` file as `LASTFM_API_KEY` and `LASTFM_API_SECRET`, then restart Docker

## Tailscale HTTPS

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

Configure in **Settings** (gear icon) under **Library > Community Cache**.

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
