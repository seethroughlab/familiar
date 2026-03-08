import { describe, expect, it } from 'vitest';
import { resolveTrackRowIntent } from '../trackRowInteraction';

describe('resolveTrackRowIntent', () => {
  it('plays on mobile regardless of modifiers', () => {
    expect(
      resolveTrackRowIntent({
        isMobile: true,
        shiftKey: true,
        metaKey: false,
        ctrlKey: true,
      })
    ).toBe('play');
  });

  it('selects a range for desktop shift-click', () => {
    expect(
      resolveTrackRowIntent({
        isMobile: false,
        shiftKey: true,
        metaKey: false,
        ctrlKey: false,
      })
    ).toBe('select-range');
  });

  it('toggles selection for desktop modifier-click', () => {
    expect(
      resolveTrackRowIntent({
        isMobile: false,
        shiftKey: false,
        metaKey: true,
        ctrlKey: false,
      })
    ).toBe('select-toggle');
  });

  it('single-selects on plain desktop click', () => {
    expect(
      resolveTrackRowIntent({
        isMobile: false,
        shiftKey: false,
        metaKey: false,
        ctrlKey: false,
      })
    ).toBe('select-single');
  });
});
