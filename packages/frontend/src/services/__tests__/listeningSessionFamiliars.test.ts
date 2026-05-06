import { describe, it, expect } from 'vitest';
import {
  hashString,
} from '../listeningSessionFamiliars';

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
