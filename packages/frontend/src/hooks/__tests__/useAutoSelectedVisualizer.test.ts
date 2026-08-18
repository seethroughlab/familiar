/* @vitest-environment jsdom */
/**
 * ADR-0064 points 7 and 8: when auto-select changes the visualizer, and — mostly — when it does not.
 *
 * Nearly every case here is a *don't switch* case, which is the point. Picking arbitrarily is worse
 * than not picking, so the failure modes worth testing are the ones where something changed that
 * should not have.
 */
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  useAutoSelectedVisualizer,
  useActiveVisualizerId,
  SWITCH_MARGIN,
} from '../useAutoSelectedVisualizer';
import { tracksApi } from '../../api';
import { useVisualizerStore } from '../../stores/visualizerStore';
import { useVisualizerAutoSelectStore } from '../../stores/visualizerAutoSelectStore';
import { registerVisualizer, visualizerRegistry } from '../../components/Visualizer/types';
import type { VisualizerRankingResponse } from '../../api/tracks';

vi.mock('../../api', () => ({ tracksApi: { rankVisualizers: vi.fn() } }));

const rank = tracksApi.rankVisualizers as ReturnType<typeof vi.fn>;

function ranking(...pairs: [string, number][]): VisualizerRankingResponse {
  return {
    ranked: true,
    visualizers: pairs.map(([id, score]) => ({
      id,
      score,
      matched_tags: [],
      matched_ranges: [],
      unmatched_ranges: [],
      ignored: [],
    })),
  };
}

beforeEach(() => {
  rank.mockReset();
  visualizerRegistry.clear();
  for (const id of ['alpha', 'beta']) {
    registerVisualizer({ id, name: id, description: '', usesMetadata: false }, () => null);
  }
  useVisualizerStore.setState({ autoSelect: true });
  useVisualizerAutoSelectStore.getState().reset();
});

afterEach(() => {
  // **Explicit, because this package has no RTL auto-cleanup** — `AudioVisualizer.test.tsx` calls
  // it by hand for the same reason. Without it a hook from a finished test stays mounted, and the
  // next `beforeEach` flipping `autoSelect` back on re-fires *its* effect, which consumes the next
  // test's mocked response and makes the failure look like a bug in the hook.
  cleanup();
  useVisualizerStore.setState({ autoSelect: false });
  vi.clearAllMocks();
});

describe('useAutoSelectedVisualizer', () => {
  it('returns null and asks nothing while switched off', async () => {
    useVisualizerStore.setState({ autoSelect: false });
    const { result } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    expect(result.current).toBeNull();
    expect(rank).not.toHaveBeenCalled();
  });

  it('chooses the best-scoring visualizer for a track', async () => {
    rank.mockResolvedValueOnce(ranking(['beta', 0.9], ['alpha', 0.2]));
    const { result } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    await waitFor(() => expect(result.current).toBe('beta'));
  });

  it('sends the registered visualizers as candidates', async () => {
    rank.mockResolvedValueOnce(ranking(['alpha', 0.5]));
    renderHook(({ id }) => useAutoSelectedVisualizer(id), { initialProps: { id: 'T1' } });
    await waitFor(() => expect(rank).toHaveBeenCalled());
    const [trackId, candidates] = rank.mock.calls[0];
    expect(trackId).toBe('T1');
    expect(candidates.map((c: { id: string }) => c.id).sort()).toEqual(['alpha', 'beta']);
  });

  it('holds the choice for the length of a track', async () => {
    rank.mockResolvedValueOnce(ranking(['alpha', 0.9]));
    const { result, rerender } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    await waitFor(() => expect(result.current).toBe('alpha'));

    // A re-render that is not a track change must not re-ask — the choice is made at the boundary.
    rerender({ id: 'T1' });
    expect(rank).toHaveBeenCalledTimes(1);
  });
});

describe('hysteresis', () => {
  it('keeps the current visualizer when a rival wins by less than the margin', async () => {
    rank.mockResolvedValueOnce(ranking(['alpha', 0.6]));
    const { result, rerender } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    await waitFor(() => expect(result.current).toBe('alpha'));

    // beta edges ahead, but not by enough. Two near-ties alternating track by track across an
    // album that suits both reads as a bug rather than a choice.
    rank.mockResolvedValueOnce(ranking(['beta', 0.6 + SWITCH_MARGIN / 2], ['alpha', 0.6]));
    rerender({ id: 'T2' });
    await waitFor(() => expect(rank).toHaveBeenCalledTimes(2));
    expect(result.current).toBe('alpha');
  });

  it('switches when a rival clears the margin', async () => {
    rank.mockResolvedValueOnce(ranking(['alpha', 0.5]));
    const { result, rerender } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    await waitFor(() => expect(result.current).toBe('alpha'));

    rank.mockResolvedValueOnce(ranking(['beta', 0.5 + SWITCH_MARGIN * 2], ['alpha', 0.5]));
    rerender({ id: 'T2' });
    await waitFor(() => expect(result.current).toBe('beta'));
  });

  it('takes the best when the incumbent is no longer offered', async () => {
    rank.mockResolvedValueOnce(ranking(['alpha', 0.9]));
    const { result, rerender } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    await waitFor(() => expect(result.current).toBe('alpha'));

    // A plugin removed between tracks: holding a visualizer that is gone would show nothing.
    rank.mockResolvedValueOnce(ranking(['beta', 0.3]));
    rerender({ id: 'T2' });
    await waitFor(() => expect(result.current).toBe('beta'));
  });
});

describe('keeping what is showing', () => {
  it('does not change anything for an unanalysed track', async () => {
    rank.mockResolvedValueOnce(ranking(['alpha', 0.9]));
    const { result, rerender } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    await waitFor(() => expect(result.current).toBe('alpha'));

    rank.mockResolvedValueOnce({ ranked: false, visualizers: [] });
    rerender({ id: 'T2' });
    await waitFor(() => expect(useVisualizerAutoSelectStore.getState().unranked).toBe(true));
    expect(result.current).toBe('alpha');
  });

  it('does not change anything when the request fails', async () => {
    rank.mockResolvedValueOnce(ranking(['alpha', 0.9]));
    const { result, rerender } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    await waitFor(() => expect(result.current).toBe('alpha'));

    rank.mockRejectedValueOnce(new Error('offline'));
    rerender({ id: 'T2' });
    await waitFor(() => expect(rank).toHaveBeenCalledTimes(2));
    expect(result.current).toBe('alpha');
  });

  it('picks nothing at all before the first ranking arrives', () => {
    rank.mockReturnValueOnce(new Promise(() => {}));
    const { result } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    // Null means "no opinion", and the caller keeps the listener's manual choice.
    expect(result.current).toBeNull();
  });

  it('ignores a late response from a previous track', async () => {
    let resolveFirst!: (r: VisualizerRankingResponse) => void;
    rank.mockReturnValueOnce(new Promise((r) => { resolveFirst = r; }));
    rank.mockResolvedValueOnce(ranking(['beta', 0.9]));

    const { result, rerender } = renderHook(({ id }) => useAutoSelectedVisualizer(id), {
      initialProps: { id: 'T1' },
    });
    rerender({ id: 'T2' });
    await waitFor(() => expect(result.current).toBe('beta'));

    await act(async () => { resolveFirst(ranking(['alpha', 1.0])); });
    // T1's answer, however emphatic, must not land on T2.
    expect(result.current).toBe('beta');
  });
});

describe('what the picker is told', () => {
  it('records the server-reported ignored declarations', async () => {
    rank.mockResolvedValueOnce({
      ranked: true,
      visualizers: [
        {
          id: 'alpha',
          score: 0.9,
          matched_tags: [],
          matched_ranges: [],
          unmatched_ranges: [],
          ignored: ['not-a-tag'],
        },
      ],
    });

    renderHook(({ id }) => useAutoSelectedVisualizer(id), { initialProps: { id: 'T1' } });

    await waitFor(() =>
      expect(useVisualizerAutoSelectStore.getState().ignoredByVisualizer).toEqual({
        alpha: ['not-a-tag'],
      })
    );
  });
});

/**
 * The active id is what anything outside the visualizer itself must read. `FullPlayer` gates its
 * entire layout on whether Music Video is playing, and reading the *stored* id would lay album art
 * over a playing video the moment auto-select chose it.
 */
describe('useActiveVisualizerId', () => {
  beforeEach(() => {
    useVisualizerStore.setState({ visualizerId: 'alpha', autoSelect: false });
    useVisualizerAutoSelectStore.getState().reset();
  });

  it('is the stored id while auto-select is off', () => {
    const { result } = renderHook(() => useActiveVisualizerId());
    expect(result.current).toBe('alpha');
  });

  it('is still the stored id when auto-select is on but has not chosen', () => {
    useVisualizerStore.setState({ autoSelect: true });
    const { result } = renderHook(() => useActiveVisualizerId());
    expect(result.current).toBe('alpha');
  });

  it('is the auto-chosen id once there is one', () => {
    useVisualizerStore.setState({ autoSelect: true });
    useVisualizerAutoSelectStore.getState().recordChoice({
      trackId: 'T1',
      chosenId: 'beta',
      unranked: false,
      ignoredByVisualizer: {},
    });
    const { result } = renderHook(() => useActiveVisualizerId());
    expect(result.current).toBe('beta');
  });

  it('reverts to the stored id when auto-select is switched off', () => {
    useVisualizerAutoSelectStore.getState().recordChoice({
      trackId: 'T1',
      chosenId: 'beta',
      unranked: false,
      ignoredByVisualizer: {},
    });
    useVisualizerStore.setState({ autoSelect: false });
    const { result } = renderHook(() => useActiveVisualizerId());
    expect(result.current).toBe('alpha');
  });

  it('asks for no ranking of its own', () => {
    useVisualizerStore.setState({ autoSelect: true });
    renderHook(() => useActiveVisualizerId());
    expect(rank).not.toHaveBeenCalled();
  });
});
