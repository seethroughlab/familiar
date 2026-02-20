# track_analysis/ — Audio Feature Extraction & Reports

Owns audio feature extraction (harmonic, rhythmic, spectral, structural, energy, melodic) and markdown report generation.

## Public API (re-exported from `__init__.py`)

- **pipeline**: `run_analysis`, `run_backfill`, `run_track_melodic`, `run_cheap_sections`, `extract_feature_scalars`, `extract_melodic_scalars`
- **reports**: `generate_report`, `generate_comparative_report`
- **constants**: `MIDI_DATA_DIR`

## Does NOT handle

- Audio I/O (expects numpy arrays from callers)
- Database persistence (returns dicts; callers store results)
- LLM calls
- Concurrency/pooling (caller manages ProcessPoolExecutor)
