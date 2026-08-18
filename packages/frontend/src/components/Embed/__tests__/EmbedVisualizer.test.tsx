/* @vitest-environment jsdom */
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EmbedVisualizer } from '../EmbedVisualizer';
import { registerVisualizer, type VisualizerProps } from '../../Visualizer/types';
import { useVisualizerStore } from '../../../stores/visualizerStore';
import {
  installVisualizerSink,
  resetVisualizerSinkForTesting,
  type AnalysisFrame,
} from '../../../services/visualizerSink';
import { tracksApi } from '../../../api/tracks';
import type { Track } from '../../../types';

vi.mock('../../../api/tracks', () => ({
  tracksApi: { get: vi.fn(), getArtworkUrl: (id: string) => `/artwork/${id}` },
}));

const get = tracksApi.get as ReturnType<typeof vi.fn>;

// Same capture harness as AudioVisualizer.test.tsx: a stub visualizer that records its props, so
// the assertion is on what actually reached a visualizer rather than on an intermediate component.
let lastProps: VisualizerProps | null = null;
const CAPTURE_ID = 'embed-capture';

registerVisualizer(
  { id: CAPTURE_ID, name: 'Capture', description: 'test', usesMetadata: true },
  (props: VisualizerProps) => {
    lastProps = props;
    return <div data-testid="capture" />;
  }
);

/** A frame as the native host sends it. Empty base64 decodes to a zero-length buffer, which is all
 *  this test needs — the spectrum never passes through React. */
function frame(track: AnalysisFrame['track']): AnalysisFrame {
  return {
    frequency: '',
    timeDomain: '',
    flux: [],
    fluxInterval: 0.1,
    cadenceHz: 10,
    playing: true,
    position: 0,
    track,
  };
}

function send(f: AnalysisFrame): void {
  (window as unknown as Record<string, (frame: AnalysisFrame) => void>).__familiarAnalysis(f);
}

beforeEach(() => {
  get.mockReset();
  resetVisualizerSinkForTesting();
  installVisualizerSink();
  useVisualizerStore.getState().setVisualizerId(CAPTURE_ID);
});

afterEach(() => {
  cleanup();
  lastProps = null;
  resetVisualizerSinkForTesting();
});

describe('EmbedVisualizer', () => {
  // ADR-0064 point 9. This surface is the one the Apple clients actually use, and it passed no
  // features at all — it built a partial Track by cast from the frame's four identity fields, so no
  // analysis reached a visualizer here. The frame still carries no analysis (ADR-0033 keeps the
  // channel narrow); the page fetches it, the way it already fetches artwork and lyrics.
  it('fetches the track detail and passes its features to the visualizer', async () => {
    get.mockResolvedValueOnce({
      id: 'T1',
      title: 'Real Title',
      features: { energy: 0.77, valence: 0.22 },
    } as Track);

    render(<EmbedVisualizer />);
    act(() => send(frame({ id: 'T1', title: 'From Frame' })));

    await waitFor(() => expect(lastProps?.features?.energy).toBe(0.77));
    expect(get).toHaveBeenCalledWith('T1');
    // Once the real track arrives it replaces the frame-derived partial.
    expect(lastProps?.track?.title).toBe('Real Title');
  });

  it('falls back to the frame fields while the fetch is pending', async () => {
    let resolve!: (t: Track) => void;
    get.mockReturnValueOnce(new Promise<Track>((r) => { resolve = r; }));

    render(<EmbedVisualizer />);
    act(() => send(frame({ id: 'T1', title: 'From Frame', artist: 'A' })));

    // The visualizer draws immediately rather than waiting on the network.
    await waitFor(() => expect(lastProps?.track?.title).toBe('From Frame'));
    expect(lastProps?.features).toBeNull();

    await act(async () => { resolve({ id: 'T1', title: 'Real Title' } as Track); });
    await waitFor(() => expect(lastProps?.track?.title).toBe('Real Title'));
  });

  it('still draws when the detail fetch fails', async () => {
    get.mockRejectedValueOnce(new Error('offline'));

    render(<EmbedVisualizer />);
    act(() => send(frame({ id: 'T1', title: 'From Frame' })));

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(lastProps?.track?.title).toBe('From Frame');
    expect(lastProps?.features).toBeNull();
  });

  it('renders with no track before any frame arrives', () => {
    render(<EmbedVisualizer />);

    expect(lastProps?.track).toBeNull();
    expect(lastProps?.features).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });
});
