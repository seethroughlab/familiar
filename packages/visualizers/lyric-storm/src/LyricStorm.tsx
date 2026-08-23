/**
 * Lyric Storm — the song's own words, drifting, and nothing else.
 *
 * **The word field has existed since the `LyricStorm` "WordParticles" effect, but only ever as a
 * layer.** `ScrollingLyrics` renders `LyricWordField` behind a synced DOM lyric column, an aurora
 * glow and a vignette dark enough to keep the column legible — which is right for a lyrics
 * visualizer and wrong for the field itself. Everything that makes the words readable also makes
 * them recede.
 *
 * This is the same scene with all of that removed: no column, no vignette, no darkening. The words
 * are the subject rather than the background, so they come forward and stay bright, and the effect
 * finally gets the name it was originally built under.
 *
 * It shares `LyricWordField` rather than copying it. A second implementation would drift from the
 * first, and the whole point is that this is the same field.
 */
import type { VisualizerProps } from './types';
import { LyricWordField } from './LyricWordField';

export function LyricStorm({ lyrics, track, artworkUrl }: VisualizerProps) {
  return (
    <div className="w-full h-full relative bg-[#050308]">
      {/*
        A backdrop, not a scrim. `ScrollingLyrics` puts a heavy radial vignette *over* the field so
        text stays readable on top of it; here there is nothing on top, so the field gets a plain
        dark ground and full contrast.
      */}
      <div className="absolute inset-0">
        <LyricWordField lyrics={lyrics} track={track} artworkUrl={artworkUrl} />
      </div>

      {/*
        **The empty state is a real state, not an edge case.** `LyricWordField` returns null when it
        has no words to float, which for a lyrics-driven visualizer is common: an instrumental, or
        any track whose lyrics have not been fetched. Inside `ScrollingLyrics` that is invisible
        because the aurora and the lyric column are still there. Here it would be a black rectangle
        with no explanation — the failure shape this codebase keeps producing — so it says what is
        happening instead.
      */}
      {!hasWords(lyrics, track) && (
        <div className="absolute inset-0 flex items-center justify-center px-8">
          <p className="text-zinc-500 text-sm text-center max-w-sm">
            Lyric Storm floats the song's own words. This track has no lyrics yet — try one with
            synced lyrics, or pick another visualizer.
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * Whether `LyricWordField` will find anything to float.
 *
 * **This has to match `useWordPool` or the message is a lie in both directions** — claiming no
 * lyrics over a working field, or a black rectangle with nothing said. So it applies the same three
 * steps: same source and same fallback to title and artist, same punctuation strip, same
 * "longer than one character" filter. A track called "4" has a title and still produces no words.
 *
 * Duplicated rather than shared because the alternative is exporting a hook and running the whole
 * pool construction — memoised arrays, `Set` dedupe — to answer a yes/no question. The coupling is
 * real, and is why it is spelled out here rather than approximated.
 */
function hasWords(lyrics: VisualizerProps['lyrics'], track: VisualizerProps['track']): boolean {
  const source =
    lyrics && lyrics.length > 0
      ? lyrics.map((l) => l.text).join(' ')
      : `${track?.title ?? ''} ${track?.artist ?? ''}`;

  return source
    .split(/\s+/)
    .some((word) => word.replace(/[^\p{L}\p{N}']/gu, '').length > 1);
}

export default LyricStorm;
