/**
 * Keyboard shortcuts help modal.
 */
import { X, Keyboard } from 'lucide-react';
import { SHORTCUTS, formatShortcutKey } from '../../hooks/useKeyboardShortcuts';

interface ShortcutsHelpProps {
  onClose: () => void;
}

export function ShortcutsHelp({ onClose }: ShortcutsHelpProps) {
  const shortcutGroups = [
    {
      title: 'Playback',
      shortcuts: [
        SHORTCUTS.playPause,
        SHORTCUTS.nextTrack,
        SHORTCUTS.prevTrack,
        SHORTCUTS.seekForward,
        SHORTCUTS.seekBackward,
      ],
    },
    {
      title: 'Volume',
      shortcuts: [SHORTCUTS.volumeUp, SHORTCUTS.volumeDown, SHORTCUTS.mute],
    },
    {
      title: 'Modes',
      shortcuts: [SHORTCUTS.shuffle, SHORTCUTS.repeat],
    },
    {
      title: 'Navigation',
      shortcuts: [SHORTCUTS.fullPlayer, SHORTCUTS.escape, SHORTCUTS.help],
    },
  ];

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-zinc-900 rounded-xl border border-zinc-800 w-full max-w-md overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Keyboard className="w-5 h-5 text-zinc-400" />
            <h2 className="text-lg font-semibold">Keyboard Shortcuts</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-zinc-800 rounded-md transition-colors"
          >
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-6 max-h-[70vh] overflow-y-auto">
          {shortcutGroups.map((group) => (
            <div key={group.title}>
              <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-wider mb-3">
                {group.title}
              </h3>
              <div className="space-y-2">
                {group.shortcuts.map((shortcut) => (
                  <div
                    key={shortcut.key}
                    className="flex items-center justify-between py-1"
                  >
                    <span className="text-zinc-300">{shortcut.description}</span>
                    <kbd className="px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-sm font-mono text-zinc-300">
                      {formatShortcutKey(shortcut.key)}
                    </kbd>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-zinc-800 text-center text-sm text-zinc-500">
          Press <kbd className="px-1.5 py-0.5 bg-zinc-800 border border-zinc-700 rounded text-xs font-mono">?</kbd> anytime to show this help
        </div>
      </div>
    </div>
  );
}
