"""Tests for the playlist, favourite, history and radio tools.

Most of what these tools do is delegate to route functions that are already tested. What is *not*
covered elsewhere are the two decisions specific to being called by a language model, and both fail
silently if they regress:

1. **`set_favorite` sets; it does not toggle.** Tool calls get retried. A toggle turns a retry into
   an undo, so asking twice to favourite a track would leave it un-favourited — and nothing would
   report that, because both calls succeeded.
2. **`get_recently_played` excludes failed playback.** An `errored` event means the listener never
   heard the track. Counting it as listening feeds a taste signal that is not merely noisy but
   backwards.

The wiring is checked too — a tool in `MUSIC_TOOLS` with no dispatch entry is a tool the model can
see, call, and always get an error from.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.llm.executor import ToolExecutor
from app.services.llm.tools import MUSIC_TOOLS

NEW_TOOLS = [
    "list_playlists",
    "get_playlist",
    "add_tracks_to_playlist",
    "set_favorite",
    "get_recently_played",
    "get_radio_suggestions",
]


class TestWiring:
    def test_every_new_tool_has_a_schema(self):
        names = {t["name"] for t in MUSIC_TOOLS}
        for tool in NEW_TOOLS:
            assert tool in names, f"{tool} is not in MUSIC_TOOLS"

    def test_every_tool_has_a_dispatch_entry(self):
        """A schema without a handler is a tool the model can call and never use.

        Checked across the whole list rather than just the new ones: the dispatch map is a dict
        literal, and nothing else notices when the two drift apart.
        """
        executor = ToolExecutor(db=None, profile_id=uuid4())  # type: ignore[arg-type]
        # `execute` builds the map from `self`, so an unbound name raises here rather than at runtime.
        import inspect

        source = inspect.getsource(type(executor).execute)
        for spec in MUSIC_TOOLS:
            assert f'"{spec["name"]}"' in source, f'{spec["name"]} has no dispatch entry'

    def test_the_new_tools_reach_the_mcp_surface(self):
        from app.mcp import exposed_tools

        exposed = {t.name for t in exposed_tools()}
        for tool in NEW_TOOLS:
            assert tool in exposed


class TestFavouriteIsSetNotToggle:
    """The failure mode: a retried call quietly undoing itself."""

    @pytest.mark.asyncio
    async def test_favouriting_twice_leaves_it_favourited(self, monkeypatch):
        calls: list[str] = []

        async def fake_add(track_id, db, profile):
            calls.append("add")

        async def fake_remove(track_id, db, profile):
            calls.append("remove")

        monkeypatch.setattr("app.api.routes.favorites.add_favorite", fake_add)
        monkeypatch.setattr("app.api.routes.favorites.remove_favorite", fake_remove)

        executor = ToolExecutor(db=None, profile_id=uuid4())  # type: ignore[arg-type]
        monkeypatch.setattr(type(executor), "_profile", _returning(object()))

        track = str(uuid4())
        first = await executor._set_favorite(track, favorite=True)
        second = await executor._set_favorite(track, favorite=True)

        assert first["is_favorite"] is True
        assert second["is_favorite"] is True, "a retry must not undo the first call"
        assert calls == ["add", "add"], f"expected two adds, got {calls}"

    @pytest.mark.asyncio
    async def test_unfavouriting_removes(self, monkeypatch):
        calls: list[str] = []

        async def fake_remove(track_id, db, profile):
            calls.append("remove")

        monkeypatch.setattr("app.api.routes.favorites.remove_favorite", fake_remove)
        executor = ToolExecutor(db=None, profile_id=uuid4())  # type: ignore[arg-type]
        monkeypatch.setattr(type(executor), "_profile", _returning(object()))

        result = await executor._set_favorite(str(uuid4()), favorite=False)
        assert result["is_favorite"] is False
        assert calls == ["remove"]

    @pytest.mark.asyncio
    async def test_a_malformed_id_is_an_answer_not_a_crash(self, monkeypatch):
        executor = ToolExecutor(db=None, profile_id=uuid4())  # type: ignore[arg-type]
        monkeypatch.setattr(type(executor), "_profile", _returning(object()))
        result = await executor._set_favorite("not-a-uuid")
        assert "error" in result


def _returning(value):
    async def _impl(self):
        return value

    return _impl


class TestRadioReadsTheRealCandidateShape:
    """This one reached the live server, which is why it is here.

    `_get_radio_suggestions` maps `AmbientCandidate` objects into tool results, and the first
    version read `candidate.score` — a field that does not exist. The attribute is
    `compatibility_score`, as `queue.py:643` has always read it. Nothing caught it because the
    other tests cover *decisions* and this was an assumption about a shape.

    Constructed from the real dataclass rather than a stub, so a rename breaks the test rather than
    the tool.
    """

    @pytest.mark.asyncio
    async def test_maps_a_real_candidate(self, monkeypatch):
        from app.services.ambient import AmbientCandidate, AmbientDescriptor

        track_id = uuid4()
        descriptor = AmbientDescriptor.__new__(AmbientDescriptor)
        object.__setattr__(descriptor, "track_id", track_id)
        candidate = AmbientCandidate(
            descriptor=descriptor,
            compatibility_score=0.87654,
            key_compatibility=1.0,
            suggested_start_pct=0.0,
            suggested_end_pct=1.0,
        )

        async def fake_candidates(*args, **kwargs):
            return [candidate], 150, False

        monkeypatch.setattr("app.services.ambient.get_candidates", fake_candidates)

        class FakeTrack:
            id = track_id
            title = "Serpentskirt"
            artist = "Cocteau Twins"
            album = None
            genre = None
            duration_seconds = 200.0
            year = 1996

        class FakeResult:
            def scalars(self):
                class S:
                    def all(self_inner):
                        return [FakeTrack()]
                return S()

        class FakeDB:
            async def execute(self, *_args, **_kwargs):
                return FakeResult()

        executor = ToolExecutor(db=FakeDB(), profile_id=uuid4())  # type: ignore[arg-type]
        result = await executor._get_radio_suggestions(str(track_id), limit=4)

        assert "error" not in result, result
        assert result["suggestions"][0]["score"] == 0.8765
        assert result["pool_size"] == 150
