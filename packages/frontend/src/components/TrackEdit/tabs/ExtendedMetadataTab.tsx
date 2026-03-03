import type { TrackMetadataUpdate } from '../../../api';

interface Props {
  formData: Partial<TrackMetadataUpdate>;
  onChange: (field: keyof TrackMetadataUpdate, value: unknown) => void;
  isBulkEdit?: boolean;
  disabledFields?: Set<string>;
}

export function ExtendedMetadataTab({ formData, onChange, isBulkEdit, disabledFields }: Props) {
  return (
    <div className="space-y-4">
      {/* Composer */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Composer</label>
        <input
          type="text"
          value={formData.composer ?? ''}
          onChange={(e) => onChange('composer', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : 'Composer name'}
          disabled={disabledFields?.has('composer')}
          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent ${disabledFields?.has('composer') ? 'opacity-50 cursor-not-allowed' : ''}`}
        />
      </div>

      {/* Conductor */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Conductor</label>
        <input
          type="text"
          value={formData.conductor ?? ''}
          onChange={(e) => onChange('conductor', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : 'Conductor name'}
          disabled={disabledFields?.has('conductor')}
          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent ${disabledFields?.has('conductor') ? 'opacity-50 cursor-not-allowed' : ''}`}
        />
      </div>

      {/* Lyricist */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Lyricist</label>
        <input
          type="text"
          value={formData.lyricist ?? ''}
          onChange={(e) => onChange('lyricist', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : 'Lyricist name'}
          disabled={disabledFields?.has('lyricist')}
          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent ${disabledFields?.has('lyricist') ? 'opacity-50 cursor-not-allowed' : ''}`}
        />
      </div>

      {/* Grouping */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Grouping</label>
        <input
          type="text"
          value={formData.grouping ?? ''}
          onChange={(e) => onChange('grouping', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : 'Grouping or category'}
          disabled={disabledFields?.has('grouping')}
          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent ${disabledFields?.has('grouping') ? 'opacity-50 cursor-not-allowed' : ''}`}
        />
        <p className="text-xs text-zinc-500 mt-1">
          Use grouping to organize tracks by theme, mood, or custom categories
        </p>
      </div>

      {/* Comment */}
      <div>
        <label className="block text-sm font-medium text-zinc-300 mb-1">Comment</label>
        <textarea
          value={formData.comment ?? ''}
          onChange={(e) => onChange('comment', e.target.value || null)}
          placeholder={isBulkEdit ? '(Mixed)' : 'Notes or comments about this track'}
          rows={3}
          disabled={disabledFields?.has('comment')}
          className={`w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent resize-none ${disabledFields?.has('comment') ? 'opacity-50 cursor-not-allowed' : ''}`}
        />
      </div>
    </div>
  );
}
