"""SPIKE — throwaway MCP server testing ADR-0043 point 3.

Not production code. Not wired into the app. Delete when the question is answered.

## The question

ADR-0043 point 3 claims the sequencing knowledge currently in `SYSTEM_PROMPT` can move into
tool descriptions and the server's `instructions`, because **MCP guarantees no system prompt**.
That is the load-bearing risk in the whole direction: if a host given only descriptions
thresholds `energy > 0.8` without ever calling `get_feature_distribution`, the MCP surface
produces worse playlists than the chat it replaces.

## The experiment

Two arms, selected by `SPIKE_ARM`:

- `bare`   — descriptions exactly as they appear in `MUSIC_TOOLS` today, no instructions.
- `guided` — the same descriptions plus the *portable* subset of `SYSTEM_PROMPT`, and server
             instructions.

`SYSTEM_PROMPT` is 11,010 characters, but most of it is chat-loop control ("SEARCH ONCE, THEN
QUEUE", "STOP CONDITIONS") that exists to stop a chat agent looping and is irrelevant under MCP,
where the host runs its own loop and the user can iterate. The portable subset is much smaller —
see `GUIDANCE` below.

Every tool call is appended to `SPIKE_LOG` (default `spike_mcp_calls.jsonl`) with its arm,
sequence number and arguments. **The log is the measurement**: run the same prompts against each
arm and read back what got called, in what order.

What to look for:
  1. Is `get_feature_distribution` called before a threshold is chosen?
  2. Is `identify_track` called before `find_similar_tracks`?
  3. Is `semantic_search` reached for abstract moods, or does it settle for `filter_tracks`?
  4. Does anything use `search_library` expecting more than 2 tracks per artist? (It caps —
     a trap that lives *only* in SYSTEM_PROMPT today and in no tool description.)

## Read-only

All five tools read. None of them writes. `ASSERT_READ_ONLY` enforces that nothing else gets
registered by accident, because this points at the production database.

## Running it

The production database is docker-internal on the NAS, so open a tunnel first:

    ssh -N -L 15432:172.19.0.4:5432 openmediavault

Then register with Claude Code (from the repo root):

    claude mcp add familiar-spike -- \
      uv run --directory backend --with mcp python scripts/spike_mcp_server.py

Switch arms with `SPIKE_ARM=bare` / `SPIKE_ARM=guided` in the environment.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.llm.executor import ToolExecutor  # noqa: E402
from app.services.llm.tools import MUSIC_TOOLS  # noqa: E402

ARM = os.environ.get("SPIKE_ARM", "guided").strip().lower()
if ARM not in ("bare", "guided"):
    raise SystemExit(f"SPIKE_ARM must be 'bare' or 'guided', got {ARM!r}")

DATABASE_URL = os.environ.get(
    "SPIKE_DATABASE_URL",
    "postgresql+asyncpg://familiar:familiar@127.0.0.1:15432/familiar",
)
PROFILE_ID = UUID(
    os.environ.get("SPIKE_PROFILE_ID", "ab83cf37-42f4-4f21-a6f6-afe221fe8688")
)
LOG_PATH = Path(os.environ.get("SPIKE_LOG", "spike_mcp_calls.jsonl")).resolve()

ASSERT_READ_ONLY = {
    "semantic_search",
    "filter_tracks",
    "get_feature_distribution",
    "identify_track",
    "find_similar_tracks",
}

_engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=2)
_Session = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

_seq = 0


def _bare(name: str) -> str:
    """The tool's description exactly as MUSIC_TOOLS has it today."""
    for tool in MUSIC_TOOLS:
        if tool["name"] == name:
            return str(tool["description"])
    raise KeyError(f"{name} is not in MUSIC_TOOLS")


# The portable subset of SYSTEM_PROMPT — the operating knowledge that survives the loss of the
# chat loop. Everything about queueing, stop conditions and search-once is deliberately absent:
# it governs a chat agent's loop, not a tool's contract.
GUIDANCE: dict[str, str] = {
    "semantic_search": (
        "\n\nPREFER THIS over filter_tracks for abstract or figurative descriptions — "
        "'dreamy', 'ethereal', 'gloomy with Eastern influences', 'sounds like a rainy commute'. "
        "Audio-feature filters cannot express those. Use filter_tracks instead only for simple "
        "mood words that map directly onto energy/valence, and for concrete metadata."
    ),
    "filter_tracks": (
        "\n\nCALIBRATE BEFORE YOU THRESHOLD. Do not guess numeric bounds. Call "
        "get_feature_distribution for a feature first and choose bounds from this library's "
        "actual spread — 'high energy' in a folk collection is a different number from an EDM "
        "collection, and a guessed threshold silently returns nothing or everything.\n"
        "Use this rather than search_library when you want more than a couple of tracks by one "
        "artist: search_library applies a diversity filter that caps results at 2 per artist."
    ),
    "get_feature_distribution": (
        "\n\nCall this BEFORE choosing any numeric bound for filter_tracks. It is cheap, and it "
        "is the difference between a filter tuned to this collection and one tuned to a guess."
    ),
    "identify_track": (
        "\n\nCall this FIRST whenever the user names a specific song — 'something like [title] "
        "by [artist]', 'based on [title]'. find_similar_tracks needs the track_id this returns "
        "and cannot accept a title. If the track is NOT in the library, do not stop: use "
        "get_similar_artists_in_library to find related artists the user does have."
    ),
    "find_similar_tracks": (
        "\n\nRequires a track_id, which you get from identify_track or from a previous search "
        "result. It will not accept a title or artist name. If you only have a title, call "
        "identify_track first."
    ),
}

INSTRUCTIONS = (
    "Familiar is a personal music library of ~26,000 locally-analysed tracks. Every track has "
    "audio features extracted from the audio itself (energy, valence, danceability, "
    "acousticness, instrumentalness, BPM, key) plus CLAP audio embeddings that support "
    "natural-language search over how music actually sounds.\n\n"
    "Two things make answers good here:\n"
    "1. Numeric thresholds are meaningless until calibrated against THIS collection. "
    "get_feature_distribution tells you the real spread; use it before filtering on a feature.\n"
    "2. Sonic similarity lives in the embeddings, not the metadata. For anything abstract, "
    "reach for semantic_search rather than trying to express the idea as feature ranges."
)


def _describe(name: str) -> str:
    if ARM == "bare":
        return _bare(name)
    return _bare(name) + GUIDANCE.get(name, "")


def _log(tool: str, args: dict[str, Any], result: Any, error: str | None = None) -> None:
    global _seq
    _seq += 1
    if isinstance(result, dict):
        summary: Any = {
            k: (f"<{len(v)} items>" if isinstance(v, list) else v)
            for k, v in list(result.items())[:8]
        }
    elif isinstance(result, list):
        summary = f"<{len(result)} items>"
    else:
        summary = result
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "arm": ARM,
        "seq": _seq,
        "tool": tool,
        "args": {k: v for k, v in args.items() if v is not None},
        "error": error,
        "result": summary,
    }
    with LOG_PATH.open("a") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


async def _run(tool: str, **kwargs: Any) -> Any:
    """Execute a real ToolExecutor handler in its own session."""
    if tool not in ASSERT_READ_ONLY:
        raise RuntimeError(f"{tool} is not on the read-only allowlist")
    args = {k: v for k, v in kwargs.items() if v is not None}
    try:
        # A session per call, never held across calls — a yield-scoped session outliving its
        # handler is how 834 downloads once became 83-byte error bodies.
        async with _Session() as session:
            executor = ToolExecutor(session, profile_id=PROFILE_ID, user_message="")
            result = await executor.execute(tool, args)
    except Exception as exc:  # noqa: BLE001 - spike: surface the failure to the host
        _log(tool, args, None, error=repr(exc))
        return {"error": repr(exc)}
    _log(tool, args, result)
    return result


server = MCPServer(
    name="familiar-spike",
    instructions=INSTRUCTIONS if ARM == "guided" else None,
)


async def semantic_search(description: str, limit: int = 20) -> Any:
    return await _run("semantic_search", description=description, limit=limit)


async def filter_tracks(
    genre: str | None = None,
    artist: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    energy_min: float | None = None,
    energy_max: float | None = None,
    valence_min: float | None = None,
    valence_max: float | None = None,
    danceability_min: float | None = None,
    acousticness_min: float | None = None,
    instrumentalness_min: float | None = None,
    is_favorite: bool | None = None,
    not_played_in_days: int | None = None,
    sort_by: str | None = None,
    limit: int = 20,
) -> Any:
    return await _run(
        "filter_tracks",
        genre=genre,
        artist=artist,
        year_min=year_min,
        year_max=year_max,
        bpm_min=bpm_min,
        bpm_max=bpm_max,
        energy_min=energy_min,
        energy_max=energy_max,
        valence_min=valence_min,
        valence_max=valence_max,
        danceability_min=danceability_min,
        acousticness_min=acousticness_min,
        instrumentalness_min=instrumentalness_min,
        is_favorite=is_favorite,
        not_played_in_days=not_played_in_days,
        sort_by=sort_by,
        limit=limit,
    )


async def get_feature_distribution(feature: str) -> Any:
    return await _run("get_feature_distribution", feature=feature)


async def identify_track(title: str, artist: str) -> Any:
    return await _run("identify_track", title=title, artist=artist)


async def find_similar_tracks(track_id: str, limit: int = 20) -> Any:
    return await _run("find_similar_tracks", track_id=track_id, limit=limit)


for _fn in (
    semantic_search,
    filter_tracks,
    get_feature_distribution,
    identify_track,
    find_similar_tracks,
):
    server.add_tool(_fn, name=_fn.__name__, description=_describe(_fn.__name__))


if __name__ == "__main__":
    print(
        f"[spike] arm={ARM} profile={PROFILE_ID} log={LOG_PATH}",
        file=sys.stderr,
    )
    server.run()
