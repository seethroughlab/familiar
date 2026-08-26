/* @vitest-environment jsdom */
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AudioVisualizer } from '../AudioVisualizer';
import { useVisualizerStore } from '../../../stores/visualizerStore';
import type { VisualizerProps } from '../types';

// **The wiring still matters, one level down.** These caught `currentTime` being hardcoded to 0,
// and under ADR-0087 the same mistake would mean the host posting a frozen playhead to every
// plugin. `DocumentVisualizer` is stubbed to record what it was handed, so this asserts the same
// property against the thing that now carries it. What the plugin then *receives* is covered by
// DocumentVisualizer's own tests.
let lastProps: VisualizerProps | null = null;

vi.mock('../DocumentVisualizer', () => ({
  DocumentVisualizer: (props: VisualizerProps & { src: string }) => {
    lastProps = props;
    return <div data-testid="document-visualizer" data-src={props.src} />;
  },
}));


afterEach(() => {
  cleanup();
  lastProps = null;
});

// The registry is gone (ADR-0087): a visualizer is a document, so setup is a catalog of
// folders rather than components registered into this page.
vi.mock('../useVisualizerCatalog', () => {
  // One array, not a literal per render — the real hook returns React state, and a mock
  // that hands back a new reference every time makes effects depending on it loop.
  const catalog = [{ id: 'reactive-terrain', name: 'Reactive Terrain', source: 'shipped', url: '/visualizers/reactive-terrain/index.html' }];
  return { useVisualizerCatalog: () => catalog, catalogPromise: () => Promise.resolve(catalog) };
});

describe('AudioVisualizer prop wiring', () => {
  it('forwards currentTime and duration to the visualizer (regression: was hardcoded 0)', () => {
    useVisualizerStore.getState().setVisualizerId('reactive-terrain');

    render(<AudioVisualizer currentTime={42.5} duration={210} isPlaying />);

    expect(lastProps).not.toBeNull();
    expect(lastProps!.currentTime).toBe(42.5);
    expect(lastProps!.duration).toBe(210);
    expect(lastProps!.isPlaying).toBe(true);
  });

  it('defaults currentTime/duration to 0 when not provided', () => {
    useVisualizerStore.getState().setVisualizerId('reactive-terrain');

    render(<AudioVisualizer />);

    expect(lastProps).not.toBeNull();
    expect(lastProps!.currentTime).toBe(0);
    expect(lastProps!.duration).toBe(0);
  });

  // ADR-0064 point 9. `features` was declared on VisualizerProps, defaulted to null here and
  // forwarded — and passed by neither call site, so ReactiveTerrain (its only reader) always took
  // its `?? 0.4` / `?? 0.5` fallbacks. Nothing asserted the prop arrived, which is why it could be
  // dead for that long.
  it('forwards features to the visualizer', () => {
    useVisualizerStore.getState().setVisualizerId('reactive-terrain');
    const features = { energy: 0.82, valence: 0.19 } as VisualizerProps['features'];

    render(<AudioVisualizer features={features} />);

    expect(lastProps).not.toBeNull();
    expect(lastProps!.features).toBe(features);
  });

  it('defaults features to null when not provided', () => {
    useVisualizerStore.getState().setVisualizerId('reactive-terrain');

    render(<AudioVisualizer />);

    expect(lastProps).not.toBeNull();
    expect(lastProps!.features).toBeNull();
  });
});
