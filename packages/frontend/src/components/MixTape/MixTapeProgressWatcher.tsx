/**
 * Global watcher: polls each tracked Mix Tape render every 2s and toasts
 * the user on terminal state transitions. Mounted once in AppShell.
 *
 * Renders nothing — just an effect coordinator.
 */
import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { mixtapesApi, type MixTape } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { showSuccess, showError } from '../../stores/toastStore';
import { useMixTapesStore } from '../../stores/mixtapesStore';

const POLL_MS = 2000;

export function MixTapeProgressWatcher() {
  const trackedIds = useMixTapesStore((s) => s.trackedIds);
  const remove = useMixTapesStore((s) => s.remove);
  const queryClient = useQueryClient();
  // Avoid double-toasting if a poll lands twice before the store updates.
  const handled = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (trackedIds.length === 0) return;

    let cancelled = false;

    const tick = async () => {
      const results = await Promise.allSettled(
        trackedIds.map((id) => mixtapesApi.get(id))
      );
      if (cancelled) return;

      for (const r of results) {
        if (r.status !== 'fulfilled') continue;
        const mt: MixTape = r.value;
        if (handled.current.has(mt.id)) continue;
        if (mt.status === 'ready') {
          handled.current.add(mt.id);
          remove(mt.id);
          queryClient.invalidateQueries({ queryKey: queryKeys.mixtapes.all });
          showSuccess(`"${mt.name}" is ready`, {
            description: 'Tap to download from the Mix Tapes page.',
          });
        } else if (mt.status === 'failed') {
          handled.current.add(mt.id);
          remove(mt.id);
          queryClient.invalidateQueries({ queryKey: queryKeys.mixtapes.all });
          showError(
            `Mix tape "${mt.name}" failed: ${mt.error_message || 'unknown error'}`
          );
        }
      }
    };

    const interval = setInterval(tick, POLL_MS);
    // Run an initial tick so a fast render doesn't wait the first 2s.
    tick();

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [trackedIds, remove, queryClient]);

  return null;
}
