# Capacitor iOS Integration Plan

## Problem

iOS kills PWA audio after ~15-30 seconds in background. The `<audio>` element loses its source, and the Web Audio API context gets suspended. There's no reliable workaround within a pure PWA.

## Solution: Capacitor Shell

Wrap the existing Vite/React frontend in a native iOS app using Capacitor. This gives us:

- **Background audio** via native AVAudioSession
- **Lock screen / Control Center** controls via MPNowPlayingInfoCenter
- **Reliable offline** via native storage (no Safari eviction)
- Same web codebase, just loaded inside WKWebView

## Prerequisites (Done)

- [x] **Centralize API URLs** - All `fetch()` and `<img src>` URLs use `getApiUrl()` / `getApiOrigin()` so switching from relative to absolute is a one-line change
- [x] **CORS expose_headers** - Backend exposes `Content-Range`, `Accept-Ranges`, `Content-Length` for cross-origin Range requests

## Phase 1: Basic Capacitor Setup

1. **Initialize Capacitor** in the frontend directory:
   ```bash
   cd frontend
   npm install @capacitor/core @capacitor/cli
   npx cap init "Familiar" "com.familiar.app" --web-dir dist
   npx cap add ios
   ```

2. **Configure `getApiOrigin()`** to return the backend URL when running in Capacitor:
   ```ts
   import { Capacitor } from '@capacitor/core';

   export function getApiOrigin(): string {
     if (Capacitor.isNativePlatform()) {
       // Backend URL - could come from settings/env
       return 'http://nas.local:4400';
     }
     return ''; // Same-origin for web
   }
   ```

3. **Build and sync**:
   ```bash
   npm run build
   npx cap sync ios
   npx cap open ios
   ```

4. **Test basic functionality** - browsing library, playing audio (foreground only at this point)

## Phase 2: Background Audio

1. **Install Capacitor plugins**:
   ```bash
   npm install @nicepkg/capacitor-background-mode
   # or use a community background audio plugin
   ```

2. **Native AVAudioSession** setup in `ios/App/App/AppDelegate.swift`:
   ```swift
   import AVFoundation

   func application(_ application: UIApplication, didFinishLaunchingWithOptions ...) -> Bool {
     let audioSession = AVAudioSession.sharedInstance()
     try? audioSession.setCategory(.playback, mode: .default)
     try? audioSession.setActive(true)
     return true
   }
   ```

3. **Enable Background Modes** in Xcode:
   - Capabilities > Background Modes > Audio, AirPlay, and Picture in Picture

4. **Bridge audio events** between WKWebView and native:
   - When the web player starts/pauses, notify native side
   - Native side updates MPNowPlayingInfoCenter
   - Lock screen controls send events back to web player

## Phase 3: Lock Screen Controls

1. **MPNowPlayingInfoCenter** integration:
   ```swift
   // Update Now Playing info when track changes
   var nowPlayingInfo = [String: Any]()
   nowPlayingInfo[MPMediaItemPropertyTitle] = trackTitle
   nowPlayingInfo[MPMediaItemPropertyArtist] = trackArtist
   nowPlayingInfo[MPNowPlayingInfoPropertyElapsedPlaybackTime] = currentTime
   nowPlayingInfo[MPMediaItemPropertyPlaybackDuration] = duration
   MPNowPlayingInfoCenter.default().nowPlayingInfo = nowPlayingInfo
   ```

2. **Remote command center** for play/pause/next/previous:
   ```swift
   let commandCenter = MPRemoteCommandCenter.shared()
   commandCenter.playCommand.addTarget { _ in
     // Send message to webview
     return .success
   }
   ```

3. **Capacitor plugin bridge** to communicate between Swift and TypeScript:
   ```ts
   // TypeScript side
   Capacitor.Plugins.NowPlaying.updateTrack({
     title: track.title,
     artist: track.artist,
     artwork: getApiUrl(`/tracks/${track.id}/artwork?size=full`),
   });
   ```

## Phase 4: Server Discovery

Since the app runs on a separate origin, it needs to find the backend:

1. **Settings screen** - Let user enter backend URL manually (e.g., `http://192.168.1.100:4400`)
2. **mDNS/Bonjour discovery** - Backend advertises via mDNS, app discovers automatically
3. **Store URL** in Capacitor Preferences (persists across launches)

## Phase 5: Native Offline Storage

Replace IndexedDB with Capacitor Filesystem for large audio files:

1. **@capacitor/filesystem** for audio blob storage
2. Keep IndexedDB/Dexie for metadata (it works fine for small data)
3. No Safari storage eviction concerns with native filesystem

## Architecture Notes

- The web app continues to work as a PWA in browsers - Capacitor is additive
- `Capacitor.isNativePlatform()` guards all native-only code paths
- Audio playback still uses `<audio>` element / Web Audio API in the WKWebView
- The native AVAudioSession just prevents iOS from killing the audio session
- All API communication uses the same HTTP endpoints, just with absolute URLs

## Estimated Effort

| Phase | Effort | Dependencies |
|-------|--------|-------------|
| Phase 1: Basic setup | 1-2 hours | Prerequisites done |
| Phase 2: Background audio | 3-4 hours | Phase 1 |
| Phase 3: Lock screen | 2-3 hours | Phase 2 |
| Phase 4: Server discovery | 2-3 hours | Phase 1 |
| Phase 5: Native offline | 4-6 hours | Phase 1 |

Total: ~12-18 hours of focused work

## References

- [Capacitor docs](https://capacitorjs.com/docs)
- [AVAudioSession background audio](https://developer.apple.com/documentation/avfaudio/avaudiosession)
- [MPNowPlayingInfoCenter](https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfocenter)
