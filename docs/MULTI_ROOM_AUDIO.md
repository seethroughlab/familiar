# Multi-Room Audio Plan

## Priority: Low

## Goal
Enable playback to Sonos speakers and AirPlay devices in addition to browser audio.

## Current State
- Output abstraction exists: `backend/app/services/outputs.py`
- Only browser audio implemented
- No network speaker support

## Target Platforms

### Sonos
- Uses UPnP/SOAP protocol
- Requires local network access
- Can play from URL (needs audio streaming endpoint)

### AirPlay
- Apple's proprietary protocol
- Options: shairport-sync, or reverse-engineered libraries
- Requires device discovery (mDNS/Bonjour)

## Architecture

### Output Manager Interface
```python
class AudioOutput(ABC):
    @abstractmethod
    async def play(self, track: Track) -> None: ...

    @abstractmethod
    async def pause(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def set_volume(self, volume: float) -> None: ...

    @abstractmethod
    async def get_status(self) -> OutputStatus: ...
```

### Current Outputs
- `BrowserOutput` - WebSocket to frontend, plays via Web Audio API

### Planned Outputs
- `SonosOutput` - UPnP/SOAP control
- `AirPlayOutput` - shairport-sync integration

## Implementation Steps

### Step 1: Audio Streaming Endpoint
Sonos/AirPlay need a URL to stream from.

**Add endpoint:** `GET /api/v1/stream/{track_id}`
- Returns audio file as streaming response
- Supports range requests for seeking
- Content-Type based on track format

### Step 2: Device Discovery
```python
# Sonos discovery via SSDP
async def discover_sonos_devices() -> list[SonosDevice]:
    # Send M-SEARCH to 239.255.255.250:1900
    # Filter for Sonos devices
    pass

# AirPlay discovery via mDNS
async def discover_airplay_devices() -> list[AirPlayDevice]:
    # Query _raop._tcp.local
    pass
```

### Step 3: Sonos Integration
```python
class SonosOutput(AudioOutput):
    def __init__(self, device_ip: str):
        self.device_ip = device_ip
        self.base_url = f"http://{device_ip}:1400"

    async def play(self, track: Track) -> None:
        stream_url = f"{FAMILIAR_URL}/api/v1/stream/{track.id}"

        # SetAVTransportURI SOAP call
        await self._soap_call("SetAVTransportURI", {
            "CurrentURI": stream_url,
            "CurrentURIMetaData": self._build_metadata(track)
        })

        # Play SOAP call
        await self._soap_call("Play", {"Speed": "1"})
```

### Step 4: AirPlay Integration
Options:
1. **shairport-sync** - Run as daemon, control via D-Bus
2. **pyatv** - Python library for Apple TV (might work)
3. **Custom implementation** - Complex, not recommended

```python
class AirPlayOutput(AudioOutput):
    def __init__(self, device_ip: str):
        # Connect to shairport-sync or direct to device
        pass
```

### Step 5: Output Selection UI
Frontend components:
- Device discovery/refresh button
- Output selector dropdown
- Per-room volume controls
- Grouping (Sonos supports this natively)

## Challenges

### Audio Format Compatibility
- Sonos supports: MP3, AAC, FLAC, WAV
- AirPlay supports: AAC, ALAC, MP3
- May need transcoding for unsupported formats

### Network Requirements
- Sonos/AirPlay require LAN access
- Docker networking complicates device discovery
- May need `--network=host` or specific port mappings

### Latency
- Network speakers have latency (100-500ms)
- Sync between multiple outputs is complex
- May need to delay browser audio to match

## Success Criteria
- [ ] Audio streaming endpoint works
- [ ] Sonos device discovery implemented
- [ ] Sonos playback control works
- [ ] AirPlay device discovery implemented
- [ ] AirPlay playback works (via shairport-sync)
- [ ] Output selector in UI
- [ ] Volume control per output
