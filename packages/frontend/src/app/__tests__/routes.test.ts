/** The destination registry (ADR-0126 points 1, 7, 8 and the redirects). */
import { describe, expect, it } from 'vitest';

import { DESTINATIONS, LEGACY_REDIRECTS, SECTIONS, isUnder } from '../routes';

describe('ancestor matching', () => {
  it('a section lights its destination, and only its destination', () => {
    expect(isUnder('/library/duplicates', '/library')).toBe(true);
    expect(isUnder('/server/providers', '/server')).toBe(true);
    expect(isUnder('/server/providers', '/library')).toBe(false);
    expect(isUnder('/libraryx', '/library')).toBe(false);
  });
  it('the Overview is exact — it would otherwise match everything', () => {
    expect(isUnder('/', '/')).toBe(true);
    expect(isUnder('/library', '/')).toBe(false);
  });
});

describe('the registry', () => {
  it('has four destinations, Overview first', () => {
    expect(DESTINATIONS.map((d) => d.label)).toEqual(['Overview', 'Library', 'Analysis', 'Server']);
  });
  it('every section sits under its destination, and the first is the destination itself', () => {
    for (const [destination, sections] of Object.entries(SECTIONS)) {
      expect(sections[0].path).toBe(destination);
      for (const s of sections) expect(isUnder(s.path, destination)).toBe(true);
    }
  });
  it('Library has no Review section until a screen exists (point 4)', () => {
    expect(SECTIONS['/library'].map((s) => s.label)).not.toContain('Review');
  });
  it('every legacy path redirects to a registered section', () => {
    const known = new Set(Object.values(SECTIONS).flat().map((s) => s.path));
    for (const to of Object.values(LEGACY_REDIRECTS)) expect(known.has(to), to).toBe(true);
  });
});
