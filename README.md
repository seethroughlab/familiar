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
- **CarPlay / Android Auto** - Stream via [Subsonic-compatible apps](docs/SUBSONIC.md)
- **Works over Tailscale** - Access your library anywhere with HTTPS

### Integrations
- **Spotify sync** - Import your Spotify favorites, see what you're missing locally
- **Last.fm scrobbling** - Automatic scrobbling, love/unlove tracks
- **Bandcamp discovery** - Search and get purchase recommendations
- **Subsonic API** - Connect native music apps for CarPlay/Android Auto ([setup guide](docs/SUBSONIC.md))

## Quick Start

```bash
git clone https://github.com/seethroughlab/familiar.git
cd familiar/docker
cp .env.example .env
# Edit .env: set MUSIC_LIBRARY_PATH and FRONTEND_URL
docker compose -f docker-compose.prod.yml up -d
```

Access at http://localhost:4400, then go to `/admin` to configure API keys and start a library scan.

See the **[Installation Guide](docs/INSTALLATION.md)** for detailed platform-specific instructions (OpenMediaVault, Synology NAS, development setup).

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

## Documentation

- **[Installation Guide](docs/INSTALLATION.md)** - Docker, OpenMediaVault, Synology NAS, and development setup
- **[Configuration](docs/CONFIGURATION.md)** - Environment variables, API keys, Tailscale HTTPS, cloud backup
- **[Subsonic / CarPlay Setup](docs/SUBSONIC.md)** - Connect native music apps for CarPlay and Android Auto
- **[Visualizer API](docs/VISUALIZER_API.md)** - Create custom audio visualizers with full metadata access
- **[Library Browser API](docs/LIBRARY_BROWSERS.md)** - Create custom 2D/3D library visualizations
- **[REST API Reference](docs/REST-API.md)** - Backend REST API documentation

## Community Plugins

Extend Familiar with community-created visualizers:
- **[Lyric Pulse](https://github.com/seethroughlab/familiar-plugin-lyric-pulse)** - BPM-synced lyric display with glowing pulse effects
- **[Timeline](https://github.com/seethroughlab/familiar-plugin-timeline)** - Visual timeline showing track position and upcoming lyrics

## Coming Soon

Features planned for future releases:

### Listening Sessions (WebRTC)
Share what you're listening to with friends in real-time. Host a session, share a link, and guests hear synchronized audio - no account required. Requires public signaling server deployment.

### Multi-Room Audio
Play to Sonos speakers and AirPlay devices in addition to browser audio. Control playback across multiple rooms with per-room volume controls.

### Additional LLM Providers
Support for more AI providers beyond Claude and Ollama, including OpenAI (ChatGPT), Google Gemini, and other compatible APIs.

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

## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting PRs.

## License

MIT License - see [LICENSE](LICENSE) for details.
