# metadata/ — Audio File Metadata I/O & Enrichment

Owns reading, writing, and enriching audio file metadata — MusicBrainz lookup, AcoustID fingerprinting, Cover Art Archive, multi-format tag I/O.

## Modules

- **reader**: `extract_metadata` (re-exported from `__init__.py`) — read tags from audio files
- **writer**: `MetadataWriter` — write tags back to audio files
- **musicbrainz**: `MusicBrainzService` — MusicBrainz API lookups
- **audio_identification**: `AudioIdentificationService` — AcoustID fingerprinting
- **lookup**: `MetadataLookupService` — orchestrates identification + MusicBrainz matching
- **enrichment**: `MetadataEnrichmentService` — batch enrichment with cover art

## Does NOT handle

- Database persistence (callers update models)
- Library scanning (`services/scanner.py`)
- Audio analysis/features (`track_analysis/`)
- Spotify OAuth
- LLM integration
