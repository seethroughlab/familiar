"""Tests for the playback command channel (ADR-0044).

The channel's job is to carry an imperative to a client that can obey it, and — when there is no
such client — to **say so** rather than swallow the command. Both halves are tested, because the
silent half is the one this project keeps rediscovering: an affordance whose destination is not
mounted, failing quietly.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.services.playback_commands import (
    NoPlayerAttached,
    PlaybackCommandChannel,
)

PLAY = {"type": "play"}


@pytest.fixture
def channel() -> PlaybackCommandChannel:
    return PlaybackCommandChannel()


def attach(channel, profile, *, name="Mac", platform="macos", caps=("play",), now=0.0):
    return channel.attach(
        profile, name=name, platform=platform, capabilities=frozenset(caps), now=now
    )


class TestDelivery:
    def test_command_reaches_the_attached_player(self, channel):
        profile = uuid4()
        player = attach(channel, profile)
        channel.send(profile, PLAY)
        assert player.queue.get_nowait() == PLAY

    def test_most_recently_attached_wins_by_default(self, channel):
        """Point 4. Foregrounding a client re-attaches it, which is what makes this the right default."""
        profile = uuid4()
        older = attach(channel, profile, name="Web", now=1.0)
        newer = attach(channel, profile, name="Mac", now=2.0)

        channel.send(profile, PLAY)

        assert newer.queue.qsize() == 1
        assert older.queue.qsize() == 0

    def test_an_explicit_target_overrides_the_default(self, channel):
        profile = uuid4()
        web = attach(channel, profile, name="Web", now=1.0)
        mac = attach(channel, profile, name="Mac", now=2.0)

        channel.send(profile, PLAY, target="Web")

        assert web.queue.qsize() == 1
        assert mac.queue.qsize() == 0

    def test_profiles_are_isolated(self, channel):
        """The channel is per-profile: one listener's command must not reach another's player."""
        mine, theirs = uuid4(), uuid4()
        my_player = attach(channel, mine)
        their_player = attach(channel, theirs)

        channel.send(mine, PLAY)

        assert my_player.queue.qsize() == 1
        assert their_player.queue.qsize() == 0

    def test_only_one_player_receives_a_command(self, channel):
        """A command is an instruction, not a broadcast — two clients must not both start playing."""
        profile = uuid4()
        players = [attach(channel, profile, name=f"c{i}", now=float(i)) for i in range(3)]
        channel.send(profile, PLAY)
        assert sum(p.queue.qsize() for p in players) == 1


class TestAnsweringRatherThanSwallowing:
    """Point 5: no attached player is an answer, not a hang and not silence."""

    def test_no_players_raises_with_a_reason(self, channel):
        with pytest.raises(NoPlayerAttached) as exc:
            channel.send(uuid4(), PLAY)
        assert "No player is attached" in str(exc.value)

    def test_unknown_target_raises_and_names_what_is_attached(self, channel):
        profile = uuid4()
        attach(channel, profile, name="Mac")
        with pytest.raises(NoPlayerAttached) as exc:
            channel.send(profile, PLAY, target="Phone")
        assert "Mac" in str(exc.value)

    def test_a_capability_nobody_declared_raises(self, channel):
        """Point 12. The Apple clients have no theme storage; the web app does.

        Without this, 'set the theme' reaches a Mac, is accepted, and does nothing — which is the
        affordance-with-no-destination defect, delivered by a channel built to avoid it.
        """
        profile = uuid4()
        attach(channel, profile, name="Mac", caps=("play", "queue"))
        with pytest.raises(NoPlayerAttached) as exc:
            channel.send(profile, {"type": "set_preference"}, requires="theme")
        assert "theme" in str(exc.value)

    def test_a_capable_client_is_preferred_over_a_newer_incapable_one(self, channel):
        profile = uuid4()
        web = attach(channel, profile, name="Web", caps=("play", "theme"), now=1.0)
        mac = attach(channel, profile, name="Mac", caps=("play",), now=2.0)

        channel.send(profile, {"type": "set_preference"}, requires="theme")

        assert web.queue.qsize() == 1, "the only client that can obey should get it"
        assert mac.queue.qsize() == 0


class TestLifecycle:
    def test_detach_removes_the_player(self, channel):
        profile = uuid4()
        player = attach(channel, profile)
        channel.detach(player)
        assert channel.players(profile) == []
        with pytest.raises(NoPlayerAttached):
            channel.send(profile, PLAY)

    def test_detach_is_idempotent(self, channel):
        """The stream's `finally` can run more than once across error paths; it must not explode."""
        profile = uuid4()
        player = attach(channel, profile)
        channel.detach(player)
        channel.detach(player)
        assert channel.players(profile) == []

    def test_nothing_is_stored_for_a_client_that_arrives_later(self, channel):
        """Point 6: an undelivered command is lost, not queued.

        Stated as a test because it is a promise to the *caller* — a tool that cannot deliver must
        report that, rather than implying the instruction will happen when a client next appears.
        """
        profile = uuid4()
        with pytest.raises(NoPlayerAttached):
            channel.send(profile, PLAY)

        late = attach(channel, profile)
        assert late.queue.qsize() == 0


class TestBackpressure:
    def test_a_full_buffer_drops_the_oldest_command(self, channel):
        """Commands are transient: the newest instruction is the one the listener meant."""
        profile = uuid4()
        player = attach(channel, profile)

        for i in range(player.queue.maxsize + 5):
            channel.send(profile, {"type": "play", "n": i})

        assert player.queue.full()
        first = player.queue.get_nowait()
        assert first["n"] > 0, "the oldest commands should have been dropped, not the newest"

    def test_sending_never_blocks(self, channel):
        """A slow client must not stall the tool call that is trying to reach it."""
        profile = uuid4()
        attach(channel, profile)

        async def flood():
            for _ in range(200):
                channel.send(profile, PLAY)

        asyncio.run(asyncio.wait_for(flood(), timeout=2.0))


class TestEndpoint:
    """The SSE surface, driven through the handler and the stream generator directly.

    The unit tests above prove the channel; these prove it is *wired* — that subscribing really
    attaches a player with the capabilities it declared, and that leaving really detaches it.
    """

    @pytest.mark.asyncio
    async def test_handler_releases_the_connection_before_streaming(self):
        """The property that matters most, and the one this codebase has already paid for.

        A `yield` dependency is held until the response finishes *sending*, and a subscription
        never finishes — so without the release, every connected client pins a database connection
        for as long as it stays connected. That is the failure that exhausted the pool during audio
        streaming, in a worse form, because a subscription is open indefinitely by design.

        Driven through the handler rather than over HTTP: an ASGI test transport never reports a
        disconnect, so a stream designed to run until the client leaves never ends.
        """
        from types import SimpleNamespace

        from app.api.routes.playback import playback_commands
        from app.services.playback_commands import get_channel

        closed: list[bool] = []

        class FakeSession:
            async def close(self):
                closed.append(True)

        profile_id = uuid4()
        channel = get_channel()
        request = SimpleNamespace(is_disconnected=lambda: True)

        response = await playback_commands(
            request=request,  # type: ignore[arg-type]
            db=FakeSession(),  # type: ignore[arg-type]
            profile=SimpleNamespace(id=profile_id),  # type: ignore[arg-type]
            client="Jeff's Mac",
            platform="macos",
            capabilities="play, queue ,crossfade",
        )
        try:
            assert closed, "release_connection was not called before returning the stream"
            assert response.media_type == "text/event-stream"
            assert response.headers.get("x-accel-buffering") == "no"

            attached = channel.players(profile_id)
            assert [p.name for p in attached] == ["Jeff's Mac"]
            # Whitespace around the comma-separated capabilities is tolerated.
            assert attached[0].capabilities == frozenset({"play", "queue", "crossfade"})
        finally:
            for player in channel.players(profile_id):
                channel.detach(player)

    @pytest.mark.asyncio
    async def test_the_stream_detaches_when_the_client_goes_away(self):
        """Leaving is the only departure signal, so the generator's cleanup has to be reliable."""
        from types import SimpleNamespace

        from app.api.routes.playback import _events
        from app.services.playback_commands import get_channel

        profile_id = uuid4()
        channel = get_channel()
        player = channel.attach(
            profile_id, name="Mac", platform="macos", capabilities=frozenset({"play"}), now=0.0
        )

        async def disconnected():
            return True

        stream = _events(SimpleNamespace(is_disconnected=disconnected), player)  # type: ignore[arg-type]
        # The greeting, then the loop sees the disconnect and the generator finishes.
        assert '"type": "attached"' in await anext(stream)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

        assert channel.players(profile_id) == [], "a departed client must not stay attached"


class TestDescription:
    def test_players_are_describable_for_the_tool_surface(self, channel):
        """Point 4's 'the MCP surface can see the choices'."""
        profile = uuid4()
        attach(channel, profile, name="Jeff's Mac", platform="macos", caps=("play", "queue"))
        described = [p.describe() for p in channel.players(profile)]
        assert described == [
            {
                "id": described[0]["id"],
                "name": "Jeff's Mac",
                "platform": "macos",
                "capabilities": ["play", "queue"],
            }
        ]
