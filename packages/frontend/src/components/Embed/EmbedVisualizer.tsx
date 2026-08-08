import { useEffect, useState } from 'react';
import { AudioVisualizer } from '../Visualizer/AudioVisualizer';
import { setNativeAnalysisBuffers, clearNativeAnalysisBuffers } from '../../player/audio/nativeAnalysisBuffers';
import { tracksApi } from '../../api/tracks';
import type { Track } from '../../types';

/**
 * One frame of analysis, as the native host sends it.
 *
 * Mirrors `VisualizerFrame` in `FamiliarKit`. **Nothing checks these two against each other** —
 * they are in different repositories and different languages, which is the seam ADR-0016 called
 * embedding's main risk. Both sides are pinned by tests to the same written shape; that is the only
 * thing keeping them in step, so a change here is a change there.
 */
interface AnalysisFrame {
  /** base64 of the per-bin spectrum, 0-255. */
  frequency: string;
  /** base64 of the waveform, 0-255 centred on 128. */
  timeDomain: string;
  /** Onset strength per analysis window, oldest first. See `nativeAnalysisBuffers`. */
  flux: number[];
  /** Seconds between `flux` values. */
  fluxInterval: number;
  /** The host's *measured* frame rate. Not assumed — the assumed figure was wrong by 6x. */
  cadenceHz: number;
  playing: boolean;
  position: number;
  track?: { id: string; title?: string; artist?: string; album?: string };
}

function decodeBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/**
 * The visualizer, drawing what the native app sends it (ADR-0033).
 *
 * **This surface only receives.** The Discover surface posts intents and is never told what is
 * playing; this is the mirror image — it has no buttons, makes no requests of the app, and its
 * entire input is the frames arriving on `window.__familiarAnalysis`.
 *
 * The buffers go to the same `nativeAnalysisBuffers` seam the iOS Capacitor engine was built
 * against, so `getAudioData()` keeps its signature and all four visualizers run unmodified. That is
 * most of what embedding is being bought for: someone writes Three.js against
 * `docs/VISUALIZER_API.md` and it runs on the Mac without touching Swift.
 */
export function EmbedVisualizer() {
  const [track, setTrack] = useState<Track | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [artworkUrl, setArtworkUrl] = useState<string | null>(null);

  useEffect(() => {
    // Reused across frames so a channel running for the length of an album does not allocate two
    // arrays ten times a second. The visualizers copy out of these on their own tick.
    let frequency: Uint8Array | null = null;
    let timeDomain: Uint8Array | null = null;
    let flux: Float32Array | null = null;
    let lastTrackId: string | null = null;

    const sink = (frame: AnalysisFrame) => {
      const freqBytes = decodeBytes(frame.frequency);
      const timeBytes = decodeBytes(frame.timeDomain);

      if (!frequency || frequency.length !== freqBytes.length) {
        frequency = new Uint8Array(freqBytes.length);
        timeDomain = new Uint8Array(timeBytes.length);
      }
      frequency.set(freqBytes);
      timeDomain!.set(timeBytes);

      if (!flux || flux.length !== frame.flux.length) flux = new Float32Array(frame.flux.length);
      flux.set(frame.flux);

      setNativeAnalysisBuffers(frequency, timeDomain!, flux, frame.fluxInterval);

      // **React state only when it changes**, not per frame. These drive re-renders, and this runs
      // ten times a second for as long as music plays — setting them unconditionally would re-render
      // the whole visualizer tree at the channel's rate, which is the mistake ADR-0041 had to undo
      // one layer down on the native side.
      setIsPlaying((was) => (was === frame.playing ? was : frame.playing));
      setCurrentTime((was) => (Math.abs(was - frame.position) < 0.2 ? was : frame.position));

      const id = frame.track?.id ?? null;
      if (id !== lastTrackId) {
        lastTrackId = id;
        if (frame.track) {
          setTrack({
            id: frame.track.id,
            title: frame.track.title ?? 'Unknown',
            artist: frame.track.artist ?? 'Unknown artist',
            album: frame.track.album ?? '',
          } as Track);
          setArtworkUrl(tracksApi.getArtworkUrl(frame.track.id));
        } else {
          setTrack(null);
          setArtworkUrl(null);
        }
      }
    };

    // The name the native side calls. Installed before anything else so a frame arriving during
    // boot lands rather than being dropped — the host optional-chains this call, so an early frame
    // is a silent no-op and the next one is 100ms away, but there is no reason to miss any.
    (window as unknown as Record<string, unknown>).__familiarAnalysis = sink;

    return () => {
      delete (window as unknown as Record<string, unknown>).__familiarAnalysis;
      clearNativeAnalysisBuffers();
    };
  }, []);

  return (
    <AudioVisualizer
      track={track}
      artworkUrl={artworkUrl}
      isPlaying={isPlaying}
      currentTime={currentTime}
      className="absolute inset-0"
    />
  );
}
