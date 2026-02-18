/**
 * WishlistRoute - Route wrapper that fetches wishlist and renders PlaylistDetail.
 */
import { Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { playlistsApi } from '../../api/client';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { PlaylistDetail } from './PlaylistDetail';

export function WishlistRoute() {
  const navigate = useNavigate();
  const { isOffline } = useOfflineStatus();

  const { data: wishlist, isLoading } = useQuery({
    queryKey: ['wishlist'],
    queryFn: () => playlistsApi.getWishlist(),
    retry: isOffline ? false : 3,
  });

  if (isLoading || !wishlist?.id) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  return (
    <PlaylistDetail
      playlistId={wishlist.id}
      onBack={() => navigate(-1)}
    />
  );
}
