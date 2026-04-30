/**
 * Global watcher: observes the shared /mixtapes list query and toasts on
 * terminal-state transitions. Mounted once in App so it survives across
 * route changes (but not full reloads — see snapshot logic below).
 *
 * Strategy:
 *   - On first mount, snapshot which mixtape IDs are currently in-flight.
 *   - On each subsequent update from the list query, watch those IDs (plus
 *     any new in-flight rows that appear) for transitions to ready/failed.
 *   - Once we see the transition, fire a sticky toast with a one-click
 *     Download action and remove the ID from the watch set.
 *
 * Renders nothing.
 */
import { useEffect, useRef } from 'react';
import { mixtapesApi, type MixTape } from '../../api';
import { showSuccess, showError } from '../../stores/toastStore';
import { useMixtapesList } from '../../hooks/useMixtapes';

function isInFlight(mt: MixTape): boolean {
  return mt.status === 'pending' || mt.status === 'rendering';
}

export function MixTapeProgressWatcher() {
  const { data } = useMixtapesList();
  // IDs we're currently watching for terminal transitions.
  const watching = useRef<Set<string>>(new Set());
  // IDs we've already toasted on, so we don't double-fire.
  const announced = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!data) return;

    // Snapshot any newly-seen in-flight rows; on first poll this catches
    // anything that survived a page reload.
    for (const mt of data) {
      if (isInFlight(mt) && !announced.current.has(mt.id)) {
        watching.current.add(mt.id);
      }
    }

    // Look for transitions on rows we're watching.
    for (const mt of data) {
      if (!watching.current.has(mt.id)) continue;
      if (announced.current.has(mt.id)) continue;
      if (isInFlight(mt)) continue;

      announced.current.add(mt.id);
      watching.current.delete(mt.id);

      if (mt.status === 'ready') {
        showSuccess(`"${mt.name}" is ready`, {
          duration: Infinity,
          action: {
            label: 'Download',
            onClick: () => {
              mixtapesApi.download(mt.id, mt.name).catch(() => {
                showError('Failed to download mix tape');
              });
            },
          },
        });
      } else if (mt.status === 'failed') {
        showError(
          `Mix tape "${mt.name}" failed: ${mt.error_message || 'unknown error'}`,
          { duration: Infinity },
        );
      }
    }
  }, [data]);

  return null;
}
