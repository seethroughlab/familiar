/**
 * Scrolling Lyrics — Apple-Music-style synced lyric column.
 *
 * The full lyric sheet scrolls vertically: the current line is centered, large
 * and bright; already-sung lines fade away above; several upcoming lines sit
 * dimmed below so you can read ahead. The readable text stays calm — no
 * per-word highlight, no continuous pulse — but each line plays a one-shot
 * entrance as it becomes current.
 *
 * Visual interest lives behind the text: a base palette "aurora" wash, a
 * drifting 3D field of the song's own words (LyricWordField), and a subtle
 * spectrum accent under the current line. The lyric text itself is crisp DOM
 * rendered on top of the WebGL field.
 *
 * Falls back to the track title/artist when a song has no synced lyrics.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { type VisualizerProps } from './types';
import { useAudioAnalyser, getAudioData } from './familiar';
import { useArtworkPalette } from './useArtworkPalette';
import { useLyricTiming } from './useLyricTiming';
import { sampleVisualizerBinValue } from './analysisMetrics';
import { LyricWordField } from './LyricWordField';

/** A small, soft spectrum accent that sits just under the centered line. */
function SpectrumAccent({ color }: { color: string }) {
  const BARS = 7;
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const fd = getAudioData()?.frequencyData;
      for (let i = 0; i < BARS; i++) {
        const el = refs.current[i];
        if (!el) continue;
        const v = fd ? sampleVisualizerBinValue(fd, i, BARS) : 0;
        el.style.transform = `scaleY(${(0.16 + v).toFixed(3)})`;
        el.style.opacity = (0.2 + v * 0.5).toFixed(3);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  return (
    <div className="absolute left-0 right-0 flex items-end justify-center gap-1.5 pointer-events-none" style={{ top: '58%', height: 26 }}>
      {Array.from({ length: BARS }).map((_, i) => (
        <div
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          style={{ width: 5, height: 24, borderRadius: 3, background: color, transformOrigin: 'bottom', transform: 'scaleY(0.16)', opacity: 0.2, filter: `drop-shadow(0 0 5px ${color})`, transition: 'transform 90ms linear, opacity 90ms linear' }}
        />
      ))}
    </div>
  );
}

export function ScrollingLyrics({ lyrics, currentTime, track, artworkUrl }: VisualizerProps) {
  const palette = useArtworkPalette(artworkUrl);
  useAudioAnalyser(true);

  const { currentIndex, hasLyrics } = useLyricTiming(lyrics, currentTime);

  const viewportRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);
  const auroraRef = useRef<HTMLDivElement>(null);
  const [translateY, setTranslateY] = useState(0);
  const [resizeTick, setResizeTick] = useState(0);

  const accent = palette[0] ?? '#a855f7';
  // The line we center on. Before the first lyric (currentIndex === -1) we
  // settle on line 0 so the opening lines sit ready in view.
  const centerIdx = Math.max(0, currentIndex);

  // Keep the centered line vertically centered in the viewport. Measured from
  // layout (transforms/opacity don't affect it) so the math stays stable.
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const active = activeRef.current;
    if (!viewport || !active) return;
    const center = active.offsetTop + active.offsetHeight / 2;
    setTranslateY(viewport.clientHeight / 2 - center);
  }, [centerIdx, hasLyrics, resizeTick, lyrics]);

  // Recompute centering on viewport resize / orientation change.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setResizeTick((t) => t + 1));
    ro.observe(viewport);
    return () => ro.disconnect();
  }, []);

  // Subtle bass shimmer — background only, so the text never moves.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const el = auroraRef.current;
      if (el) {
        const bass = getAudioData()?.bass ?? 0;
        el.style.opacity = (0.55 + bass * 0.4).toFixed(3);
        el.style.transform = `scale(${(1 + bass * 0.06).toFixed(3)})`;
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const c0 = palette[0] ?? '#7c3aed';
  const c1 = palette[1] ?? '#2563eb';
  const c2 = palette[2] ?? '#db2777';
  const c3 = palette[3] ?? '#1a0b2e';

  return (
    <div className="w-full h-full relative overflow-hidden" style={{ background: '#050308' }}>
      <style>{`
        @keyframes auroraDriftA{0%{transform:translate(-8%,-6%) scale(1)}50%{transform:translate(10%,8%) scale(1.18)}100%{transform:translate(-8%,-6%) scale(1)}}
        @keyframes auroraDriftB{0%{transform:translate(12%,10%) scale(1.1)}50%{transform:translate(-10%,-8%) scale(1)}100%{transform:translate(12%,10%) scale(1.1)}}
        @keyframes auroraDriftC{0%{transform:translate(-6%,12%) scale(1.05)}50%{transform:translate(8%,-10%) scale(1.2)}100%{transform:translate(-6%,12%) scale(1.05)}}
        @keyframes lineEnter{from{opacity:0;transform:translateY(26px);filter:blur(10px)}to{opacity:1;transform:translateY(0);filter:blur(0)}}
      `}</style>

      {/* Drifting aurora background (palette-driven, blurred, behind everything). */}
      <div ref={auroraRef} className="absolute inset-0" style={{ willChange: 'opacity, transform' }}>
        <div className="absolute rounded-full" style={{ width: '70%', height: '70%', top: '-10%', left: '-10%', background: `radial-gradient(circle, ${c0}, transparent 68%)`, filter: 'blur(70px)', animation: 'auroraDriftA 26s ease-in-out infinite' }} />
        <div className="absolute rounded-full" style={{ width: '75%', height: '75%', bottom: '-15%', right: '-12%', background: `radial-gradient(circle, ${c1}, transparent 68%)`, filter: 'blur(80px)', animation: 'auroraDriftB 32s ease-in-out infinite' }} />
        <div className="absolute rounded-full" style={{ width: '60%', height: '60%', top: '25%', left: '30%', background: `radial-gradient(circle, ${c2}, transparent 70%)`, filter: 'blur(90px)', animation: 'auroraDriftC 38s ease-in-out infinite' }} />
      </div>

      {/* Drifting 3D field of the song's own words (WebGL), over the glow. */}
      <div className="absolute inset-0 pointer-events-none">
        <LyricWordField lyrics={lyrics} track={track} artworkUrl={artworkUrl} />
      </div>

      {/* Darkening + vignette so the lyrics stay legible over glow + words. */}
      <div className="absolute inset-0" style={{ background: `radial-gradient(circle at 50% 45%, transparent 30%, ${c3}99 80%, #050308 100%)` }} />

      {hasLyrics && lyrics ? (
        <div ref={viewportRef} className="absolute inset-0 overflow-hidden px-8">
          <div
            ref={listRef}
            className="absolute left-0 right-0 flex flex-col items-center text-center"
            style={{ transform: `translateY(${translateY}px)`, transition: 'transform 700ms cubic-bezier(0.22,0.61,0.36,1)' }}
          >
            {lyrics.map((line, i) => {
              const dist = Math.abs(i - centerIdx);
              const isPast = i < currentIndex;
              const isCurrent = i === currentIndex;
              // Opacity falls off with distance; sung lines sit a touch dimmer.
              const base = dist === 0 ? 1 : dist === 1 ? 0.5 : dist === 2 ? 0.34 : dist === 3 ? 0.2 : 0.1;
              const opacity = isPast ? base * 0.7 : base;
              return (
                <div
                  key={i}
                  ref={i === centerIdx ? activeRef : undefined}
                  className="max-w-4xl"
                  style={{
                    padding: '0.42em 0',
                    fontSize: 'clamp(1.45rem, 4vw, 2.9rem)',
                    fontWeight: isCurrent ? 800 : 600,
                    lineHeight: 1.12,
                    color: '#ffffff',
                    opacity,
                    transform: isCurrent ? 'scale(1.18)' : 'scale(1)',
                    transformOrigin: 'center',
                    filter: dist >= 3 ? 'blur(1.5px)' : 'none',
                    textShadow: isCurrent ? `0 0 28px ${accent}aa` : 'none',
                    transition: 'opacity 500ms ease, transform 500ms cubic-bezier(0.22,0.61,0.36,1), text-shadow 500ms ease',
                    willChange: 'opacity, transform',
                  }}
                >
                  {/* Inner span replays a one-shot entrance each time this line
                      becomes current (its key flips), without re-triggering on
                      every scroll. Not a continuous pulse. */}
                  <span
                    key={isCurrent ? `cur-${i}` : 'idle'}
                    style={{
                      display: 'inline-block',
                      animation: isCurrent ? 'lineEnter 600ms cubic-bezier(0.22,0.61,0.36,1) both' : undefined,
                    }}
                  >
                    {line.text || '♪'}
                  </span>
                </div>
              );
            })}
          </div>
          <SpectrumAccent color={accent} />
        </div>
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-8">
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

export default ScrollingLyrics;
