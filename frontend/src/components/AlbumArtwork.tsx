/**
 * AlbumArtwork - Reactive album artwork component.
 *
 * Automatically requests artwork, shows loading placeholder, and updates
 * when artwork becomes available. Uses the artworkStore for state management.
 */
import { useEffect, useRef, useState } from 'react';
import { Disc } from 'lucide-react';
import { useArtworkStore } from '../stores/artworkStore';
import { getApiUrl } from '../api/base';

interface AlbumArtworkProps {
  artist: string | null | undefined;
  album: string | null | undefined;
  trackId?: string;
  size?: 'thumb' | 'full';
  className?: string;
  // For backwards compatibility - if provided, use this as fallback
  fallbackTrackId?: string;
  // Direct artwork URL (e.g. from external track album art)
  artworkUrl?: string | null;
}

export function AlbumArtwork({
  artist,
  album,
  trackId,
  size = 'thumb',
  className = '',
  fallbackTrackId,
  artworkUrl: directArtworkUrl,
}: AlbumArtworkProps) {
  const requestArtwork = useArtworkStore((state) => state.requestArtwork);
  // Subscribe to status map to trigger re-render when it changes
  const statusMap = useArtworkStore((state) => state.status);
  const hashesMap = useArtworkStore((state) => state.hashes);
  const [imageError, setImageError] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const requestedRef = useRef(false);

  // Normalize artist/album
  const normalizedArtist = artist || 'Unknown';
  const normalizedAlbum = album || 'Unknown';

  // Get status and hash from subscribed state
  const cacheKey = `${normalizedArtist}::${normalizedAlbum}`;
  const status = statusMap.get(cacheKey) || 'unknown';
  const hash = hashesMap.get(cacheKey);

  // Compute artwork URL from local state
  const artworkUrl = (hash && status === 'ready') ? getApiUrl(`/artwork/${hash}/${size}`) : null;

  // Determine what to show
  const showPlaceholder = (!directArtworkUrl && (!artist || !album || status === 'unknown' || status === 'checking' || status === 'pending' || status === 'missing')) || imageError;

  // For backwards compatibility, try the old track-based URL if we have a fallback
  const fallbackUrl = fallbackTrackId ? getApiUrl(`/tracks/${fallbackTrackId}/artwork?size=${size}`) : null;

  // Request artwork immediately on mount if status is unknown
  // This ensures artwork is fetched even for elements already in view
  useEffect(() => {
    if (normalizedArtist === 'Unknown' || normalizedAlbum === 'Unknown') {
      return;
    }
    if (requestedRef.current) {
      return;
    }
    if (status === 'unknown') {
      requestedRef.current = true;
      requestArtwork([{ artist: normalizedArtist, album: normalizedAlbum, trackId }]);
    }
  }, [normalizedArtist, normalizedAlbum, trackId, status, requestArtwork]);

  // Reset requested ref when artist/album changes
  useEffect(() => {
    requestedRef.current = false;
  }, [normalizedArtist, normalizedAlbum]);

  // Reset error state when artist/album changes
  useEffect(() => {
    setImageError(false);
  }, [normalizedArtist, normalizedAlbum]);

  if (showPlaceholder && !fallbackUrl) {
    return (
      <div ref={containerRef} className={`bg-zinc-700 flex items-center justify-center ${className}`}>
        <Disc className="w-1/3 h-1/3 text-zinc-500" />
      </div>
    );
  }

  const imageUrl = directArtworkUrl || artworkUrl || fallbackUrl;

  return (
    <div ref={containerRef} className={`bg-zinc-700 relative ${className}`}>
      {imageUrl && !imageError && (
        <img
          src={imageUrl}
          alt={`${normalizedArtist} - ${normalizedAlbum}`}
          className="w-full h-full object-cover"
          onError={() => setImageError(true)}
        />
      )}
      {/* Fallback icon - shown behind the image */}
      <div className="absolute inset-0 flex items-center justify-center -z-10">
        <Disc className="w-1/3 h-1/3 text-zinc-500" />
      </div>
    </div>
  );
}

/**
 * Simpler hook for cases where you just need the URL.
 * Returns null if artwork isn't ready yet.
 */
export function useAlbumArtworkUrl(
  artist: string | null | undefined,
  album: string | null | undefined,
  size: 'thumb' | 'full' = 'thumb'
): string | null {
  const { requestArtwork, getArtworkUrl } = useArtworkStore();

  useEffect(() => {
    if (artist && album) {
      requestArtwork([{ artist, album }]);
    }
  }, [artist, album, requestArtwork]);

  return getArtworkUrl(artist || 'Unknown', album || 'Unknown', size);
}
