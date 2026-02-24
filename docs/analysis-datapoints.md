# Analysis Datapoints Report

Comprehensive inventory of every analysis datapoint generated for tracks in Familiar, covering generation method, confidence, subjectivity, and external dependencies.

**Source files**: `analysis.py`, `track_analysis/analyzers.py`, `track_analysis/pipeline.py`, `track_analysis/constants.py`, `external_features.py`, `community_cache.py`, `metadata/reader.py`, `db/models/tracks.py`, `vocal_detection.py`, `mood_tags.py`

---

## Table of Contents

1. [File Metadata (Tag Extraction)](#1-file-metadata-tag-extraction)
2. [Phase 1: Core Librosa Features](#2-phase-1-core-librosa-features)
3. [Phase 1: Deep Analysis (Cheap Sections)](#3-phase-1-deep-analysis-cheap-sections)
4. [Phase 2: CLAP Embeddings](#4-phase-2-clap-embeddings)
5. [Phase 3: Melodic Analysis](#5-phase-3-melodic-analysis)
6. [Phase 4: Mood Tags](#6-phase-4-mood-tags)
7. [External Sources](#7-external-sources)
8. [Structural/Tracking Columns](#8-structuraltracking-columns)
9. [Gaps & Improvement Opportunities](#9-gaps--improvement-opportunities)

---

## 1. File Metadata (Tag Extraction)

Extracted via `metadata/reader.py` using **mutagen**. Read directly from file tags (ID3, Vorbis Comment, MP4 atoms, AIFF). No algorithmic processing — purely tag parsing.

| Datapoint | DB Column | Type | Source |
|-----------|-----------|------|--------|
| Title | `tracks.title` | `String(500)` | Tag: TIT2 / ©nam / title |
| Artist | `tracks.artist` | `String(500)` | Tag: TPE1 / ©ART / artist |
| Album | `tracks.album` | `String(500)` | Tag: TALB / ©alb / album |
| Album Artist | `tracks.album_artist` | `String(500)` | Tag: TPE2 / aART / albumartist |
| Track Number | `tracks.track_number` | `Integer` | Tag: TRCK / trkn / tracknumber (parses "3/12" format) |
| Disc Number | `tracks.disc_number` | `Integer` | Tag: TPOS / disk / discnumber |
| Year | `tracks.year` | `Integer` | Tag: TDRC / ©day / date (first 4 chars) |
| Genre | `tracks.genre` | `String(255)` | Tag: TCON / ©gen / genre |
| Duration | `tracks.duration_seconds` | `Float` | `audio.info.length` (mutagen) |
| Sample Rate | `tracks.sample_rate` | `Integer` | `audio.info.sample_rate` |
| Bit Depth | `tracks.bit_depth` | `Integer` | `audio.info.bits_per_sample` |
| Bitrate | `tracks.bitrate` | `Integer` | `audio.info.bitrate` |
| Bitrate Mode | `tracks.bitrate_mode` | `String(10)` | MP3-only: CBR/VBR from `mutagen.mp3.BitrateMode` |
| Format | `tracks.format` | `String(10)` | File extension (mp3, flac, m4a, etc.) |
| Composer | `tracks.composer` | `String(500)` | Tag: TCOM / ©wrt / composer |
| Conductor | `tracks.conductor` | `String(500)` | Tag: TPE3 / conductor |
| Lyricist | `tracks.lyricist` | `String(500)` | Tag: TEXT / lyricist |
| Grouping | `tracks.grouping` | `String(255)` | Tag: TIT1 / ©grp / grouping |
| Comment | `tracks.comment` | `Text` | Tag: COMM / ©cmt / comment |
| Sort Artist | `tracks.sort_artist` | `String(500)` | Tag: TSOP / soar / artistsort |
| Sort Album | `tracks.sort_album` | `String(500)` | Tag: TSOA / soal / albumsort |
| Sort Title | `tracks.sort_title` | `String(500)` | Tag: TSOT / sonm / titlesort |
| Lyrics | `tracks.lyrics` | `Text` | Tag: USLT / ©lyr / lyrics |
| MusicBrainz Track ID | `tracks.musicbrainz_track_id` | `String(36)` | Tag or MusicBrainz lookup |
| MusicBrainz Artist ID | `tracks.musicbrainz_artist_id` | `String(36)` | Tag or MusicBrainz lookup |
| MusicBrainz Album ID | `tracks.musicbrainz_album_id` | `String(36)` | Tag or MusicBrainz lookup |
| ISRC | `tracks.isrc` | `String(12)` | Tag or MusicBrainz lookup |
| Artist (Normalized) | `tracks.artist_normalized` | `String(500)` | Algorithmic: strips "feat." variants |
| Featuring Artists | `tracks.featuring_artists` | `String(500)` | Algorithmic: extracted from artist field |

**Confidence**: High — tags are authoritative when present, though often incomplete or inconsistent across libraries.

---

## 2. Phase 1: Core Librosa Features

Extracted via `analysis.py:derive_features()`. Audio loaded at 22050 Hz mono. Shared intermediates computed once in `precompute_shared()`: STFT, chroma, onset envelope, BPM, beat frames, RMS, MFCCs.

These map to typed columns on `TrackAnalysis`.

### 2.1 BPM

| | |
|---|---|
| **Column** | `track_analysis.bpm` (`Float`) |
| **Method** | `librosa.feature.tempo()` from onset envelope, confirmed by PLP beat tracking |
| **Range** | Typically 40–220 |
| **Confidence** | No explicit score. librosa's tempo estimation uses autocorrelation — reliable for 4/4 but can halve/double for odd meters |
| **Subjectivity** | Low — objective measurement, though "perceived tempo" can differ |

### 2.2 Key

| | |
|---|---|
| **Column** | `track_analysis.key` (`String(10)`) |
| **Method** | Krumhansl-Kessler (KK) key profile correlation via `_detect_key_kk()`: computes mean chroma vector, rotates it to each of 12 root pitch classes, and correlates (Pearson) against empirically-derived major and minor profiles. The key/mode with the highest correlation wins. Minor keys get an "m" suffix (e.g., "Am", "F#m"). |
| **Values** | C, C#, D, ..., B (major); Cm, C#m, Dm, ..., Bm (minor) — 24 total |
| **Confidence** | KK correlation score normalized to [0, 1]: `clip((best_corr + 1) / 2, 0, 1)`. Stored in `feature_confidence.key`. |
| **Subjectivity** | Low — key is an objective property; KK profiles are well-validated in music cognition research |

### 2.3 Energy

| | |
|---|---|
| **Column** | `track_analysis.energy` (`Float`) |
| **Method** | Mean RMS energy → dB scale → normalized: `clip((rms_db + 60) / 54, 0, 1)` |
| **Range** | 0.0–1.0 |
| **Confidence** | High — straightforward signal measurement |
| **Subjectivity** | Low — direct physical measurement |

### 2.4 Danceability

| | |
|---|---|
| **Column** | `track_analysis.danceability` (`Float`) |
| **Method** | `mean(PLP pulse)` — Predominant Local Pulse strength via `librosa.beat.plp()` |
| **Range** | 0.0–1.0 |
| **Confidence** | Medium — PLP measures rhythmic regularity, not all aspects of danceability |
| **Subjectivity** | Medium — "danceability" is culturally subjective; PLP captures only beat clarity |

### 2.5 Valence

| | |
|---|---|
| **Column** | `track_analysis.valence` (`Float`) |
| **Method** | Multi-feature weighted composite (7 components) with nonlinear spread: |
| | - Mode score (major vs minor triad energy ratio, key-aware chroma): **25%** |
| | - Brightness score (spectral centroid, normalized): **20%** |
| | - Tempo score (BPM mapped 60–180 → 0–1): **18%** |
| | - Harmonic tension (inverted dissonant/consonant interval ratio from chroma co-occurrence): **12%** |
| | - Spectral contrast score: **10%** |
| | - Tonality score (inverted spectral flatness — tonal content correlates with positive valence): **8%** |
| | - Dynamics score (RMS variance): **7%** |
| | Final: `clip(sign(c) * |c|^0.6 * 1.8 + 0.5, 0, 1)` for wider spread |
| **Range** | 0.0–1.0 |
| **Confidence** | Low-medium — heuristic proxy for emotional valence |
| **Subjectivity** | High — "happiness" is inherently subjective; algorithm uses acoustic correlates only |

### 2.6 Acousticness

| | |
|---|---|
| **Column** | `track_analysis.acousticness` (`Float`) |
| **Method** | 5-factor weighted composite via `_compute_acousticness()`: |
| | - MFCC1 mean (**30%**) — acoustic instruments tend to have higher MFCC1; normalized `clip((mfcc1 + 200) / 400, 0, 1)` |
| | - Spectral flatness inverse (**30%**) — low flatness = tonal = acoustic; `clip(1.0 - flatness * 10, 0, 1)` |
| | - Spectral rolloff inverse (**20%**) — acoustic tends lower rolloff; `clip(1.0 - rolloff / nyquist, 0, 1)` |
| | - MFCC temporal variance (**10%**) — natural instruments have more timbral variation; `clip(mfcc_var / 500, 0, 1)` |
| | - Crest factor (**10%**) — acoustic tends higher peak/RMS ratio; `clip(crest / 20, 0, 1)` |
| **Range** | 0.0–1.0 |
| **Confidence** | Medium (0.6) — heuristic composite, but significantly more robust than prior single-metric approach |
| **Subjectivity** | Medium — the concept is well-defined; multi-factor measurement captures more dimensions |

### 2.7 Instrumentalness

| | |
|---|---|
| **Column** | `track_analysis.instrumentalness` (`Float`) |
| **Method** | **Primary**: silero-vad ONNX model for speech probability detection. Resamples to 16kHz, processes 512-sample windows (32ms), analyzes up to 120s from the middle of the track. `instrumentalness = clip(1.0 - mean_speech_prob * 1.5, 0, 1)` — the 1.5× multiplier makes speech detection more aggressive. |
| | **Fallback** (if VAD model unavailable): spectral vocal band energy ratio `1 - (vocal_band_energy[300–3000Hz] / total_energy)`. |
| **Range** | 0.0–1.0 |
| **Confidence** | 0.5–0.9 with VAD (scales with speech signal strength: `clip(0.5 + mean_speech_prob * 0.4, 0.5, 0.9)`); 0.3 with spectral fallback |
| **Subjectivity** | Low — concept is objective; VAD model provides much more reliable detection than spectral heuristics |
| **3rd party** | `silero-vad` (ONNX, auto-downloaded from GitHub) |

### 2.8 Speechiness

| | |
|---|---|
| **Column** | `track_analysis.speechiness` (`Float`) |
| **Method** | **Primary**: VAD speech probability × (1 - RMS autocorrelation periodicity). Autocorrelation of the RMS energy envelope at lags 5–50 frames (~0.5–4 Hz) detects periodic vocal patterns (singing). High VAD + low periodicity = speech; high VAD + high periodicity = singing (suppressed). `speechiness = clip(mean_speech_prob * (1.0 - periodicity), 0, 1)` |
| | **Fallback** (if VAD unavailable): `min(1, zcr_mean * 2)` |
| **Range** | 0.0–1.0 |
| **Confidence** | 0.5–0.9 with VAD (matches instrumentalness confidence); 0.3 with ZCR fallback |
| **Subjectivity** | Low — concept is objective; VAD + periodicity distinguishes speech from singing effectively |
| **3rd party** | `silero-vad` (shared with instrumentalness) |

### 2.9 Loudness (LUFS)

| | |
|---|---|
| **Column** | `track_analysis.loudness_lufs` (`Float`) |
| **Method** | Priority: (1) ReplayGain tags from file → derive LUFS, (2) `pyloudnorm` EBU R128 measurement |
| **Range** | Typically -30 to 0 LUFS |
| **Confidence** | High — EBU R128 is a well-defined standard |
| **Subjectivity** | None — objective measurement |
| **3rd party** | `pyloudnorm` (ITU-R BS.1770-4 implementation) |

### 2.10 Track Peak

| | |
|---|---|
| **Column** | `track_analysis.track_peak` (`Float`) |
| **Method** | ReplayGain tags, or `max(abs(samples))` via soundfile |
| **Range** | 0.0–1.0+ (can exceed 1.0 for clipped audio) |
| **Confidence** | High — direct measurement |
| **Subjectivity** | None |

### 2.11 ReplayGain Track Gain

| | |
|---|---|
| **Column** | `track_analysis.replaygain_track_gain` (`Float`) |
| **Method** | ReplayGain tags, or derived as `-18.0 - loudness_lufs` |
| **Range** | Typically -20 to +20 dB |
| **Confidence** | High |
| **Subjectivity** | None |

### 2.12 Feature Confidence Scores

| | |
|---|---|
| **Column** | `track_analysis.feature_confidence` (`JSONB`) |
| **Method** | Per-feature confidence scores computed during analysis. Each feature stores a 0.0–1.0 score reflecting measurement reliability. |

| Feature | Confidence | Method |
|---------|-----------|--------|
| BPM | 0.2–1.0 | Based on onset envelope variance: `clip(onset_var / 0.5, 0.2, 1.0)` — strong beats → high confidence |
| Key | varies | KK correlation score normalized: `clip((best_corr + 1) / 2, 0, 1)` |
| Energy | 0.95 | Direct RMS measurement — fixed high confidence |
| Danceability | 0.3–0.95 | Based on PLP pulse variance: `clip(1.0 - pulse_var * 5, 0.3, 0.95)` — consistent pulse → high confidence |
| Acousticness | 0.6 | Fixed — heuristic composite |
| Instrumentalness | 0.3–0.9 | 0.3 for spectral fallback; 0.5–0.9 with VAD (scales with speech signal strength) |
| Speechiness | 0.3–0.9 | Matches instrumentalness — same VAD source |
| Valence | 0.4 | Fixed — inherently subjective heuristic |

Cross-validation results are also stored here when external features are available (see [Section 7.6](#76-cross-validation)).

---

## 3. Phase 1: Deep Analysis (Cheap Sections)

Run by `track_analysis/pipeline.py:run_cheap_sections()`. Five section analyzers produce structured data stored in `analysis_detail` JSONB, with scalar values promoted to typed columns.

### 3.1 Harmonic Section (`_analyze_harmonic`)

**Full output stored in** `analysis_detail.harmonic`

| Datapoint | Typed Column | Type | Method |
|-----------|-------------|------|--------|
| Harmonic complexity | `harmonic_complexity` | `Float` | Chord changes per bar (harmonic rhythm rate) |
| Key stability | `key_stability` | `String(20)` | Windowed key estimation (8 windows): "stable" (≤2 unique), "drifting" (≤4), "modulating" (>4) |
| Modal character | `modal_character` | `String(40)` | Best-fit mode from 84 templates (12 roots × 7 modes: Ionian, Dorian, Phrygian, Lydian, Mixolydian, Aeolian, Locrian) via cosine similarity against average chroma |
| Modal confidence | `modal_confidence` | `Float` | Cosine similarity score of best mode match (0.0–1.0) |

**Additional JSONB-only data:**
- `chords`: Full beat-synchronized chord sequence with timestamps and confidence scores. Template matching against 84 chord templates (12 roots × 7 qualities: maj, min, dim, aug, 7, maj7, min7). Threshold: correlation < 0.4 → "N" (no chord). Smoothed via RLE dedup + short-chord merge.
- `most_common_chords`: Duration-weighted top 8 chords with percentages
- `roman_numeral_chords`: Most common chords as Roman numerals relative to detected key
- `detected_progressions`: Pattern matching against 11 common progressions (I-V-vi-IV, ii-V-I, 12-bar blues, etc.)
- `key_windows`: Per-window key estimates (8 equal windows)
- `key_mode_timeline`: Sliding-window mode detection with start/end times, confidence, and RLE merging. Window size: 8 bars (or 1/8 of track). Slide: 4 bars (or half-window).

### 3.2 Rhythmic Section (`_analyze_rhythmic`)

**Full output stored in** `analysis_detail.rhythmic`

| Datapoint | Typed Column | Type | Method |
|-----------|-------------|------|--------|
| Swing ratio | `swing_ratio` | `Float` (0–1) | Mean position of 2nd onset within beats; stored 0–100 in JSONB, normalized to 0–1 for typed column. 50 = straight, >55 = swing |
| Syncopation | `syncopation` | `Float` | Mean distance of onsets from nearest 16th-note grid position × 4 (LHL-inspired simplified measure) |
| Tempo character | `tempo_character` | `String(20)` | CV of inter-beat intervals: "grid-locked" (<0.05), "slight drift" (<0.15), "breathing" (≥0.15) |

**Additional JSONB-only data:**
- `bpm`: Rounded BPM from shared computation
- `has_clear_beat`: Boolean gate — if onset envelope max < 0.05, analysis is skipped
- `tempo_cv`: Coefficient of variation of inter-beat intervals (exact value)
- `euclidean_patterns`: Quantized onset pattern compared against 16 known Euclidean rhythms (Tresillo, Bossa nova, Samba, Rumba, etc.) via Hamming distance ≤2 across all rotations
- `rhythm_pattern`: Classification: "four-on-the-floor", "half-time", "breakbeat", "shuffle", "standard backbeat", "unclassified". Based on kick/snare pattern detection via spectral centroid separation of onsets
- `density_timeline`: 8-segment onset density over time (onsets/second)
- `density_shape`: Trajectory classification: "building", "thinning", "consistent", "varied"
- `onset_count`: Total detected onsets

### 3.3 Spectral Section (`_analyze_spectral`)

**Full output stored in** `analysis_detail.spectral`

| Datapoint | Typed Column | Type | Method |
|-----------|-------------|------|--------|
| Brightness | `brightness` | `Float` (0–1) | Spectral centroid in Hz normalized: `min(centroid_hz / 8000, 1.0)`. Fallback from string label: dark=0.1, neutral=0.5, bright=0.9 |

**Additional JSONB-only data:**
- `brightness` (string): "dark" (<0.1 normalized centroid), "neutral" (<0.25), "bright" (≥0.25)
- `brightness_curve`: 8-segment spectral centroid trajectory
- `centroid_hz`: Raw mean spectral centroid in Hz
- `band_energy`: 6-band energy distribution as percentages — sub_bass (20–60Hz), bass (60–250Hz), low_mid (250–1kHz), mid (1–4kHz), high_mid (4–8kHz), high (8–16kHz)
- `mfcc_mean`: 13 averaged MFCC coefficients (timbral fingerprint)
- `spectral_contrast`: 7-band spectral contrast means
- `rolloff_hz`: Spectral rolloff frequency (85th percentile of spectral energy)
- `flatness`: Spectral flatness (0 = tonal, 1 = noise-like)

### 3.4 Structural Section (`_analyze_structural`)

**Full output stored in** `analysis_detail.structural`

| Datapoint | Typed Column | Type | Method |
|-----------|-------------|------|--------|
| Section count | `section_count` | `Integer` | Number of detected segments |
| Form string | `form_string` | `String(50)` | Section label sequence, e.g., "AABACBA" |
| Avg section length | `avg_section_length` | `Float` | Mean segment duration in seconds |

**Method details:**
1. **Self-similarity matrix**: Combined chroma (12-dim) + MFCC (13-dim) features, downsampled to ~200 frames, cosine similarity
2. **Segmentation**: Foote novelty function (kernel_size=16) with threshold `mean + 0.25 * std`, supplemented by RMS energy change detection. Single-segment retry at threshold=0.0 for tracks >60s.
3. **Section labeling**: Multi-feature similarity (chroma cosine >0.97, energy diff <3dB, MFCC cosine >0.95) to assign letter labels (A, B, C, ...)

**Additional JSONB-only data:**
- `segments`: Full segment list with start/end times, durations, and labels
- `self_similarity_png_path`: Rendered self-similarity matrix image (saved to disk)
- `section_profiles`: Per-section energy (RMS dB), brightness (string label), and density (sparse/moderate/dense based on chroma variance)

### 3.5 Energy Section (`_analyze_energy`)

**Full output stored in** `analysis_detail.energy`

| Datapoint | Typed Column | Type | Method |
|-----------|-------------|------|--------|
| Dynamic range | `dynamic_range_db` | `Float` | RMS 5th–95th percentile range in dB |
| Energy shape | `energy_shape` | `String(20)` | Classification from RMS curve quartiles: "gradual build", "fade out", "peak in middle", "consistent" (std < 0.1), "dynamic" |

**Additional JSONB-only data:**
- `rms_curve`: 32-point normalized RMS energy curve
- `rms_mean_db`: Mean RMS in dB
- `rms_peak_db`: Peak RMS in dB
- `builds`: Detected energy builds (ratio > 2.0) and drops (ratio < 0.4) with timestamps

### 3.6 Post-processing: Melodic Sketches

Added by `_add_melodic_sketches()` after structural + melodic sections complete. Stored in `analysis_detail.melodic.section_sketches`.

- Per unique section label, extracts first 12 above-median-pitch notes from MIDI data
- Formats as note names with rhythm symbols (e.g., "C4(♩) E4(♪) G4(𝅗𝅥)")
- Requires both structural segments and MIDI transcription to be available

---

## 4. Phase 2: CLAP Embeddings

| | |
|---|---|
| **Column** | `track_analysis.embedding` (`Vector(512)`) |
| **Method** | LAION CLAP model (`laion/clap-htsat-unfused`) via HuggingFace Transformers |
| **Input** | 10-second middle section at 48kHz mono |
| **Output** | 512-dimensional float vector |
| **Confidence** | N/A — embedding, not classification |
| **3rd party** | `transformers` (HuggingFace), PyTorch, CLAP model weights |
| **Versions** | `EMBEDDING_VERSION = 6` |

**Usage**: Cosine similarity search for "Music Map" and text-to-audio semantic search (via `extract_text_embedding()`).

**Text embeddings**: Same CLAP model embeds text descriptions into the same 512-dim space, enabling natural language queries like "gloomy with Eastern influences" to find matching tracks.

---

## 5. Phase 3: Melodic Analysis

Run by `_analyze_melodic()` in `analyzers.py`. Uses **basic-pitch** (Spotify's ML model) for polyphonic MIDI transcription, then derives features from the note events.

| Datapoint | Typed Column | Type | Method |
|-----------|-------------|------|--------|
| Note density | `note_density` | `Float` | Notes per beat: `note_count / (duration / 60 * bpm)` |
| Interval character | `interval_character` | `String(20)` | From mean absolute interval: "stepwise-dominant" (<2.5), "mixed" (2.5–4.0), "leap-heavy" (>4.0). No-unison variant also computed. |
| Pitch range | `pitch_range` | `Integer` | MIDI note range: `max(pitch) - min(pitch)` in semitones |

### Additional JSONB-only melodic data (`analysis_detail.melodic`):

| Datapoint | Method |
|-----------|--------|
| `note_count` | Total notes after deduplication (consecutive same-pitch <50ms gap merged) |
| `pitch_range` (detailed) | Object: low/high MIDI note, low/high note name, 10th/90th percentile primary range |
| `interval_histogram` | Distribution of intervals (-12 to +12 semitones) as percentages |
| `unison_pct` | Percentage of repeated-pitch intervals |
| `interval_histogram_no_unison` | Interval distribution excluding unisons |
| `phrase_count` | Detected phrases via gap segmentation (gap > 2 beats or 1s). Density-based fallback when gap detection yields <4 phrases. |
| `phrase_detection_method` | "gap", "density-fallback", or "low" (insufficient phrases) |
| `avg_phrase_length_seconds` | Mean phrase duration |
| `contour_summary` | Per-phrase pitch contour: "ascending", "descending", "arch", "valley", "flat". Classified by half-half net interval direction. Octave jumps (>6 semitones) skipped. |
| `dominant_contour` | Most common contour type |
| `register_trend` | Linear pitch trend over 30s windows: "rising" (slope > 0.3), "falling" (< -0.3), "stable" |
| `register_slope` | Exact slope value |
| `pitch_class_distribution` | Note name distribution as percentages |
| `register_intervals` | Per-register (bass 0–48, mid 48–72, lead 72–128) interval histograms and character |
| `interval_transitions_common` | Top 10 most frequent interval pairs with counts and percentages |
| `interval_transitions_unexpected` | Top 5 interval pairs with highest observed/expected ratio (independence model) |
| `midi_path` | Saved MIDI file path for downstream use |

**3rd party**: `basic-pitch` (Spotify, ONNX runtime), `pretty_midi`
**Versions**: `MELODIC_VERSION = 6`

---

## 6. Phase 4: Mood Tags

CLAP-based semantic tagging via `mood_tags.py`. Uses cosine similarity between a track's CLAP audio embedding and pre-computed text descriptor embeddings to assign descriptive tags.

| | |
|---|---|
| **Columns** | `track_analysis.mood_tags` (`JSONB`, GIN-indexed), `track_analysis.mood_tags_version` (`Integer`) |
| **Method** | Cosine similarity between track's 512-dim CLAP audio embedding (normalized) and 48 descriptor text embeddings. Top-K tags returned above a minimum confidence threshold. |
| **Parameters** | `top_k = 5`, `min_confidence = 0.15` |
| **Versions** | `MOOD_TAGS_VERSION = 1` |

### Descriptor Categories (48 total)

| Category | Count | Descriptors |
|----------|-------|-------------|
| Mood | 16 | happy, sad, angry, calm, dark, bright, dreamy, energetic, romantic, mysterious, nostalgic, triumphant, playful, anxious, serene, rebellious |
| Genre | 16 | jazz, electronic, rock, classical, hip-hop, folk, metal, ambient, blues, funk, reggae, soul, country, punk, world, pop |
| Instrumentation | 8 | piano, acoustic guitar, bass-heavy, strings, brass/sax, synthesizer, drums, vocal/choir |
| Energy | 8 | slow, mid-tempo, fast, building, sparse, dense, danceable, freeform |

Each descriptor has a natural-language description (e.g., "happy uplifting joyful music") that is embedded via CLAP `extract_text_embedding()` into the same 512-dim space as audio.

### Implementation Details

- **Text embedding cache**: Descriptor embeddings cached in Redis with **24-hour TTL** (key: `mood_tags:descriptor_embeddings`)
- **Performance**: Very fast per track — only numpy dot product, no model inference needed (CLAP audio embedding already exists from Phase 2)
- **Output format**: `[{"tag": str, "category": str, "confidence": float}]` (confidence rounded to 3 decimal places)
- **Prerequisite**: Requires a CLAP embedding (Phase 2) to exist for the track

---

## 7. External Sources

### 7.1 AcoustID / Chromaprint

| | |
|---|---|
| **Columns** | `track_analysis.acoustid` (fingerprint text), `track_analysis.acoustid_lookup` (JSONB) |
| **Method** | `chromaprint`/`fpcalc` generates audio fingerprint; `acoustid` Python library queries the AcoustID web service |
| **Confidence** | AcoustID returns a match score (0.0–1.0); high-confidence threshold is > 0.8 for auto-matching, > 0.5 for candidates |
| **Data returned** | `acoustid_score`, `musicbrainz_recording_id`, `title`, `artist` |
| **3rd party** | chromaprint (native binary), AcoustID web API (requires free API key) |

### 7.2 MusicBrainz

| | |
|---|---|
| **Integration** | Via `metadata/musicbrainz.py` — `MusicBrainzService` |
| **Data** | Recording ID, artist ID, album ID, ISRC, release metadata |
| **Method** | Lookup by AcoustID recording ID or ISRC; provides authoritative metadata |
| **Columns** | `tracks.musicbrainz_track_id`, `musicbrainz_artist_id`, `musicbrainz_album_id`, `isrc` |

### 7.3 ReccoBeats (External Features)

| | |
|---|---|
| **Service** | `external_features.py:ExternalFeaturesService` |
| **Trigger** | When `external_features_enabled` in app settings and track has a linked `SpotifyFavorite` |
| **API** | `https://api.reccobeats.com/v1/track/{spotify_id}/audio-features` |
| **Data returned** | Spotify-compatible features: bpm, key (pitch class + mode), energy, danceability, valence, acousticness, instrumentalness, speechiness, liveness, loudness |
| **Confidence** | Hardcoded 1.0 — assumes Spotify-grade accuracy |
| **3rd party** | ReccoBeats free API (no auth), requires Spotify track ID match |
| **Source tracking** | `features_source = "reccobeats"` |

### 7.4 Community Cache

| | |
|---|---|
| **Service** | `community_cache.py:CommunityCacheService` |
| **Server** | `https://familiar-cache.fly.dev` |
| **Key** | SHA256 hash of AcoustID fingerprint (privacy-preserving) |
| **Data types** | Embeddings (512-dim CLAP), features (all scalar columns), analysis_detail (full structured data) |
| **Versioning** | Matched by `EMBEDDING_VERSION`, `FEATURES_VERSION`, and CLAP model version |
| **Confidence** | `contributor_count` indicates how many users contributed (more = higher trust) |
| **Source tracking** | `features_source = "community_cache"`, `embedding_source = "community_cache"` |
| **Privacy** | Fingerprints are SHA256-hashed before transmission; no metadata or file info shared |
| **Opt-in** | Both lookup and contribution are controlled by app settings |

### 7.5 Spotify (via SpotifyFavorite matching)

Not a direct analysis source, but provides the Spotify track ID needed for ReccoBeats lookup. `SpotifyFavorite` records are matched to local tracks, linking the Spotify ecosystem to the local library.

### 7.6 Cross-Validation

When both local and external features are available, `_compute_disagreements()` compares them and stores results in `feature_confidence`.

**Behavior**: Local analysis always runs regardless of external source availability. When external features are primary (`features_source != "local"`), locally-computed values are preserved in the `local_features` JSONB column.

**Disagreement detection**:

| Feature | Condition | Label |
|---------|-----------|-------|
| BPM | `abs(ratio - 0.5) < 0.1` | `half_tempo` |
| BPM | `abs(ratio - 2.0) < 0.2` | `double_tempo` |
| BPM | `abs(ratio - 1.0) > 0.15` | `different` |
| Key | Different root pitch class | `different_root` |
| Key | Same root, different mode | `different_mode` |
| Energy, Valence, Danceability | `abs(local - external) > 0.3` | `large_difference` |

**Storage**: For each compared feature, sets `feature_confidence["{feat}_cross_validated"] = true`. If a disagreement is found, also sets `feature_confidence["{feat}_disagreement"] = "<type>"`.

---

## 8. Structural/Tracking Columns

These columns manage the analysis lifecycle rather than store analysis results:

| Column | Type | Purpose |
|--------|------|---------|
| `track_analysis.features_version` | `Integer` | Current `FEATURES_VERSION` (8) — triggers re-analysis when bumped |
| `track_analysis.embedding_version` | `Integer` | Current `EMBEDDING_VERSION` (6) |
| `track_analysis.melodic_version` | `Integer` | Current `MELODIC_VERSION` (6) |
| `track_analysis.mood_tags_version` | `Integer` | Current `MOOD_TAGS_VERSION` (1) |
| `track_analysis.has_melodic` | `Boolean` | Whether Phase 3 completed successfully |
| `track_analysis.midi_path` | `String(500)` | Path to saved MIDI transcription |
| `track_analysis.features_source` | `String(50)` | "local", "reccobeats", "community_cache" |
| `track_analysis.embedding_source` | `String(50)` | "local", "community_cache" |
| `track_analysis.analysis_detail` | `JSONB` | Full structured data from deep analysis (Sections 3.1–3.5 + melodic) |
| `track_analysis.feature_confidence` | `JSONB` | Per-feature confidence scores and cross-validation results (see [2.12](#212-feature-confidence-scores)) |
| `track_analysis.local_features` | `JSONB` | Locally-computed feature values when external features are primary (see [7.6](#76-cross-validation)) |
| `track_analysis.mood_tags` | `JSONB` | CLAP-based mood, genre, instrumentation, and energy tags (GIN-indexed, see [Section 6](#6-phase-4-mood-tags)) |
| `track_analysis.acoustid` | `Text` | Base64-encoded chromaprint audio fingerprint |
| `track_analysis.acoustid_lookup` | `JSONB` | Cached AcoustID API lookup results (candidates with scores/recording IDs) |
| `track_analysis.embedding_error` | `String(500)` | Last embedding failure message |
| `track_analysis.embedding_failed_at` | `DateTime` | When embedding last failed |
| `track_analysis.created_at` | `DateTime` | When the analysis record was created |
| `tracks.analyzed_at` | `DateTime` | When analysis completed |
| `tracks.analysis_error` | `String(500)` | Last analysis failure message |
| `tracks.analysis_failed_at` | `DateTime` | When analysis last failed |
| `tracks.user_overrides` | `JSONB` | User-provided corrections (e.g., `{"bpm": 124.0, "key": "Am"}`) |

---

## 9. Gaps & Improvement Opportunities

### 9.1 Algorithmic Weaknesses

#### Acousticness — ADDRESSED in v8
~~**Previous**: `1 - spectral_centroid_normalized * 2` — simply the inverse of brightness.~~
**Now**: 5-factor weighted composite (MFCC1, spectral flatness, rolloff, MFCC variance, crest factor). Confidence raised from "Low" to "Medium" (0.6). See [Section 2.6](#26-acousticness).
**Remaining**: A trained ML classifier on MFCCs could still outperform the heuristic composite. Cross-validation against ReccoBeats values where available would help calibrate.

#### Instrumentalness — ADDRESSED in v8
~~**Previous**: Energy ratio in 300–3000 Hz (the "vocal band") vs total.~~
**Now**: silero-vad ONNX model for speech probability detection, with spectral fallback. Confidence 0.5–0.9 with VAD vs 0.3 with fallback. See [Section 2.7](#27-instrumentalness).
**Remaining**: Per-segment vocal/instrumental classification (rather than whole-track average) could enable more granular tagging.

#### Speechiness — ADDRESSED in v8
~~**Previous**: Zero-crossing rate × 2.~~
**Now**: VAD speech probability × (1 - RMS autocorrelation periodicity) to distinguish speech from singing. See [Section 2.8](#28-speechiness).
**Remaining**: A dedicated speech/music discriminator could further improve accuracy for edge cases (spoken word over music, rap).

#### Valence — PARTIALLY ADDRESSED in v8
**Previous**: 5-component weighted composite (mode, brightness, tempo, contrast, dynamics).
**Now**: 7-component composite adding harmonic tension (12%) and tonality/spectral flatness (8%), with rebalanced weights. See [Section 2.5](#25-valence).
**Remaining**: Still a heuristic — lyrics, arrangement density, and cultural context are not captured. CLAP text embeddings (embed "happy"/"sad" descriptors and cosine-compare) could provide an additional signal. Cross-validation against ReccoBeats valence would help calibrate.

#### Key Detection — ADDRESSED in v8
~~**Previous**: Simple argmax of mean chroma. No major/minor distinction.~~
**Now**: Krumhansl-Kessler key profile correlation across all 24 keys (12 roots × major + minor). Returns mode suffix (e.g., "Am", "F#m"). See [Section 2.2](#22-key).
**Remaining**: Extended modes (Dorian, Mixolydian, etc.) are still only available in deep analysis `modal_character`. Could be promoted to the core `key` column for tracks with high modal confidence.

### 9.2 Confidence Scores — ADDRESSED in v8

~~**Previous**: No per-feature confidence scores for most core features.~~
**Now**: `feature_confidence` JSONB column on `TrackAnalysis` stores per-feature confidence scores (0.0–1.0). See [Section 2.12](#212-feature-confidence-scores).

| Feature | Confidence | Status |
|---------|-----------|--------|
| BPM | 0.2–1.0 | Implemented — onset envelope variance |
| Key | varies | Implemented — KK correlation score |
| Energy | 0.95 | Implemented — fixed (direct measurement) |
| Danceability | 0.3–0.95 | Implemented — PLP pulse variance |
| Acousticness | 0.6 | Implemented — fixed (heuristic) |
| Instrumentalness | 0.3–0.9 | Implemented — VAD signal strength |
| Speechiness | 0.3–0.9 | Implemented — matches instrumentalness |
| Valence | 0.4 | Implemented — fixed (subjective) |
| Chord sequence | Per-chord | Already existed |
| Structural sections | None | Still missing — Foote novelty peak height could serve as boundary confidence |

### 9.3 Features That Could Benefit from ML

| Feature | Current Approach | ML Alternative | Status |
|---------|-----------------|----------------|--------|
| Acousticness | MFCC + spectral composite (v8) | MFCCs → trained classifier | Improved in v8, ML could still help |
| Instrumentalness | silero-vad (v8) | Fine-tuned vocal detection | Addressed in v8 |
| Speechiness | VAD + periodicity (v8) | Dedicated speech/music discriminator | Addressed in v8 |
| Chord detection | Template matching (84 templates) | Neural chord recognition (e.g., madmom) | Unchanged |
| Genre/mood | CLAP cosine similarity (v8) | CLAP embedding → fine-tuned classifier heads | Addressed in v8 (heuristic), ML could improve |
| Vocal/instrumental segments | silero-vad whole-track (v8) | Per-segment silero-vad classification | Partially addressed |

The CLAP embedding captures high-level audio semantics in 512 dimensions. Adding lightweight classifier heads on top of existing embeddings would provide more accurate genre, mood, and instrumentation labels than the current cosine-similarity approach.

### 9.4 Cross-Validation — ADDRESSED in v8

~~**Previous**: No cross-validation between local and external features.~~
**Now**: `_compute_disagreements()` compares local vs external features, storing results in `feature_confidence` with `_cross_validated` and `_disagreement` suffixes. Local features preserved in `local_features` JSONB when external features are primary. See [Section 7.6](#76-cross-validation).

**Remaining**: Using disagreement data to automatically calibrate local algorithm weights over time (e.g., tuning valence weights based on ReccoBeats correlation).

### 9.5 Missing Datapoints That Would Aid Discovery

| Datapoint | Value for Discovery | Possible Approach | Status |
|-----------|-------------------|-------------------|--------|
| **Genre tags** (multi-label) | Essential for browsing/filtering | CLAP cosine similarity | **Addressed** — mood_tags genre category (16 genres) |
| **Mood tags** (multi-label) | Natural language queries ("play something chill") | CLAP cosine similarity | **Addressed** — mood_tags mood category (16 moods) |
| **Instrumentation tags** | "tracks with saxophone", "piano-driven" | CLAP cosine similarity | **Addressed** — mood_tags instrumentation category (8 tags) |
| **Vocal gender** | "female vocalist", "male vocalist" queries | Pitch range from basic-pitch lead register; or dedicated classifier | Not implemented |
| **Era/production style** | "80s synth pop", "lo-fi" | MFCC + spectral features → decade classifier; spectral flatness for lo-fi detection | Not implemented |
| **Tempo stability (exact)** | DJ-oriented "beatmatch-safe" flag | Already have `tempo_cv` — just needs a promoted column and threshold | Not implemented |
| **Time signature** | 3/4, 6/8, 5/4 detection | Beat tracking pattern analysis; basic-pitch note groupings | Not implemented |
| **Key confidence** | Ambiguous vs strong key center | KK correlation score | **Addressed** — stored in `feature_confidence.key` |
| **Similar track IDs** | "more like this" without full embedding search | Pre-compute k-NN from CLAP embeddings, store as JSONB | Not implemented |
| **Audio quality score** | Filter out poorly encoded/corrupted files | Dynamic range + spectral analysis for clipping, encoding artifacts | Not implemented |
| **Lyrics language** | Filter by language for multilingual libraries | Existing `lyrics` text → language detection library | Not implemented |
| **Chorus/hook timestamp** | Jump to "the good part" | Structural analysis + energy peaks already available — combine for hook detection | Not implemented |

### 9.6 Architecture Improvements

#### Feature Confidence as First-Class Data — ADDRESSED in v8
~~Previously stored inconsistently.~~ Now `feature_confidence` JSONB field on `TrackAnalysis` stores per-feature confidence scores and cross-validation results. Used by LLM, smart playlists, and UI to weight features appropriately.

#### Source Provenance Tracking — ADDRESSED in v8
~~No way to compare local vs external values.~~ Now `local_features` JSONB stores locally-computed values when external features are primary, and `_compute_disagreements()` flags discrepancies.

#### Incremental Deep Analysis
Currently, deep analysis is all-or-nothing per section. If the harmonic analyzer improves, all 5 sections re-run. Consider per-section versioning so improvements to one analyzer don't waste work on unchanged analyzers.

#### MIDI Transcription Reuse
basic-pitch MIDI output is saved but only used for melodic analysis and sketches. The MIDI data could also drive:
- Better instrumentalness (polyphonic instrument detection)
- Rhythm complexity beyond onset-based measures
- Arrangement density over time
- Lead melody extraction for similarity
