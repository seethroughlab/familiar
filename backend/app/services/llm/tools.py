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
        "description": "Find tracks sonically similar to a given track, using audio embeddings. Great for 'play more like this' requests.",
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
        "description": "Filter tracks by library criteria (favorites, play history, genre, artist, year, recently added) and/or audio features (BPM, energy, key). Use for requests like 'play my favorites', 'what have I been listening to', 'electronic tracks from the 90s', 'upbeat songs', 'something around 120 BPM'.",
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
                "key": {"type": "string", "description": "Musical key to filter by (e.g., 'C', 'F', 'G#', 'Bb', 'F minor', 'C major')"},
                "energy_min": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum energy (0-1)"},
                "energy_max": {"type": "number", "minimum": 0, "maximum": 1, "description": "Maximum energy (0-1)"},
                "danceability_min": {"type": "number", "minimum": 0, "maximum": 1},
                "valence_min": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum valence/happiness (0-1)"},
                "valence_max": {"type": "number", "minimum": 0, "maximum": 1},
                "acousticness_min": {"type": "number", "minimum": 0, "maximum": 1},
                "instrumentalness_min": {"type": "number", "minimum": 0, "maximum": 1},
                "limit": {"type": "integer", "default": 20}
            }
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
        "name": "get_spotify_status",
        "description": "Check if the user has connected their Spotify account and get connection status.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_spotify_favorites",
        "description": "Get user's Spotify favorites that are available in their local library. Use this to find tracks the user has liked on Spotify.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 50)",
                    "default": 50
                }
            }
        }
    },
    {
        "name": "get_unmatched_spotify_favorites",
        "description": "Get Spotify favorites that couldn't be matched to the local library. Useful for finding music the user likes on Spotify but doesn't own locally.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 50)",
                    "default": 50
                }
            }
        }
    },
    {
        "name": "get_spotify_sync_stats",
        "description": "Get statistics about the Spotify sync: total favorites, matched count, match rate.",
        "input_schema": {
            "type": "object",
            "properties": {}
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
        "description": "Suggest Bandcamp albums to purchase based on Spotify favorites that aren't in the local library. Helps users complete their collection.",
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
    # Spotify playlist tools
    {
        "name": "list_spotify_playlists",
        "description": "List the user's Spotify playlists. Returns playlist names, track counts, and IDs. Use this when the user asks about their Spotify playlists or wants to import one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max playlists to return (default 20)",
                    "default": 20
                }
            }
        }
    },
    {
        "name": "get_spotify_playlist_tracks",
        "description": "Get tracks from a Spotify playlist. Shows which tracks exist locally vs are missing. Use this to understand what's in a Spotify playlist or to recreate it with local tracks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "playlist_id": {
                    "type": "string",
                    "description": "Spotify playlist ID"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max tracks to return (default 50)",
                    "default": 50
                }
            },
            "required": ["playlist_id"]
        }
    },
    {
        "name": "import_spotify_playlist",
        "description": "Import a Spotify playlist to Familiar. Creates a local playlist with matched tracks and missing track placeholders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spotify_playlist_id": {
                    "type": "string",
                    "description": "Spotify playlist ID"
                },
                "name": {
                    "type": "string",
                    "description": "Override playlist name (optional, uses Spotify name if not provided)"
                },
                "include_missing": {
                    "type": "boolean",
                    "description": "Include unmatched tracks as missing track placeholders (default true)",
                    "default": True
                }
            },
            "required": ["spotify_playlist_id"]
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
    {
        "name": "get_similar_tracks_external",
        "description": "Get similar tracks from Last.fm for a reference track. Returns tracks that may not be in the library. Use when building discovery playlists or when the reference track isn't in library.",
        "input_schema": {
            "type": "object",
            "properties": {
                "artist": {
                    "type": "string",
                    "description": "Artist name"
                },
                "track": {
                    "type": "string",
                    "description": "Track name"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max similar tracks to return (default 10)",
                    "default": 10
                }
            },
            "required": ["artist", "track"]
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
   - Use get_similar_tracks_external to find what tracks would be similar
   - Build playlist from local similar artists
4. If discovery_mode is "suggest_missing": ALWAYS include suggested_tracks in queue_tracks

## Discovery Mode

The user's playlist_discovery_mode setting controls behavior:
- "library_only": Only use local tracks, never suggest external tracks
- "suggest_missing": ALWAYS include suggested_tracks in every queue_tracks call

**IMPORTANT**: When discovery_mode is "suggest_missing", you MUST include 3-5 suggested_tracks
in EVERY queue_tracks call. Use get_similar_tracks_external or your music knowledge to suggest
tracks that fit the request but aren't in the library. These appear as "missing tracks" the user
can preview or purchase. The current setting is shown at the end of these instructions.

## How to Handle Requests

**"Play [artist]"** or **"Songs like [artist]"**:
1. search_library for the artist
2. If found: queue_tracks immediately (include suggested_tracks if discovery_mode is "suggest_missing")
3. If NOT found: use get_similar_artists_in_library to find similar artists the user HAS
4. Search for tracks by those similar artists, then queue_tracks (with suggested_tracks if applicable)
5. IMPORTANT: If the artist isn't in the library, include the Bandcamp link from the tool result in your response so the user can discover/purchase it

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
3. If not: get_similar_artists_in_library + get_similar_tracks_external
4. queue_tracks with local tracks
5. If discovery_mode is "suggest_missing": ALWAYS include suggested_tracks from similar artists/tracks

## STOP CONDITIONS (queue and respond after ANY of these):
- You found 5+ tracks → STOP, queue them
- You've made 2 searches → STOP, queue whatever you have
- No results after 2 tries → STOP, tell user you couldn't find anything

## Audio Features Reference
- energy: 0=calm, 1=intense
- valence: 0=sad, 1=happy
- danceability: 0=not danceable, 1=danceable
- bpm: typical range 60-180

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
