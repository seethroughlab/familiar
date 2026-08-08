"""The portable half of the chat system prompt (ADR-0043 point 3).

`SYSTEM_PROMPT` in `services/llm/tools.py` is ~11,000 characters, and most of it is **chat-loop
control** — "SEARCH ONCE, THEN QUEUE", "STOP CONDITIONS", "you've made 2 searches → STOP". That
exists to stop a chat agent looping. An MCP host runs its own loop and the listener can iterate, so
porting it would be actively misleading.

What is portable is the operating knowledge a model cannot derive from a schema: which tool to reach
for, what order two tools go in, and which numbers are meaningless without calibration.

**This is not decoration.** Measured against both arms of `scripts/spike_mcp_arms.py`, the guided
arm calibrated before thresholding in 4 of 8 prompts against the bare arm's 1, and never thresholded
blind where the bare arm did so three times. The one that matters: asked for "something upbeat and
happy", an uncalibrated model filtered `energy>=0.6, valence>=0.6` — which matches 92.5% of the
library.

Two of the three worries in ADR-0043 point 3 turned out to be unfounded: both arms already ordered
`identify_track` before `find_similar_tracks`, and both already reached for `semantic_search` on
abstract moods, because those tool descriptions carry their own sequencing. **The whole measured
effect was calibration.** The other entries are kept because they cost nothing and the measurement
was n=1 per cell.
"""

from __future__ import annotations

INSTRUCTIONS = (
    "Familiar is a personal music library, locally analysed. Every track carries audio features "
    "extracted from the audio itself — energy, valence, danceability, acousticness, BPM, key — plus "
    "CLAP audio embeddings supporting natural-language search over how music actually sounds.\n\n"
    "Two things make answers good here, and neither is obvious from the schemas:\n\n"
    "1. **Numeric feature thresholds are meaningless until calibrated against this collection.** "
    "The stored values are raw measurements on compressed scales, not perceptual 0-1 ratings. Call "
    "get_feature_distribution before filtering on a feature and choose bounds from the actual "
    "spread. A guessed threshold silently returns almost everything or almost nothing.\n"
    "2. **Sonic similarity lives in the embeddings, not the metadata.** For anything abstract or "
    "figurative, reach for semantic_search rather than trying to express the idea as feature ranges."
)

# Appended to the tool's own MUSIC_TOOLS description. Keep each one about *this* tool: MCP gives no
# other channel, and a host may show only the tool it is about to call.
GUIDANCE: dict[str, str] = {
    "filter_tracks": (
        "\n\nCALIBRATE BEFORE YOU THRESHOLD. Do not guess numeric bounds. Call "
        "get_feature_distribution for a feature first and pick bounds from this library's actual "
        "spread — 'high energy' in a folk collection is a different number from an EDM collection, "
        "and a guessed threshold silently returns nothing or everything.\n"
        "Prefer this over search_library whenever you want more than a couple of tracks by one "
        "artist: search_library applies a diversity filter that caps results at 2 per artist."
    ),
    "get_feature_distribution": (
        "\n\nCall this BEFORE choosing any numeric bound for filter_tracks. It is cheap, and it is "
        "the difference between a filter tuned to this collection and one tuned to a guess."
    ),
    "search_library": (
        "\n\nNote: results are capped at 2 tracks per artist by a diversity filter. If you want a "
        "set of tracks by one artist, use filter_tracks(artist=...) instead."
    ),
    "semantic_search": (
        "\n\nPREFER THIS over filter_tracks for abstract or figurative descriptions — 'dreamy', "
        "'ethereal', 'gloomy with Eastern influences', 'sounds like a rainy commute'. Audio-feature "
        "filters cannot express those. Use filter_tracks for concrete metadata and for simple mood "
        "words that map directly onto energy/valence."
    ),
    "identify_track": (
        "\n\nCall this FIRST whenever the user names a specific song — 'something like [title] by "
        "[artist]'. find_similar_tracks needs the track_id this returns and cannot accept a title. "
        "If the track is NOT in the library, do not stop: use get_similar_artists_in_library to "
        "find related artists the listener does have."
    ),
    "find_similar_tracks": (
        "\n\nRequires a track_id from identify_track or a previous search result. It will not "
        "accept a title or artist name."
    ),
    "create_playlist_from_items": (
        "\n\nThis writes a real playlist the listener will see. Pass generation_prompt describing "
        "what was asked for, in their words where you have them — it is stored with the playlist "
        "and is what explains later why the playlist exists."
    ),
}
