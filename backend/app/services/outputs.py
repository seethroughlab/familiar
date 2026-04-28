"""Multi-room audio output abstraction layer.

Provides a unified interface for different audio outputs:
- Browser (default, via frontend streaming)
- Sonos (via SoCo library)
- AirPlay (via shairport-sync or similar)
- ChromeCast (via pychromecast)

The output manager allows playing to multiple zones simultaneously,
with each zone potentially using a different output type.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class OutputType(StrEnum):
    """Types of audio outputs."""

    BROWSER = "browser"
    SONOS = "sonos"
    AIRPLAY = "airplay"
    CHROMECAST = "chromecast"


class OutputState(StrEnum):
    """State of an audio output."""

    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    ERROR = "error"


@dataclass
class AudioOutput(ABC):
    """Abstract base class for audio outputs."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    output_type: OutputType = OutputType.BROWSER
    state: OutputState = OutputState.IDLE
    volume: int = 100  # 0-100
    current_track_id: UUID | None = None
    position_ms: int = 0

    @abstractmethod
    async def play(self, stream_url: str, track_id: UUID | None = None) -> bool:
        """Start playback of a stream URL.

        Args:
            stream_url: URL of the audio stream
            track_id: Optional track ID for metadata

        Returns:
            True if playback started successfully
        """
        pass

    @abstractmethod
    async def pause(self) -> bool:
        """Pause playback.

        Returns:
            True if paused successfully
        """
        pass

    @abstractmethod
    async def resume(self) -> bool:
        """Resume playback.

        Returns:
            True if resumed successfully
        """
        pass

    @abstractmethod
    async def stop(self) -> bool:
        """Stop playback.

        Returns:
            True if stopped successfully
        """
        pass

    @abstractmethod
    async def seek(self, position_ms: int) -> bool:
        """Seek to position.

        Args:
            position_ms: Position in milliseconds

        Returns:
            True if seeked successfully
        """
        pass

    @abstractmethod
    async def set_volume(self, volume: int) -> bool:
        """Set volume level.

        Args:
            volume: Volume level 0-100

        Returns:
            True if volume set successfully
        """
        pass

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Get current status.

        Returns:
            Dict with state, position, volume, etc.
        """
        pass

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": str(self.id),
            "name": self.name,
            "type": self.output_type.value,
            "state": self.state.value,
            "volume": self.volume,
            "current_track_id": str(self.current_track_id) if self.current_track_id else None,
            "position_ms": self.position_ms,
        }


@dataclass
class BrowserOutput(AudioOutput):
    """Browser-based audio output (default).

    This output doesn't directly control playback—it signals to the
    frontend via WebSocket that playback should happen on a specific client.
    The actual audio is handled by the frontend's Web Audio API.
    """

    output_type: OutputType = field(default=OutputType.BROWSER)
    websocket_id: str | None = None  # Connection ID for the target browser

    async def play(self, stream_url: str, track_id: UUID | None = None) -> bool:
        """Signal browser to start playback."""
        self.state = OutputState.PLAYING
        self.current_track_id = track_id
        self.position_ms = 0
        logger.info(f"Browser output {self.name}: playing {track_id}")
        return True

    async def pause(self) -> bool:
        """Signal browser to pause."""
        self.state = OutputState.PAUSED
        return True

    async def resume(self) -> bool:
        """Signal browser to resume."""
        self.state = OutputState.PLAYING
        return True

    async def stop(self) -> bool:
        """Signal browser to stop."""
        self.state = OutputState.IDLE
        self.current_track_id = None
        self.position_ms = 0
        return True

    async def seek(self, position_ms: int) -> bool:
        """Signal browser to seek."""
        self.position_ms = position_ms
        return True

    async def set_volume(self, volume: int) -> bool:
        """Signal browser to change volume."""
        self.volume = max(0, min(100, volume))
        return True

    async def get_status(self) -> dict[str, Any]:
        """Get browser output status."""
        return self.to_dict()


@dataclass
class SonosOutput(AudioOutput):
    """Sonos speaker output using SoCo library.

    Requires: pip install soco
    """

    output_type: OutputType = field(default=OutputType.SONOS)
    speaker_ip: str = ""
    _speaker: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize Sonos speaker connection."""
        if self.speaker_ip:
            self._connect()

    def _connect(self) -> bool:
        """Connect to Sonos speaker."""
        try:
            import soco
            self._speaker = soco.SoCo(self.speaker_ip)
            self.name = self._speaker.player_name
            logger.info(f"Connected to Sonos speaker: {self.name}")
            return True
        except ImportError:
            logger.error("soco library not installed. Install with: pip install soco")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Sonos at {self.speaker_ip}: {e}")
            return False

    async def play(self, stream_url: str, track_id: UUID | None = None) -> bool:
        """Play stream on Sonos speaker."""
        if not self._speaker:
            return False
        try:
            self._speaker.play_uri(stream_url)
            self.state = OutputState.PLAYING
            self.current_track_id = track_id
            self.position_ms = 0
            return True
        except Exception as e:
            logger.error(f"Sonos play error: {e}")
            self.state = OutputState.ERROR
            return False

    async def pause(self) -> bool:
        """Pause Sonos playback."""
        if not self._speaker:
            return False
        try:
            self._speaker.pause()
            self.state = OutputState.PAUSED
            return True
        except Exception as e:
            logger.error(f"Sonos pause error: {e}")
            return False

    async def resume(self) -> bool:
        """Resume Sonos playback."""
        if not self._speaker:
            return False
        try:
            self._speaker.play()
            self.state = OutputState.PLAYING
            return True
        except Exception as e:
            logger.error(f"Sonos resume error: {e}")
            return False

    async def stop(self) -> bool:
        """Stop Sonos playback."""
        if not self._speaker:
            return False
        try:
            self._speaker.stop()
            self.state = OutputState.IDLE
            self.current_track_id = None
            return True
        except Exception as e:
            logger.error(f"Sonos stop error: {e}")
            return False

    async def seek(self, position_ms: int) -> bool:
        """Seek on Sonos speaker."""
        if not self._speaker:
            return False
        try:
            # Sonos uses HH:MM:SS format
            seconds = position_ms // 1000
            h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
            self._speaker.seek(f"{h:02d}:{m:02d}:{s:02d}")
            self.position_ms = position_ms
            return True
        except Exception as e:
            logger.error(f"Sonos seek error: {e}")
            return False

    async def set_volume(self, volume: int) -> bool:
        """Set Sonos volume."""
        if not self._speaker:
            return False
        try:
            self._speaker.volume = max(0, min(100, volume))
            self.volume = volume
            return True
        except Exception as e:
            logger.error(f"Sonos volume error: {e}")
            return False

    async def get_status(self) -> dict[str, Any]:
        """Get Sonos speaker status."""
        if not self._speaker:
            return self.to_dict()
        try:
            info = self._speaker.get_current_transport_info()
            track_info = self._speaker.get_current_track_info()

            # Parse position from HH:MM:SS
            position = track_info.get("position", "0:00:00")
            parts = position.split(":")
            if len(parts) == 3:
                self.position_ms = (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * 1000

            state_map = {
                "PLAYING": OutputState.PLAYING,
                "PAUSED_PLAYBACK": OutputState.PAUSED,
                "STOPPED": OutputState.IDLE,
                "TRANSITIONING": OutputState.BUFFERING,
            }
            self.state = state_map.get(info.get("current_transport_state"), OutputState.IDLE)
            self.volume = self._speaker.volume

        except Exception as e:
            logger.error(f"Sonos status error: {e}")

        return self.to_dict()


@dataclass
class Zone:
    """A playback zone that can contain multiple outputs.

    Zones allow grouping outputs for synchronized playback.
    For example, "Living Room" could include both a Sonos speaker
    and a browser output.
    """

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    outputs: dict[UUID, AudioOutput] = field(default_factory=dict)
    is_active: bool = False
    current_track_id: UUID | None = None

    def add_output(self, output: AudioOutput) -> None:
        """Add an output to this zone."""
        self.outputs[output.id] = output

    def remove_output(self, output_id: UUID) -> bool:
        """Remove an output from this zone."""
        if output_id in self.outputs:
            del self.outputs[output_id]
            return True
        return False

    async def play(self, stream_url: str, track_id: UUID | None = None) -> dict[UUID, bool]:
        """Play on all outputs in zone."""
        results = {}
        for output_id, output in self.outputs.items():
            results[output_id] = await output.play(stream_url, track_id)
        self.is_active = True
        self.current_track_id = track_id
        return results

    async def pause(self) -> dict[UUID, bool]:
        """Pause all outputs in zone."""
        results = {}
        for output_id, output in self.outputs.items():
            results[output_id] = await output.pause()
        return results

    async def stop(self) -> dict[UUID, bool]:
        """Stop all outputs in zone."""
        results = {}
        for output_id, output in self.outputs.items():
            results[output_id] = await output.stop()
        self.is_active = False
        self.current_track_id = None
        return results

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": str(self.id),
            "name": self.name,
            "outputs": [o.to_dict() for o in self.outputs.values()],
            "is_active": self.is_active,
            "current_track_id": str(self.current_track_id) if self.current_track_id else None,
        }


class OutputManager:
    """Manages all audio outputs and zones.

    This is the main interface for multi-room audio control.
    It maintains a registry of outputs and zones, and provides
    methods for playing to specific outputs or zones.
    """

    def __init__(self) -> None:
        self.outputs: dict[UUID, AudioOutput] = {}
        self.zones: dict[UUID, Zone] = {}
        self._default_output_id: UUID | None = None

    def register_output(self, output: AudioOutput) -> UUID:
        """Register a new audio output."""
        self.outputs[output.id] = output
        if self._default_output_id is None:
            self._default_output_id = output.id
        logger.info(f"Registered output: {output.name} ({output.output_type.value})")
        return output.id

    def unregister_output(self, output_id: UUID) -> bool:
        """Unregister an audio output."""
        if output_id in self.outputs:
            del self.outputs[output_id]
            if self._default_output_id == output_id:
                self._default_output_id = next(iter(self.outputs), None)
            return True
        return False

    def create_zone(self, name: str, output_ids: list[UUID] | None = None) -> Zone:
        """Create a new zone with optional outputs."""
        zone = Zone(name=name)
        if output_ids:
            for output_id in output_ids:
                if output_id in self.outputs:
                    zone.add_output(self.outputs[output_id])
        self.zones[zone.id] = zone
        logger.info(f"Created zone: {name}")
        return zone

    def delete_zone(self, zone_id: UUID) -> bool:
        """Delete a zone."""
        if zone_id in self.zones:
            del self.zones[zone_id]
            return True
        return False

    def get_output(self, output_id: UUID) -> AudioOutput | None:
        """Get an output by ID."""
        return self.outputs.get(output_id)

    def get_zone(self, zone_id: UUID) -> Zone | None:
        """Get a zone by ID."""
        return self.zones.get(zone_id)

    def get_default_output(self) -> AudioOutput | None:
        """Get the default output."""
        if self._default_output_id:
            return self.outputs.get(self._default_output_id)
        return None

    def set_default_output(self, output_id: UUID) -> bool:
        """Set the default output."""
        if output_id in self.outputs:
            self._default_output_id = output_id
            return True
        return False

    async def play_to_output(
        self,
        output_id: UUID,
        stream_url: str,
        track_id: UUID | None = None,
    ) -> bool:
        """Play to a specific output."""
        output = self.outputs.get(output_id)
        if output:
            return await output.play(stream_url, track_id)
        return False

    async def play_to_zone(
        self,
        zone_id: UUID,
        stream_url: str,
        track_id: UUID | None = None,
    ) -> dict[UUID, bool]:
        """Play to all outputs in a zone."""
        zone = self.zones.get(zone_id)
        if zone:
            return await zone.play(stream_url, track_id)
        return {}

    def discover_sonos(self) -> list[SonosOutput]:
        """Discover Sonos speakers on the network."""
        discovered = []
        try:
            import soco
            speakers = soco.discover()
            if speakers:
                for speaker in speakers:
                    output = SonosOutput(
                        name=speaker.player_name,
                        speaker_ip=speaker.ip_address,
                    )
                    output._speaker = speaker
                    discovered.append(output)
                    self.register_output(output)
                logger.info(f"Discovered {len(discovered)} Sonos speakers")
        except ImportError:
            logger.warning("soco library not installed for Sonos discovery")
        except Exception as e:
            logger.error(f"Sonos discovery error: {e}")
        return discovered

    def list_outputs(self) -> list[dict[str, Any]]:
        """List all registered outputs."""
        return [o.to_dict() for o in self.outputs.values()]

    def list_zones(self) -> list[dict[str, Any]]:
        """List all zones."""
        return [z.to_dict() for z in self.zones.values()]


# Singleton instance
_output_manager: OutputManager | None = None


def get_output_manager() -> OutputManager:
    """Get or create the output manager singleton."""
    global _output_manager
    if _output_manager is None:
        _output_manager = OutputManager()
        # Register a default browser output
        default_output = BrowserOutput(name="This Device")
        _output_manager.register_output(default_output)
    return _output_manager
