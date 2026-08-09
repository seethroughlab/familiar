import { useSyncExternalStore } from 'react';
import { AudioVisualizer } from '../Visualizer/AudioVisualizer';
import { getVisualizerState, subscribeToVisualizerState } from '../../services/visualizerSink';
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

  const track: Track | null = state.track
    ? ({
        id: state.track.id,
        title: state.track.title ?? 'Unknown',
        artist: state.track.artist ?? 'Unknown artist',
        album: state.track.album ?? '',
      } as Track)
    : null;

  return (
    <AudioVisualizer
      track={track}
      artworkUrl={state.track ? tracksApi.getArtworkUrl(state.track.id) : null}
      isPlaying={state.playing}
      currentTime={state.position}
      className="absolute inset-0"
    />
  );
}
