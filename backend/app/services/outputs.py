"""Multi-room audio output abstraction layer.

Provides a unified interface for different audio outputs:
- Browser (default, via frontend streaming)
- Sonos (via SoCo library)
- AirPlay (via pyatv)
- ChromeCast (via pychromecast)
- UPnP/DLNA/OpenHome (via async-upnp-client, covers WiiM and generic devices)

The output manager holds one output per device and plays to them individually.
It used to group them into zones and fan a stream out to a group; ADR-0077 removed
that, because the nine zone endpoints had no client, lost their state on every
restart, and one of them — `GET /outputs/zones` — could never be reached at all.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

# Registered network outputs are persisted here so manually-added (and
# discovered) devices survive a container restart. Lives in the same `data/`
# dir as settings.json (the persisted app_data volume). Browser outputs are
# never persisted — "This Device" is re-created on each boot.
_OUTPUTS_FILE = Path("data/outputs.json")


class OutputType(StrEnum):
    """Types of audio outputs."""

    BROWSER = "browser"
    SONOS = "sonos"
    AIRPLAY = "airplay"
    CHROMECAST = "chromecast"
    UPNP = "upnp"


class OutputState(StrEnum):
    """State of an audio output."""

    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    ERROR = "error"


@dataclass
class TrackMetadata:
    """Metadata for a track being played on a network output."""

    title: str = ""
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    artwork_url: str | None = None
    content_type: str | None = None  # e.g. "audio/mpeg" — for DIDL res protocolInfo


def _build_didl_metadata(stream_url: str, metadata: TrackMetadata) -> str:
    """Build DIDL-Lite XML for UPnP/Sonos track metadata."""
    duration = ""
    if metadata.duration_ms:
        s = metadata.duration_ms // 1000
        duration = f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"

    art_tag = (
        f"<upnp:albumArtURI>{escape(metadata.artwork_url)}</upnp:albumArtURI>"
        if metadata.artwork_url
        else ""
    )

    res_duration = f' duration="{duration}"' if duration else ""

    # protocolInfo MUST match the actual stream content type — strict renderers (WiiM/LinkPlay)
    # reject SetAVTransportURI when it lies (e.g. claiming FLAC for an MP3). Default to MP3, the
    # most common case, when the type is unknown.
    content_type = metadata.content_type or "audio/mpeg"

    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="1" parentID="0" restricted="1">'
        f"<dc:title>{escape(metadata.title)}</dc:title>"
        f"<dc:creator>{escape(metadata.artist)}</dc:creator>"
        f"<upnp:artist>{escape(metadata.artist)}</upnp:artist>"
        f"<upnp:album>{escape(metadata.album)}</upnp:album>"
        f"{art_tag}"
        "<upnp:class>object.item.audioItem.musicTrack</upnp:class>"
        f'<res{res_duration} protocolInfo="http-get:*:{content_type}:*">'
        f"{escape(stream_url)}</res>"
        "</item></DIDL-Lite>"
    )


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
    async def play(
        self,
        stream_url: str,
        track_id: UUID | None = None,
        metadata: TrackMetadata | None = None,
    ) -> bool:
        """Start playback of a stream URL."""
        pass

    @abstractmethod
    async def pause(self) -> bool:
        """Pause playback."""
        pass

    @abstractmethod
    async def resume(self) -> bool:
        """Resume playback."""
        pass

    @abstractmethod
    async def stop(self) -> bool:
        """Stop playback."""
        pass

    @abstractmethod
    async def seek(self, position_ms: int) -> bool:
        """Seek to position in milliseconds."""
        pass

    @abstractmethod
    async def set_volume(self, volume: int) -> bool:
        """Set volume level 0-100."""
        pass

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Get current status."""
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
    websocket_id: str | None = None

    async def play(
        self,
        stream_url: str,
        track_id: UUID | None = None,
        metadata: TrackMetadata | None = None,
    ) -> bool:
        self.state = OutputState.PLAYING
        self.current_track_id = track_id
        self.position_ms = 0
        logger.info(f"Browser output {self.name}: playing {track_id}")
        return True

    async def pause(self) -> bool:
        self.state = OutputState.PAUSED
        return True

    async def resume(self) -> bool:
        self.state = OutputState.PLAYING
        return True

    async def stop(self) -> bool:
        self.state = OutputState.IDLE
        self.current_track_id = None
        self.position_ms = 0
        return True

    async def seek(self, position_ms: int) -> bool:
        self.position_ms = position_ms
        return True

    async def set_volume(self, volume: int) -> bool:
        self.volume = max(0, min(100, volume))
        return True

    async def get_status(self) -> dict[str, Any]:
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
        if self.speaker_ip:
            self._connect()

    def _connect(self) -> bool:
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

    async def play(
        self,
        stream_url: str,
        track_id: UUID | None = None,
        metadata: TrackMetadata | None = None,
    ) -> bool:
        if not self._speaker:
            return False
        try:
            loop = asyncio.get_running_loop()
            title = metadata.title if metadata else ""
            await loop.run_in_executor(
                None,
                lambda: self._speaker.play_uri(stream_url, title=title),
            )
            self.state = OutputState.PLAYING
            self.current_track_id = track_id
            self.position_ms = 0
            return True
        except Exception as e:
            logger.error(f"Sonos play error: {e}")
            self.state = OutputState.ERROR
            return False

    async def pause(self) -> bool:
        if not self._speaker:
            return False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speaker.pause)
            self.state = OutputState.PAUSED
            return True
        except Exception as e:
            logger.error(f"Sonos pause error: {e}")
            return False

    async def resume(self) -> bool:
        if not self._speaker:
            return False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speaker.play)
            self.state = OutputState.PLAYING
            return True
        except Exception as e:
            logger.error(f"Sonos resume error: {e}")
            return False

    async def stop(self) -> bool:
        if not self._speaker:
            return False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speaker.stop)
            self.state = OutputState.IDLE
            self.current_track_id = None
            return True
        except Exception as e:
            logger.error(f"Sonos stop error: {e}")
            return False

    async def seek(self, position_ms: int) -> bool:
        if not self._speaker:
            return False
        try:
            seconds = position_ms // 1000
            h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
            timestamp = f"{h:02d}:{m:02d}:{s:02d}"
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self._speaker.seek(timestamp))
            self.position_ms = position_ms
            return True
        except Exception as e:
            logger.error(f"Sonos seek error: {e}")
            return False

    async def set_volume(self, volume: int) -> bool:
        if not self._speaker:
            return False
        try:
            clamped = max(0, min(100, volume))
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: setattr(self._speaker, "volume", clamped))
            self.volume = clamped
            return True
        except Exception as e:
            logger.error(f"Sonos volume error: {e}")
            return False

    async def get_status(self) -> dict[str, Any]:
        if not self._speaker:
            return self.to_dict()
        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, self._speaker.get_current_transport_info)
            track_info = await loop.run_in_executor(None, self._speaker.get_current_track_info)

            position = track_info.get("position", "0:00:00")
            parts = position.split(":")
            if len(parts) == 3:
                self.position_ms = (
                    int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                ) * 1000

            state_map = {
                "PLAYING": OutputState.PLAYING,
                "PAUSED_PLAYBACK": OutputState.PAUSED,
                "STOPPED": OutputState.IDLE,
                "TRANSITIONING": OutputState.BUFFERING,
            }
            self.state = state_map.get(info.get("current_transport_state"), OutputState.IDLE)
            self.volume = await loop.run_in_executor(None, lambda: self._speaker.volume)
        except Exception as e:
            logger.error(f"Sonos status error: {e}")

        return self.to_dict()


@dataclass
class UPnPOutput(AudioOutput):
    """UPnP/DLNA/OpenHome audio output.

    Covers WiiM (via OpenHome or AVTransport), generic DLNA speakers,
    and any device that supports the UPnP AV standard.

    Requires: pip install async-upnp-client
    """

    output_type: OutputType = field(default=OutputType.UPNP)
    device_url: str = ""   # Device description XML URL (from SSDP LOCATION header)
    udn: str = ""          # Unique Device Name
    _device: Any = field(default=None, repr=False)
    _avt: Any = field(default=None, repr=False)       # AVTransport service
    _rc: Any = field(default=None, repr=False)        # RenderingControl service
    _oh_playlist: Any = field(default=None, repr=False)  # OpenHome Playlist service
    _has_openhome: bool = field(default=False, repr=False)

    async def _connect(self) -> bool:
        if not self.device_url:
            return False
        try:
            from async_upnp_client.aiohttp import AiohttpRequester
            from async_upnp_client.client_factory import UpnpFactory

            requester = AiohttpRequester()
            factory = UpnpFactory(requester)
            self._device = await factory.async_create_device(self.device_url)

            if not self.name:
                self.name = getattr(self._device, "name", None) or "UPnP Device"

            # Try OpenHome Playlist service (WiiM, Linn, etc.)
            try:
                self._oh_playlist = self._device.service(
                    "urn:av-openhome-org:service:Playlist:1"
                )
                self._has_openhome = True
                logger.info(f"UPnP device {self.name}: OpenHome Playlist detected")
            except Exception:
                self._has_openhome = False

            # AVTransport (standard DLNA fallback)
            try:
                self._avt = self._device.service("urn:schemas-upnp-org:service:AVTransport:1")
            except Exception:
                if not self._has_openhome:
                    logger.error(f"Device {self.name}: no AVTransport or OpenHome service")
                    return False

            # RenderingControl for volume
            try:
                self._rc = self._device.service("urn:schemas-upnp-org:service:RenderingControl:1")
            except Exception:
                pass

            logger.info(f"Connected to UPnP device: {self.name} (OpenHome={self._has_openhome})")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to UPnP device at {self.device_url}: {e}")
            return False

    async def _ensure_connected(self) -> bool:
        if self._device is None:
            return await self._connect()
        return True

    async def play(
        self,
        stream_url: str,
        track_id: UUID | None = None,
        metadata: TrackMetadata | None = None,
    ) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            meta_xml = _build_didl_metadata(stream_url, metadata) if metadata else ""

            if self._has_openhome and self._oh_playlist:
                # OpenHome protocol: clear playlist, insert, seek to first, play
                await self._oh_playlist.action("DeleteAll").async_call()
                result = await self._oh_playlist.action("Insert").async_call(
                    AfterId=0,
                    Uri=stream_url,
                    Metadata=meta_xml,
                )
                new_id = result.get("NewId", 1)
                await self._oh_playlist.action("SeekId").async_call(Value=new_id)
                await self._oh_playlist.action("Play").async_call()
            elif self._avt:
                await self._avt.action("SetAVTransportURI").async_call(
                    InstanceID=0,
                    CurrentURI=stream_url,
                    CurrentURIMetaData=meta_xml,
                )
                await self._avt.action("Play").async_call(InstanceID=0, Speed="1")

            self.state = OutputState.PLAYING
            self.current_track_id = track_id
            self.position_ms = 0
            return True
        except Exception as e:
            # Full traceback + the UPnP/SOAP fault — strict renderers reject SetAVTransportURI
            # with an actionable error code, which the bare message would otherwise hide.
            logger.exception(
                "UPnP play failed for %s (openhome=%s, url=%s): %r",
                self.name, self._has_openhome, stream_url, e,
            )
            self.state = OutputState.ERROR
            return False

    async def pause(self) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            if self._has_openhome and self._oh_playlist:
                await self._oh_playlist.action("Pause").async_call()
            elif self._avt:
                await self._avt.action("Pause").async_call(InstanceID=0)
            self.state = OutputState.PAUSED
            return True
        except Exception as e:
            logger.error(f"UPnP pause error: {e}")
            return False

    async def resume(self) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            if self._has_openhome and self._oh_playlist:
                await self._oh_playlist.action("Play").async_call()
            elif self._avt:
                await self._avt.action("Play").async_call(InstanceID=0, Speed="1")
            self.state = OutputState.PLAYING
            return True
        except Exception as e:
            logger.error(f"UPnP resume error: {e}")
            return False

    async def stop(self) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            if self._has_openhome and self._oh_playlist:
                await self._oh_playlist.action("Stop").async_call()
            elif self._avt:
                await self._avt.action("Stop").async_call(InstanceID=0)
            self.state = OutputState.IDLE
            self.current_track_id = None
            return True
        except Exception as e:
            logger.error(f"UPnP stop error: {e}")
            return False

    async def seek(self, position_ms: int) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            seconds = position_ms // 1000
            h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
            timestamp = f"{h:02d}:{m:02d}:{s:02d}"

            if self._has_openhome and self._oh_playlist:
                await self._oh_playlist.action("SeekSecondAbsolute").async_call(Value=seconds)
            elif self._avt:
                await self._avt.action("Seek").async_call(
                    InstanceID=0,
                    Unit="REL_TIME",
                    Target=timestamp,
                )
            self.position_ms = position_ms
            return True
        except Exception as e:
            logger.error(f"UPnP seek error: {e}")
            return False

    async def set_volume(self, volume: int) -> bool:
        if not await self._ensure_connected():
            return False
        if not self._rc:
            return False
        try:
            clamped = max(0, min(100, volume))
            await self._rc.action("SetVolume").async_call(
                InstanceID=0,
                Channel="Master",
                DesiredVolume=clamped,
            )
            self.volume = clamped
            return True
        except Exception as e:
            logger.error(f"UPnP volume error: {e}")
            return False

    async def get_status(self) -> dict[str, Any]:
        if not await self._ensure_connected():
            return self.to_dict()
        try:
            if self._avt:
                info = await self._avt.action("GetTransportInfo").async_call(InstanceID=0)
                pos_info = await self._avt.action("GetPositionInfo").async_call(InstanceID=0)

                rel_time = pos_info.get("RelTime", "0:00:00")
                parts = rel_time.split(":")
                if len(parts) == 3:
                    self.position_ms = (
                        int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    ) * 1000

                state_map = {
                    "PLAYING": OutputState.PLAYING,
                    "PAUSED_PLAYBACK": OutputState.PAUSED,
                    "STOPPED": OutputState.IDLE,
                    "TRANSITIONING": OutputState.BUFFERING,
                }
                transport_state = info.get("CurrentTransportState", "STOPPED")
                self.state = state_map.get(transport_state, OutputState.IDLE)

            if self._rc:
                vol_info = await self._rc.action("GetVolume").async_call(
                    InstanceID=0, Channel="Master"
                )
                self.volume = int(vol_info.get("CurrentVolume", self.volume))
        except Exception as e:
            logger.error(f"UPnP status error: {e}")

        return self.to_dict()


@dataclass
class AirPlayOutput(AudioOutput):
    """AirPlay audio output via pyatv.

    Supports AirPlay 1 and AirPlay 2 devices: WiiM, Apple TV, HomePod,
    AirPort Express, and many third-party speakers.

    Requires: pip install pyatv
    """

    output_type: OutputType = field(default=OutputType.AIRPLAY)
    identifier: str = ""    # pyatv device identifier
    host: str = ""          # Device IP/hostname
    _config: Any = field(default=None, repr=False)
    _atv: Any = field(default=None, repr=False)

    async def _connect(self) -> bool:
        try:
            import pyatv

            loop = asyncio.get_running_loop()

            if self._config is None:
                hosts = [self.host] if self.host else None
                identifier = {self.identifier} if self.identifier else None
                results = await pyatv.scan(loop, timeout=5, identifier=identifier, hosts=hosts)
                if not results:
                    logger.error(f"AirPlay device not found: {self.identifier or self.host}")
                    return False
                self._config = results[0]

            self._atv = await pyatv.connect(self._config, loop)
            if not self.name:
                self.name = self._config.name or "AirPlay Device"
            logger.info(f"Connected to AirPlay device: {self.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to AirPlay device: {e}")
            self._atv = None
            return False

    async def _ensure_connected(self) -> bool:
        if self._atv is None:
            return await self._connect()
        return True

    async def play(
        self,
        stream_url: str,
        track_id: UUID | None = None,
        metadata: TrackMetadata | None = None,
    ) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            await self._atv.stream.play_url(stream_url)
            self.state = OutputState.PLAYING
            self.current_track_id = track_id
            self.position_ms = 0
            return True
        except Exception as e:
            logger.error(f"AirPlay play error: {e}")
            self._atv = None  # Force reconnect next time
            self.state = OutputState.ERROR
            return False

    async def pause(self) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            await self._atv.remote_control.pause()
            self.state = OutputState.PAUSED
            return True
        except Exception as e:
            logger.error(f"AirPlay pause error: {e}")
            return False

    async def resume(self) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            await self._atv.remote_control.play()
            self.state = OutputState.PLAYING
            return True
        except Exception as e:
            logger.error(f"AirPlay resume error: {e}")
            return False

    async def stop(self) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            await self._atv.remote_control.stop()
            self.state = OutputState.IDLE
            self.current_track_id = None
            return True
        except Exception as e:
            logger.error(f"AirPlay stop error: {e}")
            return False

    async def seek(self, position_ms: int) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            await self._atv.remote_control.set_position(position_ms // 1000)
            self.position_ms = position_ms
            return True
        except Exception as e:
            logger.error(f"AirPlay seek error: {e}")
            return False

    async def set_volume(self, volume: int) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            clamped = max(0, min(100, volume))
            await self._atv.audio.set_volume(float(clamped))
            self.volume = clamped
            return True
        except Exception as e:
            logger.error(f"AirPlay volume error: {e}")
            return False

    async def get_status(self) -> dict[str, Any]:
        if not await self._ensure_connected():
            return self.to_dict()
        try:
            import pyatv.const as const

            playing = await self._atv.metadata.playing()
            state_map = {
                const.DeviceState.Playing: OutputState.PLAYING,
                const.DeviceState.Paused: OutputState.PAUSED,
                const.DeviceState.Idle: OutputState.IDLE,
                const.DeviceState.Stopped: OutputState.IDLE,
                const.DeviceState.Loading: OutputState.BUFFERING,
            }
            self.state = state_map.get(playing.device_state, OutputState.IDLE)
            if playing.position is not None:
                self.position_ms = playing.position * 1000
        except Exception as e:
            logger.error(f"AirPlay status error: {e}")

        return self.to_dict()


@dataclass
class ChromecastOutput(AudioOutput):
    """Chromecast audio output via pychromecast.

    Covers Chromecast, Chromecast Audio, Google Home/Nest, and
    Chromecast-enabled TVs and speakers.

    Requires: pip install pychromecast
    """

    output_type: OutputType = field(default=OutputType.CHROMECAST)
    cast_host: str = ""     # IP address of the Chromecast
    cast_uuid: str = ""     # UUID for targeted connection
    _cast: Any = field(default=None, repr=False)

    async def _connect(self) -> bool:
        try:
            import pychromecast

            loop = asyncio.get_running_loop()

            def _do_connect():
                if self.cast_host:
                    cast = pychromecast.get_chromecast_from_host((self.cast_host, None, None, None, None))
                    cast.wait(timeout=10)
                    return cast
                # Discovery
                chromecasts, browser = pychromecast.get_chromecasts(timeout=5)
                browser.stop_discovery()
                if not chromecasts:
                    return None
                # Match by UUID if specified
                if self.cast_uuid:
                    for cc in chromecasts:
                        if str(cc.uuid) == self.cast_uuid:
                            cc.wait(timeout=10)
                            return cc
                chromecasts[0].wait(timeout=10)
                return chromecasts[0]

            self._cast = await loop.run_in_executor(None, _do_connect)
            if not self._cast:
                logger.error("No Chromecast found")
                return False

            if not self.name:
                self.name = self._cast.cast_info.friendly_name or "Chromecast"
            logger.info(f"Connected to Chromecast: {self.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Chromecast: {e}")
            self._cast = None
            return False

    async def _ensure_connected(self) -> bool:
        if self._cast is None:
            return await self._connect()
        return True

    async def play(
        self,
        stream_url: str,
        track_id: UUID | None = None,
        metadata: TrackMetadata | None = None,
    ) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            loop = asyncio.get_running_loop()

            def _do_play():
                mc = self._cast.media_controller
                mc.play_media(
                    stream_url,
                    "audio/flac",
                    title=metadata.title if metadata else None,
                    thumb=metadata.artwork_url if metadata else None,
                    metadata={
                        "metadataType": 3,  # MusicTrackMediaMetadata
                        "title": metadata.title if metadata else "",
                        "artist": metadata.artist if metadata else "",
                        "albumName": metadata.album if metadata else "",
                    } if metadata else None,
                )
                mc.block_until_active(timeout=10)

            await loop.run_in_executor(None, _do_play)
            self.state = OutputState.PLAYING
            self.current_track_id = track_id
            self.position_ms = 0
            return True
        except Exception as e:
            logger.error(f"Chromecast play error: {e}")
            self._cast = None
            self.state = OutputState.ERROR
            return False

    async def pause(self) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._cast.media_controller.pause)
            self.state = OutputState.PAUSED
            return True
        except Exception as e:
            logger.error(f"Chromecast pause error: {e}")
            return False

    async def resume(self) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._cast.media_controller.play)
            self.state = OutputState.PLAYING
            return True
        except Exception as e:
            logger.error(f"Chromecast resume error: {e}")
            return False

    async def stop(self) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._cast.media_controller.stop)
            self.state = OutputState.IDLE
            self.current_track_id = None
            return True
        except Exception as e:
            logger.error(f"Chromecast stop error: {e}")
            return False

    async def seek(self, position_ms: int) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: self._cast.media_controller.seek(position_ms / 1000),
            )
            self.position_ms = position_ms
            return True
        except Exception as e:
            logger.error(f"Chromecast seek error: {e}")
            return False

    async def set_volume(self, volume: int) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            clamped = max(0, min(100, volume))
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: self._cast.set_volume(clamped / 100),
            )
            self.volume = clamped
            return True
        except Exception as e:
            logger.error(f"Chromecast volume error: {e}")
            return False

    async def get_status(self) -> dict[str, Any]:
        if not await self._ensure_connected():
            return self.to_dict()
        try:
            loop = asyncio.get_running_loop()

            def _get_status():
                mc = self._cast.media_controller
                status = mc.status
                return status

            status = await loop.run_in_executor(None, _get_status)
            if status:
                if status.player_state == "PLAYING":
                    self.state = OutputState.PLAYING
                elif status.player_state == "PAUSED":
                    self.state = OutputState.PAUSED
                elif status.player_state == "IDLE":
                    self.state = OutputState.IDLE
                elif status.player_state == "BUFFERING":
                    self.state = OutputState.BUFFERING
                if status.current_time is not None:
                    self.position_ms = int(status.current_time * 1000)
        except Exception as e:
            logger.error(f"Chromecast status error: {e}")

        return self.to_dict()


def _serialize_persisted(output: AudioOutput) -> dict[str, Any] | None:
    """Serialize an output to its reconstruction fields, or None if it should
    not be persisted (browser outputs are ephemeral and re-created on boot)."""
    if isinstance(output, UPnPOutput):
        return {"id": str(output.id), "type": "upnp", "name": output.name,
                "device_url": output.device_url, "udn": output.udn}
    if isinstance(output, SonosOutput):
        return {"id": str(output.id), "type": "sonos", "name": output.name,
                "speaker_ip": output.speaker_ip}
    if isinstance(output, AirPlayOutput):
        return {"id": str(output.id), "type": "airplay", "name": output.name,
                "identifier": output.identifier, "host": output.host}
    if isinstance(output, ChromecastOutput):
        return {"id": str(output.id), "type": "chromecast", "name": output.name,
                "cast_host": output.cast_host, "cast_uuid": output.cast_uuid}
    return None


def _deserialize_persisted(item: dict[str, Any]) -> AudioOutput | None:
    """Reconstruct an output from a persisted dict (mirrors the POST /outputs
    constructors). Returns None for unknown types."""
    output_type = item.get("type")
    oid = UUID(item["id"]) if item.get("id") else uuid4()
    name = item.get("name", "")
    if output_type == "upnp":
        return UPnPOutput(id=oid, name=name, device_url=item.get("device_url", ""),
                          udn=item.get("udn", ""))
    if output_type == "sonos":
        return SonosOutput(id=oid, name=name, speaker_ip=item.get("speaker_ip", ""))
    if output_type == "airplay":
        return AirPlayOutput(id=oid, name=name, identifier=item.get("identifier", ""),
                             host=item.get("host", ""))
    if output_type == "chromecast":
        return ChromecastOutput(id=oid, name=name, cast_host=item.get("cast_host", ""),
                                cast_uuid=item.get("cast_uuid", ""))
    return None


class OutputManager:
    """Manages all audio outputs."""

    def __init__(self) -> None:
        self.outputs: dict[UUID, AudioOutput] = {}
        self._default_output_id: UUID | None = None

    def register_output(self, output: AudioOutput) -> UUID:
        self.outputs[output.id] = output
        if self._default_output_id is None:
            self._default_output_id = output.id
        logger.info(f"Registered output: {output.name} ({output.output_type.value})")
        self._persist()
        return output.id

    def unregister_output(self, output_id: UUID) -> bool:
        if output_id in self.outputs:
            del self.outputs[output_id]
            if self._default_output_id == output_id:
                self._default_output_id = next(iter(self.outputs), None)
            self._persist()
            return True
        return False

    def _persist(self) -> None:
        """Write all persistable (non-browser) outputs to disk so they survive
        a restart. Best-effort: failures are logged, never raised."""
        try:
            items = [d for o in self.outputs.values()
                     if (d := _serialize_persisted(o)) is not None]
            _OUTPUTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _OUTPUTS_FILE.write_text(json.dumps(items, indent=2))
        except Exception as e:
            logger.error(f"Failed to persist outputs: {e}")

    def load_persisted(self) -> None:
        """Restore previously-registered outputs from disk. Inserts directly
        (no re-persist); each device is reconstructed independently so one bad
        entry can't block the rest."""
        try:
            if not _OUTPUTS_FILE.exists():
                return
            items = json.loads(_OUTPUTS_FILE.read_text())
        except Exception as e:
            logger.error(f"Failed to read persisted outputs: {e}")
            return
        for item in items:
            try:
                output = _deserialize_persisted(item)
                if output is not None:
                    self.outputs[output.id] = output
                    logger.info(f"Reloaded persisted output: {output.name} "
                                f"({output.output_type.value})")
            except Exception as e:
                logger.error(f"Failed to reload persisted output {item!r}: {e}")

    def get_output(self, output_id: UUID) -> AudioOutput | None:
        return self.outputs.get(output_id)

    def get_default_output(self) -> AudioOutput | None:
        if self._default_output_id:
            return self.outputs.get(self._default_output_id)
        return None

    def set_default_output(self, output_id: UUID) -> bool:
        if output_id in self.outputs:
            self._default_output_id = output_id
            return True
        return False

    async def play_to_output(
        self,
        output_id: UUID,
        stream_url: str,
        track_id: UUID | None = None,
        metadata: TrackMetadata | None = None,
    ) -> bool:
        output = self.outputs.get(output_id)
        if output:
            return await output.play(stream_url, track_id, metadata)
        return False

    # -------------------------------------------------------------------------
    # Discovery
    # -------------------------------------------------------------------------

    def discover_sonos(self) -> list[SonosOutput]:
        """Discover Sonos speakers on the network (synchronous)."""
        discovered = []
        try:
            import soco
            speakers = soco.discover()
            if speakers:
                for speaker in speakers:
                    # Skip already-registered speakers
                    already = any(
                        isinstance(o, SonosOutput) and o.speaker_ip == speaker.ip_address
                        for o in self.outputs.values()
                    )
                    if not already:
                        output = SonosOutput(
                            name=speaker.player_name,
                            speaker_ip=speaker.ip_address,
                        )
                        output._speaker = speaker
                        self.register_output(output)
                        discovered.append(output)
                logger.info(f"Discovered {len(discovered)} new Sonos speakers")
        except ImportError:
            logger.warning("soco library not installed for Sonos discovery")
        except Exception as e:
            logger.error(f"Sonos discovery error: {e}")
        return discovered

    async def discover_upnp(self) -> list[UPnPOutput]:
        """Discover UPnP/DLNA/OpenHome devices via SSDP."""
        discovered = []
        try:
            from async_upnp_client.aiohttp import AiohttpRequester
            from async_upnp_client.client_factory import UpnpFactory
            from async_upnp_client.search import async_search

            seen_locations: set[str] = set()
            # Already registered locations
            for o in self.outputs.values():
                if isinstance(o, UPnPOutput) and o.device_url:
                    seen_locations.add(o.device_url)

            pending: list[dict] = []

            async def on_ssdp_device(headers: Any) -> None:
                location = headers.get("LOCATION") or headers.get("location", "")
                # Skip non-audio and already-seen devices
                st = headers.get("ST") or headers.get("st", "")
                if not location or location in seen_locations:
                    return
                if "MediaRenderer" not in st and "upnp:rootdevice" not in st and "schemas-upnp-org" not in st:
                    return
                seen_locations.add(location)
                pending.append({"location": location})

            await async_search(async_callback=on_ssdp_device, timeout=5)

            # Create device objects for found locations
            requester = AiohttpRequester()
            factory = UpnpFactory(requester)
            for item in pending:
                try:
                    device = await factory.async_create_device(item["location"])
                    # Only include devices with audio rendering capability
                    has_avt = False
                    has_oh = False
                    try:
                        device.service("urn:schemas-upnp-org:service:AVTransport:1")
                        has_avt = True
                    except Exception:
                        pass
                    try:
                        device.service("urn:av-openhome-org:service:Playlist:1")
                        has_oh = True
                    except Exception:
                        pass

                    if not (has_avt or has_oh):
                        continue

                    output = UPnPOutput(
                        name=getattr(device, "name", None) or "UPnP Device",
                        device_url=item["location"],
                        _device=device,
                        _has_openhome=has_oh,
                    )
                    # Wire up services
                    if has_avt:
                        output._avt = device.service("urn:schemas-upnp-org:service:AVTransport:1")
                    if has_oh:
                        output._oh_playlist = device.service("urn:av-openhome-org:service:Playlist:1")
                    try:
                        output._rc = device.service("urn:schemas-upnp-org:service:RenderingControl:1")
                    except Exception:
                        pass

                    self.register_output(output)
                    discovered.append(output)
                    logger.info(f"Discovered UPnP device: {output.name}")
                except Exception as e:
                    logger.debug(f"Skipping UPnP device at {item['location']}: {e}")

        except ImportError:
            logger.warning("async-upnp-client not installed for UPnP discovery")
        except Exception as e:
            logger.error(f"UPnP discovery error: {e}")
        return discovered

    async def discover_airplay(self) -> list[AirPlayOutput]:
        """Discover AirPlay devices via mDNS."""
        discovered = []
        try:
            import pyatv

            loop = asyncio.get_running_loop()
            existing_ids = {
                o.identifier
                for o in self.outputs.values()
                if isinstance(o, AirPlayOutput)
            }

            configs = await pyatv.scan(loop, timeout=5)
            for config in configs:
                identifier = config.identifier
                if identifier in existing_ids:
                    continue
                output = AirPlayOutput(
                    name=config.name or "AirPlay Device",
                    identifier=identifier or "",
                    host=str(config.address),
                    _config=config,
                )
                self.register_output(output)
                discovered.append(output)
                logger.info(f"Discovered AirPlay device: {output.name}")
        except ImportError:
            logger.warning("pyatv not installed for AirPlay discovery")
        except Exception as e:
            logger.error(f"AirPlay discovery error: {e}")
        return discovered

    async def discover_chromecast(self) -> list[ChromecastOutput]:
        """Discover Chromecast devices via mDNS."""
        discovered = []
        try:
            import pychromecast

            loop = asyncio.get_running_loop()
            existing_uuids = {
                o.cast_uuid
                for o in self.outputs.values()
                if isinstance(o, ChromecastOutput)
            }

            def _discover():
                chromecasts, browser = pychromecast.get_chromecasts(timeout=5)
                browser.stop_discovery()
                return chromecasts

            chromecasts = await loop.run_in_executor(None, _discover)
            for cc in chromecasts:
                uuid_str = str(cc.uuid)
                if uuid_str in existing_uuids:
                    continue
                output = ChromecastOutput(
                    name=cc.cast_info.friendly_name or "Chromecast",
                    cast_host=cc.cast_info.host,
                    cast_uuid=uuid_str,
                    _cast=cc,
                )
                self.register_output(output)
                discovered.append(output)
                logger.info(f"Discovered Chromecast: {output.name}")
        except ImportError:
            logger.warning("pychromecast not installed for Chromecast discovery")
        except Exception as e:
            logger.error(f"Chromecast discovery error: {e}")
        return discovered

    async def discover_all(self) -> dict[str, list[dict]]:
        """Discover all output types in parallel."""
        sonos_task = asyncio.get_running_loop().run_in_executor(None, self.discover_sonos)
        upnp_task = self.discover_upnp()
        airplay_task = self.discover_airplay()
        chromecast_task = self.discover_chromecast()

        sonos, upnp, airplay, chromecast = await asyncio.gather(
            sonos_task, upnp_task, airplay_task, chromecast_task,
            return_exceptions=True,
        )

        def _devices(kind: str, result: Any) -> list[dict]:
            # Surface failures instead of silently returning an empty list — a swallowed
            # exception here looks identical to "no devices on the network".
            if isinstance(result, BaseException):
                logger.error(f"{kind} discovery failed: {result!r}")
                return []
            return [o.to_dict() for o in result]

        return {
            "sonos": _devices("Sonos", sonos),
            "upnp": _devices("UPnP", upnp),
            "airplay": _devices("AirPlay", airplay),
            "chromecast": _devices("Chromecast", chromecast),
        }

    def list_outputs(self) -> list[dict[str, Any]]:
        return [o.to_dict() for o in self.outputs.values()]


# Singleton instance
_output_manager: OutputManager | None = None


def get_output_manager() -> OutputManager:
    global _output_manager
    if _output_manager is None:
        _output_manager = OutputManager()
        # Restore saved devices BEFORE registering the browser default, so the
        # browser's register_output()->_persist() rewrites the file with the
        # loaded devices intact rather than clobbering it with an empty list.
        _output_manager.load_persisted()
        default_output = BrowserOutput(name="This Device")
        _output_manager.register_output(default_output)
    return _output_manager
