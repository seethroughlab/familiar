import type { TrackMetadataUpdate } from '../../../api';

interface Props {
  formData: Partial<TrackMetadataUpdate>;
  onChange: (field: keyof TrackMetadataUpdate, value: unknown) => void;
}

export function LyricsTab({ formData, onChange }: Props) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-400">
        Edit the lyrics embedded in this track. Lyrics are stored as plain text.
      </p>

      <textarea
        value={formData.lyrics ?? ''}
        onChange={(e) => onChange('lyrics', e.target.value || null)}
        placeholder="Enter lyrics here..."
        rows={16}
        className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent resize-none font-mono text-sm leading-relaxed"
      />

      <div className="flex justify-between text-xs text-zinc-500">
        <span>
          {formData.lyrics ? formData.lyrics.split('\n').length : 0} lines
        </span>
        <span>
          {formData.lyrics ? formData.lyrics.length : 0} characters
        </span>
      </div>
    </div>
  );
}
