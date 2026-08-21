/**
 * Beat Tiles as a document (ADR-0087, ADR-0088).
 *
 * The same scene that used to be a registered React component in the host page. What changed is
 * everything around it: this file makes its own React root, brings its own three.js and
 * `@react-three/fiber`, and gets playback from the three events the host posts in.
 */
import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import BeatTiles from './BeatTiles';
import { announceReady, usePlaybackState, useTrack } from './familiar';

function App() {
  const track = useTrack();
  const { isPlaying, currentTime } = usePlaybackState();
  const [mounted, setMounted] = useState(false);

  // Ready last, once this document is listening — otherwise the host posts the first track into
  // a page with no handler and the scene never learns what is playing.
  useEffect(() => {
    if (mounted) return;
    setMounted(true);
    announceReady();
  }, [mounted]);

  return (
    <BeatTiles
      track={track ? { id: track.id ?? '', title: track.title, artist: track.artist } : null}
      artworkUrl={track?.artworkUrl ?? null}
      features={track?.features ?? null}
      lyrics={null}
      currentTime={currentTime}
      duration={track?.duration ?? 0}
      isPlaying={isPlaying}
    />
  );
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
