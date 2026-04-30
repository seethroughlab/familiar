/**
 * Header chip showing in-flight Mix Tape renders.
 *
 * Shows nothing when no render is active. Mirrors the BackgroundJobsIndicator
 * pattern: spinner button with a count badge, click to open a popover listing
 * each in-flight render with its phase + progress bar.
 */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X, CassetteTape } from 'lucide-react';
import { useMixtapesList, PHASE_LABELS } from '../../hooks/useMixtapes';
import type { MixTape } from '../../api';

function isInFlight(mt: MixTape): boolean {
  return mt.status === 'pending' || mt.status === 'rendering';
}

function RenderRow({ mt }: { mt: MixTape }) {
  const phase = mt.progress?.phase ?? mt.status;
  const phaseLabel = PHASE_LABELS[phase] ?? phase;
  const percent = typeof mt.progress?.progress === 'number' ? mt.progress.progress : null;

  return (
    <div className="p-3 bg-zinc-700/50 rounded-lg">
      <div className="flex items-center gap-2 mb-1">
        <CassetteTape className="w-4 h-4 text-orange-400" />
        <span className="text-sm font-medium text-white truncate">{mt.name}</span>
        {percent !== null && (
          <span className="text-xs text-zinc-400 ml-auto">{percent}%</span>
        )}
      </div>
      <p className="text-xs text-zinc-400 mb-2">{phaseLabel}</p>
      <div className="h-1.5 bg-zinc-600 rounded-full overflow-hidden">
        {percent !== null ? (
          <div
            className="h-full bg-orange-500 transition-all duration-300"
            style={{ width: `${percent}%` }}
          />
        ) : (
          <div className="h-full bg-orange-500 w-full animate-pulse" />
        )}
      </div>
    </div>
  );
}

export function MixTapeRenderIndicator() {
  const { data } = useMixtapesList();
  const inFlight = (data ?? []).filter(isInFlight);
  const activeCount = inFlight.length;

  const [showPopover, setShowPopover] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showPopover) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (
        buttonRef.current?.contains(e.target as Node) ||
        popoverRef.current?.contains(e.target as Node)
      ) return;
      setShowPopover(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showPopover]);

  const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null);
  useEffect(() => {
    if (!showPopover || !buttonRef.current) {
      setMenuPosition(null);
      return;
    }
    const rect = buttonRef.current.getBoundingClientRect();
    setMenuPosition({ top: rect.bottom + 8, right: window.innerWidth - rect.right });
  }, [showPopover]);

  // Auto-close once everything finishes.
  useEffect(() => {
    if (activeCount === 0 && showPopover) setShowPopover(false);
  }, [activeCount, showPopover]);

  if (activeCount === 0) return null;

  const popover = showPopover && menuPosition && createPortal(
    <div
      ref={popoverRef}
      style={{ top: menuPosition.top, right: menuPosition.right }}
      className="fixed w-80 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl z-[60]"
    >
      <div className="p-3 border-b border-zinc-700 flex items-center justify-between">
        <h3 className="font-medium text-white flex items-center gap-2">
          <CassetteTape className="w-4 h-4 text-orange-400" />
          Mix Tapes Rendering
        </h3>
        <button
          onClick={() => setShowPopover(false)}
          className="p-1 hover:bg-zinc-700 rounded transition-colors"
        >
          <X className="w-4 h-4 text-zinc-400" />
        </button>
      </div>
      <div className="p-3 space-y-2 max-h-64 overflow-y-auto">
        {inFlight.map((mt) => <RenderRow key={mt.id} mt={mt} />)}
      </div>
    </div>,
    document.body,
  );

  return (
    <>
      <div className="relative">
        <button
          ref={buttonRef}
          onClick={() => setShowPopover(!showPopover)}
          className="p-2 rounded-lg transition-colors text-orange-400 hover:text-orange-300 hover:bg-orange-900/30"
          title={`${activeCount} mix tape${activeCount !== 1 ? 's' : ''} rendering`}
        >
          <Loader2 className="w-5 h-5 animate-spin" />
          {activeCount > 1 && (
            <span className="absolute -top-1 -right-1 w-4 h-4 bg-orange-500 text-white text-xs rounded-full flex items-center justify-center">
              {activeCount}
            </span>
          )}
        </button>
      </div>
      {popover}
    </>
  );
}
