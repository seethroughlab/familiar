# Listening Sessions (WebRTC)

## Priority: Medium (v0.1.1)

## Overview

Share what you're listening to with friends in real-time using WebRTC. Host a session, share the link, and guests hear synchronized audio.

**Status for v0.1.0:** Feature is hidden in UI. Re-enable when signaling server is deployed.

---

## Current State

- WebRTC listening sessions implemented in frontend
- Works on local network (same WiFi/LAN)
- No public signaling server for remote connections
- No TURN server for NAT traversal

**Key Files (all intact, just hidden from UI):**
- `frontend/src/components/Sessions/SessionPanel.tsx`
- `frontend/src/components/Sessions/SessionButton.tsx`
- `frontend/src/components/Guest/GuestListener.tsx`
- `frontend/src/hooks/useListeningSession.ts`
- `frontend/src/hooks/useWebRTCStreaming.ts`

---

## Part 1: Signaling Server (Required)

### Why It's Needed

WebRTC requires a signaling server to coordinate connection setup between peers. Currently, sessions only work on local networks because there's no public signaling endpoint.

### Architecture: Cloudflare Workers

**Repository:** `~/Developer/familliar-signaling` (new repo)

Cloudflare Workers provides:
- Global edge deployment (low latency)
- WebSocket support via Durable Objects
- No server management
- Free tier covers low-volume use

### What the Signaling Server Does

1. **Session Discovery** - Hosts announce sessions, guests find them
2. **Peer Coordination** - Exchange SDP offers/answers between peers
3. **ICE Candidate Relay** - Forward ICE candidates during connection setup
4. **No Media Relay** - Actual audio goes peer-to-peer (or through TURN)

### Implementation

#### Step 1: Create Repository

```bash
cd ~/Developer
mkdir familliar-signaling
cd familliar-signaling
npm create cloudflare@latest . -- --type=durable-objects
```

#### Step 2: Implement Signaling Protocol

**Key components:**
- `SessionRoom` Durable Object - One per listening session
- WebSocket message types:
  - `join` - Guest joins session
  - `offer` / `answer` - SDP exchange
  - `ice-candidate` - ICE candidate forwarding
  - `leave` - Peer disconnects

#### Step 3: Session Management

```typescript
// Durable Object for each session
export class SessionRoom {
  private connections: Map<string, WebSocket> = new Map();

  async fetch(request: Request) {
    const upgradeHeader = request.headers.get('Upgrade');
    if (upgradeHeader === 'websocket') {
      return this.handleWebSocket(request);
    }
    return new Response('Expected WebSocket', { status: 400 });
  }

  private handleWebSocket(request: Request) {
    const [client, server] = Object.values(new WebSocketPair());
    server.accept();

    const peerId = crypto.randomUUID();
    this.connections.set(peerId, server);

    server.addEventListener('message', (event) => {
      this.broadcast(peerId, event.data);
    });

    return new Response(null, { status: 101, webSocket: client });
  }
}
```

#### Step 4: Deploy

```bash
npx wrangler deploy
```

#### Step 5: Configure Familiar

Add to backend settings:
```python
SIGNALING_SERVER_URL = "wss://familliar-signaling.your-account.workers.dev"
```

Update frontend to use public signaling when configured.

### Security Considerations

- Session IDs should be unguessable (UUID v4)
- Consider adding session passwords
- Rate limiting to prevent abuse

---

## Part 2: TURN Server (Optional but Recommended)

### Why It's Needed

TURN is required for guests behind symmetric NAT (corporate firewalls, mobile carriers). Without it, some connections will fail even with a signaling server.

### When TURN is Required

- Users behind symmetric NAT (corporate firewalls)
- Guests on mobile networks with carrier-grade NAT
- When direct peer-to-peer connection fails after STUN

### Options

#### Option 1: Self-Hosted coturn (Recommended)

**Pros:** Full control, no usage limits, one-time setup
**Cons:** Requires VPS with public IP

#### Option 2: Managed TURN Service

**Pros:** No server management
**Cons:** Monthly cost, usage fees
- Twilio Network Traversal
- Xirsys

### Self-Hosted coturn Setup

#### Prerequisites

- Any VPS provider: DigitalOcean, Linode, Vultr, etc.
- Minimum specs: 1 vCPU, 512MB RAM
- Public IPv4 required
- Open ports: 3478 (UDP/TCP), 5349 (TCP), 49152-65535 (UDP)

#### Step 1: Install coturn

```bash
sudo apt update
sudo apt install coturn
sudo systemctl enable coturn
```

#### Step 2: Configure `/etc/turnserver.conf`

```ini
# Network
listening-port=3478
tls-listening-port=5349
external-ip=YOUR_PUBLIC_IP

# Authentication
lt-cred-mech
user=familiar:YOUR_SECURE_PASSWORD
realm=familiar.local

# Security
fingerprint
no-multicast-peers
no-cli

# Logging
log-file=/var/log/turnserver.log
simple-log
```

#### Step 3: Enable coturn Service

Edit `/etc/default/coturn`:
```
TURNSERVER_ENABLED=1
```

#### Step 4: Open Firewall Ports

```bash
sudo ufw allow 3478/udp
sudo ufw allow 3478/tcp
sudo ufw allow 5349/tcp
sudo ufw allow 49152:65535/udp
```

#### Step 5: Start Service

```bash
sudo systemctl start coturn
sudo systemctl status coturn
```

#### Step 6: Configure Familiar

Add environment variables to `.env`:
```bash
TURN_SERVER_URL=turn:your-server.com:3478
TURN_SERVER_USERNAME=familiar
TURN_SERVER_CREDENTIAL=YOUR_SECURE_PASSWORD
```

### Testing TURN

#### Trickle ICE Test

1. Go to https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/
2. Add your TURN server:
   - URL: `turn:your-server.com:3478`
   - Username: `familiar`
   - Credential: `YOUR_SECURE_PASSWORD`
3. Click "Gather candidates"
4. Look for "relay" candidates - indicates TURN is working

### Advanced: Time-Limited Credentials

For better security, generate temporary credentials:

```python
import hmac
import hashlib
import time
import base64

def generate_turn_credentials(secret: str, username: str, ttl: int = 86400):
    timestamp = int(time.time()) + ttl
    username_with_timestamp = f"{timestamp}:{username}"

    hmac_sha1 = hmac.new(
        secret.encode(),
        username_with_timestamp.encode(),
        hashlib.sha1
    )
    password = base64.b64encode(hmac_sha1.digest()).decode()

    return username_with_timestamp, password
```

---

## Part 3: Guest Listener Improvements

### Current State

- Basic guest listener exists: `frontend/src/components/Guest/GuestListener.tsx`
- Requires full app bundle
- Mobile layout needs work
- Connection status feedback minimal

### Improvements Needed

#### 1. Standalone Page (Smaller Bundle)

**Goal:** Minimal bundle for guests who don't need full app

**Current:** Guest loads entire React app (~500KB+)
**Target:** Lightweight page (~50KB)

Options:
- Separate Vite entry point for guest page
- Preact instead of React for guest bundle
- Vanilla JS with minimal dependencies

#### 2. Mobile-Optimized Layout

Improvements:
- Full-screen album art
- Large, touch-friendly controls
- Swipe gestures for next/previous
- Lock screen / notification controls (Media Session API)

```tsx
// Responsive guest layout
<div className="guest-listener">
  {/* Full-screen album art */}
  <div className="album-art-fullscreen">
    <img src={track.artworkUrl} alt={track.album} />
  </div>

  {/* Overlay with track info and controls */}
  <div className="controls-overlay">
    <div className="track-info">
      <h1>{track.title}</h1>
      <h2>{track.artist}</h2>
    </div>

    {/* Large touch targets */}
    <div className="playback-controls">
      <button className="control-button large" onClick={onPrevious}>
        <SkipBack size={48} />
      </button>
      <button className="control-button xlarge" onClick={onPlayPause}>
        {isPlaying ? <Pause size={64} /> : <Play size={64} />}
      </button>
      <button className="control-button large" onClick={onNext}>
        <SkipForward size={48} />
      </button>
    </div>
  </div>
</div>
```

#### 3. Connection Status Feedback

```tsx
function ConnectionStatus({ state, error, retryIn }) {
  if (state === 'connected') {
    return <div className="status connected">Connected to session</div>;
  }

  if (state === 'connecting') {
    return (
      <div className="status connecting">
        <Spinner />
        Connecting to session...
      </div>
    );
  }

  if (state === 'reconnecting') {
    return (
      <div className="status reconnecting">
        <Spinner />
        Connection lost. Reconnecting in {retryIn}s...
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div className="status error">
        <AlertCircle />
        {error}
        <button onClick={onRetry}>Try Again</button>
      </div>
    );
  }
}
```

#### 4. Media Session API (Lock Screen Controls)

```typescript
if ('mediaSession' in navigator) {
  navigator.mediaSession.metadata = new MediaMetadata({
    title: track.title,
    artist: track.artist,
    album: track.album,
    artwork: [{ src: track.artworkUrl, sizes: '512x512', type: 'image/jpeg' }]
  });

  navigator.mediaSession.setActionHandler('play', onPlay);
  navigator.mediaSession.setActionHandler('pause', onPause);
  navigator.mediaSession.setActionHandler('previoustrack', onPrevious);
  navigator.mediaSession.setActionHandler('nexttrack', onNext);
}
```

#### 5. Offline Resilience

Handle disconnections gracefully:
- Auto-reconnect on network recovery
- Buffer status indicator
- "Host paused" vs "Connection lost" distinction

---

## Part 4: Host Handoff

### Concept

Allow the session host to transfer control to another **Listener** (a Familiar user, not a Guest). This enables:
- "DJ rotation" where friends take turns controlling playback
- Host can step away without ending the session
- Seamless transfer of control

### User Roles Recap

| Role | Description | Can Control Playback | Can Become Host |
|------|-------------|---------------------|-----------------|
| HOST | Session creator, streams audio | Yes | N/A |
| LISTENER | Familiar user who joined | No (until handoff) | Yes |
| GUEST | Anonymous WebRTC listener | No | No |

### Implementation

#### Backend Changes

**File:** `backend/app/services/sessions.py`

Add `transfer_host` method to SessionManager:

```python
def transfer_host(
    self,
    session: ListeningSession,
    current_host_id: UUID,
    new_host_id: UUID,
) -> bool:
    """Transfer host role to another listener."""
    # Verify current host
    if session.host_id != current_host_id:
        return False

    # Verify new host is a listener (not a guest)
    new_host = session.participants.get(new_host_id)
    if not new_host or new_host.role == SessionRole.GUEST:
        return False

    # Update roles
    old_host = session.participants.get(current_host_id)
    if old_host:
        old_host.role = SessionRole.LISTENER

    new_host.role = SessionRole.HOST
    session.host_id = new_host_id

    return True
```

**File:** `backend/app/api/routes/sessions.py`

Add message handler:

```python
elif msg_type == "transfer_host":
    # Transfer host role to another listener
    if not current_user_id:
        continue

    session = manager.get_user_session(current_user_id)
    if session is None or session.host_id != current_user_id:
        await websocket.send_json({
            "type": "error",
            "message": "Only the host can transfer control",
        })
        continue

    new_host_id = UUID(data.get("new_host_id"))
    success = manager.transfer_host(session, current_user_id, new_host_id)

    if success:
        # Notify all participants
        await manager.broadcast(
            session,
            {
                "type": "host_changed",
                "old_host_id": str(current_user_id),
                "new_host_id": str(new_host_id),
            },
        )
    else:
        await websocket.send_json({
            "type": "error",
            "message": "Cannot transfer to that user",
        })
```

#### Frontend Changes

**File:** `frontend/src/hooks/useListeningSession.ts`

Add transfer function and handle `host_changed` message:

```typescript
// Handle host_changed in message handler
case 'host_changed':
  setSession(prev => {
    if (!prev) return prev;
    return {
      ...prev,
      host_id: data.new_host_id,
      participants: prev.participants.map(p => ({
        ...p,
        role: p.user_id === data.new_host_id ? 'host' :
              p.user_id === data.old_host_id ? 'listener' : p.role,
      })),
    };
  });
  break;

// Add to return object
const transferHost = useCallback((newHostId: string) => {
  if (!session || session.host_id !== userId) return;
  send({
    type: 'transfer_host',
    new_host_id: newHostId,
  });
}, [session, userId, send]);
```

**File:** `frontend/src/components/Sessions/SessionPanel.tsx`

Add UI for host to transfer control:

```tsx
{isHost && session.participants
  .filter(p => p.role === 'listener')
  .map(listener => (
    <button
      key={listener.user_id}
      onClick={() => transferHost(listener.user_id)}
      className="text-sm text-blue-400 hover:text-blue-300"
    >
      Make {listener.username} the host
    </button>
  ))
}
```

### WebRTC Considerations

When host changes:
1. New host needs to start streaming audio to guests
2. Old host stops streaming
3. Guests need to reconnect WebRTC to new host
4. Brief audio gap is acceptable during transfer

### Success Criteria

- [ ] `transfer_host` message type implemented
- [ ] SessionManager.transfer_host() method works
- [ ] Frontend handles `host_changed` message
- [ ] UI shows "Make host" button for listeners
- [ ] WebRTC streams reconnect to new host
- [ ] Guests can only receive, never become host

---

## Implementation Order

1. **Signaling Server** - Required for any remote functionality
2. **Re-enable UI** - Unhide the feature in frontend
3. **Host Handoff** - Enable DJ rotation
4. **TURN Server** - For users behind strict NAT
5. **Guest Improvements** - Polish the experience

---

## Success Criteria

### Signaling Server
- [ ] Signaling server deployed to Cloudflare Workers
- [ ] Sessions can be created and discovered
- [ ] SDP/ICE exchange works between remote peers
- [ ] Familiar frontend updated to use public signaling
- [ ] Documentation added for self-hosting option

### TURN Server
- [ ] coturn installed and running on public VPS
- [ ] Firewall configured correctly
- [ ] Trickle ICE shows "relay" candidates
- [ ] Familiar environment variables configured
- [ ] Listening sessions work for guests behind symmetric NAT

### Guest Listener
- [ ] Separate guest bundle < 100KB
- [ ] Mobile layout with large touch targets
- [ ] Media Session API for lock screen controls
- [ ] Clear connection status feedback
- [ ] Auto-reconnect on network recovery
- [ ] Swipe gestures for track navigation
- [ ] QR code generation for easy sharing

### Host Handoff
- [ ] `transfer_host` message type implemented in backend
- [ ] SessionManager.transfer_host() method works correctly
- [ ] Frontend handles `host_changed` message
- [ ] UI shows "Make host" button for eligible listeners
- [ ] WebRTC streams reconnect to new host
- [ ] Guests cannot become host (enforced)

---

## URL Structure

Guest join URL: `https://familiar.example.com/listen?session={sessionId}`

Simple, shareable, works with QR codes.
