/**
 * Kinetic Lyrics — bold beat-synced typography (rebuild of the old LyricStorm).
 *
 * The current line is huge and centered with per-word karaoke highlighting; it
 * animates in on each line change and pulses subtly on the beat. The next line
 * is ghosted below. Crisp DOM text (no WebGL) keeps it sharp and cheap. Falls
 * back to the track title/artist when a song has no synced lyrics.
 */
import { useEffect, useRef } from 'react';
import { type VisualizerProps } from '../types';
import { useAudioAnalyser, getAudioData, useArtworkPalette, useLyricTiming, getWordTiming } from '../hooks';

export function KineticLyrics({ lyrics, currentTime, track, artworkUrl }: VisualizerProps) {
  const palette = useArtworkPalette(artworkUrl);
  useAudioAnalyser(true);

  const { currentLine, nextLine, currentIndex, hasLyrics } = useLyricTiming(lyrics, currentTime);
  const wordTiming = getWordTiming(currentLine, nextLine?.time ?? null, currentTime);

  const lineRef = useRef<HTMLDivElement>(null);
  const accent = palette[0] ?? '#a855f7';

  // Beat pulse via a rAF loop (mutates the DOM directly — no React re-renders).
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const beat = getAudioData()?.beat ?? 0;
      const el = lineRef.current;
      if (el) {
        el.style.transform = `scale(${(1 + beat * 0.13).toFixed(3)})`;
        el.style.textShadow = `0 0 ${Math.round(16 + beat * 70)}px ${accent}`;
        el.style.filter = `brightness(${(1 + beat * 0.5).toFixed(2)})`;
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [accent]);

  return (
    <div
      className="w-full h-full flex flex-col items-center justify-center relative overflow-hidden px-8"
      style={{ background: `radial-gradient(circle at 50% 38%, ${palette[3] ?? '#1a0b2e'}, #050308 72%)` }}
    >
      <style>{`@keyframes kineticIn{0%{opacity:0;transform:translateY(26px) scale(0.96)}100%{opacity:1;transform:translateY(0) scale(1)}}`}</style>

      {hasLyrics ? (
        <>
          <div
            key={currentIndex}
            ref={lineRef}
            className="text-center font-extrabold leading-tight max-w-5xl"
            style={{
              animation: 'kineticIn 400ms cubic-bezier(0.2,0.8,0.2,1)',
              fontSize: 'clamp(2rem, 6.5vw, 5.5rem)',
              willChange: 'transform',
            }}
          >
            {currentLine ? (
              wordTiming.length ? (
                wordTiming.map((w, i) => (
                  <span
                    key={i}
                    style={{
                      color: w.isActive ? accent : 'rgba(255,255,255,0.88)',
                      transition: 'color 150ms ease',
                      display: 'inline-block',
                      marginRight: '0.28em',
                    }}
                  >
                    {w.word}
                  </span>
                ))
              ) : (
                <span style={{ color: '#fff' }}>{currentLine.text}</span>
              )
            ) : (
              <span style={{ color: 'rgba(255,255,255,0.4)' }}>♪</span>
            )}
          </div>

          {nextLine && (
            <div
              className="text-center mt-10"
              style={{ fontSize: 'clamp(1rem, 2.6vw, 1.9rem)', color: 'rgba(255,255,255,0.32)' }}
            >
              {nextLine.text}
            </div>
          )}
        </>
      ) : (
        <div className="text-center">
          <div className="font-extrabold text-white" style={{ fontSize: 'clamp(2rem, 5vw, 4rem)' }}>
            {track?.title ?? 'Nothing playing'}
          </div>
          <div className="mt-3" style={{ color: accent, fontSize: 'clamp(1rem, 2vw, 1.5rem)' }}>
            {track?.artist ?? ''}
          </div>
          <div className="mt-6 text-white/30 text-sm">No synced lyrics for this track</div>
        </div>
      )}
    </div>
  );
}

export default KineticLyrics;
