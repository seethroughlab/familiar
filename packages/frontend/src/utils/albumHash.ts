/**
 * Normalize a string for consistent matching.
 *
 * This must stay in sync with backend/app/services/normalize.py:normalize_for_matching
 * Handles: case, whitespace, quotes, dashes, diacritics.
 */
function normalizeForMatching(name: string | null | undefined): string {
  if (!name) return '';

  let s = name.trim();

  // Normalize quotes: ' ' ´ ` ′ → '
  s = s.replace(/[''´`′]/g, "'");
  // Normalize quotes: " " « » → "
  s = s.replace(/[""«»]/g, '"');

  // Normalize dashes: – — − ‐ ‒ ⁻ → -
  s = s.replace(/[–—−‐‒⁻]/g, '-');

  // Remove diacritics: Björk → Bjork
  // NFD decomposes characters (é → e + combining accent)
  s = s.normalize('NFD');
  // Remove combining marks (accents, umlauts, etc.) - Unicode range \u0300-\u036f
  s = s.replace(/[\u0300-\u036f]/g, '');

  // Case fold (toLowerCase is close enough for JS)
  s = s.toLowerCase();

  // Collapse whitespace
  s = s.split(/\s+/).join(' ');

  return s;
}

/**
 * Compute album hash matching the backend algorithm.
 *
 * This must stay in sync with backend/app/services/artwork.py:compute_album_hash
 * Uses a JS implementation of SHA-256 to work over HTTP (crypto.subtle requires HTTPS).
 */
export async function computeAlbumHash(
  artist: string | null | undefined,
  album: string | null | undefined
): Promise<string> {
  const artistNorm = normalizeForMatching(artist) || 'unknown';
  const albumNorm = normalizeForMatching(album) || 'unknown';
  const key = `${artistNorm}::${albumNorm}`;
  const hash = await sha256(key);
  return hash.slice(0, 16);
}

/**
 * SHA-256 implementation that works in all contexts (HTTP and HTTPS).
 * Uses crypto.subtle when available, falls back to JS implementation.
 */
async function sha256(message: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(message);

  // Try Web Crypto API first (only works in secure contexts)
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    try {
      const hashBuffer = await crypto.subtle.digest('SHA-256', data);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
    } catch {
      // Fall through to JS implementation
    }
  }

  // Fallback: JS implementation of SHA-256
  return sha256js(data);
}

/**
 * Pure JavaScript SHA-256 implementation.
 * Based on the FIPS 180-4 specification.
 */
function sha256js(data: Uint8Array): string {
  // SHA-256 constants
  const K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];

  // Initial hash values
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;

  // Pre-processing: adding padding bits
  const bitLen = data.length * 8;
  const paddedLen = Math.ceil((data.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLen);
  padded.set(data);
  padded[data.length] = 0x80;

  // Append length in bits as 64-bit big-endian
  const view = new DataView(padded.buffer);
  view.setUint32(paddedLen - 4, bitLen, false);

  // Process each 64-byte chunk
  for (let i = 0; i < paddedLen; i += 64) {
    const w = new Uint32Array(64);

    // Copy chunk into first 16 words
    for (let j = 0; j < 16; j++) {
      w[j] = view.getUint32(i + j * 4, false);
    }

    // Extend the first 16 words into the remaining 48 words
    for (let j = 16; j < 64; j++) {
      const s0 = rotr(w[j - 15], 7) ^ rotr(w[j - 15], 18) ^ (w[j - 15] >>> 3);
      const s1 = rotr(w[j - 2], 17) ^ rotr(w[j - 2], 19) ^ (w[j - 2] >>> 10);
      w[j] = (w[j - 16] + s0 + w[j - 7] + s1) >>> 0;
    }

    // Initialize working variables
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;

    // Compression function main loop
    for (let j = 0; j < 64; j++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + ch + K[j] + w[j]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) >>> 0;

      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    // Add the compressed chunk to the current hash value
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  // Produce the final hash value (big-endian)
  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((h) => h.toString(16).padStart(8, '0'))
    .join('');
}

// Right rotate helper
function rotr(x: number, n: number): number {
  return (x >>> n) | (x << (32 - n));
}
