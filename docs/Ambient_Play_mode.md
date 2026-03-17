# Ambient Play Mode for Mobile: Separate Ambient Session Player

## Summary
Add a **mobile-only Ambient screen/player** that runs as a separate listening session from normal playback. It will play **short song windows only**, layer in **airy native drones plus simple motif notes**, and choose the next snippet using **analysis-driven compatibility** across the whole library.

The implementation should ship in the existing iOS Capacitor app first, but the architecture must stay **Android-ready** by keeping ambient session orchestration in shared TS and defining a portable native synth bridge. The plan should **not** port `ambient-generator` directly; it should borrow its core ideas: long-envelope texture, sparse motif notes, reverb/delay space, and scale-aware melodic movement.

## Key Changes

### 1. Product shape and UX
- Add a dedicated **Ambient** mobile tab/screen, not a mode inside the normal player.
- Ambient playback is its own session type with its own scheduler, queue history, and controls; it should not mutate the standard queue/store semantics except when it becomes the active audio source.
- Ambient sessions are **user-seeded, then system-driven**:
  - User chooses a seed via search/select on track or artist.
  - Also provide `Surprise Me` as a seed shortcut.
  - After the seed, the system walks a compatible chain through the library.
- V1 controls are a simple 4-control set:
  - `Intensity`: `quiet | balanced | immersive`
  - `Snippet length`: `8s | 16s | 24s`
  - `Transition density`: `sparse | balanced | lush`
  - `Filter preset`: `all | soft | dark | instrumental`
- Ambient mode plays **windows/snippets only**, not full tracks.
- Remote/lock-screen behavior:
  - `play/pause` controls the ambient session.
  - `next` skips to the next planned snippet.
  - `previous` restarts current snippet if >3s elapsed, otherwise goes to prior snippet in ambient history.
  - Now Playing should show current source track metadata plus an `Ambient Mode` subtitle/marker where supported.

### 2. Session orchestration and compatibility engine
- Add a shared `ambient session` coordinator in frontend shared player code, separate from normal queue playback.
- The coordinator owns:
  - current snippet
  - rolling next 2-3 planned snippets
  - ambient history
  - transition recipe for current→next
  - user control state
- Use a **seed-chain model**:
  - pick a strong seed track from the user’s chosen seed target
  - rank next candidates from the whole eligible pool
  - keep a recent-history penalty so sessions do not bounce between the same tracks/artists
- Compatibility scoring should use existing analysis fields first:
  - hard preference for compatible `key`
  - same key, relative major/minor, and fifth-neighbor relationships score highest
  - `bpm` is a soft constraint only
  - prefer proximity in `energy`, `brightness`, `dynamic_range_db`, `valence`
  - prefer higher `instrumentalness`, lower `speechiness`
  - use CLAP `embedding` similarity as a tie-breaker and fallback when key confidence is weak
- Filter presets map to scoring/eligibility rules:
  - `all`: broad eligibility
  - `soft`: lower energy, lower brightness, higher acousticness
  - `dark`: lower valence, lower brightness, stronger minor/modal preference
  - `instrumental`: high instrumentalness, strong speechiness penalty
- Recent session guardrails:
  - no immediate track repeat
  - artist repeat cooldown over the last few snippets
  - stop or reseed cleanly if the candidate pool collapses under filters

### 3. Snippet selection and transition behavior
- Do **not** add new backend segment extraction for v1.
- Snippet windows should be chosen with analysis-guided heuristics:
  - exclude tracks below a minimum playable length
  - avoid first ~10s and final ~15-20s
  - prefer anchors in the middle 25-70% of the track
  - bias toward calmer/stabler material using existing analysis fields
  - if `section_count` / `form_string` exists, use it only as a weak hint for anchor placement
- Each planned snippet should include:
  - `trackId`
  - `startTime`
  - `endTime`
  - `compatibilityScore`
  - `targetKeyCenter`
  - `transitionRecipe`
- Transition execution:
  - current snippet starts dry-to-soft
  - native ambient layer begins before the crossfade window
  - next snippet fades in under the drone
  - motif notes bridge the current and target key centers
  - drone decays only after the next snippet is established
- Transition density mapping:
  - `sparse`: mostly drone, very few motif notes
  - `balanced`: drone plus simple scale-degree motifs
  - `lush`: thicker drone plus more frequent motif notes and longer overlap

### 4. Native audio architecture
- Extend the Capacitor native audio plugin with an **ambient synth layer** instead of building a second playback engine.
- Keep source-song playback on the existing native track engine; add a parallel native ambient bus for drones/motifs.
- V1 synthesis path is **pure oscillator synth**, not bundled samples:
  - 2 sustained drone voices
  - 1 motif voice
  - slow attack/release envelopes
  - low-pass filtering
  - native reverb/delay shaping
- Define a portable plugin seam so iOS implements first and Android can follow later with the same contract.
- Add plugin methods/events for:
  - configure ambient session parameters
  - start a transition recipe
  - stop ambient layer immediately or with release tail
  - update ambient mix/intensity without restarting the session
  - optional diagnostics for transition scheduling failures
- Keep this seam separate from the normal effects API so ambient-mode logic does not entangle with standard playback effects.

### 5. Data/API strategy
- Add a backend ambient-candidate API rather than pushing whole-library scoring into the mobile client.
- Backend should expose compact ambient descriptors built from existing `TrackAnalysis` data; no schema migration is required for v1 if existing analysis columns are sufficient.
- Add a lightweight endpoint family such as:
  - seed resolution from a user-selected track/artist
  - next-candidate ranking given current snippet/session state and control settings
  - optional batch candidate fetch for rolling preplan
- Keep scoring logic mirrored in a shared TS fallback module for **offline downloaded-only** operation.
- Offline behavior:
  - ambient mode remains available only when enough downloaded analyzed tracks exist
  - offline mode uses downloaded tracks only
  - non-downloaded tracks are never shown as ambient candidates while offline
  - if offline candidate pool is insufficient, the session should stop with an explicit user-facing reason rather than degrade unpredictably

## Public Interfaces / Contracts
- Add a new frontend ambient session store/controller in shared mobile-facing code.
- Add a new backend ambient recommendation API returning compact snippet/candidate plans, not full session persistence.
- Extend the Capacitor audio plugin with a portable ambient-layer contract for synth transitions.
- Do not change the existing standard `AudioEngine` contract for ordinary playback more than necessary; ambient mode should sit beside it, not distort normal queue semantics.

## Test Plan
- **Compatibility selection**
  - Given a user-selected seed, the next candidates prefer compatible keys and reject obvious incompatibilities.
  - Recent-track and recent-artist penalties prevent repetitive chains.
  - Filter presets materially change candidate eligibility and ranking.
- **Snippet scheduling**
  - Planned windows never exceed track duration and avoid intro/outro guard bands.
  - Ambient mode advances snippet-to-snippet without dead air or runaway skip loops.
  - Switching controls mid-session updates future planning without corrupting the active snippet.
- **Native transition layer**
  - Drone starts before the snippet crossfade and releases after the next snippet is established.
  - Sparse/balanced/lush density settings change note density and overlap deterministically.
  - Transition cancellation or skip leaves the native graph in a clean baseline state.
- **Offline**
  - In offline mode, ambient sessions only use downloaded analyzed tracks.
  - If the offline pool is too small, the user gets a clean `not enough downloaded tracks` state.
  - Returning online restores full-library candidate selection without app restart.
- **Regression**
  - Normal mobile playback, queueing, lock-screen controls, and crossfade behavior remain unchanged outside Ambient mode.
  - Ambient mode activation/deactivation does not corrupt the standard player queue/history.
  - Dedicated ambient screen is mobile-only and does not appear in desktop/web surfaces.

## Assumptions and Defaults
- V1 implementation target is the current iOS Capacitor app, but the design must stay Android-portable; Android app creation is not part of this plan.
- Ambient mode is a **separate player/session**, not a queue flag inside the existing player.
- Source material is **short snippets only**.
- Session flow is **user-guided seed, then system chain**.
- V1 uses **existing analysis fields plus heuristics**, not new segment/chapter preprocessing.
- V1 synthesis uses a **native pure-oscillator ambient layer**, not bundled instruments or rendered beds.
