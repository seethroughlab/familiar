# Changelog

All notable changes to Familiar will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0-alpha.10] - 2026-02-20

Sidebar Navigation, Deep Analysis & External Tracks

### Added

- **Sidebar navigation layout** — Replaced tab-based navigation with a persistent sidebar (desktop) and mobile bottom nav
  - Desktop: 240px sidebar with collapsible icon-only mode, sections for Library views, Collections (Favorites/Downloads/Wishlist with live counts), Playlists, and Smart Playlists
  - Mobile: 5-item bottom nav (Tracks, Artists, Favorites, Chat, More) plus slide-up "More" sheet for full navigation
  - Right panel hosts Queue and Chat on desktop; full-screen overlays on mobile
  - Chat toggle moved from header to PlayerBar and mobile bottom nav
- **Deep track analysis** — Per-track musical analysis generating downloadable Markdown reports
  - Harmonic: chord detection (84 templates), Roman numeral progressions, mode detection (Ionian through Locrian)
  - Rhythmic: swing ratio, syncopation, Euclidean rhythm identification (Tresillo, Bossa Nova, Samba, etc.)
  - Timbral/spectral character, structural form detection, optional melodic transcription via basic-pitch MIDI
  - Bulk analysis (up to 50 tracks) via context menu with toast progress notifications
  - New API: `POST /tracks/analysis/bulk`, poll + download Markdown report
- **Per-phase analysis versioning** — Independent version tracking for features, embeddings, and melodic phases
  - Three constants: `FEATURES_VERSION`, `EMBEDDING_VERSION`, `MELODIC_VERSION`
  - Bumping one phase no longer forces re-running the other phases across the entire library
  - Separate `features_version`, `embedding_version`, `melodic_version` columns on `TrackAnalysis`
- **Spotify GDPR data import** — Upload your Spotify "Download your data" zip to import saved tracks, playlists, and streaming history
  - Parses `YourLibrary.json`, `Playlist*.json`, and `Streaming_History_Audio*.json`
  - Fuzzy matching against local library
- **SpotifyCompat wrapper** — Handles Nov 2024 and Feb 2026 Spotify API breaking changes
  - Normalizes renamed endpoints (`playlist_tracks` → `playlist_items`), missing fields (`preview_url`, `popularity`, ISRC)
  - Centralized 1 req/sec rate limiting with 429 retry (up to 5 attempts) and cooldown countdown in UI
- **Remote frontend logging** — Frontend logs shipped to backend for remote diagnosis
  - Captures all `createLogger()` output plus uncaught errors to IndexedDB
  - Batches and POSTs to `/api/v1/diagnostics/frontend-logs` every 30 seconds
  - Flushes on `visibilitychange` (catches iOS tab kills)
  - Settings panel with remote log viewer, level/namespace filters, and manual flush
- **External favorites system** — Favorite tracks not in your local library
  - New `profile_external_favorites` table with migration
  - Spotify sync promotes unmatched favorites to external favorites
  - `useFavorites` hook extended with `isExternalFavorite`, `toggleExternal`, `externalFavorites`
- **External tracks in Library browser** — Unmatched external tracks appear in main track list
  - Tracks API `include_external` parameter for UNION queries across local and external tracks
  - Tagged with "External" badge and Spotify link button
- **External tracks in Smart Playlists** — Smart playlists include external tracks when rules use compatible fields
  - New `get_tracks_unified` method with UNION-based pagination
- **Sortable columns in all playlist views** — Favorites, Playlists, Smart Playlists, Ephemeral Playlists, Downloads
  - Tri-state sort cycle: ascending → descending → clear (isolated from library sort state)
  - CSS grid layout for proper column alignment; dynamic columns hidden on mobile
  - New shared `PlaylistColumnHeader` and `PlaylistColumns` components
- **Purchase links (Buy button)** for external tracks — links to find tracks on storefronts
- **Toggle to skip external track preview playback** — opt out of 30-second previews
- **Last.fm similar artists with match scores** — improved similarity results
- **FLAC remux for PTS-less files** — Auto-detects FLAC files missing PTS timestamps (causes Chromium "FFmpegDemuxer: PTS is not defined" error) and losslessly re-muxes via `ffmpeg -c:a copy` with atomic in-place replacement
- **AIFF playback support** — AIFF files now stream via on-the-fly ffmpeg transcoding to FLAC
- **Batch track enrichment** — New `POST /tracks/enrich-batch` endpoint replaces N individual requests from ArtistDetail
- **Album prefetching in ArtistDetail** — First 5 albums prefetched on artist load for near-instant navigation
- **Lower/trim functional indexes** — PostgreSQL indexes on `lower(trim(artist))`, `lower(trim(album))`, `lower(trim(coalesce(nullif(album_artist,''),artist)))` for faster library queries on the 23K-track library
- **Themed scrollbars** — Custom scrollbar styling matching dark/light theme
- **Sync phase labels** — BackgroundJobsIndicator shows human-readable phase names (Discovering files, Extracting features, Generating embeddings)
- **Sync stall detection** — Library sync has 8-hour total timeout and 5-minute stall detection that re-queues stuck tracks

### Changed

- **Expanded playlist API responses** — All playlist-type APIs return full track metadata (format, year, genre, track/disc number, album_artist, album_type, analysis_version)
- **Track type extended for external tracks** — `Track` type includes `track_type`, `preview_url`, `matched_track_id`, `external_data`, `source`, `spotify_id`
- **Player store handles external tracks natively** — `setQueue`, `refillFromReservoir`, and shuffle attach `externalInfo` for external tracks
- **Player hydration improved** — Two-phase restore: playback settings (volume, shuffle, repeat) restored instantly, queue fetched in background via batched parallel API calls (chunks of 50, up to 3 concurrent)
- **Audio engine refactored** — Extracted `useAudioControls` hook (safe to call from multiple components) from `useAudioEngine` (singleton with event listeners)
- **Album detail queries parallelized** — `get_album_detail` uses `asyncio.gather` for concurrent DB queries
- **RainWindow visualizer rewritten** — Full rewrite from 2D Canvas to Three.js/GLSL two-pass FBO rendering with refraction, SSS, caustics, surface tension, and bead physics

### Fixed

- **Spotify rate limiting** — Disabled spotipy's internal retry (was sleeping 11.5 hours on 429), added centralized 1 req/sec throttle, capped retry wait at 5 minutes, rate limit cooldown stored in Redis with UI countdown
- **Spotify sync duplicate key error** — Deduplicate `matched_local_track_ids` (multiple Spotify tracks matching same local track)
- **isLoadingAudio stuck after crossfade** — Changed element identity check to `data-track-id` comparison during crossfade transitions
- **Album navigation from ArtistDetail** — Added `?source=artist` param to skip album_artist lookup; fallback to `navigateToAlbumDetail` when no parent callback
- **BackgroundJobsIndicator popover clipped** — Render via `createPortal` to `document.body`
- **Columns dropdown behind content** — Same `createPortal` fix for `ColumnSelector`
- **Shuffle toggle for empty/single-track queues** — Edge case handling
- **Music Map broken image placeholder** — Show Music icon instead of broken image; case-insensitive artist grouping
- **Track names invisible on mobile** — Fixed in all playlist views
- **Spotify settings card cramped on mobile** — Layout fix
- **playPrevious not seeking audio** — Was only updating store state, now sets `element.currentTime = 0`
- **Keyboard seek (j/l) using stale element** — Now uses `getCurrentElement()` from audio graph singleton
- **shuffleIndex out-of-bounds** — Clamped at boundary in `advanceToNextTrack`
- **External tracks playable in Favorites** — External tracks could be favorited but not played

## [0.1.0-alpha.9] - 2026-02-08

Subsonic API, Volume Normalization & Queue Unification

### Added

- **Music Video visualizer** - Music Video moved from Full Player tab to the visualizer picker
  - Now registered as a standard visualizer (`music-video`) alongside LyricStorm, CosmicOrb, etc.
  - Selectable from the visualizer picker with a Video icon
- **Fullscreen mode** in Full Player - click to enter fullscreen with auto-hiding controls
  - Controls reappear on mouse move or touch, then hide after 3 seconds
  - Mobile shows album artwork instead of visualizer (except for music video)
- **Auto-Download Toggle** - Automatically download new tracks for offline use
  - Toggle on any playlist, smart playlist, or favorites to enable auto-download
  - New tracks added to enabled playlists are downloaded automatically
  - Favorites: newly favorited tracks auto-download from any page in the app
  - New `useAutoDownload` hook for reusable download trigger logic
  - Backend: `auto_download` column on playlists and smart_playlists tables
  - Backend: favorites auto-download setting stored in profile settings
- **Ephemeral Playlists** - LLM-generated playlists are no longer auto-saved
  - Playlists from chat appear in "Unsaved" section until explicitly saved
  - Save button persists playlist to database
  - Dismiss button removes ephemeral playlist without saving
  - Ephemeral playlists stored in Zustand (survive page navigation, cleared on refresh)
  - Reduces database clutter from experimental/throwaway requests
- **5 New Audio Effects** - Expanded real-time audio effects system
  - **Stereo Width**: Mono to extra wide (200%) stereo image control
  - **Saturation**: Warm/tape/hard modes with drive and mix controls
  - **Chorus**: 2-3 voices with rate/depth for thickness
  - **Tremolo**: Sine/triangle/square LFO shapes
  - **Bitcrusher**: Bit depth (1-16) and sample rate reduction
- **15 New Audio Presets** using new and existing effects
  - Lo-Fi, Late Night, Club, Telephone, Underwater, 80s Gated, Spoken Word
  - Wide Stereo, Analog Warmth, Retro 8-Bit, Thick & Lush, Vintage Amp, Psychedelic, Synthwave, Broken Radio
  - Enhanced classic presets: Warm Vinyl (tape saturation), Live Concert (stereo width), Studio Polish (warm saturation), Dreamy (chorus + stereo width)
- **Sortable Columns** in track list view
- **Library Scan in Separate Process** - Library scanning now runs in its own process for better stability
- **Subsonic API for CarPlay and native music app support** - Subsonic/OpenSubsonic REST API at `/rest`
  - Enables native music apps (play:Sub, Amperfy, Symfonium) with CarPlay/Android Auto
  - SubsonicCredential model with bcrypt + token auth
  - Credential management UI in Settings > Integrations
  - Endpoints: ping, getLicense, getMusicFolders, getArtists, getArtist, getAlbum, getSong, stream, getCoverArt, search3, getAlbumList2, getRandomSongs, getStarred2, star/unstar
- **Volume Normalization with EBU R128 loudness measurement**
  - Backend: extract loudness_lufs, track_peak, replaygain_track_gain during analysis
  - Reads existing ReplayGain tags first, falls back to pyloudnorm measurement
  - Album-mode normalization endpoint: `/tracks/{id}/album-gain`
  - Frontend: normalization gain nodes in audio graph
  - Settings UI: track/album/auto modes, target LUFS, preamp, clipping prevention
  - ANALYSIS_VERSION bumped to 6
- **LLM tool for library searches** - New tool enabling Claude to search the library more effectively
- **S3 Backup improvements** - Backup feature moved to global admin
  - Read-only config from env vars (no longer editable in UI)
  - Fix validate failing on GetObject with DEEP_ARCHIVE objects
  - Fix enable toggle rendering
  - File size tracking on scan
- **Documentation restructured** - README slimmed down, installation/configuration/setup docs moved to `docs/`

### Changed

- **Centralized API URLs** - All frontend `fetch()`, `<img src>`, `EventSource`, and XHR URLs now use `getApiUrl()` helper from `api/base.ts`
  - Preparation for Capacitor iOS integration (switching to absolute URLs is a one-line change)
  - Updated 14+ call sites across 11 component/API files
  - Added CORS `expose_headers` for cross-origin Range requests
  - No behavior change - `getApiOrigin()` returns empty string for same-origin
- **Full Player simplified** - removed 4-tab layout (visualizer/video/lyrics/discover), replaced with single visualizer view
  - Lyrics now handled by LyricStorm/LyricPulse visualizers
  - Discovery moved out of Full Player
  - LyricsDisplay component removed
- **LyricStorm visual improvements** - depth-based particle fade, emissive glow on swarm particles, added fill light
- Refactored playlist import/export system
- **Unified queue system for all playback types** - Lazy queue (library shuffle-all) now materializes tracks into `queue[]`
  - All queue operations (playNext, addToQueue, removeFromQueue, reorderQueue, jumpToQueueIndex) work identically regardless of playback source
  - QueueView uses single code path with no lazy-mode branching for interaction
  - Concurrency guard prevents duplicate track fetches during rapid skipping
  - Refill threshold check consolidated into single self-contained function
- Performance optimizations

### Fixed

- **AlphabetBar touch handling** - fixed stale closure bug where touch handlers read stale state
  - Touch handlers now use refs instead of state for `isDragging` and `dragLetter`
  - Replaced async while-loop page loading with reactive `useEffect`
  - Added `MAX_PRELOAD_ITEMS = 2000` safety cap
  - Scroll behavior changed from smooth to instant for faster jumps
  - Active letter pulses during jump animation
- **Video download bug fixes** - Resolved issues with music video downloads
- **Mobile interface fixes** - Various mobile layout and interaction improvements
- **External track UX fixes** - Improved display and interaction with external/discovery tracks
- **CI failures** - pg_trgm extension properly initialized, lint errors resolved
- **E2E test reliability** - Chat panel and library view selectors updated for current DOM structure
- **Library sync failure after external track matching error** - DB session rollback after external track matching failure (e.g., missing pg_trgm)
  - Previously left session in failed transaction state, blocking subsequent operations
- **Queue "Clear All" in lazy mode** - Previously only cleared the reservoir, leaving materialized tracks playing; now clears both reservoir and queue
- **Backwards mobile scroll** - Fixed reverse scroll direction on mobile devices
- **FullPlayer fixes** - Various Full Player layout and interaction fixes
- **HNSW index / Alembic autogenerate** - Alembic env.py now skips manually-managed pgvector indexes during autogenerate

## [0.1.0-alpha.8] - 2026-02-04

Library Migration & UX Polish

### Added

- **Library Export/Import for Migration** - Export complete library data for migrating to a new machine
  - **Export includes**: metadata, analysis features, audio embeddings, fingerprints, user overrides
  - **Intelligent matching**: Matches tracks by file_hash (exact), acoustid (fingerprint), ISRC, MusicBrainz ID, or fuzzy title/artist
  - **Import modes**: match_only (safe), merge (fill gaps), replace (overwrite)
  - **Gzip compression**: Reduces ~100MB library exports to ~15MB
  - **Progress indicators**: Upload/download progress in UI
  - **New endpoints**: `/library/export`, `/library/import/preview`, `/library/import/execute`
  - **Settings UI**: New "Library Migration" section in Data Management
- **Toast Notification System** - User-friendly notifications throughout the app
  - New `toastStore` using Sonner library with dark theme styling
  - Success/error/warning/info toast types with descriptions
  - Loading toasts that can be updated
  - Promise-based toasts for async operations
  - `useToast` hook for component usage
  - `errorNotifications` utility with user-friendly error message extraction
  - `useRetryableOperation` hook for operations with automatic retry logic
- **Play History Tracking** - Local play history is now recorded
  - New `usePlayTracking` hook tracks playback and records to backend
  - Records plays after 30 seconds AND (50% of track OR 4 minutes)
  - Follows same rules as Last.fm scrobbling
  - Enables new releases feature to work (relies on play history)
- **Improved Error Feedback** - Visual feedback for failures throughout the app
  - Audio playback errors show toast with track name
  - Download completion/failure shows toast notification
  - Offline sync completion shows toast with count
  - Playlist reorder/remove failures show toast
  - Profile avatar upload failures show toast
  - New releases dismiss failures show toast
  - Downloads management actions show toast feedback
- **Alphabet Bar** - Quick A-Z navigation for long lists
  - Hover on right edge to reveal vertical A-Z bar
  - Click a letter to jump directly to that section
  - Works on Tracks, Artists, and Albums views
  - Only appears when list has 100+ items and is sorted alphabetically
  - Backend `/library/letter-index` endpoint returns letter→index mapping
  - Touch-drag with haptic feedback on mobile
- **Docked Queue Panel** - Desktop queue now docks to right side
  - Click Queue tab to toggle persistent side panel
  - Separate from mobile tab behavior (mobile still uses tab view)
  - Drag tracks from library directly into queue panel
- **Now Playing indicator for playlists** - Visual feedback for active playlist
  - Green highlight and animated equalizer icon on currently playing playlist
  - Appears in AI Playlists section
- **Favorite toggle in context menu** - Quick access to favorites
  - Right-click any track to add/remove from favorites
  - Heart icon shows current favorite status
- **Album Download button** - Download entire album for offline
  - New download button in album header view
  - Shows progress during download
  - Shows "Downloaded" status when complete
- **Auto-scroll to current track** - Track list follows playback
  - Automatically scrolls to show currently playing track
  - Centers track in viewport for better context
  - Works especially well with shuffle mode

### Fixed

- **CORS blocking audio on non-localhost origins** - Audio playback now works from any hostname
  - Previously only allowed localhost and Tailscale IPs (100.x.x.x)
  - Now allows any single-word hostname (e.g., `nas`, `openmediavault`) and any IPv4 address
  - Fixes 20+ second delays when accessing via NAS hostname on local network
- **Error Message Sanitization** - Internal error details no longer exposed to users
  - Health check endpoints return "Connection failed" instead of raw exception messages
  - Spotify OAuth callback returns generic error codes instead of raw exceptions
  - Library map computation SSE returns user-friendly messages
  - Export/import errors return helpful guidance instead of stack traces
  - Added `create_sse_error()` helper for sanitized SSE error events
  - All sanitized errors are still logged server-side for debugging
- **Replaced alert() dialogs with toast notifications** - Modern UX for user feedback
  - Profile settings: avatar upload validation and errors
  - Offline settings: sync status and errors
  - Track artwork upload: file validation warnings
- **Artist image lookup logging** - Debug logging for Last.fm and Spotify failures
- **README screenshot links** - Fixed broken image references
  - Full Player screenshot now points to correct file
- **Track restarts when opening Visualizer/FullPlayer** - Playback no longer restarts when switching views
  - Root cause: `loadedTrackIdRef` was a local ref but guarded global audio elements
  - Fix: Moved tracking state to module scope so all hook instances share the same state
  - Opening Visualizer, FullPlayer, or switching tabs no longer interrupts playback
  - Timeline screenshot replaced with Albums (timeline screenshot was never generated)

## [0.1.0-alpha.7] - 2026-02-03

Queue Management & Discovery Mode

### Added

- **Playlist Discovery Mode** - AI-generated playlists can now suggest tracks you don't own
  - **New setting** - Settings > AI Assistant > Playlist Discovery Mode
  - **Library Only mode** - legacy behavior, only uses local tracks
  - **Include Suggestions mode** (default) - includes local tracks + suggests missing tracks you might want
  - **`identify_track` tool** - LLM can now disambiguate "based on [song] by [artist]" requests
  - **`get_similar_tracks_external` tool** - queries Last.fm for similar tracks not in library
  - **Enhanced `queue_tracks`** - supports `suggested_tracks` parameter for discovery mode
  - **Updated system prompt** - guides LLM to use identify_track first for "based on" requests
- **Download management improvements** - better control over offline tracks
  - **Clear All Downloads** - red button in Downloads view with confirmation dialog showing track count and storage size
  - **Multi-select bulk delete** - Cmd/Ctrl+click to select individual tracks, Shift+click for range selection
  - **Selection toolbar** - appears when tracks selected with count display and "Remove from Downloads" action
  - **Checkboxes** - visible checkbox column for quick selection, green highlight on selected rows
  - **Context menu delete** - "Remove from Downloads" option in right-click menu
- **Queue tab** - new top-level tab to view and manage the playback queue
  - **Queue view** - see all queued tracks with current track highlighted
  - **Drag-to-reorder** - drag tracks to change playback order (regular queue mode)
  - **Click to jump** - click any track to jump to it immediately
  - **Remove tracks** - X button to remove individual tracks from queue
  - **Clear All** - button to empty the entire queue
  - **Lazy queue support** - shows limited view when shuffling large libraries (current + next 3 tracks)
  - **Shuffle indicator** - header shows when shuffle is enabled
  - **Empty state** - helpful message when queue is empty

### Changed

- **Clickable genres and years** - navigation links throughout the UI
  - Artist view tags now link to genre filter (previously non-interactive)
  - Artist view album years now link to year filter
  - Album grid years now link to year filter
  - Album detail already had clickable year/genre (unchanged)

### Fixed

- **Mobile infinite scroll in Track view** - lazy loading now works on mobile devices
  - Both mobile and desktop views rendered but used the same IntersectionObserver ref
  - The ref was assigned to the last (desktop) element, which is hidden on mobile
  - Fixed by using separate refs for mobile and desktop sentinels
- **Artist view back button** - no longer gets stuck when navigating back
  - Fixed auto-switch useEffect that would re-open artist detail after closing
  - Now clears both `artistDetail` and `artist` filter params on back
- **Album not found from Artist view** - clicking albums now works correctly
  - Fixed mismatch between Artist Detail (groups by `track.artist`) and Album Detail (looked up by `album_artist`)
  - Album Detail now falls back to `track.artist` lookup if `album_artist` lookup fails
- **Playlist discovery artist navigation** - now correctly switches to library tab
  - Added missing `window.location.hash = 'library'` when navigating to artist from playlist discovery section

## [0.1.0-alpha.5] - 2026-01-25

External Tracks & Offline

### Added

- **Missing Track System** - first-class support for "missing tracks" (tracks you want but don't have locally)
  - **External Tracks model** - new `ExternalTrack` table to store metadata for tracks not in your library
  - **Mixed playlists** - playlists can now contain both local tracks and external track placeholders
  - **Visual distinction** - external tracks appear at 75% opacity with "Not in library" label
  - **Preview playback** - 30-second previews from Spotify/Deezer for external tracks (amber Radio icon)
  - **Purchase links** - external link pills to find tracks on Bandcamp, Spotify, Last.fm
  - **Auto-matching** - when you add tracks to library, they automatically link to matching external tracks
  - **Wishlist playlist** - special system playlist for tracks you're interested in
  - **Add to Wishlist** - purple "+" button on discovery items to save tracks you want
- **Spotify playlist import** - import Spotify playlists with automatic local/external track splitting
  - `GET /spotify/playlists` - list your Spotify playlists
  - `GET /spotify/playlists/{id}/tracks` - preview tracks with local match status
  - `POST /spotify/playlists/{id}/import` - import playlist with local matches + external placeholders
- **External track matching service** - intelligent matching algorithm
  - ISRC exact match (highest confidence)
  - Exact artist + title match
  - Partial match with title/artist contains
  - Fuzzy match with 85% threshold using rapidfuzz
  - Background re-matching after library scans
- **LLM tools for Spotify playlists** - Claude can now work with your Spotify playlists
  - `list_spotify_playlists` - "What Spotify playlists do I have?"
  - `get_spotify_playlist_tracks` - "What's in my Spotify workout playlist?" (shows match rate)
  - `import_spotify_playlist` - "Import my Spotify chill playlist"
- **Downloads view** - dedicated section for browsing all downloaded/offline tracks
  - New "Downloads" button in Playlists tab (below Favorites) with green gradient styling
  - Shows total track count and storage size used
  - Full track list with play, context menu, and remove from downloads actions
  - Empty state guidance when no tracks are downloaded
- **Downloaded-only filter** - filter to show only offline-available tracks
  - **Library view**: "Downloaded" toggle button in toolbar filters entire library
  - **Smart Playlist detail**: "Downloaded only" button filters playlist tracks
  - **Regular Playlist detail**: Same filter toggle for AI-generated and manual playlists
  - Filter state persists in URL for Library view (`?downloadedOnly=true`)
- **useDownloadedTracks hook** - returns downloaded tracks with metadata, total count, and storage size

### Changed

- **Playlist API responses** - now include `is_wishlist`, `local_track_count`, `external_track_count` fields
- **Playlist tracks** - unified `PlaylistTrackItem` type with `type: 'local' | 'external'` discriminator
- **Discovery components** - all discovery views now support "Add to Wishlist" action for non-library items

## [0.1.0-alpha.4] - 2026-01-15 to 2026-01-23

Playback & Mobile

### Added

- **Non-Places visualizer enhancements** - inspired by "Islands: Non-Places" game
  - New objects with glowing parts: vending machine, ATM, streetlight, exit sign
  - New palm tree silhouette with detailed fronds
  - Ground plane with parallax depth and subtle horizon line
  - Shadows beneath objects (darker/sharper for closer objects)
  - Gentle swaying animation on plant fronds
- **Rain Window visualizer** - new calm visualizer for ambient music
  - Rain droplets with physics-based trails sliding down glass
  - Soft bokeh lights in background using album artwork colors
  - Subtle bass reactivity for spawn rate and brightness
- **Import quality comparison** - duplicate detection now compares audio quality
  - Shows whether incoming file is higher/lower/equal quality vs existing track
  - Quality factors: format tier (FLAC > AAC > MP3), bitrate, sample rate, bit depth
  - Visual indicators: green up-arrow (trumps existing), red down-arrow (trumped by), dash (equal)
  - One-click actions: "Replace" to upgrade, "Skip" to keep existing, "Import" for new tracks
  - New `quality.py` service with format tier definitions and comparison logic
- **AcoustID result caching** - API responses are now cached in the database
  - Avoids repeated API calls when identifying the same track multiple times
  - Cached per analysis version in `TrackAnalysis.acoustid_lookup`
  - Added `skip_cache` parameter to force fresh lookups when needed
- **Shuffle All for large libraries** - new lazy queue system fetches track metadata on demand
  - "Shuffle All" button in Tracks view shuffles entire library (or filtered results)
  - Server-side shuffle via `ORDER BY random()` for true randomization
  - Track metadata fetched just-in-time with prefetching for seamless playback
  - New API endpoints: `GET /tracks/ids` (lightweight) and `POST /tracks/batch`
- **get_similar_artists_in_library LLM tool** - find similar artists that exist in your library
  - Uses Last.fm for similarity data, checks against local library
  - Returns Bandcamp search URL when requested artist isn't in library
  - Updated system prompt with discovery suggestions workflow
- **README tools reference** - expandable "Available AI Tools (25)" section documenting all LLM capabilities
- **Audio Effects Panel** - comprehensive real-time audio effects system (desktop only)
  - **3-Band EQ** - Low (250 Hz), Mid (1 kHz), High (4 kHz) shelving filters with ±12 dB range
  - **Compressor** - Dynamics compression with threshold, ratio, attack, release, knee, and makeup gain
  - **Reverb** - Convolution reverb with 5 algorithmic presets (Small Room, Medium Room, Large Hall, Plate, Cathedral)
  - **Delay** - Echo effect with time, feedback, mix controls and ping-pong stereo mode
  - **Filters** - High-pass and low-pass filters with adjustable frequency and Q
  - 5 built-in presets: Warm Vinyl, Live Concert, Studio Polish, Bass Boost, Dreamy
  - Custom preset save/load with persistence
  - Quick-access button in FullPlayer header for fast preset switching
  - Settings panel in Playback section with collapsible effect sections
  - Effects chain inserted after volume control, before visualizer (effected audio visible in visualizations)
- **Debug Settings panel** - new Developer section at bottom of Settings
  - Platform detection info (iOS, mobile, hybrid mode)
  - Audio engine state (AudioContext, Analyser, current mode)
  - Live console log viewer with filtering
  - Test buttons for AudioContext and visibility state

### Changed

- **Comprehensive mobile layout audit** - fixed 26 components for better mobile experience
  - **iOS auto-zoom prevention**: All text inputs now use `text-base` (16px) to prevent viewport zoom on focus
  - **Responsive grids**: Grid layouts now adapt column count on mobile (e.g., `grid-cols-2 sm:grid-cols-4`)
  - **Stacking layouts**: Horizontal button groups stack vertically on mobile
  - **Touch-friendly buttons**: Hover-only buttons now always visible on touch devices
  - **Reduced padding**: Full player, lyrics, modals use smaller padding on mobile
  - **Responsive dropdowns**: Pickers constrain width on small screens
  - Files updated: PlayerBar, FullPlayer, PlaylistDetail, ArtistDetail, AlbumDetail, TrackEditModal, ChatPanel, Settings panels, and more
- **Unified shuffle via global toggle** - Play buttons now respect the playbar's shuffle toggle
  - Removed separate "Shuffle" and "Shuffle All" buttons from ArtistDetail and TrackListBrowser
  - Play action checks global shuffle state and passes it to server for large track sets
  - Single source of truth: toggle shuffle in playbar, then click Play anywhere
  - `setQueue()` already respected shuffle toggle; now lazy queue mode does too
- **Unified Discovery Section** - consolidated discovery/recommendation UI into single component
  - All views (Playlist, Artist, Album, Full Player) now use identical discovery UI
  - Tab interface for switching between content types (Artists, Albums, Tracks)
  - Consistent styling with purple header icon and "via {sources}" metadata
  - Eliminated wrapper components (RecommendationsPanel, FullPlayer/DiscoverSection)
  - Data fetching moved to parent components for cleaner architecture
- **Improved album artwork fallbacks** - tracks and albums now use AlbumArtwork component with hash-based fallback
- **Filtered Last.fm placeholder images** - generic Last.fm placeholder URLs no longer shown, prefer our icons instead
- **URL state persistence** - playlist selection, visualizer type, and tab state now persist in URL
  - Playlist detail views survive page refresh
  - Visualizer type selection persists across navigation
  - Tab switching clears irrelevant URL params
- **Discovery section shows album names** for recommended tracks in library
- **Non-Places object distribution** - weighted toward iconic glowing objects
  - Vending machines, ATMs, streetlights appear 2x as often
  - Palm trees appear 3x as often (good silhouette)
  - Removed abstract "ring" shape (didn't fit aesthetic)

### Fixed

- **Visualizer stability** - fixed useEffect dependency bug causing objects to flicker/respawn every frame
  - Affected both Rain Window (bokeh lights) and Non-Places (silhouettes)
  - Root cause: `audioData` in dependency array caused effect to re-run on every frame
- **Plant frond rotation** - fronds now point upward correctly instead of sideways
  - Added -π/2 offset to canvas rotation so angle 0 means "up" not "right"
  - Affects both potted plant and palm tree shapes
- **Playlist detail overflow** - header now stacks vertically on mobile, preventing title/button clipping
- **Track skipping during queue changes** - fixed race condition where tracks could skip unexpectedly
  - Added transition tracking to ignore spurious "ended" events during queue/track loading
  - Prevents double-advancing when rapidly changing tracks
- **iOS background playback** - audio now continues playing when app is backgrounded on iOS
  - Implemented hybrid audio mode that switches between Web Audio (for visualizer) and direct playback (for background)
  - Default: uses direct playback for reliable background audio
  - When visualizer is visible: switches to Web Audio mode for visualizer to work
  - When app backgrounds or visualizer closes: switches back to direct playback
  - Audio effects not available on iOS (they require Web Audio routing which breaks background playback)

## [0.1.0-alpha.3] - 2026-01-11 to 2026-01-14

Discovery & Metadata Intelligence

### Added

- **Ego-centric Music Map** - completely redesigned artist similarity visualization
  - Select any artist to center the map on them
  - 200 most similar artists radiate outward based on audio embeddings
  - Click any artist to recenter the map on them
  - Double-click to navigate to artist detail view
  - **Lasso selection** - drag to select multiple artists, then "Create Playlist" sends them to the LLM
  - **Figma-style controls** - drag to select, space+drag to pan, scroll to zoom
  - Deep zoom support (up to 15x)
- **3D Explorer audio previews** - hover over artists to hear a preview
  - Crossfade transitions when moving between artists
  - Representative track selection - uses track closest to artist's audio centroid
  - Toggle button to enable/disable audio previews
  - Respects player volume slider in real-time
- **Proactive album art downloading** - artwork fetches in background when browsing
  - Fetches from Cover Art Archive, Last.fm, and Spotify (in order)
  - Rate-limited to avoid API bans
- **Background jobs status indicator** - see active background tasks in the header
  - Spinner icon appears when any background job is running
  - Click to see detailed progress for each job type
  - Tracks: Library Sync, Spotify Sync, New Releases Check, Artwork Fetch
- **"Explore Similar Artists"** context menu item - right-click any track to open the Music Map centered on that artist
- **Proposed Changes system** for metadata corrections
  - LLM can suggest metadata fixes that go to a review queue
  - New Settings panel to view, approve, reject, and apply proposed changes
  - Support for different scopes: database only, ID3 tags, or file organization
  - New LLM tools: `lookup_correct_metadata`, `propose_metadata_change`, `get_album_tracks`, `mark_album_as_compilation`, `propose_album_artwork`
  - MusicBrainz integration for looking up correct metadata
  - Cover Art Archive integration for album artwork
- **Proposed Changes indicator** in header bar
  - Amber badge shows count of pending changes
  - Click for quick preview popover
  - Links to full review interface in Settings
- **Album/artist name normalization** for consistent matching
  - Case-insensitive grouping: "Alice In Ultraland" and "Alice in Ultraland" now appear as one album
  - Handles diacritics (Björk = Bjork), quotes, dashes, and whitespace variations
  - Applied to album grouping, artwork hash computation, and compilation detection
- **Duplicate artist detection** LLM tools
  - `find_duplicate_artists` - detects artists with variant spellings (e.g., "Arovane_Phonem" vs "Arovane and Phonem")
  - `merge_duplicate_artists` - proposes merging duplicates via the review queue
- **Proposed Changes as main view** - now accessible from Library browser picker
  - Click the amber indicator to jump directly to the Proposed Changes view
  - Removed from Settings panel (now has its own dedicated view)
  - Improved card layout with more space for reviewing changes
- **Semantic search** for natural language music queries
  - New `semantic_search` LLM tool uses CLAP text embeddings
  - Ask for "gloomy with Eastern influences" or "dreamy atmospheric synths" and find sonically matching tracks
  - Works by encoding your text description into the same embedding space as the audio
  - Gracefully falls back to metadata search when CLAP is disabled

### Changed

- Music Map now uses ego-centric layout instead of UMAP projection (scales beyond 200 artists)
- **Artwork fetch order** - Last.fm checked first when API key is configured (faster than MusicBrainz)
- **Background Jobs indicator** now shows queue count (e.g., "5/10 (3 queued)")
- **Bulk change display** - shows unique values instead of raw JSON with track IDs
  - Before: `{"uuid1":"proem","uuid2":"Proem",...}`
  - After: `proem, Proem`

### Fixed

- Broken image placeholders - Music Map and 3D Explorer now show Music icon instead of broken image link
- Header popovers (Background Jobs, Proposed Changes, Health) now display above album art
  - Added proper z-index stacking: header z-30, PlayerBar z-20, popovers z-60
- Settings page crash caused by API responses not being arrays
- Proposed Changes API endpoint missing trailing slash

## [0.1.0-alpha.2] - 2026-01-04 to 2026-01-09

Infrastructure & Library UX

### Added

- Memory tracking in analysis subprocess for debugging OOM issues
- **Split analysis into separate phases** for better memory efficiency
  - Phase 1: Feature extraction (librosa, artwork, AcoustID) - ~1-2GB memory
  - Phase 2: Embedding generation (CLAP model) - ~2-3GB memory
  - Each phase runs in its own subprocess that exits after completion
  - Peak memory reduced from ~5GB to ~3GB, works on 4GB containers
- **Updated sync UI** to show 4 phases: Discover → Read → Features → Embeddings
- **Environment variable** `DISABLE_CLAP_EMBEDDINGS=true` to skip embedding phase
- **Artist images** in library browser with fallback chain (Last.fm → Spotify → album artwork)
- **Infinite scroll** for all library views (Artists, Albums, Tracks)
- **View persistence** - app remembers your selected library view
- **Track metadata editing** - right-click any track and select "Edit Metadata..."
  - Tabbed modal with Basic, Extended, Sort, Lyrics, and Analysis tabs
  - Edit core fields: title, artist, album, album artist, track/disc number, year, genre
  - Edit extended fields: composer, conductor, lyricist, grouping, comment
  - Edit sort fields for proper alphabetization (e.g., "Beatles, The")
  - Edit embedded lyrics
  - Override detected BPM and key values
  - Option to write changes back to audio file tags (MP3, FLAC, M4A, OGG, AIFF)
- **Context menu everywhere** - full context menu now available on:
  - Player bar (currently playing track)
  - Full player overlay
  - Artist detail page
  - Favorites list
  - Playlist detail
  - All library browser views
- **Auto-enrich metadata** when viewing artist detail page - triggers enrichment for all tracks

### Changed

- **Default library view** changed from Tracks to Artists
- **Artists view** redesigned as visual grid with artwork (matches Albums view)
- Skip tracks shorter than 30 seconds or longer than 30 minutes during analysis
- Add restart policies to postgres and redis containers in docker-compose
- Disable Docker layer cache for more reliable builds
- More aggressive disk cleanup during Docker build
- Extended Track database model with new metadata fields
- Improved MusicBrainz release selection (prefers original albums over compilations)

### Fixed

- Rate-limited ProcessPoolExecutor recreation to prevent runaway process spawning
- Increased file descriptor limit to prevent EMFILE errors during bulk analysis
- Detect and clear stale sync locks on every sync attempt
- Install PyTorch after uv sync to prevent package removal during build
- Configure logging in analysis subprocess for better debugging
- Reduce uvicorn workers to 1 to prevent OOM during analysis
- Library Sync progress bar now correctly shows progress during Features and Embeddings phases
- **Compilation album duplication** - Albums like "80's Wave" no longer appear multiple times
  - Sync now auto-detects compilation albums (multiple artists, no album_artist set)
  - Sets `album_artist = "Various Artists"` for tracks in detected compilations
- Process pool crashing during analysis
- Tab selection now persists in URL hash across page reloads
- Simplify sync queue management to prevent stalls during feature extraction
- Artist detail URL persistence - artist selection now stored in URL, survives page reload
- YouTube video search - add yt-dlp to Docker image (was missing, causing empty search results)

## [0.1.0-alpha.1] - 2026-01-03

First alpha release of Familiar - an LLM-powered local music player.

### Features

- **AI-powered music chat** using Claude API with tool use
  - Natural language playlist creation
  - Music discovery through conversation
- **Local music library scanning** with metadata extraction
- **Audio analysis** with librosa for BPM, key, energy, valence, and audio features
- **CLAP embeddings** for semantic music search (optional, can be disabled)
- **Library Browser Views**
  - Album Grid with cover art thumbnails
  - Artist List with artist detail pages and discography
  - Mood Grid organizing tracks by energy/valence
  - Music Map with clustered visualization of similar tracks
  - Timeline view browsing by release year
  - Track List with sortable columns
- **Multi-select & Context Menus** in library browser
  - Shift-click and Ctrl/Cmd-click for multi-selection
  - Selection toolbar for batch actions
  - Right-click context menu on tracks
- **Spotify integration** for syncing favorites and matching to local tracks
- **Last.fm scrobbling** support
- **Smart playlists** with rule-based track filtering
- **PWA support** with offline playback
- **Music video downloads** from YouTube
- **Multi-profile support** for household use
- **Visualizer API** for community-contributed visualizers
  - Full access to track metadata, audio features, real-time audio data, and timed lyrics
  - Hooks: `useArtworkPalette`, `useBeatSync`, `useLyricTiming`
  - Built-in visualizers: FrequencyBars, AlbumKaleidoscope, LyricStorm, LyricPulse, CosmicOrb, ColorFlow
- **Admin setup page** at `/admin` for API key and library configuration
- **Version display** in Settings UI

### Technical

- **Backend**: Python FastAPI with async SQLAlchemy
- **Frontend**: React + TypeScript + Vite + Tailwind + Zustand
- **Database**: PostgreSQL with pgvector for embeddings
- **Cache**: Redis for session state and task queues
- **In-process background tasks** using ProcessPoolExecutor with spawn context
  - Single worker to limit memory usage (CLAP model is ~1.5GB)
  - APScheduler for periodic tasks (library scans every 6 hours)
- Docker deployment with multi-service compose
- CPU-only PyTorch for smaller Docker images (~200MB vs ~5GB)
- E2E tests with Playwright

### Known Issues

- Audio analysis can be memory-intensive on systems with <8GB RAM
- MoodMap accuracy depends on proper key detection

[Unreleased]: https://github.com/seethroughlab/familiar/compare/v0.1.0-alpha.10...HEAD
[0.1.0-alpha.10]: https://github.com/seethroughlab/familiar/compare/v0.1.0-alpha.9...v0.1.0-alpha.10
[0.1.0-alpha.9]: https://github.com/seethroughlab/familiar/compare/v0.1.0-alpha.8...v0.1.0-alpha.9
[0.1.0-alpha.8]: https://github.com/seethroughlab/familiar/compare/v0.1.0-alpha.7...v0.1.0-alpha.8
[0.1.0-alpha.7]: https://github.com/seethroughlab/familiar/compare/v0.1.0-alpha.5...v0.1.0-alpha.7
[0.1.0-alpha.5]: https://github.com/seethroughlab/familiar/compare/v0.1.0-alpha.4...v0.1.0-alpha.5
[0.1.0-alpha.4]: https://github.com/seethroughlab/familiar/compare/v0.1.0-alpha.3...v0.1.0-alpha.4
[0.1.0-alpha.3]: https://github.com/seethroughlab/familiar/compare/v0.1.0-alpha.2...v0.1.0-alpha.3
[0.1.0-alpha.2]: https://github.com/seethroughlab/familiar/compare/v0.1.0-alpha.1...v0.1.0-alpha.2
[0.1.0-alpha.1]: https://github.com/seethroughlab/familiar/releases/tag/v0.1.0-alpha.1
