/**
 * Favorite toggle button for individual tracks.
 * Supports both local and external tracks via isExternal prop.
 */
import { Heart } from 'lucide-react';
import { useFavorites } from '../../../../hooks/useFavorites';

export function FavoriteButton({ trackId, isExternal = false }: { trackId: string; isExternal?: boolean }) {
  const { isFavorite, toggle, isExternalFavorite, toggleExternal } = useFavorites();
  const favorited = isExternal ? isExternalFavorite(trackId) : isFavorite(trackId);

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        if (isExternal) {
          toggleExternal(trackId);
        } else {
          toggle(trackId);
        }
      }}
      aria-pressed={favorited}
      aria-label={favorited ? 'Remove from favorites' : 'Add to favorites'}
      className={`p-1 transition-colors ${
        favorited
          ? 'text-pink-500 hover:text-pink-400'
          : 'text-zinc-500 hover:text-pink-400 opacity-100 sm:opacity-0 sm:group-hover:opacity-100'
      }`}
      title={favorited ? 'Remove from favorites' : 'Add to favorites'}
    >
      <Heart className="w-4 h-4" fill={favorited ? 'currentColor' : 'none'} />
    </button>
  );
}
