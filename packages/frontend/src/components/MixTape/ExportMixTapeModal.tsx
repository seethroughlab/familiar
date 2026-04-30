/**
 * Modal for kicking off a Mix Tape Export render.
 *
 * The render runs server-side; this modal just collects the user's choices
 * (name, optional crossfade duration), POSTs to /mixtapes, and registers
 * the resulting id with the progress watcher so the user gets a toast when
 * the bundle is ready to download.
 */
import { useState, useEffect, useRef } from 'react';
import { X, CassetteTape } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { mixtapesApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { showSuccess, showError } from '../../stores/toastStore';

export interface ExportMixTapeModalProps {
  isOpen: boolean;
  onClose: () => void;
  source:
    | { kind: 'playlist'; id: string; defaultName: string }
    | { kind: 'smart_playlist'; id: string; defaultName: string };
}

const DEFAULT_CROSSFADE_SECONDS = 5;

export function ExportMixTapeModal({ isOpen, onClose, source }: ExportMixTapeModalProps) {
  const [name, setName] = useState('');
  const [byline, setByline] = useState('');
  const [crossfadeEnabled, setCrossfadeEnabled] = useState(true);
  const [crossfadeSeconds, setCrossfadeSeconds] = useState(DEFAULT_CROSSFADE_SECONDS);
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (isOpen) {
      // Default name: source playlist's name + " Mix Tape"
      setName(source.defaultName ? `${source.defaultName} Mix Tape` : '');
      setByline('');
      setCrossfadeEnabled(true);
      setCrossfadeSeconds(DEFAULT_CROSSFADE_SECONDS);
      setTimeout(() => inputRef.current?.select(), 50);
    }
  }, [isOpen, source.defaultName]);

  if (!isOpen) return null;

  const handleSubmit = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setSubmitting(true);
    try {
      const trimmedByline = byline.trim();
      const payload = {
        name: trimmed,
        crossfade_seconds: crossfadeEnabled ? crossfadeSeconds : null,
        byline: trimmedByline ? trimmedByline : null,
        ...(source.kind === 'playlist'
          ? { source_playlist_id: source.id }
          : { source_smart_playlist_id: source.id }),
      };
      await mixtapesApi.create(payload);
      queryClient.invalidateQueries({ queryKey: queryKeys.mixtapes.all });
      showSuccess('Mix tape rendering — we\'ll let you know when it\'s ready');
      onClose();
    } catch (err: unknown) {
      const message =
        err && typeof err === 'object' && 'response' in err
          ? // axios shape
            (err as { response?: { data?: { message?: string } } }).response?.data?.message
          : null;
      showError(message || 'Failed to start mix tape render');
    } finally {
      setSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
    if (e.key === 'Escape') {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl w-96 p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-white flex items-center gap-2">
            <CassetteTape className="w-4 h-4 text-orange-400" />
            Export Mix Tape
          </h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Mix Tape Name</label>
            <input
              ref={inputRef}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={handleKeyDown}
              maxLength={64}
              className="w-full px-2 py-1.5 text-sm bg-zinc-900 border border-zinc-600 rounded text-white focus:outline-none focus:border-zinc-500"
              placeholder="My Mix Tape"
            />
            <p className="text-xs text-zinc-500 mt-1">
              Appears on the cover and in the audio file's tags.
            </p>
          </div>

          <div>
            <label className="block text-xs text-zinc-400 mb-1">By</label>
            <input
              value={byline}
              onChange={(e) => setByline(e.target.value)}
              onKeyDown={handleKeyDown}
              maxLength={32}
              className="w-full px-2 py-1.5 text-sm bg-zinc-900 border border-zinc-600 rounded text-white focus:outline-none focus:border-zinc-500"
              placeholder="Your name"
            />
            <p className="text-xs text-zinc-500 mt-1">
              Optional — appears on the cover and in the file's tags.
            </p>
          </div>

          <div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={crossfadeEnabled}
                onChange={(e) => setCrossfadeEnabled(e.target.checked)}
                className="w-3.5 h-3.5 rounded border-zinc-600 bg-zinc-900"
              />
              <span className="text-sm text-white">Crossfade between tracks</span>
            </label>
            {crossfadeEnabled && (
              <div className="mt-2 pl-5">
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={1}
                    max={10}
                    value={crossfadeSeconds}
                    onChange={(e) => setCrossfadeSeconds(parseInt(e.target.value, 10))}
                    className="flex-1 accent-orange-400"
                  />
                  <span className="text-xs text-zinc-400 w-10 text-right">
                    {crossfadeSeconds}s
                  </span>
                </div>
              </div>
            )}
          </div>

          <div className="text-xs text-zinc-500 bg-zinc-900/50 rounded p-2 leading-relaxed">
            Renders as 128 kbps MP3 (radio-quality) with auto-generated cover and
            tracklist, bundled in a ZIP. Up to 15 tracks.
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-zinc-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || !name.trim()}
            className="px-3 py-1.5 text-sm bg-orange-600 hover:bg-orange-500 text-white rounded disabled:opacity-50 transition-colors"
          >
            {submitting ? 'Starting…' : 'Start Render'}
          </button>
        </div>
      </div>
    </div>
  );
}
