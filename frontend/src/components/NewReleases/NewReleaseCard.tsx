import { useState } from 'react';
import {
  ExternalLink,
  X,
  Music,
  ShoppingCart,
  ChevronDown,
  ChevronUp,
  Disc3,
} from 'lucide-react';
import type { NewRelease } from '../../api';

interface NewReleaseCardProps {
  release: NewRelease;
  onDismiss: (id: string) => void;
}

export function NewReleaseCard({ release, onDismiss }: NewReleaseCardProps) {
  const [showPurchaseLinks, setShowPurchaseLinks] = useState(false);
  const [isDismissing, setIsDismissing] = useState(false);

  const handleDismiss = async () => {
    setIsDismissing(true);
    try {
      await onDismiss(release.id);
    } finally {
      setIsDismissing(false);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return null;
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  const releaseTypeLabel = release.release_type
    ? release.release_type.charAt(0).toUpperCase() + release.release_type.slice(1)
    : 'Release';

  const purchaseLinks = Object.entries(release.purchase_links || {});

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg overflow-hidden border border-zinc-700/50 dark:border-zinc-700/50 light:border-zinc-200 hover:border-zinc-600 dark:hover:border-zinc-600 light:hover:border-zinc-300 transition-colors">
      {/* Artwork and main info */}
      <div className="flex gap-4 p-4">
        {/* Artwork */}
        <div className="flex-shrink-0 w-20 h-20 rounded-md bg-zinc-700 dark:bg-zinc-700 light:bg-zinc-200 overflow-hidden">
          {release.artwork_url ? (
            <img
              src={release.artwork_url}
              alt={`${release.release_name} artwork`}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <Disc3 className="w-8 h-8 text-zinc-500" />
            </div>
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h4 className="font-medium text-white dark:text-white light:text-zinc-900 truncate">
                {release.release_name}
              </h4>
              <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600 truncate">
                {release.artist_name}
              </p>
            </div>
            <button
              onClick={handleDismiss}
              disabled={isDismissing}
              className="flex-shrink-0 p-1 text-zinc-500 hover:text-zinc-300 dark:hover:text-zinc-300 light:hover:text-zinc-700 disabled:opacity-50"
              title="Dismiss"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex items-center gap-2 mt-2 text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-500">
            <span className="px-1.5 py-0.5 rounded bg-zinc-700/50 dark:bg-zinc-700/50 light:bg-zinc-200">
              {releaseTypeLabel}
            </span>
            {release.release_date && (
              <span>{formatDate(release.release_date)}</span>
            )}
            {release.track_count && (
              <span className="flex items-center gap-1">
                <Music className="w-3 h-3" />
                {release.track_count} tracks
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="px-4 pb-4 flex flex-wrap gap-2">
        {/* External link (Spotify/MusicBrainz) */}
        {release.external_url && (
          <a
            href={release.external_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded bg-zinc-700 dark:bg-zinc-700 light:bg-zinc-200 text-zinc-300 dark:text-zinc-300 light:text-zinc-700 hover:bg-zinc-600 dark:hover:bg-zinc-600 light:hover:bg-zinc-300 transition-colors"
          >
            <ExternalLink className="w-3 h-3" />
            {release.source === 'spotify' ? 'Spotify' : 'MusicBrainz'}
          </a>
        )}

        {/* Purchase links toggle */}
        {purchaseLinks.length > 0 && (
          <button
            onClick={() => setShowPurchaseLinks(!showPurchaseLinks)}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded bg-green-600/20 text-green-400 hover:bg-green-600/30 transition-colors"
          >
            <ShoppingCart className="w-3 h-3" />
            Buy
            {showPurchaseLinks ? (
              <ChevronUp className="w-3 h-3" />
            ) : (
              <ChevronDown className="w-3 h-3" />
            )}
          </button>
        )}
      </div>

      {/* Purchase links dropdown */}
      {showPurchaseLinks && purchaseLinks.length > 0 && (
        <div className="px-4 pb-4 border-t border-zinc-700/50 dark:border-zinc-700/50 light:border-zinc-200 pt-3">
          <p className="text-xs text-zinc-500 mb-2">Search stores:</p>
          <div className="flex flex-wrap gap-2">
            {purchaseLinks.map(([key, link]) => (
              <a
                key={key}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded bg-zinc-700 dark:bg-zinc-700 light:bg-zinc-200 text-zinc-300 dark:text-zinc-300 light:text-zinc-700 hover:bg-zinc-600 dark:hover:bg-zinc-600 light:hover:bg-zinc-300 transition-colors"
              >
                <ExternalLink className="w-3 h-3" />
                {link.name}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
