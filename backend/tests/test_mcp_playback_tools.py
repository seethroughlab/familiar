"""Tests for the MCP playback tools (ADR-0044).

These tools are the difference between a surface that finds music and one that plays it. The
interesting half is not delivery — it is what happens when delivery is impossible, because that is
the case a listener meets whenever no Familiar client happens to be running, and the case where a
silent failure would read as a broken player rather than a closed app.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.mcp import playback as playback_tools
from app.services.playback_commands import get_channel


@pytest.fixture
def profile():
    """A profile with a clean channel, left clean afterwards.

    The channel is process-global by design (ADR-0044 point 6), so a test that attaches must
    detach or the next one inherits a player it never created.
    """
    profile_id = uuid4()
    yield profile_id
    channel = get_channel()
    for player in channel.players(profile_id):
        channel.detach(player)


def attach(profile_id, *, name="Mac", caps=("play", "queue"), now=0.0):
    return get_channel().attach(
        profile_id, name=name, platform="macos", capabilities=frozenset(caps), now=now
    )


async def _execute_returning(tracks):
    async def execute(_name, _arguments):
        return {"queued": len(tracks), "tracks": tracks}

    return execute


TRACK = {"id": "t1", "title": "Teardrop", "artist": "Massive Attack"}


class TestControlPlayback:
    @pytest.mark.asyncio
    async def test_delivers_to_the_attached_player(self, profile):
        player = attach(profile)
        result = await playback_tools.handle(
            "control_playback", {"action": "play"}, profile_id=profile, execute=None
        )
        assert result["delivered"] is True
        assert player.queue.get_nowait() == {"type": "play"}

    @pytest.mark.asyncio
    async def test_unknown_action_is_rejected_before_delivery(self, profile):
        player = attach(profile)
        result = await playback_tools.handle(
            "control_playback", {"action": "obliterate"}, profile_id=profile, execute=None
        )
        assert "error" in result
        assert player.queue.qsize() == 0, "an invalid action must not reach a client"

    @pytest.mark.asyncio
    async def test_no_player_is_an_answer_not_an_exception(self, profile):
        """ADR-0044 point 5, and the whole reason this layer exists.

        A tool that raised here would surface to the host as a failure; a tool that returned
        nothing would read as success. Neither tells the listener the truth, which is that their
        music player is closed.
        """
        result = await playback_tools.handle(
            "control_playback", {"action": "play"}, profile_id=profile, execute=None
        )
        assert result["delivered"] is False
        assert "No player is attached" in result["reason"]
        assert result["attached_players"] == []

    @pytest.mark.asyncio
    async def test_an_explicit_target_is_honoured(self, profile):
        web = attach(profile, name="Web", now=1.0)
        mac = attach(profile, name="Mac", now=2.0)
        await playback_tools.handle(
            "control_playback",
            {"action": "pause", "player": "Web"},
            profile_id=profile,
            execute=None,
        )
        assert web.queue.qsize() == 1
        assert mac.queue.qsize() == 0


class TestQueueTracks:
    @pytest.mark.asyncio
    async def test_resolved_tracks_travel_as_the_command(self, profile):
        player = attach(profile)
        result = await playback_tools.handle(
            "queue_tracks",
            {"track_ids": ["t1"]},
            profile_id=profile,
            execute=await _execute_returning([TRACK]),
        )
        assert result["delivered"] is True
        assert result["queued"] == 1
        command = player.queue.get_nowait()
        assert command["type"] == "queue"
        assert command["tracks"] == [TRACK]

    @pytest.mark.asyncio
    async def test_clear_existing_actually_reaches_the_client(self, profile):
        """ADR-0044 point 8.

        `clear_existing` has always been accepted, echoed and dropped: `_queue_tracks` never
        assigns `_clear_queue`, and the web client ignored the flag too. Doubly inert. Here it is
        read from the arguments directly and carried, so the model can finally request an
        additive queue.
        """
        player = attach(profile)
        await playback_tools.handle(
            "queue_tracks",
            {"track_ids": ["t1"], "clear_existing": False},
            profile_id=profile,
            execute=await _execute_returning([TRACK]),
        )
        assert player.queue.get_nowait()["clear"] is False

    @pytest.mark.asyncio
    async def test_clear_defaults_to_replacing(self, profile):
        player = attach(profile)
        await playback_tools.handle(
            "queue_tracks",
            {"track_ids": ["t1"]},
            profile_id=profile,
            execute=await _execute_returning([TRACK]),
        )
        assert player.queue.get_nowait()["clear"] is True

    @pytest.mark.asyncio
    async def test_no_player_still_reports_what_was_found(self, profile):
        """Finding the music and being unable to play it are different failures.

        Saying how many tracks matched lets the model offer to save them as a playlist, which is
        a thing it *can* do — rather than reporting a flat failure and dropping the work.
        """
        result = await playback_tools.handle(
            "queue_tracks",
            {"track_ids": ["t1"]},
            profile_id=profile,
            execute=await _execute_returning([TRACK]),
        )
        assert result["delivered"] is False
        assert result["tracks_found"] == 1

    @pytest.mark.asyncio
    async def test_unmatched_ids_are_reported_without_a_command(self, profile):
        player = attach(profile)
        result = await playback_tools.handle(
            "queue_tracks",
            {"track_ids": ["nope"]},
            profile_id=profile,
            execute=await _execute_returning([]),
        )
        assert result["delivered"] is False
        assert player.queue.qsize() == 0, "an empty queue command must not be sent"

    @pytest.mark.asyncio
    async def test_a_resolution_error_is_passed_through(self, profile):
        attach(profile)

        async def failing(_name, _arguments):
            return {"error": "database is on fire"}

        result = await playback_tools.handle(
            "queue_tracks", {"track_ids": ["t1"]}, profile_id=profile, execute=failing
        )
        assert result == {"error": "database is on fire"}

    @pytest.mark.asyncio
    async def test_a_client_that_cannot_queue_is_not_sent_a_queue(self, profile):
        """Point 12's capability check, end to end through the tool."""
        listener_only = attach(profile, name="Speaker", caps=("play",))
        result = await playback_tools.handle(
            "queue_tracks",
            {"track_ids": ["t1"]},
            profile_id=profile,
            execute=await _execute_returning([TRACK]),
        )
        assert result["delivered"] is False
        assert "queue" in result["reason"]
        assert listener_only.queue.qsize() == 0


class TestListPlayers:
    @pytest.mark.asyncio
    async def test_reports_attached_players(self, profile):
        attach(profile, name="Jeff's Mac", caps=("play", "queue"))
        result = await playback_tools.handle(
            "list_players", {}, profile_id=profile, execute=None
        )
        assert [p["name"] for p in result["players"]] == ["Jeff's Mac"]
        assert result["players"][0]["capabilities"] == ["play", "queue"]

    @pytest.mark.asyncio
    async def test_says_plainly_when_nothing_is_running(self, profile):
        """The answer a model needs in order to tell the listener something true."""
        result = await playback_tools.handle(
            "list_players", {}, profile_id=profile, execute=None
        )
        assert result["players"] == []
        assert "nothing can play" in result["note"]
