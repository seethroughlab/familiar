import {
  ArrowUp,
  ArrowDown,
  Minus,
  RefreshCw,
} from 'lucide-react';
import type { EditableTrack } from './types';
import { formatQuality } from './types';

interface DuplicatePanelProps {
  tracks: EditableTrack[];
  onSetTrackAction: (duplicateIdx: number, action: 'import' | 'replace' | 'skip') => void;
  onReplaceAllUpgrades: () => void;
  onSkipAllDowngrades: () => void;
}

export function DuplicatePanel({
  tracks,
  onSetTrackAction,
  onReplaceAllUpgrades,
  onSkipAllDowngrades,
}: DuplicatePanelProps) {
  const duplicates = tracks.filter((t) => t.duplicate_of);
  if (duplicates.length === 0) return null;

  const upgradeCount = tracks.filter((t) => t.trump_status === 'trumps').length;
  const downgradeCount = tracks.filter((t) => t.trump_status === 'trumped_by').length;
  const equalCount = tracks.filter((t) => t.trump_status === 'equal').length;

  return (
    <div className="space-y-3">
      {/* Summary badges */}
      <div className="flex items-center gap-3">
        <span className="text-sm text-zinc-400">Duplicates found:</span>
        {upgradeCount > 0 && (
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-green-500/20 text-green-400 text-xs font-medium rounded">
            <ArrowUp className="w-3 h-3" />
            {upgradeCount} upgrade{upgradeCount !== 1 ? 's' : ''}
          </span>
        )}
        {downgradeCount > 0 && (
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-red-500/20 text-red-400 text-xs font-medium rounded">
            <ArrowDown className="w-3 h-3" />
            {downgradeCount} downgrade{downgradeCount !== 1 ? 's' : ''}
          </span>
        )}
        {equalCount > 0 && (
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-zinc-500/20 text-zinc-400 text-xs font-medium rounded">
            <Minus className="w-3 h-3" />
            {equalCount} same
          </span>
        )}
        {/* Bulk actions */}
        <div className="ml-auto flex items-center gap-2">
          {tracks.some((t) => t.trump_status === 'trumps') && (
            <button
              onClick={onReplaceAllUpgrades}
              className="px-2 py-0.5 text-xs bg-green-600/20 text-green-400 hover:bg-green-600/40 rounded transition-colors"
            >
              Replace all upgrades
            </button>
          )}
          {tracks.some((t) => t.trump_status === 'trumped_by' || t.trump_status === 'equal') && (
            <button
              onClick={onSkipAllDowngrades}
              className="px-2 py-0.5 text-xs bg-zinc-600/20 text-zinc-400 hover:bg-zinc-600/40 rounded transition-colors"
            >
              Skip all downgrades
            </button>
          )}
        </div>
      </div>

      {/* Duplicate tracks with quality comparison */}
      <div className="bg-zinc-800/50 rounded-lg border border-zinc-700/50 divide-y divide-zinc-700/50 max-h-48 overflow-y-auto">
        {duplicates.map((track, idx) => (
          <div key={track.relative_path} className="p-3">
            <div className="flex items-start gap-3">
              {/* Quality indicator */}
              <div className="flex-shrink-0 mt-0.5">
                {track.trump_status === 'trumps' && (
                  <div className="w-6 h-6 rounded-full bg-green-500/20 flex items-center justify-center" title="Better quality">
                    <ArrowUp className="w-4 h-4 text-green-400" />
                  </div>
                )}
                {track.trump_status === 'trumped_by' && (
                  <div className="w-6 h-6 rounded-full bg-red-500/20 flex items-center justify-center" title="Lower quality">
                    <ArrowDown className="w-4 h-4 text-red-400" />
                  </div>
                )}
                {track.trump_status === 'equal' && (
                  <div className="w-6 h-6 rounded-full bg-zinc-500/20 flex items-center justify-center" title="Same quality">
                    <Minus className="w-4 h-4 text-zinc-400" />
                  </div>
                )}
              </div>

              {/* Track info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">
                  {track.artist || track.detected_artist} - {track.title || track.detected_title}
                </p>
                <div className="flex items-center gap-2 mt-1 text-xs">
                  <span className={track.trump_status === 'trumps' ? 'text-green-400' : track.trump_status === 'trumped_by' ? 'text-zinc-400' : 'text-zinc-400'}>
                    New: {formatQuality(track.incoming_quality)}
                  </span>
                  <span className="text-zinc-600">vs</span>
                  <span className={track.trump_status === 'trumped_by' ? 'text-green-400' : track.trump_status === 'trumps' ? 'text-zinc-400' : 'text-zinc-400'}>
                    Library: {formatQuality(track.existing_quality)}
                  </span>
                </div>
                {track.trump_reason && (
                  <p className="text-xs text-zinc-500 mt-0.5">{track.trump_reason}</p>
                )}
                {track.duplicate_match_type === 'artist_title' && track.duplicate_info && (
                  <p className="text-xs text-amber-400/80 mt-0.5">
                    Matched by artist + title only (different album: {track.duplicate_info.split(' - ')[1] || 'unknown'})
                  </p>
                )}
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  onClick={() => onSetTrackAction(idx, 'skip')}
                  className={`px-2 py-1 text-xs rounded transition-colors ${
                    track.action === 'skip'
                      ? 'bg-zinc-600 text-white'
                      : 'bg-zinc-700/50 text-zinc-400 hover:text-white hover:bg-zinc-700'
                  }`}
                >
                  Skip
                </button>
                {track.trump_status === 'trumps' && (
                  <button
                    onClick={() => onSetTrackAction(idx, 'replace')}
                    className={`px-2 py-1 text-xs rounded transition-colors ${
                      track.action === 'replace'
                        ? 'bg-green-600 text-white'
                        : 'bg-green-600/20 text-green-400 hover:bg-green-600/40'
                    }`}
                  >
                    <RefreshCw className="w-3 h-3 inline mr-1" />
                    Replace
                  </button>
                )}
                {track.trump_status !== 'trumps' && (
                  <button
                    onClick={() => onSetTrackAction(idx, 'import')}
                    className={`px-2 py-1 text-xs rounded transition-colors ${
                      track.action === 'import'
                        ? 'bg-amber-600 text-white'
                        : 'bg-amber-600/20 text-amber-400 hover:bg-amber-600/40'
                    }`}
                    title={track.trump_status === 'trumped_by' ? 'Import anyway (not recommended)' : 'Import as duplicate'}
                  >
                    Import
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
