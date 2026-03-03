import {
  Music,
  FileArchive,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  RotateCcw,
} from 'lucide-react';
import type { EditableTrack, EditableField, BulkEditField } from './types';
import { formatDuration } from './types';

interface TrackEditTableProps {
  tracks: EditableTrack[];
  expandedTracks: boolean;
  hasAnyEdits: boolean;
  bulkArtist: string;
  bulkAlbum: string;
  bulkYear: string;
  onSetExpandedTracks: (expanded: boolean) => void;
  onSetBulkArtist: (value: string) => void;
  onSetBulkAlbum: (value: string) => void;
  onSetBulkYear: (value: string) => void;
  onUpdateTrack: (index: number, field: EditableField, value: string | number | null) => void;
  onResetTrackField: (index: number, field: EditableField) => void;
  onResetTrack: (index: number) => void;
  onResetAllTracks: () => void;
  onApplyToAll: (field: BulkEditField, value: string | number | null) => void;
}

export function TrackEditTable({
  tracks,
  expandedTracks,
  hasAnyEdits,
  bulkArtist,
  bulkAlbum,
  bulkYear,
  onSetExpandedTracks,
  onSetBulkArtist,
  onSetBulkAlbum,
  onSetBulkYear,
  onUpdateTrack,
  onResetTrackField,
  onResetTrack,
  onResetAllTracks,
  onApplyToAll,
}: TrackEditTableProps) {
  return (
    <div className="space-y-3">
      {/* Header with expand/collapse and reset */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => onSetExpandedTracks(!expandedTracks)}
          className="flex items-center gap-2 text-sm text-zinc-400 hover:text-white"
        >
          {expandedTracks ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          {expandedTracks ? 'Show summary' : 'Edit track details'}
        </button>
        {expandedTracks && hasAnyEdits && (
          <button
            onClick={onResetAllTracks}
            className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            title="Reset all tracks to detected values"
          >
            <RotateCcw className="w-3 h-3" />
            Reset all
          </button>
        )}
      </div>

      {expandedTracks ? (
        <>
          {/* Bulk edit section */}
          {tracks.length > 1 && (
            <div className="p-3 bg-zinc-800/50 rounded-lg border border-zinc-700/50">
              <p className="text-xs font-medium text-zinc-400 mb-2">Apply to all tracks</p>
              <div className="flex gap-2">
                <div className="flex-1">
                  <label htmlFor="bulk-artist" className="text-xs text-zinc-500 mb-1 block">Artist</label>
                  <div className="flex gap-1">
                    <input
                      id="bulk-artist"
                      type="text"
                      value={bulkArtist}
                      onChange={(e) => onSetBulkArtist(e.target.value)}
                      placeholder="Enter artist..."
                      className="flex-1 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm text-white placeholder-zinc-500"
                    />
                    <button
                      onClick={() => { if (bulkArtist) { onApplyToAll('artist', bulkArtist); onSetBulkArtist(''); } }}
                      disabled={!bulkArtist}
                      className="px-2 py-1 text-xs bg-zinc-600 hover:bg-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded transition-colors"
                    >
                      Apply
                    </button>
                  </div>
                </div>
                <div className="flex-1">
                  <label htmlFor="bulk-album" className="text-xs text-zinc-500 mb-1 block">Album</label>
                  <div className="flex gap-1">
                    <input
                      id="bulk-album"
                      type="text"
                      value={bulkAlbum}
                      onChange={(e) => onSetBulkAlbum(e.target.value)}
                      placeholder="Enter album..."
                      className="flex-1 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm text-white placeholder-zinc-500"
                    />
                    <button
                      onClick={() => { if (bulkAlbum) { onApplyToAll('album', bulkAlbum); onSetBulkAlbum(''); } }}
                      disabled={!bulkAlbum}
                      className="px-2 py-1 text-xs bg-zinc-600 hover:bg-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded transition-colors"
                    >
                      Apply
                    </button>
                  </div>
                </div>
                <div className="w-28">
                  <label htmlFor="bulk-year" className="text-xs text-zinc-500 mb-1 block">Year</label>
                  <div className="flex gap-1">
                    <input
                      id="bulk-year"
                      type="number"
                      value={bulkYear}
                      onChange={(e) => onSetBulkYear(e.target.value)}
                      placeholder="YYYY"
                      className="w-16 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm text-white placeholder-zinc-500"
                    />
                    <button
                      onClick={() => { if (bulkYear) { onApplyToAll('year', parseInt(bulkYear)); onSetBulkYear(''); } }}
                      disabled={!bulkYear}
                      className="px-2 py-1 text-xs bg-zinc-600 hover:bg-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded transition-colors"
                    >
                      Apply
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Table header */}
          <div className="grid grid-cols-[40px_48px_1fr_1fr_1fr_64px_32px] gap-2 px-2 text-xs font-medium text-zinc-500 border-b border-zinc-700/50 pb-2">
            <div></div>
            <div>#</div>
            <div>Title</div>
            <div>Artist</div>
            <div>Album</div>
            <div>Year</div>
            <div></div>
          </div>

          {/* Track rows */}
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {tracks.map((track, index) => (
              <div
                key={track.relative_path}
                className={`grid grid-cols-[40px_48px_1fr_1fr_1fr_64px_32px] gap-2 items-center py-1.5 px-2 rounded-lg ${
                  track.duplicate_of ? 'bg-amber-500/10 border border-amber-500/20' : 'bg-zinc-800/30 hover:bg-zinc-800/50'
                } transition-colors`}
              >
                {/* Icon and duration */}
                <div className="flex items-center justify-center">
                  {track.duplicate_of ? (
                    <span title={`Duplicate: ${track.duplicate_info}`}>
                      <AlertCircle className="w-4 h-4 text-amber-400" />
                    </span>
                  ) : track.format === 'zip' ? (
                    <FileArchive className="w-4 h-4 text-zinc-500" />
                  ) : (
                    <Music className="w-4 h-4 text-zinc-500" />
                  )}
                </div>

                {/* Track number */}
                <div className="relative">
                  <input
                    type="number"
                    value={track.track_num || ''}
                    onChange={(e) => onUpdateTrack(index, 'track_num', e.target.value ? parseInt(e.target.value) : null)}
                    aria-label={`Track number for ${track.title || track.filename}`}
                    placeholder="#"
                    className={`w-full px-1.5 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 text-center ${
                      track.editedFields.has('track_num') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                    }`}
                  />
                </div>

                {/* Title */}
                <div className="relative group">
                  <input
                    type="text"
                    value={track.title}
                    onChange={(e) => onUpdateTrack(index, 'title', e.target.value)}
                    aria-label={`Title for track ${index + 1}`}
                    placeholder="Title"
                    title={track.filename}
                    className={`w-full px-2 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 ${
                      track.editedFields.has('title') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                    }`}
                  />
                  {track.editedFields.has('title') && (
                    <button
                      onClick={() => onResetTrackField(index, 'title')}
                      className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 text-zinc-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                      title="Reset to detected value"
                    >
                      <RotateCcw className="w-3 h-3" />
                    </button>
                  )}
                </div>

                {/* Artist */}
                <div className="relative group">
                  <input
                    type="text"
                    value={track.artist}
                    onChange={(e) => onUpdateTrack(index, 'artist', e.target.value)}
                    aria-label={`Artist for ${track.title || `track ${index + 1}`}`}
                    placeholder="Artist"
                    className={`w-full px-2 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 ${
                      track.editedFields.has('artist') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                    }`}
                  />
                  {track.editedFields.has('artist') && (
                    <button
                      onClick={() => onResetTrackField(index, 'artist')}
                      className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 text-zinc-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                      title="Reset to detected value"
                    >
                      <RotateCcw className="w-3 h-3" />
                    </button>
                  )}
                </div>

                {/* Album */}
                <div className="relative group">
                  <input
                    type="text"
                    value={track.album}
                    onChange={(e) => onUpdateTrack(index, 'album', e.target.value)}
                    aria-label={`Album for ${track.title || `track ${index + 1}`}`}
                    placeholder="Album"
                    className={`w-full px-2 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 ${
                      track.editedFields.has('album') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                    }`}
                  />
                  {track.editedFields.has('album') && (
                    <button
                      onClick={() => onResetTrackField(index, 'album')}
                      className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 text-zinc-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                      title="Reset to detected value"
                    >
                      <RotateCcw className="w-3 h-3" />
                    </button>
                  )}
                </div>

                {/* Year */}
                <div className="relative group">
                  <input
                    type="number"
                    value={track.year || ''}
                    onChange={(e) => onUpdateTrack(index, 'year', e.target.value ? parseInt(e.target.value) : null)}
                    aria-label={`Year for ${track.title || `track ${index + 1}`}`}
                    placeholder="Year"
                    className={`w-full px-1.5 py-1 bg-zinc-700/50 border rounded text-sm text-white placeholder-zinc-500 text-center ${
                      track.editedFields.has('year') ? 'border-green-500/50 bg-green-500/10' : 'border-zinc-600/50'
                    }`}
                  />
                </div>

                {/* Reset track button */}
                <div className="flex justify-center">
                  {track.editedFields.size > 0 && (
                    <button
                      onClick={() => onResetTrack(index)}
                      className="p-1 text-zinc-500 hover:text-white transition-colors"
                      title="Reset all fields to detected values"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Legend */}
          <div className="flex items-center gap-4 text-xs text-zinc-500 pt-2 border-t border-zinc-700/50">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded border border-green-500/50 bg-green-500/10"></span>
              Edited field
            </span>
            <span className="flex items-center gap-1.5">
              <RotateCcw className="w-3 h-3" />
              Reset to detected
            </span>
          </div>
        </>
      ) : (
        /* Collapsed summary view */
        <div className="bg-zinc-800/50 rounded-lg p-3 max-h-32 overflow-y-auto">
          {tracks.slice(0, 5).map((track) => (
            <div key={track.relative_path} className="flex items-center gap-2 text-sm text-zinc-300 py-1">
              {track.duplicate_of ? (
                <AlertCircle className="w-3 h-3 text-amber-400 flex-shrink-0" />
              ) : (
                <Music className="w-3 h-3 text-zinc-500 flex-shrink-0" />
              )}
              <span className={`truncate ${track.duplicate_of ? 'text-amber-200' : ''}`}>
                {track.artist && track.title
                  ? `${track.artist} - ${track.title}`
                  : track.title || track.filename}
              </span>
              {track.editedFields.size > 0 && (
                <span className="text-xs text-green-400 flex-shrink-0">edited</span>
              )}
              <span className="ml-auto text-zinc-500 flex-shrink-0">{formatDuration(track.duration_seconds)}</span>
            </div>
          ))}
          {tracks.length > 5 && (
            <p className="text-xs text-zinc-500 mt-1">+{tracks.length - 5} more tracks</p>
          )}
        </div>
      )}
    </div>
  );
}
