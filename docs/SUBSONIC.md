# Subsonic API / CarPlay Setup

Familiar implements the [Subsonic API](http://www.subsonic.org/pages/api.jsp), allowing you to use native music apps on your phone with CarPlay and Android Auto support. Browse, search, and stream your entire library from any Subsonic-compatible client.

## What This Enables

- **CarPlay / Android Auto** - Control your music library from your car's dashboard
- **Native app experience** - Dedicated music apps with offline downloads, gapless playback, and background audio
- **Multiple devices** - Connect from any phone, tablet, or desktop Subsonic client

## Setup

### 1. Generate Credentials

1. Open Familiar in your browser
2. Go to **Settings** > **Subsonic API**
3. Click **Generate Credentials**
4. Copy the **username** and **password** (the password is shown once — save it somewhere safe)

If you lose the password, click **Regenerate** to create new credentials. This invalidates the old ones.

### 2. Choose a Client App

| App | Platform | Price | Notes |
|-----|----------|-------|-------|
| [Symfonium](https://symfonium.app/) | Android | $5 (one-time) | Best Android client. Excellent CarPlay/Android Auto, offline, gapless playback |
| [play:Sub](https://apps.apple.com/app/play-sub-music-streamer/id955329386) | iOS | $5 (one-time) | Best iOS client. CarPlay support, offline downloads |
| [Amperfy](https://github.com/BLeeEZ/Amperfy) | iOS | Free | Open-source, CarPlay support, good feature set |
| [Ultrasonic](https://github.com/ultrasonic/ultrasonic) | Android | Free | Open-source, mature, Android Auto support |
| [Sublime Music](https://sublimemusic.app/) | Linux | Free | GTK desktop client |
| [Sonixd](https://github.com/jeffvli/sonixd) | Desktop | Free | Electron-based, cross-platform |

### 3. Configure the Client

In your chosen app, add a new server with these settings:

| Setting | Value |
|---------|-------|
| **Server URL** | `http://your-server-ip:4400` (or your Tailscale HTTPS URL) |
| **Username** | The username from step 1 |
| **Password** | The password from step 1 |
| **Server type** | Subsonic or Open Subsonic |

**Tips:**
- Use your Tailscale HTTPS URL (`https://server.tailnet.ts.net`) if you want access outside your home network
- Some apps call it "Server address" instead of "Server URL"
- If your app asks for an API path or endpoint, leave it as the default (usually `/rest`)

## What Works (Phase 1)

- Browse artists, albums, and tracks
- Search across your library
- Stream audio (all formats — MP3, FLAC, M4A, AAC, OGG, WAV)
- Album artwork
- Genre browsing
- Random song playback

## Coming Soon (Phase 2)

- Playlist sync (view and manage your Familiar playlists)
- Favorites / starred tracks
- Scrobbling (Last.fm integration through the Subsonic client)
- Now playing notifications

## Troubleshooting

**"Wrong username or password"**
- Verify you're using the credentials from Settings > Subsonic API (not your Familiar profile name)
- Credentials are case-sensitive
- Try regenerating credentials if unsure

**"Connection refused" or timeout**
- Ensure Familiar is running and reachable from your phone
- If on the same network, use `http://192.168.x.x:4400` (your server's local IP)
- If using Tailscale, ensure both devices are connected to your tailnet

**No albums / empty library**
- Make sure you've run a library scan in Familiar first (Settings > Library Management)
- The Subsonic API serves the same library as the web UI

**CarPlay / Android Auto not showing the app**
- This depends on your client app, not Familiar — check the app's documentation
- Symfonium, play:Sub, and Amperfy all support CarPlay/Android Auto natively

**Artwork not loading**
- Artwork uses the same album art as the web UI
- If artwork is missing in the web UI too, try rescanning the library
