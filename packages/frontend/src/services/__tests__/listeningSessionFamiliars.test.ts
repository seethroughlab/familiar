import { describe, it, expect } from 'vitest';
import {
  FALLBACK_BOB_PERIOD_MS,
  STAGE_HOST_POSITION,
  computeBeatPhase,
  computeRoomPosition,
  hashString,
  type BeatAnchor,
} from '../listeningSessionFamiliars';

describe('computeRoomPosition', () => {
  it('places the host at the fixed stage position', () => {
    const pos = computeRoomPosition(
      { user_id: 'host-1', role: 'host' },
      0,
      0,
    );
    expect(pos).toEqual(STAGE_HOST_POSITION);
  });

  it('returns the same position for the same user_id and crowd shape', () => {
    const a = computeRoomPosition(
      { user_id: 'alice-42', role: 'listener' },
      2,
      6,
    );
    const b = computeRoomPosition(
      { user_id: 'alice-42', role: 'listener' },
      2,
      6,
    );
    expect(a).toEqual(b);
  });

  it('keeps positions inside the safe stage area', () => {
    for (let total = 1; total <= 12; total += 1) {
      for (let i = 0; i < total; i += 1) {
        const pos = computeRoomPosition(
          { user_id: `u-${i}-${total}`, role: 'listener' },
          i,
          total,
        );
        expect(pos.xPct).toBeGreaterThanOrEqual(6);
        expect(pos.xPct).toBeLessThanOrEqual(94);
        expect(pos.yPct).toBeGreaterThanOrEqual(50);
        expect(pos.yPct).toBeLessThanOrEqual(96);
      }
    }
  });

  it('does not stack two crowd members on top of each other for typical N', () => {
    const totals = [2, 3, 5, 8, 12];
    for (const total of totals) {
      const positions = Array.from({ length: total }, (_, i) =>
        computeRoomPosition(
          { user_id: `user-${i}`, role: 'listener' },
          i,
          total,
        ),
      );
      for (let i = 0; i < positions.length; i += 1) {
        for (let j = i + 1; j < positions.length; j += 1) {
          const dx = positions[i].xPct - positions[j].xPct;
          const dy = positions[i].yPct - positions[j].yPct;
          const distance = Math.sqrt(dx * dx + dy * dy);
          expect(distance).toBeGreaterThan(4);
        }
      }
    }
  });

  it('treats guests like listeners (not stage)', () => {
    const guest = computeRoomPosition(
      { user_id: 'g-1', role: 'guest' },
      0,
      1,
    );
    expect(guest.yPct).toBeGreaterThanOrEqual(50);
  });
});

describe('computeBeatPhase', () => {
  const baseAnchor: BeatAnchor = {
    bpm: 120,
    positionMs: 10_000,
    receivedAt: 1_700_000_000_000,
    isPlaying: true,
    trackId: 'track-a',
  };

  it('returns 0 for a null anchor', () => {
    expect(computeBeatPhase(null, 0)).toBe(0);
  });

  it('phase advances linearly within a beat at 120 BPM', () => {
    // 120 BPM → 500ms period. anchorPos=10000, +250ms elapsed → 10250 % 500 = 250 → phase 0.5
    const phase = computeBeatPhase(baseAnchor, baseAnchor.receivedAt + 250);
    expect(phase).toBeCloseTo(0.5, 5);
  });

  it('wraps at 1.0 and stays in [0, 1)', () => {
    const phase = computeBeatPhase(baseAnchor, baseAnchor.receivedAt + 500);
    // 10500 % 500 = 0
    expect(phase).toBeCloseTo(0, 5);
    expect(phase).toBeLessThan(1);
    expect(phase).toBeGreaterThanOrEqual(0);
  });

  it('uses fallback period when bpm is null', () => {
    const anchor: BeatAnchor = { ...baseAnchor, bpm: null, positionMs: 0 };
    const phase = computeBeatPhase(anchor, anchor.receivedAt + FALLBACK_BOB_PERIOD_MS / 2);
    expect(phase).toBeCloseTo(0.5, 5);
  });

  it('uses fallback period when bpm is 0 or non-finite', () => {
    const a0: BeatAnchor = { ...baseAnchor, bpm: 0, positionMs: 0 };
    const aInf: BeatAnchor = { ...baseAnchor, bpm: Number.POSITIVE_INFINITY, positionMs: 0 };
    expect(computeBeatPhase(a0, a0.receivedAt + FALLBACK_BOB_PERIOD_MS / 4)).toBeCloseTo(0.25, 5);
    expect(computeBeatPhase(aInf, aInf.receivedAt + FALLBACK_BOB_PERIOD_MS / 4)).toBeCloseTo(0.25, 5);
  });

  it('does not advance position-derived phase when paused', () => {
    const anchor: BeatAnchor = { ...baseAnchor, isPlaying: false };
    // Paused: phase derives from (now - receivedAt), not positionMs.
    const phase = computeBeatPhase(anchor, anchor.receivedAt + 250);
    expect(phase).toBeCloseTo(0.5, 5);
  });
});

describe('hashString', () => {
  it('is deterministic', () => {
    expect(hashString('alice')).toBe(hashString('alice'));
  });

  it('returns different hashes for different inputs', () => {
    expect(hashString('alice')).not.toBe(hashString('bob'));
  });

  it('returns 0 for empty string', () => {
    expect(hashString('')).toBe(0);
  });
});
