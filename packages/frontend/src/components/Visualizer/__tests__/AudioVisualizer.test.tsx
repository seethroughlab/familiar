/* @vitest-environment jsdom */
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { AudioVisualizer } from '../AudioVisualizer';
import { registerVisualizer } from '../types';
import { useVisualizerStore } from '../../../stores/visualizerStore';
import type { VisualizerProps } from '../types';

// A stub visualizer that records the props it was rendered with. Registering it
// and pointing the store at it lets us assert AudioVisualizer's prop wiring
// without loading the real (three.js / DOM-rAF) visualizers.
let lastProps: VisualizerProps | null = null;
const CAPTURE_ID = 'test-capture';

registerVisualizer(
  { id: CAPTURE_ID, name: 'Capture', description: 'test', usesMetadata: false },
  (props: VisualizerProps) => {
    lastProps = props;
    return <div data-testid="capture" />;
  }
);

afterEach(() => {
  cleanup();
  lastProps = null;
});

describe('AudioVisualizer prop wiring', () => {
  it('forwards currentTime and duration to the visualizer (regression: was hardcoded 0)', () => {
    useVisualizerStore.getState().setVisualizerId(CAPTURE_ID);

    render(<AudioVisualizer currentTime={42.5} duration={210} isPlaying />);

    expect(lastProps).not.toBeNull();
    expect(lastProps!.currentTime).toBe(42.5);
    expect(lastProps!.duration).toBe(210);
    expect(lastProps!.isPlaying).toBe(true);
  });

  it('defaults currentTime/duration to 0 when not provided', () => {
    useVisualizerStore.getState().setVisualizerId(CAPTURE_ID);

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
    useVisualizerStore.getState().setVisualizerId(CAPTURE_ID);
    const features = { energy: 0.82, valence: 0.19 } as VisualizerProps['features'];

    render(<AudioVisualizer features={features} />);

    expect(lastProps).not.toBeNull();
    expect(lastProps!.features).toBe(features);
  });

  it('defaults features to null when not provided', () => {
    useVisualizerStore.getState().setVisualizerId(CAPTURE_ID);

    render(<AudioVisualizer />);

    expect(lastProps).not.toBeNull();
    expect(lastProps!.features).toBeNull();
  });
});
