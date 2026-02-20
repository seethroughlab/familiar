import type { TrackMetadataUpdate } from '../../../api';
import { AutoPopulateButton } from '../AutoPopulateButton';
import { MusicBrainzLookup } from '../MusicBrainzLookup';

interface Props {
  formData: Partial<TrackMetadataUpdate>;
  onChange: (field: keyof TrackMetadataUpdate, value: unknown) => void;
  isBulkEdit?: boolean;
  trackId?: string;
}

export function BasicMetadataTab({ formData, onChange, isBulkEdit, trackId }: Props) {
  // Handle applying metadata from lookup (MusicBrainz or AutoPopulate)
  const handleApplyLookup = (metadata: Partial<TrackMetadataUpdate>) => {
    Object.entries(metadata).forEach(([field, value]) => {
      if (value !== null && value !== undefined) {
        onChange(field as keyof TrackMetadataUpdate, value);
      }
    });
  };

  return (
    <div className="space-y-4">
      {/* Title */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Title</label>
        <input
          type="text"
          value={formData.title ?? ''}
          onChange={(e) => onChange('title', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : 'Track title'}
          className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
        />
      </div>

      {/* Artist */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Artist</label>
        <input
          type="text"
          value={formData.artist ?? ''}
          onChange={(e) => onChange('artist', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : 'Artist name'}
          className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
        />
      </div>

      {/* Album */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Album</label>
        <input
          type="text"
          value={formData.album ?? ''}
          onChange={(e) => onChange('album', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : 'Album name'}
          className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
        />
      </div>

      {/* Album Artist */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Album Artist</label>
        <input
          type="text"
          value={formData.album_artist ?? ''}
          onChange={(e) => onChange('album_artist', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : 'Album artist (for compilations)'}
          className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
        />
      </div>

      {/* Track & Disc Numbers */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-zinc-300 mb-1">Track Number</label>
          <input
            type="number"
            min="1"
            value={formData.track_number ?? ''}
            onChange={(e) => onChange('track_number', e.target.value ? parseInt(e.target.value) : null)}
            placeholder={isBulkEdit ? '(Mixed)' : '#'}
            className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-zinc-300 mb-1">Disc Number</label>
          <input
            type="number"
            min="1"
            value={formData.disc_number ?? ''}
            onChange={(e) => onChange('disc_number', e.target.value ? parseInt(e.target.value) : null)}
            placeholder={isBulkEdit ? '(Mixed)' : '#'}
            className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
        </div>
      </div>

      {/* Year & Genre */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-zinc-300 mb-1">Year</label>
          <input
            type="number"
            min="1900"
            max="2100"
            value={formData.year ?? ''}
            onChange={(e) => onChange('year', e.target.value ? parseInt(e.target.value) : null)}
            placeholder={isBulkEdit ? '(Mixed)' : 'YYYY'}
            className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-zinc-300 mb-1">Genre</label>
          <input
            type="text"
            value={formData.genre ?? ''}
            onChange={(e) => onChange('genre', e.target.value || null)}
            placeholder={isBulkEdit ? '(Mixed)' : 'Genre'}
            className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
        </div>
      </div>

      {/* Auto-populate and MusicBrainz Lookup - only for single track edit */}
      {!isBulkEdit && trackId && (
        <div className="pt-4 border-t border-zinc-800 space-y-3">
          {/* Primary: Audio fingerprint-based identification */}
          <AutoPopulateButton
            trackId={trackId}
            onApply={handleApplyLookup}
          />

          {/* Fallback: Text-based search */}
          <MusicBrainzLookup
            title={formData.title}
            artist={formData.artist}
            album={formData.album}
            onApply={handleApplyLookup}
          />
        </div>
      )}
    </div>
  );
}
