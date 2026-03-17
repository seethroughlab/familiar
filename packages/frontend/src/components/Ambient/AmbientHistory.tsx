/**
 * AmbientHistory — scrollable list of recently played snippets.
 */

import { Clock } from 'lucide-react';
import { useThemeStore } from '../../stores/themeStore';
import type { AmbientSnippet } from '../../player/ambient/types';

interface Props {
  history: AmbientSnippet[];
}

export function AmbientHistory({ history }: Props) {
  const light = useThemeStore((s) => s.resolvedTheme === 'light');

  if (history.length === 0) return null;

  return (
    <div className="px-4">
      <div className={`flex items-center gap-1.5 mb-2 text-xs font-semibold uppercase tracking-wider ${
        light ? 'text-zinc-400' : 'text-zinc-500'
      }`}>
        <Clock className="w-3 h-3" />
        <span>History</span>
      </div>
      <div className="flex flex-col gap-1">
        {[...history].reverse().map((snippet, i) => (
          <div
            key={`${snippet.descriptor.track_id}-${i}`}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg ${
              light ? 'bg-zinc-50' : 'bg-zinc-800/50'
            }`}
          >
            <div className="flex-1 min-w-0">
              <div className={`text-sm truncate ${light ? 'text-zinc-700' : 'text-zinc-300'}`}>
                {snippet.descriptor.title || 'Unknown'}
              </div>
              <div className={`text-xs truncate ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>
                {snippet.descriptor.artist || 'Unknown'}
              </div>
            </div>
            <span className={`text-xs flex-shrink-0 ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>
              {Math.round(snippet.compatibility_score * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
