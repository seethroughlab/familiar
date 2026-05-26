"""Multi-room audio output API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.exceptions import NotFoundError, ValidationError
from app.db.models import Track
from app.services.outputs import (
    AirPlayOutput,
    AudioOutput,
    BrowserOutput,
    ChromecastOutput,
    OutputType,
    SonosOutput,
    TrackMetadata,
    UPnPOutput,
    get_output_manager,
)

router = APIRouter(prefix="/outputs", tags=["outputs"])


class OutputResponse(BaseModel):
    id: str
    name: str
    type: str
    state: str
    volume: int
    current_track_id: str | None
    position_ms: int


class ZoneResponse(BaseModel):
    id: str
    name: str
    outputs: list[OutputResponse]
    is_active: bool
    current_track_id: str | None


class CreateZoneRequest(BaseModel):
    name: str
    output_ids: list[str] | None = None


class CreateOutputRequest(BaseModel):
    name: str
    type: OutputType
    # Sonos
    speaker_ip: str | None = None
    # UPnP/DLNA/OpenHome (WiiM, generic)
    device_url: str | None = None
    # AirPlay
    airplay_identifier: str | None = None
    airplay_host: str | None = None
    # Chromecast
    cast_host: str | None = None
    cast_uuid: str | None = None


class PlayRequest(BaseModel):
    stream_url: str
    track_id: str | None = None


class VolumeRequest(BaseModel):
    volume: int


class SeekRequest(BaseModel):
    position_ms: int


async def _build_track_metadata(db: DbSession, track_id: UUID | None) -> TrackMetadata | None:
    """Look up track and build metadata for network outputs."""
    if not track_id:
        return None
    try:
        result = await db.execute(select(Track).where(Track.id == track_id))
        track = result.scalar_one_or_none()
        if not track:
            return None
        return TrackMetadata(
            title=track.title or "",
            artist=track.artist or "",
            album=track.album or "",
            duration_ms=int((track.duration_seconds or 0) * 1000),
        )
    except Exception:
        return None


@router.get("", response_model=list[OutputResponse])
async def list_outputs() -> list[dict[str, Any]]:
    """List all registered audio outputs."""
    manager = get_output_manager()
    return manager.list_outputs()


@router.post("", response_model=OutputResponse, status_code=status.HTTP_201_CREATED)
async def create_output(request: CreateOutputRequest) -> dict[str, Any]:
    """Register a new audio output."""
    manager = get_output_manager()
    output: AudioOutput

    if request.type == OutputType.BROWSER:
        output = BrowserOutput(name=request.name)

    elif request.type == OutputType.SONOS:
        if not request.speaker_ip:
            raise ValidationError("speaker_ip required for Sonos output")
        output = SonosOutput(name=request.name, speaker_ip=request.speaker_ip)

    elif request.type == OutputType.UPNP:
        if not request.device_url:
            raise ValidationError("device_url required for UPnP output")
        output = UPnPOutput(name=request.name, device_url=request.device_url)

    elif request.type == OutputType.AIRPLAY:
        if not request.airplay_identifier and not request.airplay_host:
            raise ValidationError("airplay_identifier or airplay_host required for AirPlay output")
        output = AirPlayOutput(
            name=request.name,
            identifier=request.airplay_identifier or "",
            host=request.airplay_host or "",
        )

    elif request.type == OutputType.CHROMECAST:
        if not request.cast_host and not request.cast_uuid:
            raise ValidationError("cast_host or cast_uuid required for Chromecast output")
        output = ChromecastOutput(
            name=request.name,
            cast_host=request.cast_host or "",
            cast_uuid=request.cast_uuid or "",
        )

    else:
        raise ValidationError("Unsupported output type", detail=f"Received: {request.type}")

    manager.register_output(output)
    return output.to_dict()


# Discovery endpoints

@router.get("/discover", response_model=dict[str, list[OutputResponse]])
async def discover_all_outputs() -> dict[str, list[dict[str, Any]]]:
    """Discover all output types in parallel (Sonos, UPnP, AirPlay, Chromecast)."""
    manager = get_output_manager()
    return await manager.discover_all()


@router.get("/discover/sonos", response_model=list[OutputResponse])
async def discover_sonos() -> list[dict[str, Any]]:
    """Discover Sonos speakers on the network."""
    manager = get_output_manager()
    discovered = manager.discover_sonos()
    return [o.to_dict() for o in discovered]


@router.get("/discover/upnp", response_model=list[OutputResponse])
async def discover_upnp() -> list[dict[str, Any]]:
    """Discover UPnP/DLNA/OpenHome devices (WiiM, generic DLNA speakers)."""
    manager = get_output_manager()
    discovered = await manager.discover_upnp()
    return [o.to_dict() for o in discovered]


@router.get("/discover/airplay", response_model=list[OutputResponse])
async def discover_airplay() -> list[dict[str, Any]]:
    """Discover AirPlay devices on the network."""
    manager = get_output_manager()
    discovered = await manager.discover_airplay()
    return [o.to_dict() for o in discovered]


@router.get("/discover/chromecast", response_model=list[OutputResponse])
async def discover_chromecast() -> list[dict[str, Any]]:
    """Discover Chromecast devices on the network."""
    manager = get_output_manager()
    discovered = await manager.discover_chromecast()
    return [o.to_dict() for o in discovered]


# Output control endpoints

@router.get("/{output_id}", response_model=OutputResponse)
async def get_output(output_id: UUID) -> dict[str, Any]:
    """Get an audio output by ID."""
    manager = get_output_manager()
    output = manager.get_output(output_id)
    if not output:
        raise NotFoundError("Output not found")
    return await output.get_status()


@router.delete("/{output_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_output(output_id: UUID) -> None:
    """Unregister an audio output."""
    manager = get_output_manager()
    if not manager.unregister_output(output_id):
        raise NotFoundError("Output not found")


@router.post("/{output_id}/play")
async def play_to_output(
    output_id: UUID,
    request: PlayRequest,
    db: DbSession,
) -> dict[str, str]:
    """Play to a specific output."""
    manager = get_output_manager()
    track_id = UUID(request.track_id) if request.track_id else None
    metadata = await _build_track_metadata(db, track_id)
    success = await manager.play_to_output(output_id, request.stream_url, track_id, metadata)
    if not success:
        raise ValidationError("Failed to start playback")
    return {"status": "playing"}


@router.post("/{output_id}/pause")
async def pause_output(output_id: UUID) -> dict[str, str]:
    """Pause an output."""
    manager = get_output_manager()
    output = manager.get_output(output_id)
    if not output:
        raise NotFoundError("Output not found")
    await output.pause()
    return {"status": "paused"}


@router.post("/{output_id}/resume")
async def resume_output(output_id: UUID) -> dict[str, str]:
    """Resume an output."""
    manager = get_output_manager()
    output = manager.get_output(output_id)
    if not output:
        raise NotFoundError("Output not found")
    await output.resume()
    return {"status": "playing"}


@router.post("/{output_id}/stop")
async def stop_output(output_id: UUID) -> dict[str, str]:
    """Stop an output."""
    manager = get_output_manager()
    output = manager.get_output(output_id)
    if not output:
        raise NotFoundError("Output not found")
    await output.stop()
    return {"status": "stopped"}


@router.post("/{output_id}/seek")
async def seek_output(output_id: UUID, request: SeekRequest) -> dict[str, str | int]:
    """Seek an output to a position."""
    manager = get_output_manager()
    output = manager.get_output(output_id)
    if not output:
        raise NotFoundError("Output not found")
    await output.seek(request.position_ms)
    return {"status": "seeked", "position_ms": request.position_ms}


@router.post("/{output_id}/volume")
async def set_output_volume(output_id: UUID, request: VolumeRequest) -> dict[str, str | int]:
    """Set output volume."""
    manager = get_output_manager()
    output = manager.get_output(output_id)
    if not output:
        raise NotFoundError("Output not found")
    await output.set_volume(request.volume)
    return {"status": "volume_set", "volume": request.volume}


# Zone endpoints

@router.get("/zones", response_model=list[ZoneResponse])
async def list_zones() -> list[dict[str, Any]]:
    """List all zones."""
    manager = get_output_manager()
    return manager.list_zones()


@router.post("/zones", response_model=ZoneResponse, status_code=status.HTTP_201_CREATED)
async def create_zone(request: CreateZoneRequest) -> dict[str, Any]:
    """Create a new zone."""
    manager = get_output_manager()
    output_ids = [UUID(oid) for oid in request.output_ids] if request.output_ids else None
    zone = manager.create_zone(request.name, output_ids)
    return zone.to_dict()


@router.get("/zones/{zone_id}", response_model=ZoneResponse)
async def get_zone(zone_id: UUID) -> dict[str, Any]:
    """Get a zone by ID."""
    manager = get_output_manager()
    zone = manager.get_zone(zone_id)
    if not zone:
        raise NotFoundError("Zone not found")
    return zone.to_dict()


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(zone_id: UUID) -> None:
    """Delete a zone."""
    manager = get_output_manager()
    if not manager.delete_zone(zone_id):
        raise NotFoundError("Zone not found")


@router.post("/zones/{zone_id}/play")
async def play_to_zone(
    zone_id: UUID,
    request: PlayRequest,
    db: DbSession,
) -> dict[str, Any]:
    """Play to all outputs in a zone."""
    manager = get_output_manager()
    track_id = UUID(request.track_id) if request.track_id else None
    metadata = await _build_track_metadata(db, track_id)
    results = await manager.play_to_zone(zone_id, request.stream_url, track_id, metadata)
    if not results:
        raise NotFoundError("Zone not found")
    return {"status": "playing", "results": {str(k): v for k, v in results.items()}}


@router.post("/zones/{zone_id}/pause")
async def pause_zone(zone_id: UUID) -> dict[str, Any]:
    """Pause all outputs in a zone."""
    manager = get_output_manager()
    zone = manager.get_zone(zone_id)
    if not zone:
        raise NotFoundError("Zone not found")
    results = await zone.pause()
    return {"status": "paused", "results": {str(k): v for k, v in results.items()}}


@router.post("/zones/{zone_id}/stop")
async def stop_zone(zone_id: UUID) -> dict[str, Any]:
    """Stop all outputs in a zone."""
    manager = get_output_manager()
    zone = manager.get_zone(zone_id)
    if not zone:
        raise NotFoundError("Zone not found")
    results = await zone.stop()
    return {"status": "stopped", "results": {str(k): v for k, v in results.items()}}


@router.post("/zones/{zone_id}/outputs/{output_id}")
async def add_output_to_zone(zone_id: UUID, output_id: UUID) -> dict[str, Any]:
    """Add an output to a zone."""
    manager = get_output_manager()
    zone = manager.get_zone(zone_id)
    if not zone:
        raise NotFoundError("Zone not found")
    output = manager.get_output(output_id)
    if not output:
        raise NotFoundError("Output not found")
    zone.add_output(output)
    return zone.to_dict()


@router.delete("/zones/{zone_id}/outputs/{output_id}")
async def remove_output_from_zone(zone_id: UUID, output_id: UUID) -> dict[str, Any]:
    """Remove an output from a zone."""
    manager = get_output_manager()
    zone = manager.get_zone(zone_id)
    if not zone:
        raise NotFoundError("Zone not found")
    if not zone.remove_output(output_id):
        raise NotFoundError("Output not in zone")
    return zone.to_dict()
