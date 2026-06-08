# Changelog

All notable changes to Familiar will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-alpha8] - 2026-06-07

Eighth alpha — **network audio output** arrives: stream from Familiar to a WiiM (and other UPnP/DLNA/AirPlay 2 receivers) over your LAN, with a native iOS AirPlay button in the player. Plus an **un-skip** path so files you skipped during import are no longer gone for good.

### Added

- **Network audio output (WiiM / UPnP / DLNA)** — the "Play To" picker now streams the current track to a network renderer and keeps it in sync with the player (play/pause/seek/next). Devices can be discovered on the LAN or added directly by address. Selecting a device silences the local speakers so you don't get double audio.
- **Native iOS AirPlay** — an AirPlay button in the player opens the system route picker, sending the app's audio to AirPlay 2 devices (a WiiM, HomePod, Apple TV, …) at the OS level.
- **Un-skip skipped imports** — Library → Pending Review has a new **Skipped** tab listing files you skipped during review, with per-track, per-folder, and bulk **Un-skip** to send them back to the review queue. Skipping is no longer permanent.
- **LAN stream base URL** — a runtime `DEVICE_STREAM_BASE_URL` setting so network devices can fetch the audio even when you open the app over Tailscale or a public domain (the device always gets a LAN-reachable URL, regardless of how you reached the app).

### Fixed

- **Network playback to strict renderers** — WiiM/LinkPlay devices now play correctly: the stream metadata advertises the track's real audio type instead of always claiming FLAC, and discovery/playback errors surface in logs instead of being silently swallowed.

### Infrastructure

- CI: release wait-for-CI timeout raised 30 → 60 min.

## [0.1.0-alpha7] - 2026-06-05

Seventh alpha — a major **visualizer overhaul** (a new audio-reactive vaporwave/outrun scene, richer 3D album-art tiles, and synced lyrics) plus a **library/feature cleanup** that consolidates the map browsers and status UI and adds background metadata auto-proposals.

### Added

- **Reactive Terrain visualizer** — a driving vaporwave/outrun scene that locks to the music. Hills rise **per-frequency-band across the landscape** (the spectrum mapped left→right, adaptively normalized so no region is ever inert) under a neon GL wireframe grid; a mood-based **sun/moon** with classic outrun horizontal bars and a soft light aura; **metallic "shards"** scattered across the side terrain that glow as they catch the sun; a **computer-vision detection HUD** that boxes the floating wireframe shapes; procedural **palm trees** whose individual fronds and trunk segments glow to different frequency bands; scrolling road chevrons; a **driving car** (CC0 model, neon edge highlights) with a grounded contact shadow; and a solid, height-shaded **"sound river"** waveform ribbon flowing down the road. Chromatic aberration, bloom, and fog throughout.
- **Beat Tiles visualizer** — the album cover as a grid of **3D box tiles** that pop outward in a wave **rippling from the center** on each onset. **Holographic + embossed foil** side faces (the cover drives a normal map under a fresnel iridescence), a **reflective floor** and soft blurred-cover **backdrop**, a drifting camera with an idle "breathing" wave, and flip-dot **tile flips** on strong beats. The artwork still reassembles and stays recognizable.
- **Scrolling Lyrics visualizer** — an Apple-Music-style **synced lyric column** (current line centered and bright, sung lines fading above, upcoming lines to read ahead) over an ambient **3D field of the song's own words** and a palette "aurora" wash. Synced lyrics are fetched from LRCLIB and **cached per track**.
- **Vibe Map** — a single consolidated library map, replacing the separate map browsers.
- **Background auto-proposals** — a backend service that proposes metadata changes in the background, surfaced in the Proposed Changes panel.
- **Real-time audio analysis** — onset/beat detection (spectral flux) shared across the visualizers so visuals track the actual audio.

### Changed

- **Status UI consolidated** — background-jobs, download, health, proposed-changes, and mixtape-render indicators merged into a single **Status menu**.
- **Full Player now-playing layout** — over a visualizer, the now-playing info uses the transport-bar layout (artwork left, title/artist right) instead of a thumbnail floating over the title.
- **Audio engine analysis tuning** — FFT size / smoothing adjusted so the spectrum reacts tightly to the music.

### Removed

- **Unused library browsers** — Music Map, Ego Music Map, Mood Grid, Spotify Browser, and UMAP Explorer (consolidated into Vibe Map).
- **Unused features** — S3 backup settings, playlist import/export sharing, and the keyboard-shortcuts help overlay.
- **Old visualizers** — Album Kaleidoscope, Cosmic Orb, Frequency Bars, Lyric Storm, and Rain Window (replaced by Reactive Terrain, Beat Tiles, and Scrolling Lyrics).

### Fixed

- **Synced-lyrics fetching** — lyrics no longer linger from the previous track or get overwritten by a late, out-of-order response when skipping quickly between tracks.

### Infrastructure

- New backend migration: a `synced_lyrics` JSONB cache on `tracks` (cached LRCLIB result per track).
- CI: site deploy migrated from GitHub Pages to **Cloudflare Pages**; GitHub Actions runners moved to **Node.js 24**.

## [0.1.0-alpha6] - 2026-05-26

Sixth alpha — adds network audio output routing so playback can be sent to Sonos, WiiM/UPnP, AirPlay, and Chromecast devices directly from the player bar or full player.

### Added

- **Network audio output routing** — new "Play To" selector in the player bar and full player lets you route audio to Sonos, WiiM/UPnP (generic DLNA/OpenHome), AirPlay, or Chromecast devices. "Scan for devices" discovers available outputs on the local network. Switching away from a network device stops it automatically; switching to one while a track is playing starts it immediately
- **UPnP/DLNA/OpenHome output** — covers WiiM streamers and other generic UPnP renderers via `async-upnp-client`; DIDL-Lite metadata (title, artist, album, artwork, duration) sent with each play command
- **AirPlay output** — native AirPlay 1/2 support via `pyatv`
- **Chromecast output** — cast to any Google Cast device via `pychromecast`

### Infrastructure

- iOS build number bumped to 11
- Deploy script SSH user changed from `root` to `jeff`

## [0.1.0-alpha5] - 2026-05-18

Fifth alpha — focused on reliability fixes across PWA playback, iOS audio, and first-run Docker setup for macOS, plus Opus format support and listening session simplification.

### Added

- **Opus audio format support** — `.opus` files are now recognized, scanned, and playable

### Changed

- **Listening sessions simplified** — 2D spatial room and FamiliarPicker avatar chooser removed; per-user reactions retained; session kick corrected
- **AI playlist naming** — creative naming dropped; playlists now use the user's original request as the name directly
- **iOS lock screen controls** — 15-second skip commands removed from the lock screen control set
- **Dynamic search placeholder** in the library browser now reflects the active tab (Artists, Albums, Tracks, etc.)

### Fixed

- **Continuous playback (PWA)** — a transient buffering stall near the end of a track could silently block queue advancement, leaving the player silent indefinitely; playback now always advances when a track ends regardless of prior buffering state
- **Stall recovery (PWA)** — on a slow connection the audio element can buffer and stall mid-track; the browser's `canplay` event fires when data is ready but does not guarantee auto-resume; the player now calls `play()` explicitly on recovery so the track resumes without user intervention
- **Continuous playback (PWA) regression guard** — added integration tests asserting that `engine.load()` and `engine.play()` are invoked after `ended`, that a `waiting` stall on the current track does not suppress queue advancement, and that stall-recovery via `canplay` is correctly gated on `isPlaying` state
- **macOS Docker setup: music library not mounting** — `MUSIC_LIBRARY_PATH=~/Music` in `.env` was not expanded by Docker Compose, causing the container's `/music` to be empty; `start.sh` now exports the expanded absolute path so Docker picks it up correctly
- **macOS Docker setup: blank `MUSIC_LIBRARY_PATH`** now shows a clear warning instead of falling through silently
- **iOS now-playing / lock-screen metadata** — `playing` event now emits on the first non-zero `timeUpdate` per track, fixing stale metadata on the lock screen and in CarPlay
- **iOS audio engine hardening** — audio interruptions (phone calls, Siri) handled correctly in `NativeAudioEngine`; temp files cleaned up via RAII wrapper; audio analysis tap race condition fixed
- **Full Player: music video layout** — incorrect clip offset, overlapping search view, and stray thumbnail element removed
- **Artist alias race condition** — `ON CONFLICT DO NOTHING` prevents a crash when registering artist aliases concurrently during library scan
- **AI artist playlists** — fixed playlist generation for artist-scoped queries

### Infrastructure

- **`update.sh`** — one-command update script: pulls the latest Docker image, refreshes all scripts from the master ZIP (preserving `.env`), and restarts Familiar
- **`Update Familiar.command`** — double-clickable macOS wrapper for `update.sh`; no Terminal needed for future updates
- `MACOS.md` and `INSTALLATION.md` updated to reference the new update scripts
- `start.sh` script version bumped to semver format to match the Docker image version, eliminating a spurious "scripts outdated" warning that fired on every run
- Beginner macOS install guide updated: drag-from-Finder tip promoted as primary method, "no tracks after scan" troubleshooting entry added, update instructions simplified to one step
- CI: pinned pnpm to v10, migrated `onlyBuiltDependencies` config to `pnpm-workspace.yaml`, bumped Node.js to 22

## [0.1.0-alpha4] - 2026-05-03

Fourth alpha — headline changes are CarPlay support, real-time listening sessions with a spatial 2D Room and beat-synced avatars, mixtape MP3 export with crossfades, and the canonical-artists model rolled out across the library and discovery surfaces.

### Added

- **CarPlay support** (iOS) — browse Favorites, Library (Recently Played, Artists, Albums), and Playlists from the car via native CarPlay templates. Tap any track to start playback; lock-screen now-playing metadata and favorite state stay in sync as the queue advances
- **Listening sessions** — host streams the audio you're playing over WebRTC to friends in real time. Open the Radio panel to create a session, share the code or link, and friends can join from any browser without being on your network. Participant list with kick, in-session chat, optional password, and live ICE/TURN diagnostics
- **2D Room for listening sessions** — avatars now occupy a spatial stage in the session panel: host on a DJ booth at the back (with crown + plinth glow), listeners and guests arranged as a crowd in front. Positions are deterministic from `user_id` so every client sees the same room without any extra wire traffic
- **Beat-synced avatar motion** — when something is playing, every avatar in the room bobs in unison to the host's track BPM (threaded through the 1Hz playback broadcast's `track_meta`). Falls back to a gentle 2.6s idle bob when paused or when no BPM is available; track changes pulse the room with a 1.2s glow
- **`VITE_SESSIONS_RELAY_URL`** build-time env var pointing at the public signaling relay (`familiar-sessions`); falls back to same-origin for local dev
- **`AudioEngine.getOutputStream()`** capability — Web Audio engine exposes a `MediaStream` from a lazy `MediaStreamAudioDestinationNode` off masterGain, used for WebRTC streaming
- **Hook test coverage** for the new session machinery — 20 vitest cases across `useListeningSession` (connect lifecycle, message dispatch, malformed-payload safety, leave/unmount cleanup) and `useWebRTCStreaming` (peer add/remove, guest renegotiation cleanup, host-disabled fallback)
- **CarPlayCoordinator vitest suite** — 8 cases covering startup snapshot sync, reconnect refresh, favorite/playlist track selection, cached-favorites fallback, and partial-builder-failure resilience

### Changed

- **CarPlay browse refresh is now partial-failure resilient** — coordinator uses `Promise.allSettled` with per-builder fallbacks, so a single failing backend call (e.g. flaky `playlistsApi.list`) no longer blanks every CarPlay tab. Coordinator also early-returns with a clear log when no API origin is configured, instead of silently hammering relative URLs
- **Diagnostic instrumentation** for the CarPlay data flow — `[CarPlay]` NSLog lines in the Swift bridge/scene/plugin and matching `log.info` lines in the JS coordinator make a single simulator boot enough to pinpoint which gate fails (scene attach, listener registration, profile/origin checks, builder failures, sync calls)

### Compatibility

- iOS host (listening sessions) is intentionally deferred — `CapacitorEngine` doesn't implement `getOutputStream()`. Listeners on iOS still join other people's sessions, and the panel surfaces a clear "host from a desktop browser" notice if you try to host on iOS
- CarPlay requires the iOS app installed via TestFlight and a CarPlay-compatible head unit (or the Xcode CarPlay simulator for development). The app must have at least one profile selected and a server URL configured before CarPlay tabs will populate

## [0.1.0-alpha3] - 2026-04-22

Third alpha — headline change is opt-in OpenAI-compatible LLM provider support alongside Anthropic, so installs can point at Groq, Together, OpenRouter, LocalAI, vLLM, llama.cpp, LM Studio, or Ollama's `/v1` endpoint. Also ships the public landing page at [familiar.seethroughlab.com](https://familiar.seethroughlab.com).

### Added

- **OpenAI-compatible LLM provider** — set `LLM_PROVIDER=openai` to route chat + playlist naming through any OpenAI-compatible server. Configurable `OPENAI_API_KEY`, `OPENAI_BASE_URL` (optional; defaults to api.openai.com), `OPENAI_CHAT_MODEL`, and `OPENAI_UTILITY_MODEL`
- **Provider abstraction** for chat + utility LLM calls — service layer is no longer tied to the Anthropic SDK; each provider owns its own conversation-and-tool loop and yields a normalized event stream
- **Tool-schema translation** — the 31 library tools are defined once and re-serialized to OpenAI function format at call time, with fallback for servers that reject `tool_choice="required"`
- **LLM provider selection UI** — radio toggle in Settings > AI, OpenAI status row in the API Keys panel, provider-aware copy in the chat warning banner
- **Diagnostics payload** now reports `llm_provider`, `has_openai_config`, and `active_provider_configured`
- **Public landing page** at familiar.seethroughlab.com — restyled to match the app's visual identity, expanded install guidance, sticky Install CTA, GitHub Pages workflow

### Changed

- Chat readiness (`/chat/status`) and route guards now check the *selected* provider rather than assuming Anthropic, so selecting OpenAI mode without OpenAI credentials correctly reports `configured=false`
- Exception sanitization recognizes both `anthropic.*Error` and `openai.*Error`, with auth-error copy that names the active provider

### Compatibility

- **Fully backward-compatible.** Default provider remains Anthropic; installs with only `ANTHROPIC_API_KEY` set see zero behavior change. No `settings.json` migration required — new fields default to null and fall back to env vars via existing precedence rules

## [0.1.0-alpha2] - 2026-04-17

Second alpha — focused on first-run UX, Spotify workflow improvements, LLM discovery tools, and reliability hardening across audio playback, scanner, and CI/release infrastructure.

### Added

- **Home entry screen and onboarding prompts** for first-time users
- **ARM64 native Docker support** — all dependencies including PyTorch now have arm64 wheels; release builds produce multi-arch manifest lists
- **CLAP smoke tests** — standalone script and CI job verifying PyTorch + CLAP work on both amd64 and arm64
- **New LLM tools** — new releases, discovery, and Spotify-unmatched track handling
- **Spotify endpoints** — `GET /spotify/unmatched` and `GET /spotify/stats`
- **Audio analysis diagnostics and metrics tracking** with iOS native analysis improvements
- **Beginner-friendly macOS installation guide** with start.sh/stop.sh scripts, platform detection, pre-flight checks, 8GB RAM warnings, and post-start health check
- **macOS Docker Compose override** switching journald logging to json-file (journald is Linux-only)
- **Sortable track lists on mobile**
- **Heavy pytest suite** (`FAMILIAR_HEAVY_TESTS=1`) for real CLAP inference
- **macOS Docker Compose integration CI job** booting the full stack

### Changed

- **Unified Anthropic model selection** in backend
- **Optimized Spotify sync** with artist pre-filtering and auto-favoriting
- **FrequencyBars visualizer** — refined colors and intensity
- **Release workflow fully moved to GitHub-hosted runners** with matrix-by-native-arch build (ubuntu-latest for amd64, ubuntu-24.04-arm for arm64), eliminating QEMU emulation
- **iOS CI tests** now run on the self-hosted macOS runner
- **CI hardened against transient network issues** — uv/pnpm caching, HTTP timeouts, fetch retries, persistent buildx cache, Dockerfile ENV for in-image package managers

### Fixed

- **0-byte audio files rejected in scanner** — no more stuck `skipped` tracks with NULL metadata
- **Transcoding hardened** — per-track locking, error recovery, safer defaults; playback retries once before skipping on transcode/load errors
- **Reduced audio clicking** by disconnecting idle effects from the audio graph
- **Scroll-to-current-track** works correctly with lastPlayed sort and weighted shuffle
- **Favorites listing** excludes non-active tracks
- **Docs cleanup** — outdated `/admin` references replaced with current setup instructions; beginner guide uses ZIP download instead of `git clone`; `MUSIC_LIBRARY_PATH` documented in `.env.example`

### Infrastructure

- CI and release workflows follow a clear split: self-hosted runners for everyday CI, GitHub-hosted runners for cutting releases
- Docker Build and E2E Tests in CI are advisory (`continue-on-error: true`) while the self-hosted NAS runner's upstream network is unreliable for long multi-stage builds

## [0.1.0-alpha1] - 2026-03-31

First alpha release of Familiar — an LLM-powered local music player that combines library management with AI-powered discovery.

### Added

#### Core
- **AI-powered music chat** using Claude API with tool use — natural language playlist creation and music discovery through conversation
- **Local music library scanning** with metadata extraction (MP3, FLAC, M4A, OGG, AIFF)
- **Multi-profile support** for household use (profile-based, no traditional auth)
- **PWA support** with offline playback, IndexedDB track caching, download queue, and playlist cache
- **Settings panel** for library management and configuration (API keys set via environment variables)
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

[0.1.0-alpha8]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha8
[0.1.0-alpha7]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha7
[0.1.0-alpha6]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha6
[0.1.0-alpha5]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha5
[0.1.0-alpha4]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha4
[0.1.0-alpha3]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha3
[0.1.0-alpha2]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha2
[0.1.0-alpha1]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha1
