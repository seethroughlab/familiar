/**
 * Lyrics as a document (ADR-0087, ADR-0088).
 *
 * The same scene that used to be a registered React component in the host page. It makes its own
 * React root, brings its own libraries, and gets playback from the three events the host posts in.
 */
import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ScrollingLyrics from './ScrollingLyrics';
import { announceReady, usePlaybackState, useTrack } from './familiar';

function App() {
  const track = useTrack();
  const { isPlaying, currentTime } = usePlaybackState();
  const [announced, setAnnounced] = useState(false);

  // Ready last, once this document is listening — otherwise the host posts the first track into
  // a page with no handler and the scene never learns what is playing.
  useEffect(() => {
    if (announced) return;
    setAnnounced(true);
    announceReady();
  }, [announced]);

  return (
    <ScrollingLyrics
      track={track ? { id: track.id ?? '', title: track.title, artist: track.artist } : null}
      artworkUrl={track?.artworkUrl ?? null}
      features={track?.features ?? null}
      lyrics={(track?.lyrics as never) ?? null}
      currentTime={currentTime}
      duration={track?.duration ?? 0}
      isPlaying={isPlaying}
    />
  );
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
