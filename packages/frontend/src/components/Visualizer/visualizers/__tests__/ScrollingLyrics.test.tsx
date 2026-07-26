/* @vitest-environment jsdom */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ScrollingLyrics } from '../ScrollingLyrics';
import type { VisualizerProps } from '../../types';
import type { LyricLine } from '../../../../api';

// The 3D word field is a WebGL <Canvas> that can't render in jsdom — stub it.
vi.mock('../LyricWordField', () => ({ LyricWordField: () => null }));

const lyrics: LyricLine[] = [
  { time: 0, text: 'first line' },
  { time: 5, text: 'second line' },
  { time: 10, text: 'third line' },
  { time: 15, text: 'fourth line' },
];

function renderViz(props: Partial<VisualizerProps>) {
  const base: VisualizerProps = {
    currentTime: 0,
    duration: 60,
    isPlaying: true,
    track: { id: 't', title: 'Song', artist: 'Artist' } as VisualizerProps['track'],
    features: null,
    artworkUrl: null,
    lyrics: null,
  };
  return render(<ScrollingLyrics {...base} {...props} />);
}

afterEach(cleanup);

describe('ScrollingLyrics', () => {
  it('renders every lyric line so upcoming lines are visible (read-ahead)', () => {
    renderViz({ lyrics, currentTime: 6 }); // on the 2nd line
    // Past, current AND upcoming lines are all in the DOM (getByText throws if missing).
    expect(screen.getByText('first line')).toBeTruthy();
    expect(screen.getByText('second line')).toBeTruthy();
    expect(screen.getByText('third line')).toBeTruthy();
    expect(screen.getByText('fourth line')).toBeTruthy();
  });

  it('emphasizes the current line and dims the others', () => {
    renderViz({ lyrics, currentTime: 11 }); // 3rd line is current
    // Text now lives in an inner span; the styled row is its parent.
    const current = screen.getByText('third line').parentElement!;
    const other = screen.getByText('first line').parentElement!;
    expect(current.style.fontWeight).toBe('800');
    expect(current.style.opacity).toBe('1');
    // A sung line several rows back is heavily dimmed.
    expect(parseFloat(other.style.opacity)).toBeLessThan(0.5);
  });

  it('plays a one-shot entrance animation on the current line only', () => {
    renderViz({ lyrics, currentTime: 11 }); // 3rd line is current
    const currentSpan = screen.getByText('third line');
    const otherSpan = screen.getByText('first line');
    expect(currentSpan.style.animation).toContain('lineEnter');
    expect(otherSpan.style.animation).toBe('');
  });

  it('falls back to title/artist when there are no synced lyrics', () => {
    renderViz({ lyrics: null });
    expect(screen.getByText('Song')).toBeTruthy();
    expect(screen.getByText('Artist')).toBeTruthy();
    expect(screen.getByText(/No synced lyrics/i)).toBeTruthy();
  });
});
