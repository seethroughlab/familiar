import { useState, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Video,
  Download,
  Loader2,
  Search,
  Trash2,
  ExternalLink,
} from 'lucide-react';
import { videosApi, type VideoSearchResult } from '../../api/client';
import { usePlayerStore } from '../../stores/playerStore';

interface VideoPlayerProps {
  trackId: string;
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function VideoPlayer({ trackId }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const { currentTime, isPlaying } = usePlayerStore();
  const [showSearch, setShowSearch] = useState(false);
  const queryClient = useQueryClient();

  // Get video status
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ['video-status', trackId],
    queryFn: () => videosApi.getStatus(trackId),
    refetchInterval: (query) => {
      // Poll while downloading
      const dlStatus = query.state.data?.download_status;
      if (dlStatus === 'downloading' || dlStatus === 'pending') {
        return 1000;
      }
      return false;
    },
  });

  // Search for videos
  const {
    data: searchResults,
    isLoading: searchLoading,
    refetch: searchVideos,
  } = useQuery({
    queryKey: ['video-search', trackId],
    queryFn: () => videosApi.search(trackId),
    enabled: false, // Manual trigger only
  });

  // Download video mutation
  const downloadMutation = useMutation({
    mutationFn: ({ videoUrl }: { videoUrl: string }) =>
      videosApi.download(trackId, videoUrl),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['video-status', trackId] });
      setShowSearch(false);
    },
  });

  // Delete video mutation
  const deleteMutation = useMutation({
    mutationFn: () => videosApi.delete(trackId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['video-status', trackId] });
    },
  });

  // Sync video playback with audio
  useEffect(() => {
    if (videoRef.current && status?.has_video) {
      const video = videoRef.current;

      // Sync time if more than 0.5s off
      if (Math.abs(video.currentTime - currentTime) > 0.5) {
        video.currentTime = currentTime;
      }

      // Sync play/pause state
      if (isPlaying && video.paused) {
        video.play().catch(() => {});
      } else if (!isPlaying && !video.paused) {
        video.pause();
      }
    }
  }, [currentTime, isPlaying, status?.has_video]);

  // Reset search view when switching tracks
  useEffect(() => {
    setShowSearch(false);
  }, [trackId]);

  const handleSearchClick = () => {
    setShowSearch(true);
    searchVideos();
  };

  const handleDownload = (result: VideoSearchResult) => {
    downloadMutation.mutate({ videoUrl: result.url });
  };

  // Loading state
  if (statusLoading) {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-zinc-900">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  // Video available - show player
  if (status?.has_video) {
    return (
      <div className="absolute inset-0 bg-black">
        <video
          ref={videoRef}
          src={videosApi.getStreamUrl(trackId)}
          className="w-full h-full object-contain"
          muted // Muted since audio plays from the audio engine
          playsInline
        />
        <button
          onClick={() => deleteMutation.mutate()}
          className="absolute top-4 right-4 p-2 bg-black/50 hover:bg-red-500/50 rounded-full transition-colors"
          title="Delete video"
        >
          <Trash2 className="w-5 h-5" />
        </button>
      </div>
    );
  }

  // Search results view (before error/downloading so "Try again" works)
  if (showSearch) {
    return (
      <div className="absolute inset-0 bg-zinc-900 overflow-auto p-4 sm:p-6">
        <div className="max-w-2xl mx-auto">
          <h3 className="text-xl font-bold mb-4">Select a music video</h3>

          {searchLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
            </div>
          ) : searchResults && searchResults.length > 0 ? (
            <div className="space-y-3">
              {searchResults.map((result) => (
                <div
                  key={result.video_id}
                  className="flex gap-4 p-3 bg-zinc-800 hover:bg-zinc-700 rounded-lg transition-colors group"
                >
                  <img
                    src={result.thumbnail_url}
                    alt={result.title}
                    className="w-32 h-20 object-cover rounded flex-shrink-0"
                  />
                  <div className="flex-1 min-w-0">
                    <h4 className="font-medium truncate">{result.title}</h4>
                    <p className="text-sm text-zinc-400">{result.channel}</p>
                    <p className="text-sm text-zinc-500">
                      {formatDuration(result.duration)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <a
                      href={result.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-2 hover:bg-zinc-600 rounded-full transition-colors"
                      title="Open in YouTube"
                    >
                      <ExternalLink className="w-5 h-5" />
                    </a>
                    <button
                      onClick={() => handleDownload(result)}
                      disabled={downloadMutation.isPending}
                      className="p-2 bg-green-600 hover:bg-green-500 rounded-full transition-colors disabled:opacity-50"
                      title="Download this video"
                    >
                      {downloadMutation.isPending ? (
                        <Loader2 className="w-5 h-5 animate-spin" />
                      ) : (
                        <Download className="w-5 h-5" />
                      )}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-center text-zinc-500 py-12">
              No videos found for this track
            </p>
          )}

          <button
            onClick={() => setShowSearch(false)}
            className="mt-6 text-zinc-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  // Downloading state
  if (status?.download_status === 'downloading' || status?.download_status === 'pending') {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-900">
        <Loader2 className="w-12 h-12 animate-spin text-green-500 mb-4" />
        <p className="text-white text-lg">Downloading video...</p>
        <div className="w-48 sm:w-64 h-2 bg-zinc-700 rounded-full mt-4 overflow-hidden">
          <div
            className="h-full bg-green-500 transition-all duration-300"
            style={{ width: `${status.progress || 0}%` }}
          />
        </div>
        <p className="text-zinc-400 mt-2">{Math.round(status.progress || 0)}%</p>
      </div>
    );
  }

  // Error state
  if (status?.download_status === 'error') {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-900">
        <Video className="w-16 h-16 text-red-500 mb-4 opacity-50" />
        <p className="text-red-400">Download failed</p>
        <p className="text-sm text-zinc-500 mt-2">{status.error}</p>
        <button
          onClick={handleSearchClick}
          className="mt-4 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg transition-colors"
        >
          Try again
        </button>
      </div>
    );
  }

  // No video - show search prompt
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-900">
      <Video className="w-16 h-16 text-zinc-600 mb-4" />
      <p className="text-zinc-400 mb-4">No music video available</p>
      <button
        onClick={handleSearchClick}
        className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg transition-colors"
      >
        <Search className="w-5 h-5" />
        Find music video
      </button>
      <p className="text-sm text-zinc-600 mt-4">
        Search YouTube for the official music video
      </p>
    </div>
  );
}
