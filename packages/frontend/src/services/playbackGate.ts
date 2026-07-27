/**
 * Keeps bulk offline downloads from starving playback.
 *
 * A bulk download saturates the link. Measured on a real failure: a single 34.9 MB track
 * took 41s (~850 KB/s, the whole pipe), and a track that had started playing 15s earlier
 * died with `PIPELINE_ERROR_READ: FFmpegDemuxer: data source error` — the media element
 * had no bandwidth left to read with (issue #13).
 *
 * Downloads already run one at a time, so this is not connection-pool contention and
 * lowering concurrency would not help.
 *
 * **Why throttle rather than pause.** Measured across the library (26,446 tracks), a
 * track needs 33.8 KB/s sustained on average and 102.5 KB/s at p95 — 4% and 12% of that
 * 850 KB/s link. The failing track itself needed 40 KB/s. Stopping downloads outright
 * hands playback 100% of the link to do a job that needs a twentieth of it, and a large
 * offline backlog would then only advance while nobody is listening.
 *
 * **Why a duty cycle rather than a KB/s cap.** The link speed is unknown and varies —
 * Tailscale over WAN, LAN, tethered. A fixed 300 KB/s cap throttles nothing on a 200 KB/s
 * link. Pacing by time takes a roughly constant *fraction* of whatever is available, with
 * nothing to measure or configure: at 850 KB/s downloads get ~210 KB/s and leave ~640
 * free; at 200 KB/s they get ~50 and leave ~150, still above p95.
 *
 * Cycles are kept short so the player's buffer rides through each burst.
 */
import { usePlaybackStore } from '../player/playbackStore';

/** Transfer window, then idle window, while audio is playing. ~25% duty cycle. */
export const THROTTLE_BURST_MS = 200;
export const THROTTLE_IDLE_MS = 600;

export function isPlaybackActive(): boolean {
  return usePlaybackStore.getState().isPlaying;
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Paces a download loop against playback.
 *
 * Call once per chunk. Returns immediately when nothing is playing, so an idle device
 * downloads at full speed. While audio plays it lets `THROTTLE_BURST_MS` of transfer
 * through, then sleeps `THROTTLE_IDLE_MS`.
 *
 * One instance per download; state is per-transfer, not global.
 */
export class DownloadThrottle {
  private burstStartedAt = 0;

  /** True if the most recent call actually slept — for surfacing "throttled" in the UI. */
  public throttling = false;

  async pace(signal?: AbortSignal): Promise<void> {
    if (!isPlaybackActive()) {
      this.throttling = false;
      this.burstStartedAt = 0;
      return;
    }

    this.throttling = true;
    const now = Date.now();
    if (this.burstStartedAt === 0) {
      this.burstStartedAt = now;
      return;
    }
    if (now - this.burstStartedAt < THROTTLE_BURST_MS) return;

    await sleep(THROTTLE_IDLE_MS);
    // Re-check rather than assume: playback may have stopped during the sleep, in which
    // case the next burst should run unthrottled.
    if (signal?.aborted || !isPlaybackActive()) {
      this.throttling = false;
      this.burstStartedAt = 0;
      return;
    }
    this.burstStartedAt = Date.now();
  }
}
