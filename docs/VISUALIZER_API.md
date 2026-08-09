# Visualizer API

Create custom audio visualizers for Familiar. Visualizers are React components that receive track metadata, audio features, real-time audio data, and timed lyrics.

## Quick Start

Create a new visualizer in `frontend/src/components/Visualizer/visualizers/`:

```tsx
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { registerVisualizer, type VisualizerProps } from '../types';
import { useAudioAnalyser, getAudioData } from '../hooks';

function Scene() {
  const meshRef = useRef<THREE.Mesh>(null);
  useAudioAnalyser(true);

  useFrame(() => {
    const audioData = getAudioData();
    if (meshRef.current && audioData) {
      meshRef.current.scale.y = 1 + audioData.bass;
    }
  });

  return (
    <mesh ref={meshRef}>
      <boxGeometry />
      <meshBasicMaterial color="#a855f7" />
    </mesh>
  );
}

export function MyVisualizer(props: VisualizerProps) {
  return (
    <Canvas camera={{ position: [0, 0, 5] }}>
      <Scene />
    </Canvas>
  );
}

// Register the visualizer
registerVisualizer(
  {
    id: 'my-visualizer',
    name: 'My Visualizer',
    description: 'A custom audio visualizer',
    usesMetadata: false,
  },
  MyVisualizer
);
```

Then import it in `frontend/src/components/Visualizer/visualizers/index.ts`:

```tsx
import './MyVisualizer';
```

Your visualizer will appear in the visualizer picker.

---

## VisualizerProps

Props passed to every visualizer component.

```typescript
interface VisualizerProps {
  // === Playback State ===
  currentTime: number;    // Current playback position in seconds
  duration: number;       // Track duration in seconds
  isPlaying: boolean;     // Whether audio is currently playing

  // === Track Metadata ===
  track: Track | null;    // Full track object, null if nothing playing

  // === Audio Analysis ===
  features: TrackFeatures | null;  // BPM, key, energy, etc.

  // === Media ===
  artworkUrl: string | null;       // Album artwork URL
  lyrics: LyricLine[] | null;      // Time-synced lyrics
}
```

---

## Data Types

### Track

```typescript
interface Track {
  id: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  album_type: 'album' | 'compilation' | 'soundtrack';
  track_number: number | null;
  disc_number: number | null;
  year: number | null;
  genre: string | null;
  duration_seconds: number | null;
  format: string | null;           // mp3, flac, m4a, etc.
  analysis_version: number;
  features?: TrackFeatures;
}
```

### TrackFeatures

Audio analysis data (available when track has been analyzed):

```typescript
interface TrackFeatures {
  bpm: number | null;              // Tempo in beats per minute
  key: string | null;              // Musical key (e.g., "Am", "C#")
  energy: number | null;           // 0-1, calm to energetic
  danceability: number | null;     // 0-1, suitability for dancing
  valence: number | null;          // 0-1, sad to happy
  acousticness: number | null;     // 0-1, acoustic vs electronic
  instrumentalness: number | null; // 0-1, vocals vs instrumental
  speechiness: number | null;      // 0-1, spoken word presence
}
```

### LyricLine

```typescript
interface LyricLine {
  time: number;   // Start time in seconds
  text: string;   // Lyric text
}
```

---

## Hooks

Import from `../hooks`:

```typescript
import {
  useAudioAnalyser,
  getAudioData,
  useArtworkPalette,
  useBeatSync,
  useLyricTiming,
} from '../hooks';
```

### useAudioAnalyser

Real-time audio frequency data from Web Audio API.

```typescript
const audioData = useAudioAnalyser(enabled: boolean = true);
```

**Returns:**

```typescript
interface AudioAnalysisData {
  frequencyData: Uint8Array;    // Raw frequency bins (0-255 per bin)
  timeDomainData: Uint8Array;   // Waveform data (centered at 128)
  bass: number;                 // 0-1, low frequency intensity
  mid: number;                  // 0-1, mid frequency intensity
  treble: number;               // 0-1, high frequency intensity
  averageFrequency: number;     // 0-255, overall intensity
  beat: number;                 // 0-1, decaying envelope; spikes to 1 on a detected onset
  onset: boolean;               // true only on the frame an onset is detected
}
```

### `beat` and `onset`

**These were undocumented for a long time while two shipping visualizers used them**, so if you have
read this file before and not seen them, that is why rather than because they are new.

`beat` is an envelope, not a flag: it jumps to 1 when a transient is detected and falls linearly to
0 over ~230 ms. Multiply things by it. It is the right choice for anything continuous — a scale, an
intensity, a camera nudge — and it degrades gracefully, because a missed onset just means a smaller
number.

`onset` is true for **exactly one frame**. Use it to *start* something — spawn a ripple, flip a
tile — and read it every frame if you do, because a consumer that samples less often than the
analyser can miss it entirely.

Both come from spectral flux against an adaptive threshold: energy appearing across the spectrum,
compared to a running average of how much has been appearing lately. There is no tempo model and no
beat grid behind them, so they respond to *events* rather than to a pulse. On music with a strong
regular beat that amounts to the same thing; on rubato or free time it does not, and nothing here
will pretend otherwise.

**Timing.** In a browser these lag the audio by roughly 40–60 ms — an FFT window plus smoothing plus
a frame. Inside the native apps the audio arrives from a different process and the lag is closer to
120–140 ms. That is inherent to reacting rather than predicting: nothing can respond to a transient
before it has heard it. If you are building something where being exactly on the beat matters more
than reacting to what actually happened, this is the wrong signal for it.

```typescript
```

**Example:**

```tsx
function MyScene() {
  const audioData = useAudioAnalyser(true);

  // Use in render (triggers re-renders)
  const scale = 1 + (audioData?.bass ?? 0);

  return <mesh scale={scale}>...</mesh>;
}
```

### getAudioData

Synchronous access to audio data for use in Three.js `useFrame` (doesn't trigger re-renders).

```typescript
const audioData = getAudioData();
```

**Example:**

```tsx
function MyScene() {
  const meshRef = useRef<THREE.Mesh>(null);
  useAudioAnalyser(true);  // Enable analysis

  useFrame(() => {
    const audioData = getAudioData();
    if (meshRef.current && audioData) {
      meshRef.current.scale.y = 1 + audioData.bass * 2;
    }
  });

  return <mesh ref={meshRef}>...</mesh>;
}
```

### useArtworkPalette

Extract dominant colors from album artwork.

```typescript
const palette = useArtworkPalette(
  artworkUrl: string | null,
  numColors: number = 5
): string[];
```

**Returns:** Array of hex color strings (e.g., `['#a855f7', '#06b6d4', ...]`)

**Example:**

```tsx
function MyVisualizer({ artworkUrl }: VisualizerProps) {
  const palette = useArtworkPalette(artworkUrl);

  return (
    <Canvas>
      <mesh>
        <meshBasicMaterial color={palette[0]} />
      </mesh>
    </Canvas>
  );
}
```

### useBeatSync

**Not recommended, and documented here mainly so you know why it is not.** It is a pure metronome
over `bpm`: it assumes the first beat is at `t=0`, which is true of almost no recording, and it is
driven by `currentTime`, which updates about four times a second — so its `onBeat` window at 120 BPM
is narrower than the interval between updates and it misses most beats. No shipping visualizer uses
it. Prefer `beat` from `useAudioAnalyser` above.

Synchronize animations with detected BPM.

```typescript
const beatData = useBeatSync(
  bpm: number | null | undefined,
  currentTime: number
): BeatSyncData;
```

**Returns:**

```typescript
interface BeatSyncData {
  beat: number;         // Current beat number (0, 1, 2, ...)
  beatProgress: number; // Progress through current beat (0-1)
  onBeat: boolean;      // True when a new beat just started
  bpm: number;          // Effective BPM (120 if not detected)
  beatDuration: number; // Seconds per beat
}
```

**Example:**

```tsx
function MyVisualizer({ features, currentTime }: VisualizerProps) {
  const { beatProgress, onBeat, bpm } = useBeatSync(features?.bpm, currentTime);

  // Pulse on each beat
  const scale = onBeat ? 1.2 : 1 + beatProgress * 0.1;

  // Smooth sine wave synced to beat
  const pulse = Math.sin(beatProgress * Math.PI);

  return <div style={{ transform: `scale(${scale})` }}>...</div>;
}
```

### useLyricTiming

Get current and upcoming lyric lines.

```typescript
const lyricData = useLyricTiming(
  lyrics: LyricLine[] | null,
  currentTime: number
): LyricTimingData;
```

**Returns:**

```typescript
interface LyricTimingData {
  currentLine: LyricLine | null;  // Current line being sung
  currentIndex: number;           // Index in lyrics array
  nextLine: LyricLine | null;     // Upcoming line
  progress: number;               // 0-1 progress through current line
  timeToNext: number;             // Seconds until next line
  words: string[];                // Individual words from current line
  hasLyrics: boolean;             // Whether lyrics are available
}
```

**Example:**

```tsx
function LyricDisplay({ lyrics, currentTime }: VisualizerProps) {
  const { currentLine, nextLine, progress, hasLyrics } = useLyricTiming(lyrics, currentTime);

  if (!hasLyrics) {
    return <div>No lyrics available</div>;
  }

  return (
    <div>
      <div style={{ opacity: 1 - progress * 0.5 }}>
        {currentLine?.text}
      </div>
      <div style={{ opacity: progress * 0.5 }}>
        {nextLine?.text}
      </div>
    </div>
  );
}
```

---

## Rendering Approaches

### Three.js (3D)

Best for: particle systems, 3D shapes, shader effects, GPU-accelerated animations.

```tsx
import { Canvas, useFrame } from '@react-three/fiber';
import { useAudioAnalyser, getAudioData } from '../hooks';

function Scene() {
  const meshRef = useRef<THREE.Mesh>(null);
  useAudioAnalyser(true);

  useFrame((_, delta) => {
    const audioData = getAudioData();
    if (meshRef.current && audioData) {
      meshRef.current.rotation.y += delta * (1 + audioData.mid);
      meshRef.current.scale.setScalar(1 + audioData.bass);
    }
  });

  return (
    <mesh ref={meshRef}>
      <icosahedronGeometry args={[1, 2]} />
      <meshStandardMaterial color="#a855f7" wireframe />
    </mesh>
  );
}

export function MyVisualizer(props: VisualizerProps) {
  return (
    <Canvas camera={{ position: [0, 0, 5] }}>
      <ambientLight intensity={0.5} />
      <Scene />
    </Canvas>
  );
}
```

**See:** `CosmicOrb.tsx`, `FrequencyBars.tsx`, `AlbumKaleidoscope.tsx`, `LyricStorm.tsx`

### Canvas 2D

Best for: custom drawing, text effects, pixel manipulation.

```tsx
import { useRef, useEffect } from 'react';
import { useAudioAnalyser } from '../hooks';

export function MyVisualizer({ currentTime }: VisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const audioData = useAudioAnalyser(true);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!ctx || !canvas) return;

    ctx.fillStyle = '#0a0015';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Draw frequency bars
    if (audioData?.frequencyData) {
      const barWidth = canvas.width / 64;
      for (let i = 0; i < 64; i++) {
        const value = audioData.frequencyData[i] / 255;
        const hue = (i / 64) * 60 + 260;
        ctx.fillStyle = `hsl(${hue}, 80%, 50%)`;
        ctx.fillRect(
          i * barWidth,
          canvas.height - value * canvas.height,
          barWidth - 1,
          value * canvas.height
        );
      }
    }
  }, [audioData]);

  return <canvas ref={canvasRef} width={800} height={600} className="w-full h-full" />;
}
```

**See:** `TypographyWave.tsx`

### HTML/CSS

Best for: text-heavy visualizers, simple animations, accessibility.

```tsx
import { useAudioAnalyser, useLyricTiming } from '../hooks';

export function MyVisualizer({ track, lyrics, currentTime }: VisualizerProps) {
  const audioData = useAudioAnalyser(true);
  const { currentLine } = useLyricTiming(lyrics, currentTime);

  const bass = audioData?.bass ?? 0;
  const scale = 1 + bass * 0.1;
  const glow = 10 + bass * 30;

  return (
    <div className="flex items-center justify-center h-full bg-[#0a0015]">
      <h1
        className="text-6xl font-bold text-purple-500"
        style={{
          transform: `scale(${scale})`,
          textShadow: `0 0 ${glow}px #a855f7`,
        }}
      >
        {currentLine?.text || track?.title || 'No Track'}
      </h1>
    </div>
  );
}
```

**See:** `LyricPulse.tsx`

---

## Post-Processing Effects

Add bloom, vignette, and audio-reactive effects using the `AudioReactiveEffects` component:

```tsx
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';

function MyScene() {
  return (
    <>
      {/* Your scene content */}
      <mesh>...</mesh>

      {/* Add post-processing */}
      <AudioReactiveEffects
        enableBloom
        enableVignette
        bloomIntensity={1.5}
        bloomThreshold={0.6}
        vignetteIntensity={0.4}
      />
    </>
  );
}
```

**Props:**

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `enableBloom` | boolean | true | Enable bloom/glow effect |
| `enableVignette` | boolean | true | Enable vignette darkening |
| `bloomIntensity` | number | 1.0 | Bloom strength (audio-reactive) |
| `bloomThreshold` | number | 0.85 | Brightness threshold for bloom |
| `bloomRadius` | number | 0.5 | Bloom spread radius |
| `vignetteIntensity` | number | 0.5 | Vignette darkness |

Effects automatically react to bass and average frequency.

---

## Registration

Register your visualizer at the bottom of your file:

```typescript
import { registerVisualizer, type VisualizerProps } from '../types';

registerVisualizer(
  {
    id: 'my-visualizer',           // Unique ID (kebab-case)
    name: 'My Visualizer',         // Display name in picker
    description: 'A cool effect',  // Short description
    usesMetadata: true,            // true if using track/artwork/lyrics
    author: 'Your Name',           // Optional: for community visualizers
  },
  MyVisualizer
);
```

---

## Existing Visualizers

| Visualizer | Description | Key Features |
|------------|-------------|--------------|
| `CosmicOrb` | Glowing orb with particle field | GPU particles, custom shaders, waveform ring |
| `FrequencyBars` | Spectrum analyzer | 128 bars, gradient colors, reflective floor |
| `AlbumKaleidoscope` | Kaleidoscope from artwork | Shader-based mirroring, twist effects, sparkles |
| `ColorFlow` | Flowing color particles | Palette extraction, flow field, glowing rings |
| `LyricStorm` | 3D floating lyrics | drei Text, depth sorting, current line highlight |
| `LyricPulse` | Pulsing current lyric | BPM sync, glow effects, progress bar |
| `TypographyWave` | Animated text waves | Canvas 2D, per-character animation |

---

## Guidelines

1. **Handle null props** - Track, features, artwork, and lyrics may be null
2. **Clean up resources** - Return cleanup function from useEffect
3. **Use getAudioData() in useFrame** - Avoids triggering React re-renders
4. **Keep files small** - Target under 50KB per visualizer
5. **No external APIs** - Use only provided data
6. **Test with various tracks** - Different genres, with/without lyrics

---

## Performance Tips

1. **Use useMemo** for geometry and materials:
   ```tsx
   const geometry = useMemo(() => new THREE.BoxGeometry(1, 1, 1), []);
   ```

2. **Update uniforms, not geometry** in animations:
   ```tsx
   useFrame(() => {
     materialRef.current.uniforms.uTime.value = clock.elapsedTime;
   });
   ```

3. **Limit particle counts** based on device:
   ```tsx
   const particleCount = window.devicePixelRatio > 1 ? 5000 : 2000;
   ```

4. **Use getAudioData()** in useFrame to avoid re-renders

5. **Respect reduced motion**:
   ```tsx
   const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
   ```

---

## Drop-In Plugins

Everything above describes a visualizer compiled into the app. A visualizer can also be **dropped
in as a pre-built bundle**, with no pull request and no redeploy
([ADR-0034](decisions/ADR-0034-visualizers-are-drop-in-bundles.md)). The component you write is
identical — same `VisualizerProps`, same hooks, same `registerVisualizer` — only how it reaches the
app differs.

### Anatomy

```
my-visualizer/
├── familiar-plugin.json     # the manifest
└── dist/index.js            # the built bundle
```

```json
{
  "name": "Non-Places",
  "id": "non-places",
  "version": "0.1.0",
  "type": "visualizer",
  "description": "Surreal 3D models drifting through fog",
  "main": "dist/index.js",
  "familiar": { "apiVersion": 1 },
  "icon": "Building2"
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Lowercase letters, digits and hyphens. Must match the id your bundle registers, and must not be one of the built-ins (`reactive-terrain`, `beat-tiles`, `lyrics`, `music-video`). |
| `name` | yes | Shown in the picker. |
| `type` | yes | Must be `visualizer`. Library browsers are out of scope. |
| `main` | yes | Path to the bundle, relative to this folder. It may not point outside it. |
| `familiar.apiVersion` | yes | Must equal the version the app implements — currently **1**. A missing or mismatched value is refused before the bundle is run. |
| `version`, `description`, `icon`, `author` | no | `icon` is a [lucide](https://lucide.dev) name, used by the web picker only. |

### Building the bundle

The bundle is an **IIFE**, not an ES module, and it reads `window.Familiar` at its top level:

```js
// rollup.config.js
export default {
  input: 'src/index.tsx',
  output: {
    file: 'dist/index.js',
    format: 'iife',
    globals: {
      react: 'window.Familiar.React',
      'react/jsx-runtime': 'window.Familiar.React',
      three: 'window.Familiar.THREE',
      '@react-three/fiber': 'window.Familiar.ReactThreeFiber',
      '@react-three/drei': 'window.Familiar.Drei',
    },
  },
  external: ['react', 'react/jsx-runtime', 'three', '@react-three/fiber', '@react-three/drei'],
  plugins: [nodeResolve(), typescript()],
};
```

**Externalise React, three.js, `@react-three/fiber` and `@react-three/drei` — the host provides all
four.** This is not a size optimisation: two copies of React in one document do not work, and two
copies of three.js in one WebGL context is a megabyte of duplicate for nothing. Nothing enforces
this; a bundle that carries its own will break in ways that look like a host bug.

```js
const { React, THREE, ReactThreeFiber, Drei, registerVisualizer, hooks } = window.Familiar;
const { useAudioAnalyser, getAudioData, useBeatSync, useLyricTiming, useArtworkPalette } = hooks;
```

### Installing

Copy the folder into Familiar's `Visualizers` directory, then reopen the visualizer:

- **macOS** — `~/Library/Application Support/Familiar/Visualizers`. Settings → Playback has a
  **Show Visualizers Folder** button.
- **iOS** — Files → On My iPhone → Familiar → Visualizers.
- **Web** — not supported. A browser has no such directory, and ADR-0034 admits no third source;
  drop-in plugins are a Mac and phone feature. Install-from-URL is deferred, not rejected.

### When it does not appear

**It always says why.** A plugin that is present and not loaded is listed under **Not loaded** in
the visualizer menu (native) or the picker (web), with the reason:

| Reason | Cause |
|---|---|
| *is not a JSON object* / *could not be read* | The manifest is malformed. |
| *needs plugin API version N* | `familiar.apiVersion` does not match this app. |
| *is a browser plugin* | `type` is not `visualizer`. |
| *is a built-in visualizer* | The `id` collides with one of the four compiled in. |
| *registered no visualizer with the id* | The bundle ran but the id it registered differs from the manifest's. |
| *Could not read `main`* | The path is wrong, or the bundle was never built. |
| *threw while loading* | The bundle raised at evaluation. |

A folder with **no `familiar-plugin.json` at all** is ignored silently — that directory collects
`.DS_Store` and half-unzipped archives, and complaining about each would bury the reasons above.

A plugin that crashes while *rendering* falls back to the album art and is marked **failed**; it
cannot take the visualizer down with it.

---

## Contributing

1. Fork the repository
2. Create your visualizer in `visualizers/community/`
3. Copy `_template/ExampleVisualizer.tsx` as a starting point
4. Test with various music (different genres, with/without lyrics)
5. Submit a PR with a screenshot or GIF

See the [template README](../frontend/src/components/Visualizer/visualizers/_template/README.md) for detailed instructions.

For a plugin you do not want to upstream, see **Drop-In Plugins** above — it needs no PR at all.
