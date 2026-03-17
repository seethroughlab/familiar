/**
 * AmbientNowPlaying — current snippet display with artwork and progress.
 */

import { tracksApi } from '../../api';
import { useThemeStore } from '../../stores/themeStore';
import type { AmbientSnippet } from '../../player/ambient/types';

interface Props {
  snippet: AmbientSnippet;
  snippetCurrentTime: number;
}

export function AmbientNowPlaying({ snippet, snippetCurrentTime }: Props) {
  const light = useThemeStore((s) => s.resolvedTheme === 'light');
  const { descriptor } = snippet;
  const snippetDuration = snippet.endTime - snippet.startTime;
  const progress = snippetDuration > 0 ? Math.min(snippetCurrentTime / snippetDuration, 1) : 0;

  return (
    <div className="flex flex-col items-center gap-4 px-6">
      {/* Artwork */}
      <div className="w-48 h-48 rounded-2xl overflow-hidden shadow-lg">
        <img
          src={tracksApi.getArtworkUrl(descriptor.track_id)}
          alt={descriptor.title || 'Album art'}
          className="w-full h-full object-cover"
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = 'none';
          }}
        />
      </div>

      {/* Badge */}
      <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${
        light ? 'bg-purple-100 text-purple-700' : 'bg-purple-900/40 text-purple-300'
      }`}>
        Ambient Mode
      </span>

      {/* Track info */}
      <div className="text-center">
        <div className={`text-lg font-semibold truncate max-w-[280px] ${light ? 'text-zinc-900' : 'text-white'}`}>
          {descriptor.title || 'Unknown'}
        </div>
        <div className={`text-sm truncate max-w-[280px] ${light ? 'text-zinc-500' : 'text-zinc-400'}`}>
          {descriptor.artist || 'Unknown'}
        </div>
        {descriptor.album && (
          <div className={`text-xs truncate max-w-[280px] mt-0.5 ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>
            {descriptor.album}
          </div>
        )}
      </div>

      {/* Progress bar */}
      <div className="w-full max-w-[280px]">
        <div className={`h-1 rounded-full overflow-hidden ${light ? 'bg-zinc-200' : 'bg-zinc-700'}`}>
          <div
            className="h-full bg-purple-500 rounded-full transition-all duration-300"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
        <div className="flex justify-between mt-1">
          <span className={`text-xs ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>
            {formatTime(snippetCurrentTime)}
          </span>
          <span className={`text-xs ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>
            {formatTime(snippetDuration)}
          </span>
        </div>
      </div>
    </div>
  );
}

function formatTime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}
