/* @vitest-environment jsdom */
/**
 * ADR-0064 point 3 and point 7, at the surface where they are visible.
 *
 * The picker had no test at all. What it needs one for is the two things that are easy to get
 * quietly wrong: an auto-select toggle that overrules a listener who has just chosen, and an
 * ignored declaration with nowhere to be said — the same "no destination" shape this surface keeps
 * producing.
 *
 * Plain DOM assertions rather than `toBeInTheDocument`: this package installs no jest-dom matchers.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VisualizerPicker } from '../VisualizerPicker';
import { useVisualizerStore } from '../../../stores/visualizerStore';
import { useVisualizerPluginStore } from '../../../stores/visualizerPluginStore';
import { useVisualizerAutoSelectStore } from '../../../stores/visualizerAutoSelectStore';

beforeEach(() => {
  useVisualizerStore.setState({ visualizerId: 'alpha', autoSelect: false });
  useVisualizerPluginStore.setState({ records: [], scanned: true });
  useVisualizerAutoSelectStore.getState().reset();
});

afterEach(cleanup);

/** The list only exists once the dropdown is open. */
function open() {
  render(<VisualizerPicker />);
  fireEvent.click(screen.getAllByRole('button')[0]);
}

/** A row is identified by its description, which the trigger button does not repeat. */
function row(description: string): HTMLElement {
  const node = screen.getByText(description).closest('button');
  if (!node) throw new Error(`no row for ${description}`);
  return node;
}

const checkbox = () => screen.getByRole('checkbox') as HTMLInputElement;
const text = (pattern: RegExp | string) => screen.queryByText(pattern);

// The registry is gone (ADR-0087): a visualizer is a document, so setup is a catalog of
// folders rather than components registered into this page.
vi.mock('../useVisualizerCatalog', () => {
  // One array, not a literal per render — the real hook returns React state, and a mock
  // that hands back a new reference every time makes effects depending on it loop.
  const catalog = [
    { id: 'alpha', name: 'Alpha', description: 'the alpha scene', source: 'shipped', url: '/visualizers/alpha/index.html' },
    { id: 'beta', name: 'Beta', description: 'the beta scene', source: 'shipped', url: '/visualizers/beta/index.html' },
  ];
  return { useVisualizerCatalog: () => catalog, catalogPromise: () => Promise.resolve(catalog) };
});

describe('auto-select', () => {
  it('is off by default', () => {
    open();
    expect(checkbox().checked).toBe(false);
  });

  it('can be switched on', () => {
    open();
    fireEvent.click(checkbox());
    expect(useVisualizerStore.getState().autoSelect).toBe(true);
  });

  it('marks the auto-chosen visualizer rather than the stored one', () => {
    useVisualizerStore.setState({ autoSelect: true, visualizerId: 'alpha' });
    useVisualizerAutoSelectStore.getState().recordChoice({
      trackId: 'T1',
      chosenId: 'beta',
      unranked: false,
      ignoredByVisualizer: {},
    });
    open();

    expect(text('AUTO')).not.toBeNull();
    // The badge sits on Beta's row, not Alpha's — the stored id is still 'alpha'.
    expect(row('the beta scene').textContent).toContain('AUTO');
    expect(row('the alpha scene').textContent).not.toContain('AUTO');
  });

  // ADR-0064 point 7: auto-select must never overrule a choice the listener just made. Leaving it
  // on would let the next track do exactly that.
  it('turns itself off when a visualizer is chosen by hand', () => {
    useVisualizerStore.setState({ autoSelect: true });
    open();
    fireEvent.click(row('the beta scene'));

    expect(useVisualizerStore.getState().visualizerId).toBe('beta');
    expect(useVisualizerStore.getState().autoSelect).toBe(false);
  });

  it('says so when the track has no analysis to rank against', () => {
    useVisualizerStore.setState({ autoSelect: true });
    useVisualizerAutoSelectStore.getState().recordChoice({
      trackId: 'T1',
      chosenId: null,
      unranked: true,
      ignoredByVisualizer: {},
    });
    open();
    expect(text(/has not been analysed/i)).not.toBeNull();
  });
});

describe('ignored declarations', () => {
  it('shows nothing when everything was understood', () => {
    open();
    expect(text(/Ignored in manifest/i)).toBeNull();
  });

  it('reports what the manifest parser dropped', () => {
    useVisualizerPluginStore.setState({
      records: [
        {
          id: 'alpha',
          name: 'Alpha',
          source: 'local',
          status: 'loaded',
          ignored: ['affinity.tags entry 42'],
        },
      ],
      scanned: true,
    });
    open();
    expect(text(/Ignored in manifest/i)).not.toBeNull();
    expect(text(/affinity\.tags entry 42/)).not.toBeNull();
  });

  // The vocabulary is the server's, so an unknown *tag* can only be reported from the ranking.
  it('reports what the server did not recognise', () => {
    useVisualizerAutoSelectStore.getState().recordChoice({
      trackId: 'T1',
      chosenId: 'alpha',
      unranked: false,
      ignoredByVisualizer: { beta: ['not-a-real-tag'] },
    });
    open();
    expect(text(/not-a-real-tag/)).not.toBeNull();
  });

  // A loaded plugin stays selectable; an unusable optional field is not a reason to withhold it.
  it('leaves a plugin with ignored declarations in the selectable list', () => {
    useVisualizerPluginStore.setState({
      records: [{ id: 'beta', name: 'Beta', source: 'local', status: 'loaded', ignored: ['x'] }],
      scanned: true,
    });
    open();
    fireEvent.click(row('the beta scene'));
    expect(useVisualizerStore.getState().visualizerId).toBe('beta');
  });
});

describe('refused plugins', () => {
  it('lists a refused plugin separately from an ignored declaration', () => {
    useVisualizerPluginStore.setState({
      records: [
        {
          id: 'gamma',
          name: 'Gamma',
          source: 'local',
          status: 'refused',
          detail: 'Bad api version.',
        },
      ],
      scanned: true,
    });
    open();
    expect(text(/Not loaded/i)).not.toBeNull();
    expect(text('Bad api version.')).not.toBeNull();
    // A refusal is not an ignored declaration; the two sections mean different things.
    expect(text(/Ignored in manifest/i)).toBeNull();
  });
});
