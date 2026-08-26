/**
 * Contextual Mix Tape button for the playlist / smart-playlist detail views.
 *
 * State machine:
 *   - in-flight (pending / rendering)  →"Rendering Mix Tape…" with phase, disabled
 *   - ready                            →"Download Mix Tape"  (one-click download)
 *                                         + small"+" button to start a new render
 *   - failed or none                   →"Export Mix Tape" (opens the modal)
 *
 * The modal state is owned by the parent detail view (so right-click and
 * inline click both feed the same modal).
 */
import { useState } from 'react';
import { CassetteTape, Download, Loader2, Plus } from 'lucide-react';
import { useMixtapeForSource, PHASE_LABELS } from '../../hooks/useMixtapes';
import { mixtapesApi } from '../../api';
import { showError } from '../../stores/toastStore';
import { ExportMixTapeModal } from './ExportMixTapeModal';

interface Props {
  source:
    | { kind: 'playlist'; id: string; defaultName: string }
    | { kind: 'smart_playlist'; id: string; defaultName: string };
  /**
   * Number of tracks currently in the source. Used to disable Export when
   * the playlist is too small (or — for static playlists only — too large).
   */
  trackCount: number;
  /** Smart playlists may exceed 15; the backend truncates. */
  enforceMaxFifteen?: boolean;
}

export function MixTapeButton({ source, trackCount, enforceMaxFifteen = false }: Props) {
  const current = useMixtapeForSource(source.kind, source.id);
  const [modalOpen, setModalOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const tooSmall = trackCount < 2;
  const tooLarge = enforceMaxFifteen && trackCount > 15;
  const cannotRender = tooSmall || tooLarge;

  const handleDownload = async () => {
    if (!current) return;
    setDownloading(true);
    try {
      await mixtapesApi.download(current.id, current.name);
    } catch {
      showError('Failed to download mix tape');
    } finally {
      setDownloading(false);
    }
  };

  // ── In-flight: show a progress-aware disabled chip ─────────────────────────
  if (current && (current.status === 'pending' || current.status === 'rendering')) {
    const phase = current.progress?.phase ?? current.status;
    const phaseLabel = PHASE_LABELS[phase] ?? 'Starting…';
    return (
      <button
        disabled
        title={`Rendering"${current.name}" — ${phaseLabel}`}
        className="flex items-center justify-center gap-2 px-4 py-2 bg-zinc-700 opacity-70 rounded-full cursor-default"
      >
        <Loader2 className="w-4 h-4 text-orange-400 animate-spin" />
        <span className="text-sm">{phaseLabel}…</span>
      </button>
    );
  }

  // ── Ready: download primary,"+" secondary ─────────────────────────────────
  if (current && current.status === 'ready') {
    return (
      <>
        <div className="flex items-stretch">
          <button
            onClick={handleDownload}
            disabled={downloading}
            title={`Download"${current.name}"`}
            className="flex items-center justify-center gap-2 pl-4 pr-3 py-2 bg-orange-600 hover:bg-orange-500 disabled:opacity-50 rounded-l-full transition-colors text-white"
          >
            {downloading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            <span className="text-sm">Download Mix Tape</span>
          </button>
          <button
            onClick={() => setModalOpen(true)}
            disabled={cannotRender}
            title={
              cannotRender
                ? tooSmall
                  ? 'Mix tape needs at least 2 tracks'
                  : 'Mix tapes are limited to 15 tracks'
                : 'Make a new mix tape'
            }
            className="flex items-center justify-center px-2 py-2 bg-orange-600 hover:bg-orange-500 disabled:opacity-50 disabled:hover:bg-orange-600 rounded-r-full border-l border-orange-500 transition-colors text-white"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
        <ExportMixTapeModal
          isOpen={modalOpen}
          onClose={() => setModalOpen(false)}
          source={source}
        />
      </>
    );
  }

  // ── Default (none / failed): existing Export Mix Tape flow ─────────────────
  return (
    <>
      <button
        onClick={() => setModalOpen(true)}
        disabled={cannotRender}
        title={
          cannotRender
            ? tooSmall
              ? 'Mix tape needs at least 2 tracks'
              : 'Mix tapes are limited to 15 tracks'
            : current?.status === 'failed'
              ? `Last render failed: ${current.error_message ?? 'unknown error'} — retry?`
              : 'Render this playlist as a single mix tape MP3'
        }
        className="flex items-center justify-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 disabled:hover:bg-zinc-700 rounded-full transition-colors"
      >
        <CassetteTape className="w-4 h-4 text-orange-400" />
        <span className="text-sm">
          {current?.status === 'failed' ? 'Retry Mix Tape' : 'Export Mix Tape'}
        </span>
      </button>
      <ExportMixTapeModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        source={source}
      />
    </>
  );
}
