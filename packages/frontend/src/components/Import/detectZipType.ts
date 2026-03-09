export type ZipContentType = 'spotify' | 'audio';

/**
 * Detect whether a ZIP file contains Spotify data export or audio files.
 * Reads the first 1MB of raw bytes — ZIP local file headers store filenames
 * in plaintext, so this works without decompression.
 */
export async function detectZipType(file: File): Promise<ZipContentType> {
  const slice = file.slice(0, 1024 * 1024);
  const buf = new Uint8Array(await slice.arrayBuffer());
  const text = new TextDecoder('ascii', { fatal: false }).decode(buf);

  const spotifyMarkers = ['YourLibrary', 'StreamingHistory', 'Playlist1.json', 'Userdata.json'];
  if (spotifyMarkers.some(m => text.includes(m))) return 'spotify';
  return 'audio';
}
