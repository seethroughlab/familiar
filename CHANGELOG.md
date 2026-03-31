# Changelog

All notable changes to Familiar will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-alpha1] - 2026-03-31

First alpha release of Familiar — an LLM-powered local music player that combines library management with AI-powered discovery.

### Added

#### Core
- **AI-powered music chat** using Claude API with tool use — natural language playlist creation and music discovery through conversation
- **Local music library scanning** with metadata extraction (MP3, FLAC, M4A, OGG, AIFF)
- **Multi-profile support** for household use (profile-based, no traditional auth)
- **PWA support** with offline playback, IndexedDB track caching, download queue, and playlist cache
- **Admin setup page** at `/admin` for API key and library configuration
- **Version display** and **update checker** with configurable release channel (stable/beta/alpha/disabled)

#### Audio Analysis
- **Audio analysis** with librosa for BPM, key, energy, valence, and audio features
- **CLAP embeddings** for semantic music search (optional, `DISABLE_CLAP_EMBEDDINGS=true` to skip)
- **Per-phase analysis versioning** — independent version tracking for features (`FEATURES_VERSION 8`), embeddings (`EMBEDDING_VERSION 6`), and melodic (`MELODIC_VERSION 6`) phases; bumping one phase no longer forces re-running others
- **Audio analysis overhaul** — key detection (Krumhansl-Kessler), acousticness (weighted composite), instrumentalness (silero-vad ONNX), speechiness (VAD + RMS), expanded valence model, per-feature confidence scores, cross-validation against external features
- **48 CLAP-based mood/genre/instrumentation/energy tags** with GIN-indexed JSONB storage
- **Deep track analysis** — per-track musical analysis generating downloadable Markdown reports (harmonic, rhythmic, timbral, structural, melodic transcription via basic-pitch MIDI)
- **Melodic analysis** — density-based phrase detection, fixed-window register movement, interval histograms
- **Loudness measurement** — EBU R128 loudness (`loudness_lufs`, `track_peak`, `replaygain_track_gain`) with ReplayGain tag fallback
- **AcoustID result caching** in database to avoid repeated API calls
- **FLAC remux** for PTS-less files (auto-detects and losslessly re-muxes via ffmpeg)
- **AIFF playback** via on-the-fly ffmpeg transcoding to FLAC
- **Community analysis cache** — cache hits populate deep_scalars and analysis_detail, potentially skipping entire local analysis pipeline
- **Library scan in separate process** with 8-hour timeout and 5-minute stall detection

#### Library Browser
- **Sidebar navigation** — persistent sidebar (desktop) with collapsible icon-only mode; mobile bottom nav with slide-up "More" sheet
- **Library browser views** — Album Grid, Artist Grid (with artwork and Last.fm/Spotify/album art fallback), Mood Grid (configurable axes), Music Map (ego-centric layout), Track List (sortable columns)
- **Virtualized album and artist grids** — `@tanstack/react-virtual` row-based virtualization on desktop; mobile retains infinite scroll
- **Alphabet bar** — hover-reveal A-Z navigation for lists with 100+ items, touch-drag with haptic feedback on mobile, instant scroll-to-index via sparse page fetching
- **Multi-select & context menus** — shift-click/ctrl-click selection, selection toolbar for batch actions, right-click context menu on tracks everywhere (player bar, full player, artist detail, favorites, playlists, library browser)
- **Sidebar context menus** — right-click any sidebar item for contextual actions (play, shuffle, queue, download ZIP, edit, duplicate, delete, etc.)
- **Sortable columns** in all playlist views with tri-state sort cycle and persistent sort preferences via localStorage
- **Column resizing** in playlist track lists

#### Playlists & Smart Playlists
- **Smart playlists** with rule-based track filtering, mood tag rules, and external track support
- **Ephemeral playlists** — LLM-generated playlists appear in "Unsaved" section until explicitly saved or dismissed
- **Create Empty Playlist** button next to Playlists section header
- **Playlist Discovery Mode** — AI playlists can suggest tracks you don't own, with `identify_track`, `get_similar_tracks_external`, and enhanced `queue_tracks` tools
- **Weighted random shuffle** with preset-driven track selection
- **Now Playing indicator** — green highlight and animated equalizer icon on currently playing playlist

#### Audio Playback & Effects
- **Audio engine abstraction** with registration pattern — `WebAudioEngine` for web, `CapacitorEngine` for iOS
- **10 real-time audio effects** — 3-Band EQ, Compressor, Reverb (5 algorithmic presets), Delay (ping-pong stereo), Filters (HP/LP), Stereo Width, Saturation (warm/tape/hard), Chorus, Tremolo, Bitcrusher
- **20 audio presets** — Lo-Fi, Late Night, Club, Telephone, Underwater, 80s Gated, Warm Vinyl, Live Concert, Studio Polish, Bass Boost, Dreamy, Wide Stereo, Analog Warmth, Retro 8-Bit, Thick & Lush, Vintage Amp, Psychedelic, Synthwave, Broken Radio, Spoken Word; plus custom preset save/load
- **Volume normalization** — track/album/auto modes, target LUFS, preamp, clipping prevention
- **Unified queue system** — lazy queue materializes tracks; all queue operations work identically regardless of playback source
- **Shuffle All** for large libraries — server-side `ORDER BY random()` with just-in-time metadata fetching
- **Docked Queue Panel** on desktop with drag-to-reorder, click-to-jump, remove, clear all
- **Crossfade** and transition tracking to prevent double-advancing
- **iOS background playback** — hybrid audio mode switches between Web Audio (visualizer) and direct playback (background)

#### Visualizers
- **Visualizer API** for community-contributed visualizers with full access to track metadata, audio features, real-time audio data, and timed lyrics
- **Built-in visualizers**: FrequencyBars, AlbumKaleidoscope, LyricStorm, LyricPulse, CosmicOrb, ColorFlow, Non-Places, Rain Window (Three.js/GLSL), Music Video
- **Fullscreen mode** in Full Player with auto-hiding controls

#### Discovery & Metadata
- **Ego-centric Music Map** — select any artist to center; 200 most similar artists radiate outward; lasso selection to create playlists; Figma-style controls (drag, space+drag, scroll zoom up to 15x)
- **3D Explorer audio previews** — hover to hear crossfaded previews of representative tracks
- **Semantic search** — `semantic_search` LLM tool uses CLAP text embeddings for natural language queries
- **Proposed Changes system** — LLM suggests metadata fixes via review queue with approve/reject/apply; MusicBrainz and Cover Art Archive integration
- **Duplicate artist detection** — `find_duplicate_artists` and `merge_duplicate_artists` LLM tools
- **Proactive album art downloading** from Cover Art Archive, Last.fm, and Spotify
- **Generative album art** — deterministic artwork generated from audio analysis features for albums without cover art, with vinyl label overlay
- **New Releases detail page** — `/new-releases` with infinite scroll, search, show/hide dismissed/owned, sidebar entry with live count
- **Track metadata editing** — tabbed modal (Basic, Extended, Sort, Lyrics, Analysis) with write-back to audio file tags
- **Bulk metadata editing** — dedicated endpoint for multi-track edits with common value pre-population
- **Album/artist name normalization** — case-insensitive, diacritics, quotes, dashes, whitespace; feat./ft./featuring suffix stripping
- **Last.fm similar artists** with match scores
- **LLM tools** (30+) — library search, feature distribution, mood tags, Spotify playlist import, metadata correction, semantic search, and more

#### Integrations
- **Spotify integration** — favorites sync, playlist import, GDPR data import, external favorites for unmatched tracks
- **SpotifyCompat wrapper** — handles Nov 2024 and Feb 2026 Spotify API breaking changes with centralized rate limiting (1 req/sec, 429 retry, UI countdown)
- **Last.fm scrobbling** support
- **Subsonic API** at `/rest` for CarPlay and native music app support (play:Sub, Amperfy, Symfonium)
- **Music video downloads** from YouTube via yt-dlp with auto-update

#### Offline & Downloads
- **Offline-first architecture** — IndexedDB (Dexie) for track storage, playlist caching, download queue with persistence and resume
- **Auto-Download Toggle** — enable on any playlist, smart playlist, or favorites for automatic offline sync
- **Downloads view** with total count, storage size, multi-select bulk delete, clear all
- **Downloaded-only filter** in library, playlists, and smart playlists
- **Album download** button in album header

#### Data Management
- **Library Export/Import** for migration — export metadata, analysis, embeddings, fingerprints, user overrides; intelligent matching (file_hash, acoustid, ISRC, MusicBrainz, fuzzy); gzip compression (~100MB to ~15MB)
- **S3 backup** with file size tracking, moved to global admin
- **Play history tracking** — records after 30s AND (50% or 4min), same rules as Last.fm scrobbling
- **Import quality comparison** — duplicate detection compares format tier, bitrate, sample rate, bit depth with one-click replace/skip/import

#### UI & UX
- **Toast notification system** using Sonner with loading/promise toasts and retry logic
- **Background jobs indicator** — spinner in header with detailed progress, phase labels, queue counts
- **Proposed Changes indicator** — amber badge with pending count and quick preview
- **Remote frontend logging** — logs shipped to backend via IndexedDB batching for remote diagnosis
- **Debug Settings panel** — platform detection, audio engine state, live console viewer
- **Themed scrollbars** matching dark/light theme
- **Dynamic viewport height** (`100dvh` with `100vh` fallback) and safe-area padding
- **Favorite toggle** in context menu with heart icon status
- **Auto-scroll** to currently playing track
- **Store search links** dropdown on unmatched favorites and missing tracks
- **Purchase links** for external tracks (Bandcamp, Spotify, Last.fm)

#### Infrastructure
- **Backend**: Python FastAPI with async SQLAlchemy, PostgreSQL (pgvector), Redis
- **Frontend**: React + TypeScript + Vite + Tailwind + Zustand (pnpm workspace monorepo)
- **Docker deployment** with multi-service compose, CPU-only PyTorch
- **CI pipeline** — backend (migration lint, ruff, mypy, 3 test suites), frontend (ESLint, guardrails, unit tests, bundle budget), iOS (xcodebuild), Docker build, E2E (Playwright)
- **Release workflow** — git tag triggers Docker image build and GitHub release
- **iOS app** via Capacitor with native Swift — deploy-device and release-testflight scripts
- **Lower/trim functional indexes** on PostgreSQL for faster library queries
- **Task session factory** with proper pool tuning for background tasks
- **Batch track enrichment** endpoint and album prefetching in ArtistDetail

### Known Issues

- Audio analysis can be memory-intensive on systems with <8GB RAM
- Audio effects not available on iOS (require Web Audio routing which breaks background playback)

[0.1.0-alpha1]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha1
