/**
 * Choose a visualizer to suit the playing track (ADR-0064 points 5, 7 and 8).
 *
 * Returns the id auto-select settled on, or `null` when it has no opinion — the caller keeps the
 * listener's manual choice in that case, which is every case where this is switched off.
 *
 * **The choice is made when a track starts and holds for that track.** The request is keyed on the
 * track id, so nothing can switch mid-song: a three.js scene tearing down halfway through is more
 * disruptive than an imperfect match is dull. `section_count` and `form_string` would make
 * within-track switching tempting and it is deliberately not done.
 *
 * **Hysteresis, so a run of similar tracks does not flicker.** Once something is chosen it stays
 * unless another candidate beats it by `SWITCH_MARGIN`. Without that, two visualizers scoring 0.61
 * and 0.60 would alternate track by track on an album that suits both, which reads as a bug rather
 * than a choice.
 *
 * **Every failure keeps what is showing.** An unanalysed track, an offline server, an empty
 * ranking: all leave the current visualizer alone. Picking arbitrarily would be worse than not
 * picking, and on a library mid-sync unanalysed tracks are a meaningful fraction.
 */
import { useEffect, useRef, useState } from 'react';
import { tracksApi } from '../api';
import { getVisualizers } from '../components/Visualizer/types';
import { useVisualizerStore } from '../stores/visualizerStore';
import { useVisualizerAutoSelectStore } from '../stores/visualizerAutoSelectStore';

/** How much better a rival must be before the visualizer changes. */
export const SWITCH_MARGIN = 0.1;

/**
 * The visualizer actually drawing — auto-select's choice when it has one, the listener's otherwise.
 *
 * **One definition, because there is more than one consumer.** Auto-select introduces a second
 * possible answer to "which visualizer is on", and anything still reading `visualizerId` directly
 * gets the wrong one: `FullPlayer` gates its whole layout on whether Music Video is playing, and
 * would have laid album art over a video the moment auto-select chose it. Re-deriving this at each
 * call site is how those two answers come apart.
 *
 * Reads state only — it never triggers a ranking. `useAutoSelectedVisualizer` is what asks, and it
 * is called once, by `AudioVisualizer`.
 */
export function useActiveVisualizerId(): string {
  const visualizerId = useVisualizerStore((s) => s.visualizerId);
  const autoSelect = useVisualizerStore((s) => s.autoSelect);
  const chosenId = useVisualizerAutoSelectStore((s) => s.chosenId);
  return (autoSelect && chosenId) || visualizerId;
}

export function useAutoSelectedVisualizer(trackId: string | null | undefined): string | null {
  const autoSelect = useVisualizerStore((s) => s.autoSelect);

  const [chosenId, setChosenId] = useState<string | null>(null);
  // Read inside the effect without making it a dependency — depending on the chosen id would
  // re-run the request each time it changed and could settle into a loop.
  const chosenRef = useRef<string | null>(null);

  useEffect(() => {
    if (!autoSelect || !trackId) return;

    let ignore = false;
    // Read the action off the store rather than subscribing to it. A store action in the
    // dependency array is one identity change away from re-requesting on every render — and
    // this effect's whole contract is that it fires once per track.
    const { recordChoice } = useVisualizerAutoSelectStore.getState();

    const candidates = getVisualizers().map(({ metadata }) => ({
      id: metadata.id,
      affinity: metadata.affinity,
    }));
    if (candidates.length === 0) return;

    tracksApi
      .rankVisualizers(trackId, candidates)
      .then((response) => {
        if (ignore) return;

        const ignoredByVisualizer: Record<string, string[]> = {};
        for (const entry of response.visualizers) {
          if (entry.ignored.length > 0) ignoredByVisualizer[entry.id] = entry.ignored;
        }

        if (!response.ranked || response.visualizers.length === 0) {
          // Nothing to rank against. Report it — the picker says so rather than leaving
          // auto-select looking inert — but do not disturb the visualizer in force.
          recordChoice({ trackId, chosenId: null, unranked: true, ignoredByVisualizer });
          return;
        }

        const best = response.visualizers[0];
        const current = chosenRef.current;
        const currentScore = current
          ? response.visualizers.find((v) => v.id === current)?.score
          : undefined;

        // Nothing chosen yet, or the incumbent is no longer offered (a plugin removed between
        // tracks): take the best. Otherwise it has to clear the margin.
        const shouldSwitch =
          current === null || currentScore === undefined || best.score > currentScore + SWITCH_MARGIN;

        const settled = shouldSwitch ? best.id : current;
        chosenRef.current = settled;
        setChosenId(settled);
        recordChoice({ trackId, chosenId: settled, unranked: false, ignoredByVisualizer });
      })
      .catch(() => {
        // Offline, or the server does not know this track. Keep what is showing.
      });

    return () => {
      ignore = true;
    };
  }, [trackId, autoSelect]);

  return autoSelect ? chosenId : null;
}
