/**
 * Tests for albumHash - normalization and SHA-256 hashing for album deduplication.
 */
import { describe, it, expect } from 'vitest';
import { computeAlbumHash } from '../albumHash';

describe('computeAlbumHash', () => {
  it('should produce a 16-character hex hash', async () => {
    const hash = await computeAlbumHash('Radiohead', 'OK Computer');
    expect(hash).toMatch(/^[0-9a-f]{16}$/);
  });

  it('should be deterministic', async () => {
    const hash1 = await computeAlbumHash('Radiohead', 'OK Computer');
    const hash2 = await computeAlbumHash('Radiohead', 'OK Computer');
    expect(hash1).toBe(hash2);
  });

  it('should be case insensitive', async () => {
    const hash1 = await computeAlbumHash('Radiohead', 'OK Computer');
    const hash2 = await computeAlbumHash('RADIOHEAD', 'ok computer');
    expect(hash1).toBe(hash2);
  });

  it('should normalize whitespace', async () => {
    const hash1 = await computeAlbumHash('Pink Floyd', 'The Wall');
    const hash2 = await computeAlbumHash('Pink  Floyd', '  The   Wall  ');
    expect(hash1).toBe(hash2);
  });

  it('should normalize diacritics', async () => {
    const hash1 = await computeAlbumHash('Bjork', 'Debut');
    const hash2 = await computeAlbumHash('Björk', 'Debut');
    expect(hash1).toBe(hash2);
  });

  it('should normalize backtick and acute accent to straight quote', async () => {
    const hash1 = await computeAlbumHash("Artist", "Don't Stop");
    const hash2 = await computeAlbumHash("Artist", "Don\u00B4t Stop"); // acute accent
    expect(hash1).toBe(hash2);
  });

  it('should normalize dashes', async () => {
    const hash1 = await computeAlbumHash('Artist', 'Pre-Album');
    const hash2 = await computeAlbumHash('Artist', 'Pre\u2013Album'); // en-dash
    expect(hash1).toBe(hash2);
  });

  it('should use "unknown" for null/undefined/empty', async () => {
    const hash1 = await computeAlbumHash(null, null);
    const hash2 = await computeAlbumHash(undefined, undefined);
    const hash3 = await computeAlbumHash('', '');
    expect(hash1).toBe(hash2);
    expect(hash2).toBe(hash3);
  });

  it('should differentiate different artists with same album', async () => {
    const hash1 = await computeAlbumHash('Artist A', 'Album');
    const hash2 = await computeAlbumHash('Artist B', 'Album');
    expect(hash1).not.toBe(hash2);
  });

  it('should differentiate same artist with different albums', async () => {
    const hash1 = await computeAlbumHash('Artist', 'Album A');
    const hash2 = await computeAlbumHash('Artist', 'Album B');
    expect(hash1).not.toBe(hash2);
  });

  it('should normalize prime to straight quote', async () => {
    const hash1 = await computeAlbumHash("Artist", "it's");
    const hash2 = await computeAlbumHash("Artist", "it\u2032s"); // prime symbol
    expect(hash1).toBe(hash2);
  });
});
