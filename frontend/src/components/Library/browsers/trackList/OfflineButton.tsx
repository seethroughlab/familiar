/**
 * Offline download button for individual tracks.
 * Shows download/downloaded/downloading state with progress.
 */
import { Download, Check, Loader2 } from 'lucide-react';
import { useOfflineTrack } from '../../../../hooks/useOfflineTrack';

export function OfflineButton({ trackId }: { trackId: string }) {
  const { isOffline, isDownloading, downloadProgress, download, remove } = useOfflineTrack(trackId);

  if (isDownloading) {
    return (
      <div
        className="relative p-1 text-purple-400"
        role="status"
        aria-label={`Downloading, ${downloadProgress} percent`}
        title={`Downloading... ${downloadProgress}%`}
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        {downloadProgress > 0 && downloadProgress < 100 && (
          <span className="absolute -bottom-1 left-1/2 -translate-x-1/2 text-[8px] font-medium">
            {downloadProgress}%
          </span>
        )}
      </div>
    );
  }

  if (isOffline) {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation();
          remove();
        }}
        aria-label="Remove offline copy"
        className="p-1 text-green-500 hover:text-red-400 transition-colors"
        title="Remove offline copy"
      >
        <Check className="w-4 h-4" />
      </button>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        download();
      }}
      aria-label="Download for offline"
      className="p-1 text-zinc-500 hover:text-white transition-colors opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
      title="Download for offline"
    >
      <Download className="w-4 h-4" />
    </button>
  );
}
