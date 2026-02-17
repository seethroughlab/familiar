import { describe, it, expect, beforeEach } from 'vitest';
import { shouldHandleEnded, getErrorAction, getCrossfadeTrigger, getEffectiveCrossfadeDuration } from '../eventHandlers';

function createMockElement(src = 'http://localhost/track.mp3'): HTMLAudioElement {
  return { src } as unknown as HTMLAudioElement;
}

// ============================================================================
// shouldHandleEnded
// ============================================================================

describe('shouldHandleEnded', () => {
  let elementA: HTMLAudioElement;
  let directElementA: HTMLAudioElement;
  let otherElement: HTMLAudioElement;

  beforeEach(() => {
    elementA = createMockElement();
    directElementA = createMockElement();
    otherElement = createMockElement();
  });

  it('returns false when queueTransition is true', () => {
    expect(shouldHandleEnded(elementA, elementA, directElementA, true, true, false)).toBe(false);
  });

  it('returns false when ended fires on non-current element (after A/B swap)', () => {
    // currentElementIsA=true but target is not elementA or directElementA
    expect(shouldHandleEnded(otherElement, elementA, directElementA, false, true, false)).toBe(false);
  });

  it('returns false when crossfade is active', () => {
    expect(shouldHandleEnded(elementA, elementA, directElementA, false, true, true)).toBe(false);
  });

  it('returns true for current element with no crossfade and no queue transition', () => {
    // target is elementA, currentElementIsA=true
    expect(shouldHandleEnded(elementA, elementA, directElementA, false, true, false)).toBe(true);
  });

  it('returns true when target matches via directElementA', () => {
    expect(shouldHandleEnded(directElementA, elementA, directElementA, false, true, false)).toBe(true);
  });

  it('returns true for B element when currentElementIsA=false', () => {
    // target is otherElement (B), elementA is not target, directElementA is not target
    // so isA=false, currentElementIsA=false => match
    expect(shouldHandleEnded(otherElement, elementA, directElementA, false, false, false)).toBe(true);
  });

  it('returns true after crossfade completes (context cleared, element swapped)', () => {
    // After crossfade: currentElementIsA flipped to false, crossfadeActive=false
    // ended fires on the NEW current element (B, which is not elementA or directElementA)
    expect(shouldHandleEnded(otherElement, elementA, directElementA, false, false, false)).toBe(true);
  });
});

// ============================================================================
// getErrorAction
// ============================================================================

describe('getErrorAction', () => {
  let currentElement: HTMLAudioElement;
  let otherElement: HTMLAudioElement;

  beforeEach(() => {
    currentElement = createMockElement('http://localhost/current.mp3');
    otherElement = createMockElement('http://localhost/next.mp3');
  });

  it("returns 'ignore' for element with no src", () => {
    const noSrc = createMockElement('');
    expect(getErrorAction(noSrc, currentElement, false, true)).toBe('ignore');
  });

  it("returns 'ignore' for element with src matching window.location.href", () => {
    const locationElement = createMockElement(window.location.href);
    expect(getErrorAction(locationElement, currentElement, false, true)).toBe('ignore');
  });

  it("returns 'ignore' for non-current element with no crossfade", () => {
    expect(getErrorAction(otherElement, currentElement, false, true)).toBe('ignore');
  });

  it("returns 'stop' for current element error during normal playback", () => {
    expect(getErrorAction(currentElement, currentElement, false, true)).toBe('stop');
  });

  it("returns 'cancel-crossfade-and-stop' for current element error during crossfade", () => {
    expect(getErrorAction(currentElement, currentElement, true, true)).toBe('cancel-crossfade-and-stop');
  });

  it("returns 'cancel-crossfade' for next element error during crossfade", () => {
    expect(getErrorAction(otherElement, currentElement, true, true)).toBe('cancel-crossfade');
  });

  it("returns 'ignore' when not playing", () => {
    expect(getErrorAction(currentElement, currentElement, false, false)).toBe('ignore');
  });

  it("returns 'cancel-crossfade-and-stop' even when not playing if crossfade is active", () => {
    // During crossfade, if current errors, we should still cancel even if isPlaying got cleared
    expect(getErrorAction(currentElement, currentElement, true, false)).toBe('cancel-crossfade-and-stop');
  });
});

// ============================================================================
// getCrossfadeTrigger
// ============================================================================

describe('getCrossfadeTrigger', () => {
  describe('desktop with crossfade enabled', () => {
    const isDirectPlayback = false;
    const mobileOverlap = 0.3;
    const crossfadeDuration = 5;

    it("returns 'preload' well before crossfade point", () => {
      // effectiveCrossfade=5, preload window: 5+1 < timeRemaining <= 5+15 => 6 < t <= 20
      expect(getCrossfadeTrigger(14, true, crossfadeDuration, isDirectPlayback, mobileOverlap)).toBe('preload');
    });

    it("returns 'crossfade' at crossfade point", () => {
      // timeRemaining=4.5, effectiveCrossfade=5 => 4.5 <= 5 && 4.5 > 0.1
      expect(getCrossfadeTrigger(4.5, true, crossfadeDuration, isDirectPlayback, mobileOverlap)).toBe('crossfade');
    });

    it("returns 'none' when too far from crossfade point", () => {
      // timeRemaining=25, effectiveCrossfade=5 => 25 > 5+15=20
      expect(getCrossfadeTrigger(25, true, crossfadeDuration, isDirectPlayback, mobileOverlap)).toBe('none');
    });

    it("returns 'none' in the dead zone between preload and crossfade", () => {
      // timeRemaining=5.5, effectiveCrossfade=5 => not <= 5, not > 6 for preload => none
      expect(getCrossfadeTrigger(5.5, true, crossfadeDuration, isDirectPlayback, mobileOverlap)).toBe('none');
    });
  });

  describe('desktop with crossfade disabled', () => {
    const isDirectPlayback = false;
    const mobileOverlap = 0.3;

    it("effectiveCrossfade is 0, 'crossfade' never triggers for normal time remaining", () => {
      // effectiveCrossfade=0, crossfade needs: timeRemaining <= 0 && > 0.1 => impossible
      // timeRemaining=20 is outside the preload window (1 < t <= 15) too
      expect(getCrossfadeTrigger(20, false, 5, isDirectPlayback, mobileOverlap)).toBe('none');
    });

    it("returns 'preload' when within 15s of end", () => {
      // effectiveCrossfade=0, preload: 1 < timeRemaining <= 15
      expect(getCrossfadeTrigger(10, false, 5, isDirectPlayback, mobileOverlap)).toBe('preload');
    });
  });

  describe('mobile (direct playback)', () => {
    const isDirectPlayback = true;
    const mobileOverlap = 0.3;

    it('uses max(crossfadeDuration, mobileOverlap) when crossfade enabled', () => {
      // crossfadeDuration=5, mobileOverlap=0.3 => effectiveCrossfade=5
      expect(getCrossfadeTrigger(4, true, 5, isDirectPlayback, mobileOverlap)).toBe('crossfade');
    });

    it('uses mobileOverlap when crossfade disabled', () => {
      // effectiveCrossfade=0.3
      expect(getCrossfadeTrigger(0.2, false, 5, isDirectPlayback, mobileOverlap)).toBe('crossfade');
    });

    it("returns 'preload' on mobile with crossfade disabled", () => {
      // effectiveCrossfade=0.3, preload window: 1.3 < timeRemaining <= 15.3
      expect(getCrossfadeTrigger(10, false, 5, isDirectPlayback, mobileOverlap)).toBe('preload');
    });
  });

  it("returns 'none' when timeRemaining <= 0.1 (below lower bound)", () => {
    expect(getCrossfadeTrigger(0.05, true, 5, false, 0.3)).toBe('none');
  });

  it("returns 'none' when timeRemaining is exactly 0.1", () => {
    expect(getCrossfadeTrigger(0.1, true, 5, false, 0.3)).toBe('none');
  });
});

// ============================================================================
// getEffectiveCrossfadeDuration
// ============================================================================

describe('getEffectiveCrossfadeDuration', () => {
  it('returns crossfadeDuration on desktop with crossfade enabled', () => {
    expect(getEffectiveCrossfadeDuration(true, 5, false, 0.3)).toBe(5);
  });

  it('returns 0 on desktop with crossfade disabled', () => {
    expect(getEffectiveCrossfadeDuration(false, 5, false, 0.3)).toBe(0);
  });

  it('returns max(crossfadeDuration, mobileOverlap) on mobile with crossfade enabled', () => {
    expect(getEffectiveCrossfadeDuration(true, 5, true, 0.3)).toBe(5);
    expect(getEffectiveCrossfadeDuration(true, 0.1, true, 0.3)).toBe(0.3);
  });

  it('returns mobileOverlap on mobile with crossfade disabled', () => {
    expect(getEffectiveCrossfadeDuration(false, 5, true, 0.3)).toBe(0.3);
  });

  it('returns 0 when crossfade disabled on desktop regardless of crossfadeDuration', () => {
    expect(getEffectiveCrossfadeDuration(false, 10, false, 0.3)).toBe(0);
    expect(getEffectiveCrossfadeDuration(false, 0, false, 0.3)).toBe(0);
  });
});
