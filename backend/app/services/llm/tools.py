"""LLM tool definitions for music discovery."""

from typing import Any

# Tool definitions for Claude
MUSIC_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_library",
        "description": "Search the user's music library by text query. Searches across title, artist, album, and genre. Returns matching tracks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20)",
                    "default": 20
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "find_similar_tracks",
        "description": "Find tracks that SOUND like a given track — nearest neighbours in the audio embedding space, and nothing else. Use it for 'what else sounds like this?'. For a listening session rather than a similarity list, prefer get_radio_suggestions, which adds this listener's taste and what they have skipped.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track_id": {
                    "type": "string",
                    "description": "UUID of the reference track"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of similar tracks to return",
                    "default": 10
                }
            },
            "required": ["track_id"]
        }
    },
    {
        "name": "semantic_search",
        "description": "Search for tracks using natural language descriptions of sound, mood, or style. Uses AI audio embeddings to find tracks that sonically match descriptions like 'dreamy atmospheric synths', 'aggressive heavy guitars', 'mellow jazz with piano', 'gloomy with Eastern influences'. Best for abstract or mood-based queries where metadata search won't work well.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Natural language description of the sound, mood, or style you're looking for"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20)",
                    "default": 20
                }
            },
            "required": ["description"]
        }
    },
    {
        "name": "filter_tracks",
        "description": "Filter tracks by library criteria (favorites, play history, genre, artist, year, recently added) and/or audio features (BPM, energy, key, swing feel, brightness, modal character, energy shape, and more). Use for requests like 'play my favorites', 'what have I been listening to', 'electronic tracks from the 90s', 'upbeat songs', 'something around 120 BPM', 'tracks with swing feel', 'something in Dorian mode', 'bright sounding tracks'.",
        "input_schema": {
            "type": "object",
            "properties": {
                # Library criteria
                "genre": {"type": "string", "description": "Genre filter (case-insensitive partial match, e.g. 'electronic', 'jazz')"},
                "artist": {"type": "string", "description": "Artist filter (case-insensitive partial match)"},
                "year_min": {"type": "integer", "description": "Minimum release year"},
                "year_max": {"type": "integer", "description": "Maximum release year"},
                "added_in_last_days": {"type": "integer", "description": "Only tracks added to library within N days"},
                "is_favorite": {"type": "boolean", "description": "Only favorited tracks (requires profile)"},
                "min_play_count": {"type": "integer", "description": "Minimum play count"},
                "max_play_count": {"type": "integer", "description": "Maximum play count (0 = never played)"},
                "played_in_last_days": {"type": "integer", "description": "Only tracks played within N days"},
                "not_played_in_days": {"type": "integer", "description": "Tracks not played within N days (includes never-played)"},
                "sort_by": {
                    "type": "string",
                    "enum": ["random", "play_count", "last_played", "recently_added", "title", "artist", "year"],
                    "description": "Sort order (default: random)"
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Sort direction (default depends on sort_by)"
                },
                # Audio feature criteria
                "bpm_min": {"type": "number", "description": "Minimum BPM"},
                "bpm_max": {"type": "number", "description": "Maximum BPM"},
                "key": {"type": "string", "description": "Musical key to filter by. Supports major keys ('C', 'F', 'G#', 'Bb') and minor keys ('Am', 'F#m', 'A minor'). Plain letter matches both major and minor (e.g., 'A' matches 'A' and 'Am')."},
                "mood_tag": {"type": "string", "description": "Filter by mood/genre/instrumentation tag (e.g., 'dreamy', 'jazz', 'piano', 'energetic'). Use get_available_mood_tags to see all available tags."},
                "lyrics_language": {"type": "string", "description": "ISO 639-1 language code for lyrics (e.g., 'en', 'fr', 'de', 'ja', 'es'). Only applies to tracks with lyrics."},
                "energy_min": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum energy (0-1)"},
                "energy_max": {"type": "number", "minimum": 0, "maximum": 1, "description": "Maximum energy (0-1)"},
                "danceability_min": {"type": "number", "minimum": 0, "maximum": 1},
                "valence_min": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum valence/happiness (0-1)"},
                "valence_max": {"type": "number", "minimum": 0, "maximum": 1},
                "acousticness_min": {"type": "number", "minimum": 0, "maximum": 1},
                "instrumentalness_min": {"type": "number", "minimum": 0, "maximum": 1},
                # Deep analysis feature criteria
                "swing_min": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum swing ratio (0=straight, 1=heavy swing)"},
                "swing_max": {"type": "number", "minimum": 0, "maximum": 1, "description": "Maximum swing ratio"},
                "syncopation_min": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum syncopation index"},
                "brightness_min": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum brightness (spectral centroid, 0=dark, 1=bright)"},
                "brightness_max": {"type": "number", "minimum": 0, "maximum": 1, "description": "Maximum brightness"},
                "dynamic_range_min": {"type": "number", "description": "Minimum dynamic range in dB"},
                "energy_shape": {"type": "string", "enum": ["gradual_build", "fade_out", "peak_middle", "consistent", "dynamic"], "description": "Energy shape pattern"},
                "modal_character": {"type": "string", "description": "Modal character filter (e.g. 'dorian', 'mixolydian', 'lydian')"},
                "key_stability": {"type": "string", "enum": ["stable", "drifting", "modulating"], "description": "Key stability filter"},
                "section_count_min": {"type": "integer", "description": "Minimum number of song sections"},
                "section_count_max": {"type": "integer", "description": "Maximum number of song sections"},
                "note_density_min": {"type": "number", "description": "Minimum melodic note density (notes per beat)"},
                "note_density_max": {"type": "number", "description": "Maximum melodic note density"},
                "harmonic_complexity_min": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum harmonic complexity (0=simple triads, 1=dense jazz chords)"},
                "harmonic_complexity_max": {"type": "number", "minimum": 0, "maximum": 1, "description": "Maximum harmonic complexity"},
                "speechiness_min": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum speechiness (0=singing/instrumental, 1=spoken word)"},
                "speechiness_max": {"type": "number", "minimum": 0, "maximum": 1, "description": "Maximum speechiness"},
                "tempo_character": {"type": "string", "enum": ["grid-locked", "slight drift", "breathing"], "description": "Tempo feel: 'grid-locked' (tight quantized), 'slight drift' (natural), 'breathing' (rubato/expressive)"},
                "tempo_cv_max": {"type": "number", "minimum": 0, "maximum": 1, "description": "Maximum tempo CV (coefficient of variation). <0.05 = beatmatch-safe/grid-locked, <0.15 = natural, >0.15 = rubato"},
                "pitch_range_min": {"type": "integer", "description": "Minimum pitch range in semitones (narrow=<12, wide=24+)"},
                "pitch_range_max": {"type": "integer", "description": "Maximum pitch range in semitones"},
                "limit": {"type": "integer", "default": 20}
            }
        }
    },
    {
        "name": "generate_playlist",
        "description": (
            "Build a playlist from a seed — a track, an album, an artist, or an explicit set of "
            "tracks — using the library's audio analysis. This is the same implementation the app's "
            "'Make a playlist' menu items call (ADR-0048), so a host and the app produce identical "
            "results. Prefer this over composing a playlist by hand from search results: it scores "
            "the whole library by embedding similarity plus this listener's taste, and enforces "
            "artist and album diversity. The seed material is excluded from the result unless "
            "include_seed is set. Provide exactly one seed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "track_id": {
                    "type": "string",
                    "description": "UUID of a single seed track"
                },
                "album": {
                    "type": "string",
                    "description": "Album name to seed from. Pair with artist when the name is ambiguous."
                },
                "artist": {
                    "type": "string",
                    "description": "Artist name to seed from, or to disambiguate album"
                },
                "track_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit set of seed track UUIDs, averaged into one centroid"
                },
                "limit": {
                    "type": "integer",
                    "description": "How many tracks to aim for (default 25)",
                    "default": 25
                },
                "max_per_artist": {
                    "type": "integer",
                    "description": "Cap per artist in the result (default 2)",
                    "default": 2
                },
                "include_seed": {
                    "type": "boolean",
                    "description": "Include the seed tracks themselves (default false)",
                    "default": False
                },
                "name": {
                    "type": "string",
                    "description": "Override the generated name. Omit for a deterministic one."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_library_stats",
        "description": "Get statistics about the music library: total tracks, artists, albums, genres. Use when user asks about their library.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_library_genres",
        "description": "Get all genres in the library with track counts. IMPORTANT: Use this first when user asks for mood-based music (e.g., 'sleepy', 'chill', 'upbeat') to find what actual genre names match their request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max genres to return (default 50)",
                    "default": 50
                }
            }
        }
    },
    {
        "name": "get_feature_distribution",
        "description": "Get min/max/mean/median statistics for an audio feature across the library. Use this to calibrate filter values to the user's actual collection before filtering — e.g., know that 'high energy' in a folk library is different from an EDM library.",
        "input_schema": {
            "type": "object",
            "properties": {
                "feature": {
                    "type": "string",
                    "enum": [
                        "energy", "valence", "danceability", "bpm",
                        "acousticness", "instrumentalness", "speechiness",
                        "brightness", "dynamic_range_db", "harmonic_complexity",
                        "swing_ratio", "syncopation", "note_density", "pitch_range",
                        "section_count", "tempo_cv",
                    ],
                    "description": "The audio feature to get statistics for"
                }
            },
            "required": ["feature"]
        }
    },
    {
        "name": "get_available_mood_tags",
        "description": "Get all available mood/genre/instrumentation tags with track counts. Use this to see what mood tags exist in the library before filtering by mood_tag.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["mood", "genre", "instrumentation", "energy"],
                    "description": "Filter to a specific category (optional, returns all if omitted)"
                }
            }
        }
    },
    {
        "name": "get_visible_tracks",
        "description": "Get the tracks currently visible in the user's library view. Use this when the user refers to 'these tracks', 'this list', 'what I'm looking at', 'all of these', or wants to queue/analyze the tracks they're currently viewing. Returns track IDs and basic metadata for all tracks in the current view.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "queue_tracks",
        "description": "Add tracks to the playback queue. Can include both local tracks and suggested external tracks (if discovery mode allows). Use after finding tracks the user wants to play.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of local track UUIDs to queue"
                },
                "suggested_tracks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Track title"},
                            "artist": {"type": "string", "description": "Artist name"},
                            "album": {"type": "string", "description": "Album name (optional)"},
                            "reason": {"type": "string", "description": "Why this track is suggested"}
                        },
                        "required": ["title", "artist"]
                    },
                    "description": "External tracks to suggest (only added if discovery_mode is 'suggest_missing')"
                },
                "clear_existing": {
                    "type": "boolean",
                    "default": False,
                    "description": "Clear current queue before adding"
                }
            },
            "required": ["track_ids"]
        }
    },
    {
        "name": "control_playback",
        "description": "Control music playback: play, pause, skip, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous", "shuffle_on", "shuffle_off"],
                    "description": "Playback action to perform"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "get_track_details",
        "description": "Get detailed information about a specific track including audio features.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track_id": {
                    "type": "string",
                    "description": "UUID of the track"
                }
            },
            "required": ["track_id"]
        }
    },
    {
        "name": "search_bandcamp",
        "description": "Search Bandcamp for albums or tracks the user might want to purchase. Use this when the user wants to find music to buy, especially for artists they like but don't have locally.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (artist name, album name, or general search)"
                },
                "item_type": {
                    "type": "string",
                    "enum": ["album", "track", "artist"],
                    "description": "Type of result to search for",
                    "default": "album"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "recommend_bandcamp_purchases",
        "description": "Suggest Bandcamp albums to purchase based on artists in the local library. Helps users discover more music to buy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max recommendations (default 5)",
                    "default": 5
                }
            }
        }
    },
    {
        "name": "select_diverse_tracks",
        "description": "From a list of track IDs, select a diverse subset with variety across different artists and albums. Use this before queueing to ensure the playlist has good variety.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of track UUIDs to select from"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max tracks to return (default 20)",
                    "default": 20
                },
                "max_per_artist": {
                    "type": "integer",
                    "description": "Maximum tracks from any single artist (default 2)",
                    "default": 2
                },
                "max_per_album": {
                    "type": "integer",
                    "description": "Maximum tracks from any single album (default 2)",
                    "default": 2
                }
            },
            "required": ["track_ids"]
        }
    },
    # Discovery tools
    {
        "name": "get_new_releases",
        "description": "Find recent releases by the user's most-played artists via MusicBrainz. Use when the user asks about new music from artists they listen to, what's new, or recent releases. May take 10-15 seconds due to MusicBrainz lookups. Returns releases with in_library flag indicating if the user already has them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "How far back to look for releases (default 90 days, max 365)",
                    "default": 90
                },
                "limit": {
                    "type": "integer",
                    "description": "Max releases to return (default 20)",
                    "default": 20
                }
            }
        }
    },
    {
        "name": "get_discovery_recommendations",
        "description": "Get recommended artists based on the user's most-played artists. Returns external artists similar to what the user listens to (via Last.fm), plus unheard tracks and deep cuts from artists they already have. Use when the user wants to discover new artists, asks 'who should I listen to', or wants recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_in_library": {
                    "type": "boolean",
                    "description": "Include artists already in library (default false, external only)",
                    "default": False
                },
                "seed_artists": {
                    "type": "integer",
                    "description": "Number of top-played artists to base recommendations on (default 5)",
                    "default": 5
                },
                "limit": {
                    "type": "integer",
                    "description": "Max recommended artists to return (default 8)",
                    "default": 8
                }
            }
        }
    },
    {
        "name": "get_spotify_unmatched",
        "description": "Find Spotify favorites and playlist tracks that aren't in the user's local library. Requires a prior Spotify data import. Use when the user asks what they're missing from Spotify, what to add next, or wants to compare libraries. Returns unmatched tracks with stats.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Free-text search across artist, track, and album names"
                },
                "artist": {
                    "type": "string",
                    "description": "Filter by artist name (case-insensitive)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 50)",
                    "default": 50
                }
            }
        }
    },
    {
        "name": "get_similar_artists_in_library",
        "description": "Find artists similar to a given artist that exist in the user's library. Uses Last.fm to find similar artists, then checks which ones the user actually has. IMPORTANT: Use this when the user asks for music like an artist they may not have. Returns similar artists in the library plus a Bandcamp link if the requested artist isn't in the library.",
        "input_schema": {
            "type": "object",
            "properties": {
                "artist": {
                    "type": "string",
                    "description": "Artist name to find similar artists for"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max similar artists to return (default 20)",
                    "default": 20
                }
            },
            "required": ["artist"]
        }
    },
    # Metadata correction tools
    {
        "name": "lookup_correct_metadata",
        "description": "Look up correct metadata for a track from external sources (MusicBrainz). Use when the user reports incorrect metadata or you notice potential issues like wrong artist, album, year, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track_id": {
                    "type": "string",
                    "description": "UUID of the track to look up"
                }
            },
            "required": ["track_id"]
        }
    },
    {
        "name": "propose_metadata_change",
        "description": "Propose a metadata correction for user review. The change will be queued in Proposed Changes for the user to approve/reject. Use after lookup_correct_metadata confirms the correct value, or when the user explicitly tells you the correct value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of track UUIDs to change"
                },
                "field": {
                    "type": "string",
                    "enum": ["title", "artist", "album", "album_artist", "year", "genre"],
                    "description": "Which metadata field to change"
                },
                "new_value": {
                    "type": "string",
                    "description": "The correct value for the field"
                },
                "reason": {
                    "type": "string",
                    "description": "Explanation of why this change is needed"
                },
                "source": {
                    "type": "string",
                    "enum": ["user_request", "llm_suggestion"],
                    "description": "user_request if user explicitly asked, llm_suggestion if you noticed the issue",
                    "default": "user_request"
                }
            },
            "required": ["track_ids", "field", "new_value", "reason"]
        }
    },
    {
        "name": "get_album_tracks",
        "description": "Get all tracks from a specific album. Useful before proposing album-wide metadata changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "album": {
                    "type": "string",
                    "description": "Album name to find tracks for"
                },
                "artist": {
                    "type": "string",
                    "description": "Artist name (optional but recommended for accuracy)"
                }
            },
            "required": ["album"]
        }
    },
    {
        "name": "mark_album_as_compilation",
        "description": "Mark an album as a compilation and set the album_artist field. Use when an album has tracks from multiple artists but should be grouped together (e.g., compilations curated by a DJ, Various Artists albums).",
        "input_schema": {
            "type": "object",
            "properties": {
                "album": {
                    "type": "string",
                    "description": "Album name"
                },
                "album_artist": {
                    "type": "string",
                    "description": "The album artist to set (e.g., 'Ladytron', 'Various Artists', 'Ministry of Sound')"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this album should be marked as a compilation"
                }
            },
            "required": ["album", "album_artist", "reason"]
        }
    },
    {
        "name": "propose_album_artwork",
        "description": "Search for and propose new album artwork. Searches Cover Art Archive (MusicBrainz) for artwork options and creates a proposed change for the user to review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "artist": {
                    "type": "string",
                    "description": "Artist name"
                },
                "album": {
                    "type": "string",
                    "description": "Album name"
                },
                "reason": {
                    "type": "string",
                    "description": "Why the artwork needs to be changed (e.g., 'missing artwork', 'wrong album art')"
                }
            },
            "required": ["artist", "album", "reason"]
        }
    },
    {
        "name": "find_duplicate_artists",
        "description": "Find artists in the library that are likely duplicates (same artist with different spellings). Detects variations like 'Artist_Name' vs 'Artist and Name', '&' vs 'and', etc. Use when the user mentions duplicate artists or to help clean up the library.",
        "input_schema": {
            "type": "object",
            "properties": {
                "artist_hint": {
                    "type": "string",
                    "description": "Optional: specific artist name to check for duplicates"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max duplicate groups to return (default 10)",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "merge_duplicate_artists",
        "description": "Propose merging duplicate artists by changing the artist field on all tracks. Creates a proposed change for user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_artist": {
                    "type": "string",
                    "description": "The artist name to change FROM (the duplicate/incorrect spelling)"
                },
                "target_artist": {
                    "type": "string",
                    "description": "The artist name to change TO (the canonical/correct spelling)"
                },
                "reason": {
                    "type": "string",
                    "description": "Explanation of why these are duplicates"
                }
            },
            "required": ["source_artist", "target_artist", "reason"]
        }
    },
    # Track identification tools
    {
        "name": "identify_track",
        "description": "Identify a specific track by title and artist. Use this FIRST when user says 'based on [song title] by [artist]' to get the track_id for find_similar_tracks. Returns the track if found in library, or external info if not.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Track title"
                },
                "artist": {
                    "type": "string",
                    "description": "Artist name"
                }
            },
            "required": ["title", "artist"]
        }
    },
    # Deep analysis tools
    {
        "name": "get_track_analysis",
        "description": "Get deep musical analysis for one or more tracks. Returns harmonic, melodic, rhythmic, timbral, and structural analysis. Use when the user wants to understand musical character, compare tracks, or use tracks as creative reference. Triggers analysis if not cached.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "UUIDs of tracks to analyze"
                },
                "include_comparative": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include cross-track comparison for multiple tracks"
                }
            },
            "required": ["track_ids"]
        }
    },
    # Web page reading tools
    {
        "name": "fetch_webpage",
        "description": "Fetch a web page and extract its readable content. Use this when the user provides a URL to an article, list, or page containing music information (artists, albums, tracks). Returns the page content for analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "list_playlists",
        "description": (
            "List this listener's playlists, most recently updated first. Call this BEFORE "
            "creating a playlist when they refer to one they already have — 'add these to my "
            "Ambient playlist' needs its id, and creating a second playlist with the same name is "
            "not what was asked for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "include_auto": {
                    "type": "boolean",
                    "description": "Include auto-generated playlists. Default true.",
                },
                "limit": {"type": "integer", "description": "Maximum playlists to return."},
            },
        },
    },
    {
        "name": "get_playlist",
        "description": (
            "The tracks on one playlist, in order. Use it to see what is already there before "
            "adding, and to check what you just created."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "playlist_id": {"type": "string", "description": "Playlist UUID, from list_playlists."},
            },
            "required": ["playlist_id"],
        },
    },
    {
        "name": "add_tracks_to_playlist",
        "description": (
            "Append tracks to a playlist that already exists. Tracks already on the playlist are "
            "skipped, so this is safe to repeat. Use this rather than create_playlist_from_items "
            "whenever the listener names a playlist they already have."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "playlist_id": {"type": "string", "description": "Playlist UUID, from list_playlists."},
                "track_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Local track UUIDs to append.",
                },
            },
            "required": ["playlist_id", "track_ids"],
        },
    },
    {
        "name": "set_favorite",
        "description": (
            "Mark or unmark a track as a favourite. Setting, not toggling: calling it twice with "
            "the same value leaves the track in that state, so it is safe to retry. To read "
            "favourites, use filter_tracks with is_favorite."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "track_id": {"type": "string", "description": "Local track UUID."},
                "favorite": {
                    "type": "boolean",
                    "description": "True to favourite, false to un-favourite. Default true.",
                },
            },
            "required": ["track_id"],
        },
    },
    {
        "name": "get_recently_played",
        "description": (
            "What this listener has actually played, newest first, one entry per play. Use it for "
            "'what have I been listening to?' and to ground recommendations in recent listening "
            "rather than all-time counts. Each entry carries an outcome: a skip is a much weaker "
            "signal of liking something than a completed play. For all-time favourites use "
            "filter_tracks with sort_by play_count instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum plays to return, up to 100."},
                "days": {
                    "type": "integer",
                    "description": "Only plays within this many days. Omit for the most recent regardless of age.",
                },
            },
        },
    },
    {
        "name": "get_radio_suggestions",
        "description": (
            "Familiar's own recommender, seeded from one track — what to play NEXT. Unlike "
            "find_similar_tracks, which is pure sonic similarity, this also weighs this listener's "
            "taste and the tracks they have skipped, so it is the better choice for building a "
            "listening session. Needs a seed track id: get one from get_now_playing, "
            "identify_track, or a previous search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "seed_track_id": {"type": "string", "description": "Local track UUID to seed from."},
                "limit": {"type": "integer", "description": "How many suggestions, up to 20."},
                "profile": {
                    "type": "string",
                    "enum": ["radio", "ambient"],
                    "description": "'radio' follows taste more strongly; 'ambient' favours continuity and low disruption.",
                },
            },
            "required": ["seed_track_id"],
        },
    },
    {
        "name": "create_playlist_from_items",
        "description": "Create a playlist from a list of music items (artists, albums, tracks). Matches items to local library and creates missing track placeholders for items not found. Use after analyzing web page content with fetch_webpage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Playlist name"
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "artist": {
                                "type": "string",
                                "description": "Artist name"
                            },
                            "album": {
                                "type": "string",
                                "description": "Album name (optional)"
                            },
                            "track": {
                                "type": "string",
                                "description": "Track name (optional, use for specific tracks)"
                            },
                            "year": {
                                "type": "integer",
                                "description": "Release year (optional)"
                            }
                        },
                        "required": ["artist"]
                    },
                    "description": "List of music items to include in the playlist"
                },
                "description": {
                    "type": "string",
                    "description": "Playlist description (optional, e.g., source URL)"
                },
                "tracks_per_album": {
                    "type": "integer",
                    "description": "How many tracks to include per album (default 3)",
                    "default": 3
                }
            },
            "required": ["name", "items"]
        }
    }
]

SYSTEM_PROMPT = """You are Familiar, a music assistant for a personal music library.

## CRITICAL: SEARCH ONCE, THEN QUEUE

You MUST follow this exact workflow:
1. Search ONCE (maybe twice if first search returns nothing)
2. IMMEDIATELY queue the tracks you found using queue_tracks
3. Tell the user what you queued

DO NOT keep searching repeatedly. If your first search returns tracks, USE THEM.

## Handling "Based on [track/album]" Requests

When user says "make a playlist based on [title] by [artist]":
1. Use identify_track(title, artist) FIRST to determine if it's in the library
2. If in library: Use find_similar_tracks(track_id) to find similar local tracks
3. If NOT in library:
   - Use get_similar_artists_in_library to find related artists the user has
   - Build playlist from local similar artists
4. If discovery_mode is "suggest_missing": ALWAYS include suggested_tracks in queue_tracks

## Discovery Mode

The user's playlist_discovery_mode setting controls behavior:
- "library_only": Only use local tracks, never suggest external tracks
- "suggest_missing": ALWAYS include suggested_tracks in every queue_tracks call

**IMPORTANT**: When discovery_mode is "suggest_missing", you MUST include 3-5 suggested_tracks
in EVERY queue_tracks call. Use your music knowledge to suggest tracks that fit the request but
aren't in the library. The current setting is shown at the end of these instructions.

## How to Handle Requests

**"Play [artist]"** or **"Make me a [artist] playlist"** or any playlist/queue request for a specific artist:
1. filter_tracks(artist=name, limit=20) — do NOT use search_library here; search_library caps results at 2 per artist due to diversity filtering
2. If found: queue_tracks immediately (include suggested_tracks if discovery_mode is "suggest_missing")
3. If NOT found: use get_similar_artists_in_library to find similar artists the user HAS
4. filter_tracks(artist=similar_artist_name) for those similar artists, then queue_tracks (with suggested_tracks if applicable)
5. IMPORTANT: If the artist isn't in the library, include the Bandcamp link from the tool result in your response so the user can discover/purchase it

NOTE: queue_tracks automatically creates an ephemeral playlist the user can save if they want. There is no separate "save playlist" tool — always use queue_tracks.

**"Play my favorites"** or **"What have I been listening to?"**:
1. filter_tracks(is_favorite=true) for favorites
2. filter_tracks(sort_by="play_count") or filter_tracks(played_in_last_days=7) for recent listening
3. queue_tracks immediately

**"Something I haven't heard in a while"** or **"Play something new"**:
1. filter_tracks(not_played_in_days=30) for unheard tracks
2. filter_tracks(added_in_last_days=14) for recently added
3. queue_tracks immediately

**"Electronic tracks from the 90s"** or other genre+era combos:
1. filter_tracks(genre="electronic", year_min=1990, year_max=1999)
2. queue_tracks immediately

**"Play something [abstract mood/vibe]"** (e.g., "dreamy", "ethereal", "aggressive", "gloomy with Eastern influences"):
1. semantic_search with the description
2. If unavailable, fall back to filter_tracks or search_library
3. queue_tracks immediately (include suggested_tracks if discovery_mode is "suggest_missing")

**"Play something chill/upbeat/etc"** (simple mood words that map to audio features):
1. filter_tracks with appropriate energy/valence values
2. queue_tracks immediately

**"More like this"**:
1. find_similar_tracks
2. queue_tracks immediately

**"Based on [track/album] by [artist]"**:
1. identify_track to check if it's in library
2. If in library: find_similar_tracks
3. If not: get_similar_artists_in_library to find related artists the user has
4. queue_tracks with local tracks
5. If discovery_mode is "suggest_missing": ALWAYS include suggested_tracks from similar artists/tracks

## STOP CONDITIONS (queue and respond after ANY of these):
- You found 5+ tracks → STOP, queue them
- You've made 2 searches → STOP, queue whatever you have
- No results after 2 tries → STOP, tell user you couldn't find anything

## Audio Features Reference

Use filter_tracks with these features. Use get_feature_distribution first to calibrate values to the user's library.

**Basic (0-1 scale unless noted):**
- energy: 0=calm, 1=intense
- valence: 0=sad/dark, 1=happy/bright
- danceability: 0=not danceable, 1=very danceable
- bpm: tempo in beats per minute (typical 60-180)
- acousticness: 0=electronic/produced, 1=acoustic
- instrumentalness: 0=vocals, 1=instrumental
- speechiness: 0=singing/instrumental, 1=spoken word/rap

**Rhythmic:**
- swing_min/max (0-1): 0=straight/quantized, 0.5+=swung (jazz, shuffle)
- syncopation_min (0-1): rhythmic complexity, off-beat emphasis
- tempo_character: "grid-locked" (electronic/quantized), "slight drift" (live band), "breathing" (rubato/expressive)
- tempo_cv_max: tempo coefficient of variation. "beatmatch-safe" → tempo_cv_max=0.05, "natural feel" → tempo_cv_max=0.15

**Harmonic:**
- key: musical key with mode (e.g., "C" for C major, "Am" for A minor, "F#m" for F# minor). Plain letter matches both major and minor.
- modal_character: "dorian", "mixolydian", "lydian", "phrygian", "aeolian", "ionian", "chromatic"
- key_stability: "stable", "drifting", "modulating"
- harmonic_complexity_min/max (0-1): 0=simple triads, 0.5=pop complexity, 0.8+=jazz/progressive

**Spectral/Dynamic:**
- brightness_min/max (0-1): 0=dark/warm, 1=bright/crisp
- dynamic_range_min (dB): higher=more dynamic, lower=compressed (typical 5-25)

**Structural:**
- section_count_min/max: number of song sections (simple=3-5, complex=8+)
- energy_shape: "gradual_build", "fade_out", "peak_middle", "consistent", "dynamic"

**Melodic:**
- note_density_min/max: notes per beat (sparse=0.5, busy=4+)
- pitch_range_min/max: range in semitones (narrow=<12, octave=12, wide=24+)

**Mood/Genre Tags:**
- mood_tag: CLAP-based tags (mood, genre, instrumentation, energy). Use get_available_mood_tags to see what's available.
- Examples: "dreamy", "jazz", "piano", "energetic", "dark", "acoustic guitar", "fast"
- These are computed from audio similarity and complement genre metadata tags.

**Feature Confidence:**
- Features have confidence scores (0-1) stored in feature_confidence. Most reliable: energy (0.95), key (varies). Least reliable: valence (0.4), speechiness (0.3 without VAD).
- When external features (ReccoBeats) exist, local analysis is also run for cross-validation. Disagreements are flagged.

**Mood mapping examples:**
- "chill" → energy<0.4, valence 0.3-0.6
- "upbeat/happy" → energy>0.6, valence>0.6, danceability>0.5
- "melancholy" → valence<0.3, energy<0.5
- "aggressive/intense" → energy>0.8, brightness>0.6
- "dreamy/ambient" → energy<0.3, acousticness>0.4, dynamic_range_min<10
- "jazzy" → swing_min>0.3, harmonic_complexity_min>0.5
- "tight electronic" → tempo_character="grid-locked", energy>0.5
- "loose live feel" → tempo_character="breathing", swing_min>0.2
- "beatmatch-safe" → tempo_cv_max=0.05
- "French lyrics" → lyrics_language="fr"

## Metadata Corrections

You can help fix incorrect metadata when the user reports issues:

**"Album X is showing under the wrong artist"** or **"The album artist is wrong"**:
1. Use get_album_tracks to find all tracks on that album
2. Use mark_album_as_compilation or propose_metadata_change to suggest the fix
3. Tell the user the change has been proposed for review in Settings

**"This track has the wrong [field]"**:
1. Optionally use lookup_correct_metadata to find the correct value from MusicBrainz
2. Use propose_metadata_change to suggest the correction
3. The user will review and approve the change in Settings > Proposed Changes

**"This album has wrong/missing artwork"** or **"Fix the album art for X"**:
1. Use propose_album_artwork to search Cover Art Archive and propose new artwork
2. The user can preview and approve the artwork change

Changes are NOT applied immediately - they go to a review queue where the user can:
- Preview what will change
- Approve or reject the change
- Choose scope: database only, ID3 tags, or file organization

## Proactive Metadata Observations

While handling requests, if you notice metadata issues, proactively use propose_metadata_change or propose_album_artwork to fix them:
- Placeholder values ("Unknown Artist", "Track 01", "Untitled", etc.)
- Missing album artwork on tracks you're queuing
- Inconsistent artist spellings (use merge_duplicate_artists)
- Missing year/genre on albums

After proposing a fix, briefly mention it: "I've proposed a fix for the missing artwork on that album - you can review it in Proposed Changes."

Don't ask permission first - just propose the change. The user reviews all proposals before they're applied.

## New Releases & Discovery

**"What's new from my favorite artists?"** or **"Any new releases?"**:
1. Use get_new_releases to find recent releases from top-played artists
2. Present releases grouped by artist, highlighting ones NOT in the library
3. For releases not in library, suggest searching Bandcamp to purchase them

**"Recommend artists I don't have"** or **"Who should I listen to?"**:
1. Use get_discovery_recommendations to get similar artists + unheard tracks
2. Present recommended_artists with Bandcamp links for discovery
3. Optionally mention unheard_tracks and deep_cuts for re-discovering existing library

**"What Spotify tracks am I missing?"** or **"What should I add from Spotify?"**:
1. Use get_spotify_unmatched to find unmatched Spotify tracks
2. Present stats (match rate) and top unmatched tracks
3. If user asks about a specific artist, use the artist filter

## Discovery Suggestions

When a user asks for an artist that's NOT in their library:
1. Use get_similar_artists_in_library - this returns a bandcamp_search_url
2. Build a playlist from similar artists that ARE in the library
3. In your response, include a "Discovery" section with the Bandcamp link

Example response format when artist not in library:
"[Artist] isn't in your library, but I found similar artists you have: [list]. I've queued [N] tracks from them.

**Want to add [Artist] to your collection?**
[Bandcamp link from tool result]"

## Web Page Music Discovery

When a user provides a URL to an article, blog post, or list about music:
1. Use fetch_webpage to get the content
2. Analyze the content to extract music references (artists, albums, tracks, years)
3. Use create_playlist_from_items with the extracted data
4. Report results: how many items found locally vs marked as missing

Example workflow:
- User: "make me a playlist from this article: https://example.com/best-albums-2024"
- fetch_webpage(url="https://...")
- Analyze content, extract: [{"artist": "...", "album": "...", "year": 2024}, ...]
- create_playlist_from_items(name="Best Albums 2024", items=[...], description="From: https://...")
- Response: "Created playlist with X tracks. Y are in your library, Z are marked as missing."

NEVER make up track names. Only mention tracks returned by tools."""
