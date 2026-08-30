/**
 * The visualizer pipeline's vital signs, drawn over the plugin.
 *
 * **In the host page, not the plugin.** A document has an opaque origin and the host cannot reach
 * into it, so this cannot be injected the way a devtools overlay would be — it sits on top of the
 * iframe instead. The one number that has to come *from* the plugin is its frame rate, which it
 * volunteers; everything else the host already knows.
 *
 * Deliberately unstyled beyond legibility, and `pointer-events-none` so it never intercepts a
 * click meant for the visualizer.
 */
import { useSyncExternalStore } from 'react';
import { getMetrics, subscribeToMetrics } from './visualizerMetrics';

/** What each row means when it goes wrong, so the panel diagnoses rather than just reports. */
function verdict(m: ReturnType<typeof getMetrics>): { text: string; tone: string } {
  if (m.analysisAgeMs > 2000) {
    return { text: 'no analysis from the player — nothing is driving the scene', tone: 'text-danger' };
  }
  if (m.analysisFps > 0 && m.analysisFps < 6) {
    return { text: 'analysis arriving slowly; motion will look stepped', tone: 'text-warning' };
  }
  if (m.pluginFps !== null && m.pluginFps < 30) {
    return { text: 'the plugin itself is slow — its scene, not the pipeline', tone: 'text-warning' };
  }
  if (m.hostFps > 0 && m.hostFps < 45) {
    return { text: 'the host loop is slow; a debug build does this', tone: 'text-warning' };
  }
  return { text: 'healthy', tone: 'text-emerald-400' };
}

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex justify-between gap-6">
      <span className="text-white/50">{label}</span>
      <span className="tabular-nums">
        {value}
        {hint && <span className="text-white/30"> {hint}</span>}
      </span>
    </div>
  );
}

export function VisualizerDebugPanel() {
  const m = useSyncExternalStore(subscribeToMetrics, getMetrics);
  const v = verdict(m);

  return (
    <div
      className="absolute top-3 left-3 z-50 pointer-events-none select-none rounded-md
                 bg-black/70 px-3 py-2 font-mono text-[11px] leading-relaxed text-white/80
                 backdrop-blur-sm"
      // The visualizer surface renders inside a native window; a panel that could be dragged over
      // or clicked through would be worse than one that is simply inert.
      aria-hidden
    >
      <div className="mb-1 text-white/40">visualizer</div>
      <Row label="plugin" value={m.pluginFps === null ? '—' : String(m.pluginFps)} hint="fps" />
      <Row label="host loop" value={String(m.hostFps)} hint="fps" />
      <Row label="analysis in" value={String(m.analysisFps)} hint="/s ~10 expected" />
      <Row label="posted out" value={String(m.postedFps)} hint="/s" />
      <Row
        label="last frame"
        value={m.analysisAgeMs === Infinity ? 'never' : `${m.analysisAgeMs}ms ago`}
      />
      {m.last && (
        <Row
          label="values"
          value={`bass ${m.last.bass.toFixed(2)}  beat ${m.last.beat.toFixed(2)}${m.last.onset ? '  ONSET' : ''}`}
        />
      )}
      <div className={`mt-1 max-w-[22rem] ${v.tone}`}>{v.text}</div>
    </div>
  );
}
