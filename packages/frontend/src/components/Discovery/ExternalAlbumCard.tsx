/**
 * ExternalAlbumCard — visual card for external (not-in-library) album recommendations.
 *
 * Used by:
 *   - Discover page "New releases from your artists" section (#3)
 *   - Discover page "Albums you might want" section (listening-profile #2)
 *   - Playlist drawer (#2 per-playlist, Pass 4)
 *
 * The `/library/discover/new-releases` detail page was here too. It was deleted when ADR-0050 made
 * the web app a management surface, and this list went on naming it — which is how the "See all"
 * link that reached it survived being dead on every platform.
 *
 * Visually mirrors DiscoveryCard's grid look, but adds external-album-specific
 * affordances: dismiss button, context label, release type/date, purchase links.
 */
import { X, Check } from 'lucide-react';
import type { ExternalAlbum } from '../../api/discovery';
import { AlbumArtwork } from '../AlbumArtwork';
import { FindDropdown, type FindLink } from './FindDropdown';

export interface ExternalAlbumCardProps {
  album: ExternalAlbum;
  /** "New release · Apr 2026", "Recommended", "Recommended · matches this playlist" */
  contextLabel: string;
  onDismiss?: (id: string) => void;
  layout?: 'grid' | 'list';
}

function formatReleaseLabel(album: ExternalAlbum): string | null {
  if (!album.release_type && !album.release_date) return null;
  const type = album.release_type ? album.release_type.toUpperCase() : '';
  if (!album.release_date) return type || null;
  try {
    // Parse YYYY-MM-DD as a calendar date in UTC to avoid timezone shifts
    // that make "2024-06-01" render as "May 2024" west of UTC.
    const d = new Date(album.release_date);
    if (Number.isNaN(d.valueOf())) return type || null;
    const month = d.toLocaleString('default', { month: 'short', timeZone: 'UTC' });
    const year = d.getUTCFullYear();
    const date = `${month} ${year}`;
    return type ? `${type} · ${date}` : date;
  } catch {
    return type || null;
  }
}

function purchaseLinksToFindLinks(
  links: ExternalAlbum['purchase_links'],
): FindLink[] {
  return Object.values(links ?? {}) as FindLink[];
}

export function ExternalAlbumCard({
  album,
  contextLabel,
  onDismiss,
  layout = 'grid',
}: ExternalAlbumCardProps) {
  const releaseLabel = formatReleaseLabel(album);

  if (layout === 'list') {
    return (
      <div className="group flex items-center gap-3 p-2 rounded-lg transition-colors hover:bg-zinc-800/50">
        <div className="w-12 h-12 flex-shrink-0 rounded overflow-hidden bg-zinc-800">
          <AlbumArtwork
            artist={album.artist_name}
            album={album.release_name}
            artworkUrl={album.artwork_url}
            size="thumb"
          />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500 truncate">
            {contextLabel}
          </div>
          <div className="font-medium text-sm truncate">{album.release_name}</div>
          <div className="text-xs text-zinc-400 truncate">
            {album.artist_name}
            {releaseLabel ? ` · ${releaseLabel}` : ''}
          </div>
        </div>
        {album.local_album_match && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-success-surface/30 text-success text-xs">
            <Check className="w-3 h-3" />
            In library
          </span>
        )}
        <FindDropdown
          links={purchaseLinksToFindLinks(album.purchase_links)}
          ariaLabel="Find this album"
        />
        {onDismiss && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDismiss(album.id);
            }}
            className="p-1 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
            aria-label="Dismiss"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
    );
  }

  // Grid layout (default)
  return (
    <div className="group relative overflow-hidden rounded-lg bg-zinc-800/50 transition-all hover:bg-zinc-800">
      <div className="aspect-square">
        <AlbumArtwork
          artist={album.artist_name}
          album={album.release_name}
          artworkUrl={album.artwork_url}
          size="full"
          className="w-full h-full"
        />
      </div>

      {/* Dismiss button — top-right, hover-revealed on desktop */}
      {onDismiss && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDismiss(album.id);
          }}
          className="absolute top-2 right-2 p-1 rounded-full bg-black/60 backdrop-blur-sm text-zinc-300 hover:text-white hover:bg-black/80 transition-all sm:opacity-0 sm:group-hover:opacity-100"
          aria-label="Dismiss"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}

      {/* In-library badge — top-left if applicable */}
      {album.local_album_match && (
        <div className="absolute top-2 left-2 flex items-center gap-1 px-2 py-0.5 rounded-full bg-success-surface/80 backdrop-blur-sm text-success-subtle text-[10px] font-medium">
          <Check className="w-3 h-3" />
          In library
        </div>
      )}

      {/* Bottom overlay: context label, title, artist, optional date, purchase links */}
      <div className="absolute bottom-0 left-0 right-0 p-3 bg-gradient-to-t from-black/95 via-black/70 to-transparent">
        <div className="text-[10px] uppercase tracking-wider text-zinc-400 truncate mb-0.5">
          {contextLabel}
        </div>
        <div className="font-medium text-sm truncate text-zinc-100">
          {album.release_name}
        </div>
        <div className="flex items-end justify-between gap-2">
          <div className="text-xs text-zinc-400 truncate min-w-0">
            <div className="truncate">{album.artist_name}</div>
            {releaseLabel && (
              <div className="text-[10px] text-zinc-500 truncate">{releaseLabel}</div>
            )}
          </div>
          <div className="flex-shrink-0">
            <FindDropdown
              links={purchaseLinksToFindLinks(album.purchase_links)}
              ariaLabel="Find this album"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
