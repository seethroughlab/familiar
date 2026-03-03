# Creating a Visualizer

This guide explains how to create a custom visualizer for Familiar.

## Quick Start

1. Copy `ExampleVisualizer.tsx` to `visualizers/YourVisualizer.tsx`
2. Rename the component and update the registration at the bottom
3. Import it in `visualizers/index.ts`
4. Run `npm run dev` and test with music

## Available Data (VisualizerProps)

Your visualizer receives these props:

| Prop | Type | Description |
|------|------|-------------|
| `track` | `Track \| null` | Current track metadata (title, artist, album, year, genre) |
| `features` | `TrackFeatures \| null` | Audio analysis (BPM, key, energy, danceability, valence) |
| `artworkUrl` | `string \| null` | Album artwork URL |
| `lyrics` | `LyricLine[] \| null` | Time-synced lyrics array |
| `currentTime` | `number` | Playback position in seconds |
| `duration` | `number` | Track duration in seconds |
| `isPlaying` | `boolean` | Whether audio is currently playing |

### Track Metadata

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
  format: string | null;
}
```

### Audio Features

```typescript
interface TrackFeatures {
  bpm: number | null;           // Tempo in beats per minute
  key: string | null;           // Musical key (e.g., "Am", "C#")
  energy: number | null;        // 0-1, intensity/activity
  danceability: number | null;  // 0-1, suitability for dancing
  valence: number | null;       // 0-1, musical positiveness
  acousticness: number | null;  // 0-1, acoustic vs electronic
  instrumentalness: number | null; // 0-1, vocals vs instrumental
  speechiness: number | null;   // 0-1, spoken words presence
}
```

## Utility Hooks

Import from `../hooks`:

### useAudioAnalyser()

Real-time audio frequency data. Essential for reactive visualizations.

```typescript
import { useAudioAnalyser, getAudioData } from '../hooks';

function MyVisualizer() {
  const audioData = useAudioAnalyser(true);
  // audioData.bass: 0-1, low frequency intensity
  // audioData.mid: 0-1, mid frequency intensity
  // audioData.treble: 0-1, high frequency intensity
  // audioData.frequencyData: Uint8Array of all frequency bins
  // audioData.timeDomainData: Uint8Array waveform data
}

// For Three.js useFrame (doesn't trigger re-renders):
useFrame(() => {
  const audioData = getAudioData();
  if (audioData) {
    mesh.scale.y = 1 + audioData.bass;
  }
});
```

### useArtworkPalette(artworkUrl)

Extract dominant colors from album artwork.

```typescript
import { useArtworkPalette } from '../hooks';

function MyVisualizer({ artworkUrl }: VisualizerProps) {
  const palette = useArtworkPalette(artworkUrl);
  // palette = ['#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff']
}
```

### useBeatSync(bpm, currentTime)

Synchronize animations with the detected BPM.

```typescript
import { useBeatSync } from '../hooks';

function MyVisualizer({ features, currentTime }: VisualizerProps) {
  const { beat, beatProgress, onBeat, bpm } = useBeatSync(features?.bpm, currentTime);

  // beat: current beat number (0, 1, 2, ...)
  // beatProgress: 0-1 progress through current beat
  // onBeat: true when a new beat just started
  // bpm: actual BPM being used

  // Example: pulse on beat
  const scale = onBeat ? 1.2 : 1 + beatProgress * 0.1;
}
```

### useLyricTiming(lyrics, currentTime)

Get current and upcoming lyric lines.

```typescript
import { useLyricTiming } from '../hooks';

function MyVisualizer({ lyrics, currentTime }: VisualizerProps) {
  const { currentLine, nextLine, progress, words } = useLyricTiming(lyrics, currentTime);

  // currentLine: { text: "Hello world", start_time: 10.5 }
  // nextLine: next upcoming line
  // progress: 0-1 through current line
  // words: ["Hello", "world"] for per-word animations
}
```

## Rendering Approaches

### Three.js (3D)

Best for: particle systems, 3D shapes, complex animations

```typescript
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

function Scene() {
  useAudioAnalyser(true);

  useFrame(() => {
    const audioData = getAudioData();
    // Animate based on audio
  });

  return <mesh>...</mesh>;
}

export function MyVisualizer(props: VisualizerProps) {
  return (
    <Canvas camera={{ position: [0, 0, 5] }}>
      <Scene />
    </Canvas>
  );
}
```

See: `CosmicOrb.tsx`, `FrequencyBars.tsx`, `AlbumKaleidoscope.tsx`

### Canvas 2D

Best for: custom drawing, text effects, pixel manipulation

```typescript
import { useRef, useEffect } from 'react';

export function MyVisualizer({ currentTime }: VisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const audioData = useAudioAnalyser(true);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!ctx) return;

    // Draw here
    ctx.fillStyle = `hsl(${audioData?.bass * 360}, 70%, 50%)`;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }, [audioData]);

  return <canvas ref={canvasRef} className="w-full h-full" />;
}
```

See: `TypographyWave.tsx`

### HTML/CSS

Best for: text-heavy, simple animations, accessibility

```typescript
export function MyVisualizer({ track, lyrics }: VisualizerProps) {
  const audioData = useAudioAnalyser(true);

  return (
    <div
      className="flex items-center justify-center h-full"
      style={{ transform: `scale(${1 + (audioData?.bass ?? 0) * 0.1})` }}
    >
      <h1 className="text-4xl">{track?.title}</h1>
    </div>
  );
}
```

See: `LyricPulse.tsx`

## Registration

Register your visualizer at the bottom of your file:

```typescript
import { registerVisualizer, type VisualizerProps } from '../types';

// ... your component ...

registerVisualizer(
  {
    id: 'my-visualizer',           // Unique ID (kebab-case)
    name: 'My Visualizer',         // Display name
    description: 'A cool effect',  // Short description
    usesMetadata: true,            // Set true if using track/artwork/lyrics
    author: 'Your Name',           // Optional: for community visualizers
  },
  MyVisualizer
);
```

## Guidelines

1. **Handle null props** - Track, features, artwork, and lyrics may be null
2. **Clean up resources** - Return cleanup function from useEffect
3. **Use requestAnimationFrame** - For smooth animations outside Three.js
4. **Keep files small** - Target under 50KB per visualizer
5. **No external APIs** - Use only provided data
6. **Test with various tracks** - Different genres, with/without lyrics

## Performance Tips

- Use `useMemo` for expensive calculations and geometry
- In Three.js, update uniforms instead of recreating materials
- Limit particle counts based on device capability
- Use `getAudioData()` in `useFrame` to avoid re-renders
- Consider using `prefers-reduced-motion` media query

## Submitting to Community

1. Fork the repository
2. Create your visualizer in `visualizers/community/`
3. Test thoroughly with various music
4. Create a PR with a screenshot or GIF
5. Follow code review feedback

## Examples

- **Audio-reactive**: `CosmicOrb.tsx` - GPU particles respond to bass/treble
- **Artwork-based**: `AlbumKaleidoscope.tsx` - Kaleidoscope from album art
- **Lyric-focused**: `LyricStorm.tsx` - 3D floating lyrics
- **Spectrum**: `FrequencyBars.tsx` - Classic frequency bars
- **Color flow**: `ColorFlow.tsx` - Colors extracted from artwork
