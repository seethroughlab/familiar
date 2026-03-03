import type { TrackMetadataUpdate } from '../../../api';

interface Props {
  formData: Partial<TrackMetadataUpdate>;
  onChange: (field: keyof TrackMetadataUpdate, value: unknown) => void;
  isBulkEdit?: boolean;
  disabledFields?: Set<string>;
}

export function SortFieldsTab({ formData, onChange, isBulkEdit, disabledFields }: Props) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-400 mb-4">
        Sort fields control how tracks are alphabetized. Use these to ensure proper sorting
        for names with articles (The Beatles &rarr; Beatles, The) or non-Latin characters.
      </p>

      {/* Sort Artist */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Sort Artist</label>
        <input
          type="text"
          value={formData.sort_artist ?? ''}
          onChange={(e) => onChange('sort_artist', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : formData.artist || 'Sort artist name'}
          disabled={disabledFields?.has('sort_artist')}
          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent ${disabledFields?.has('sort_artist') ? 'opacity-50 cursor-not-allowed' : ''}`}
        />
        <p className="text-xs text-zinc-500 mt-1">
          Example: "Beatles, The" for "The Beatles"
        </p>
      </div>

      {/* Sort Album */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Sort Album</label>
        <input
          type="text"
          value={formData.sort_album ?? ''}
          onChange={(e) => onChange('sort_album', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : formData.album || 'Sort album name'}
          disabled={disabledFields?.has('sort_album')}
          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent ${disabledFields?.has('sort_album') ? 'opacity-50 cursor-not-allowed' : ''}`}
        />
      </div>

      {/* Sort Title */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Sort Title</label>
        <input
          type="text"
          value={formData.sort_title ?? ''}
          onChange={(e) => onChange('sort_title', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : formData.title || 'Sort title'}
          disabled={disabledFields?.has('sort_title')}
          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent ${disabledFields?.has('sort_title') ? 'opacity-50 cursor-not-allowed' : ''}`}
        />
      </div>
    </div>
  );
}
