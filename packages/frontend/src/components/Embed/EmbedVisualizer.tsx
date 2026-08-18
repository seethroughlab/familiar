import { useSyncExternalStore } from 'react';
import { AudioVisualizer } from '../Visualizer/AudioVisualizer';
import { getVisualizerState, subscribeToVisualizerState } from '../../services/visualizerSink';
import { useTrackDetail } from '../../hooks/useTrackDetail';
import { tracksApi } from '../../api/tracks';
import type { Track } from '../../types';

/**
 * The visualizer, drawing what the native app sends it (ADR-0033).
 *
 * **This surface only receives.** The Discover surface posts intents and is never told what is
 * playing; this is the mirror image — it has no buttons, makes no requests of the app, and its
 * entire input is the frames arriving on the sink.
 *
 * The sink itself is installed at module load rather than here (see `visualizerSink`). This
 * component subscribes to the small amount of metadata React needs; the spectrum never passes
 * through React at all, it goes straight into the analysis buffers that `getAudioData()` reads. So
 * all four visualizers run unmodified, which is most of what embedding is being bought for.
 */
export function EmbedVisualizer() {
  const state = useSyncExternalStore(subscribeToVisualizerState, getVisualizerState);

  // The frame carries four identity fields and no analysis — deliberately, since a channel that
  // carries everything has no shape (ADR-0033). Artwork and lyrics are already fetched by the page
  // rather than pushed, so the analysis is fetched the same way (ADR-0064 point 9).
  const detail = useTrackDetail(state.track?.id ?? null);

  // Until that resolves — and if it never does, because the page is offline — fall back to the
  // frame's own fields. Partial, and cast as such; it is what this surface has always drawn with.
  const fallback: Track | null = state.track
    ? ({
        id: state.track.id,
        title: state.track.title ?? 'Unknown',
        artist: state.track.artist ?? 'Unknown artist',
        album: state.track.album ?? '',
      } as Track)
    : null;

  const track = detail ?? fallback;

  return (
    <AudioVisualizer
      track={track}
      features={detail?.features ?? null}
      artworkUrl={state.track ? tracksApi.getArtworkUrl(state.track.id) : null}
      isPlaying={state.playing}
      currentTime={state.position}
      className="absolute inset-0"
    />
  );
}
