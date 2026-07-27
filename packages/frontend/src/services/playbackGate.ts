/**
 * Lets background bulk transfers yield to active playback.
 *
 * A bulk offline download saturates the link. Measured on a real failure: a single
 * 34.9 MB track took 41s (~850 KB/s, the whole pipe), and a track that started playing
 * 15s earlier died with `PIPELINE_ERROR_READ: FFmpegDemuxer: data source error` — the
 * media element simply had no bandwidth left to read with (issue #13).
 *
 * Downloads already run one at a time, so this is not connection-pool contention and
 * lowering concurrency would not help. The only fix is to stop moving those bytes while
 * audio needs them.
 *
 * Note the check must also apply *inside* a transfer, not just between transfers: one
 * file occupies the link for the better part of a minute, which is far longer than a
 * track's buffer.
 */
import { usePlaybackStore } from '../player/playbackStore';
import { createLogger } from '../utils/logger';

const log = createLogger('PlaybackGate');

/**
 * How long playback must stay stopped before downloads resume.
 *
 * `isPlaying` dips briefly during ordinary transitions — track changes, seeks, engine
 * reloads. Resuming on the first `false` would restart a large transfer into the gap and
 * starve the very next track, so wait for the stop to look settled.
 */
export const RESUME_SETTLE_MS = 3000;

/** Thrown to abandon an in-flight download so playback gets the bandwidth back. */
export class DownloadPausedError extends Error {
  constructor(message = 'Download paused: playback is active') {
    super(message);
    this.name = 'DownloadPausedError';
  }
}

export function isPlaybackActive(): boolean {
  return usePlaybackStore.getState().isPlaying;
}

/**
 * Resolve once playback has been stopped for `RESUME_SETTLE_MS`.
 *
 * Returns immediately if nothing is playing. Rejects nothing — if `signal` aborts it
 * resolves so the caller can observe the abort through its own normal path.
 */
export function waitForPlaybackIdle(signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.resolve();
  if (!isPlaybackActive()) return Promise.resolve();

  log.info('Pausing downloads while playback is active');

  return new Promise<void>((resolve) => {
    let settleTimer: ReturnType<typeof setTimeout> | null = null;

    const finish = () => {
      if (settleTimer) clearTimeout(settleTimer);
      unsubscribe();
      signal?.removeEventListener('abort', onAbort);
      resolve();
    };

    const onAbort = () => finish();

    const evaluate = (playing: boolean) => {
      if (playing) {
        // Playback resumed before the settle window elapsed — start it over.
        if (settleTimer) {
          clearTimeout(settleTimer);
          settleTimer = null;
        }
        return;
      }
      if (settleTimer) return;
      settleTimer = setTimeout(() => {
        log.info('Playback idle, resuming downloads');
        finish();
      }, RESUME_SETTLE_MS);
    };

    const unsubscribe = usePlaybackStore.subscribe((state) => evaluate(state.isPlaying));

    signal?.addEventListener('abort', onAbort, { once: true });

    // The store may already be stopped by the time we subscribed.
    evaluate(isPlaybackActive());
  });
}
