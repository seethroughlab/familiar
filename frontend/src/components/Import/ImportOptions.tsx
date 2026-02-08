import type { FormatOption, OrganizationOption, PreviewResponse } from './types';
import { formatBytes } from './types';

interface ImportOptionsProps {
  hasConvertible: boolean;
  format: FormatOption;
  mp3Quality: number;
  organization: OrganizationOption;
  queueAnalysis: boolean;
  estimatedSizes: PreviewResponse['estimated_sizes'] | null;
  onSetFormat: (format: FormatOption) => void;
  onSetMp3Quality: (quality: number) => void;
  onSetOrganization: (organization: OrganizationOption) => void;
  onSetQueueAnalysis: (queueAnalysis: boolean) => void;
}

export function ImportOptions({
  hasConvertible,
  format,
  mp3Quality,
  organization,
  queueAnalysis,
  estimatedSizes,
  onSetFormat,
  onSetMp3Quality,
  onSetOrganization,
  onSetQueueAnalysis,
}: ImportOptionsProps) {
  return (
    <>
      {/* Format options */}
      {hasConvertible && (
        <div>
          <h3 className="text-sm font-medium text-zinc-400 mb-2">Format</h3>
          <div className="space-y-2" role="radiogroup" aria-label="Format options">
            <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
              <input
                type="radio"
                name="format"
                checked={format === 'original'}
                onChange={() => onSetFormat('original')}
                className="text-green-500"
              />
              <div className="flex-1">
                <span className="text-white">Keep Original</span>
                <span className="text-zinc-500 text-sm ml-2">
                  {formatBytes(estimatedSizes?.original || 0)}
                </span>
              </div>
            </label>
            <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
              <input
                type="radio"
                name="format"
                checked={format === 'flac'}
                onChange={() => onSetFormat('flac')}
                className="text-green-500"
              />
              <div className="flex-1">
                <span className="text-white">Convert to FLAC</span>
                <span className="text-zinc-500 text-sm ml-2">
                  {formatBytes(estimatedSizes?.flac || 0)}
                </span>
                <span className="text-xs text-green-400 ml-2">Lossless</span>
              </div>
            </label>
            <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
              <input
                type="radio"
                name="format"
                checked={format === 'mp3'}
                onChange={() => onSetFormat('mp3')}
                className="text-green-500"
              />
              <div className="flex-1 flex items-center gap-2">
                <span className="text-white">Convert to MP3</span>
                <select
                  value={mp3Quality}
                  onChange={(e) => onSetMp3Quality(parseInt(e.target.value))}
                  onClick={(e) => e.stopPropagation()}
                  aria-label="MP3 quality"
                  className="px-2 py-0.5 bg-zinc-700 border border-zinc-600 rounded text-sm text-white"
                >
                  <option value={320}>320 kbps</option>
                  <option value={192}>192 kbps</option>
                  <option value={128}>128 kbps</option>
                </select>
                <span className="text-zinc-500 text-sm">
                  {formatBytes(estimatedSizes?.mp3_320 || 0)}
                </span>
              </div>
            </label>
          </div>
        </div>
      )}

      {/* Organization options */}
      <div>
        <h3 className="text-sm font-medium text-zinc-400 mb-2">Organization</h3>
        <div className="space-y-2" role="radiogroup" aria-label="Organization options">
          <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
            <input
              type="radio"
              name="organization"
              checked={organization === 'organized'}
              onChange={() => onSetOrganization('organized')}
              className="text-green-500"
            />
            <div>
              <span className="text-white">Organize into folders</span>
              <p className="text-xs text-zinc-500">Artist / Album / ## - Title.ext</p>
            </div>
          </label>
          <label className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg cursor-pointer hover:bg-zinc-800 transition-colors">
            <input
              type="radio"
              name="organization"
              checked={organization === 'imports'}
              onChange={() => onSetOrganization('imports')}
              className="text-green-500"
            />
            <div>
              <span className="text-white">Import to _imports folder</span>
              <p className="text-xs text-zinc-500">Flat structure, timestamped folder</p>
            </div>
          </label>
        </div>
      </div>

      {/* Additional options */}
      <div className="space-y-3">
        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={queueAnalysis}
            onChange={(e) => onSetQueueAnalysis(e.target.checked)}
            className="rounded text-green-500"
          />
          <span className="text-sm text-zinc-300">
            Queue for audio analysis after import
          </span>
        </label>
      </div>
    </>
  );
}
