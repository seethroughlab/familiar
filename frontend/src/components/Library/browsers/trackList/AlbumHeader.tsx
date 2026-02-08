/**
 * Album header component displayed when viewing a single album.
 * Shows artwork, album info, play button, and offline download button.
 */
import { Play, Download, Check, Loader2, Disc, Clock } from 'lucide-react';
import { useOfflineAlbum } from '../../../../hooks/useOfflineAlbum';
import { AlbumArtwork } from '../../../AlbumArtwork';

interface AlbumTrack {
  id: string;
}

interface AlbumOfflineButtonProps {
  tracks: AlbumTrack[];
  artist: string;
  album: string;
}

function AlbumOfflineButton({ tracks, artist, album }: AlbumOfflineButtonProps) {
  const {
    offlineCount,
    totalCount,
    isFullyOffline,
    isPartiallyOffline,
    isDownloading,
    currentTrack,
    overallProgress,
    download,
    remove,
  } = useOfflineAlbum(tracks, { artist, album });

  if (isDownloading) {
    return (
      <button
        className="flex items-center gap-2 px-4 py-2 bg-zinc-700 rounded-full transition-colors"
        title={`Downloading track ${currentTrack} of ${totalCount}...`}
      >
        <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
        <span className="text-sm">{overallProgress}%</span>
      </button>
    );
  }

  if (isFullyOffline) {
    return (
      <button
        onClick={remove}
        className="flex items-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-full transition-colors"
        title="Remove offline copies"
      >
        <Check className="w-4 h-4 text-green-500" />
        <span className="text-sm">Downloaded</span>
      </button>
    );
  }

  return (
    <button
      onClick={download}
      className="flex items-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-full transition-colors"
      title={isPartiallyOffline ? `Download remaining ${totalCount - offlineCount} tracks` : 'Download album for offline'}
    >
      <Download className="w-4 h-4" />
      <span className="text-sm">
        {isPartiallyOffline ? `${offlineCount}/${totalCount}` : 'Download'}
      </span>
    </button>
  );
}

export interface AlbumStats {
  artist: string;
  album: string;
  year: number | null;
  trackCount: number;
  totalDuration: number;
  firstTrackId: string | undefined;
}

interface AlbumHeaderProps {
  albumStats: AlbumStats;
  tracks: { id: string }[];
  isLoadingPlayAll: boolean;
  onPlayAll: () => void;
  onGoToArtist: (artistName: string) => void;
}

function formatTotalDuration(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (hours > 0) {
    return `${hours}h ${mins}m`;
  }
  return `${mins} min`;
}

export function AlbumHeader({
  albumStats,
  tracks,
  isLoadingPlayAll,
  onPlayAll,
  onGoToArtist,
}: AlbumHeaderProps) {
  return (
    <div className="flex items-start gap-4 md:gap-6 p-4 mb-4 bg-zinc-800/30 rounded-lg">
      {/* Album artwork */}
      <div className="w-24 h-24 md:w-40 md:h-40 rounded-lg overflow-hidden flex-shrink-0 shadow-lg">
        <AlbumArtwork
          artist={albumStats.artist}
          album={albumStats.album}
          trackId={albumStats.firstTrackId}
          size="full"
          className="w-full h-full"
        />
      </div>

      {/* Album info */}
      <div className="flex-1 min-w-0 py-1">
        <div className="text-xs text-zinc-400 uppercase tracking-wider mb-1">Album</div>
        <h2 className="text-xl md:text-2xl font-bold truncate mb-2">{albumStats.album}</h2>

        {/* Artist (clickable) */}
        <button
          onClick={() => onGoToArtist(albumStats.artist)}
          className="text-zinc-300 hover:text-white hover:underline truncate block mb-2"
        >
          {albumStats.artist}
        </button>

        {/* Stats row */}
        <div className="flex items-center gap-4 text-sm text-zinc-400">
          {albumStats.year && <span>{albumStats.year}</span>}
          <span className="flex items-center gap-1">
            <Disc className="w-4 h-4" />
            {albumStats.trackCount} tracks
          </span>
          <span className="flex items-center gap-1">
            <Clock className="w-4 h-4" />
            {formatTotalDuration(albumStats.totalDuration)}
          </span>
        </div>

        {/* Play and Download buttons */}
        <div className="mt-4 flex items-center gap-2">
          <button
            onClick={onPlayAll}
            disabled={isLoadingPlayAll}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-full transition-colors"
          >
            {isLoadingPlayAll ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" fill="currentColor" />
            )}
            Play
          </button>
          <AlbumOfflineButton
            tracks={tracks}
            artist={albumStats.artist}
            album={albumStats.album}
          />
        </div>
      </div>
    </div>
  );
}
