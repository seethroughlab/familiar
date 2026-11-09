/* @vitest-environment jsdom */
/**
 * Found moving tracks to generated types (ADR-0173): the schema says each detected feature may be
 * absent as well as null, and the tab tested `!== null`, so an absent one rendered as "NaN%".
 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { TrackMetadataResponse } from '../../../../api';
import { AnalysisTab } from '../AnalysisTab';

function metadata(features: TrackMetadataResponse['features']): TrackMetadataResponse {
  return { features } as TrackMetadataResponse;
}

describe('AnalysisTab', () => {
  afterEach(cleanup);

  it('shows a feature the server sent, and leaves out one it did not', () => {
    render(
      <AnalysisTab formData={{}} metadata={metadata({ energy: 0.42, valence: null })} onChange={vi.fn()} />,
    );
    expect(screen.getByText('42%')).toBeTruthy();
    expect(screen.queryByText('Valence')).toBeNull();
    expect(screen.queryByText('Danceability')).toBeNull();
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it('prefers a numeric override, and ignores one that is not a number or a string', () => {
    const { rerender } = render(
      <AnalysisTab
        formData={{ user_overrides: { bpm: 128 } }}
        metadata={metadata({ bpm: 120 })}
        onChange={vi.fn()}
      />,
    );
    expect((screen.getByPlaceholderText('BPM') as HTMLInputElement).value).toBe('128');
    rerender(
      <AnalysisTab
        formData={{ user_overrides: { bpm: { not: 'a number' } } }}
        metadata={metadata({ bpm: 120 })}
        onChange={vi.fn()}
      />,
    );
    expect((screen.getByPlaceholderText('BPM') as HTMLInputElement).value).toBe('120');
  });
});
