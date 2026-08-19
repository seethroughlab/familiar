/**
 * MobileMoreSheet - Bottom sheet with additional navigation items.
 *
 * Shows library browsers, collections, playlists, and utility items
 * that don't fit in the 4-item bottom nav bar.
 */
import { useNavigate, useLocation } from 'react-router-dom';
import {
  List, FileText,
  Settings, X,
} from 'lucide-react';
import { useUIStore } from '../../stores/uiStore';
import { useThemeStore } from '../../stores/themeStore';

interface Props {
  onClose: () => void;
}

// Trimmed with the desktop sidebar (docs/WEB-PARITY.md). ADR-0002 point 3 already made mobile web a
// non-target; this stops it advertising destinations that no longer exist.
const LIBRARY_ITEMS = [
  { path: '/library/tracks', label: 'Tracks', icon: List },
  { path: '/library/artist-cleanup', label: 'Cleanup', icon: FileText },
];

const COLLECTION_ITEMS: { path: string; label: string; icon: typeof List }[] = [];

export function MobileMoreSheet({ onClose }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const resolvedTheme = useThemeStore((s) => s.resolvedTheme);
  const setShowSettings = useUIStore((s) => s.setShowSettings);



  const light = resolvedTheme === 'light';
  const isActive = (path: string) => location.pathname === path || location.pathname.startsWith(path + '/');

  const handleNav = (path: string) => {
    navigate(path);
    onClose();
  };


  const handleSettings = () => {
    setShowSettings(true);
    onClose();
  };

  const itemClass = (path: string) =>
    `flex items-center gap-3 px-4 py-3 transition-colors ${
      isActive(path)
        ? 'text-green-500'
        : light ? 'text-zinc-700 active:bg-zinc-100' : 'text-zinc-300 active:bg-zinc-800'
    }`;

  const sectionClass = `px-4 pt-4 pb-1 text-xs font-semibold uppercase tracking-wider ${
    light ? 'text-zinc-400' : 'text-zinc-500'
  }`;

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Sheet */}
      <div
        className={`absolute bottom-0 left-0 right-0 rounded-t-2xl pb-safe-bottom max-h-[75vh] flex flex-col ${
          light ? 'bg-white' : 'bg-zinc-900'
        }`}
      >
        {/* Handle + close */}
        <div className="flex items-center justify-between px-4 pt-3 pb-1">
          <div className="w-8 h-1 bg-zinc-600 rounded-full mx-auto" />
          <button
            onClick={onClose}
            className={`absolute right-3 top-3 p-1.5 rounded-lg ${
              light ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800'
            }`}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable content */}
        <div className="overflow-y-auto min-h-0 flex-1 pb-4">
          {/* Library browsers */}
          <div className={sectionClass}>Library</div>
          {LIBRARY_ITEMS.map((item) => (
            <button key={item.path} onClick={() => handleNav(item.path)} className={itemClass(item.path)}>
              <item.icon className="w-5 h-5 flex-shrink-0" />
              <span>{item.label}</span>
            </button>
          ))}

          {/* Collections */}
          <div className={sectionClass}>Collections</div>
          {COLLECTION_ITEMS.map((item) => (
            <button key={item.path} onClick={() => handleNav(item.path)} className={itemClass(item.path)}>
              <item.icon className="w-5 h-5 flex-shrink-0" />
              <span>{item.label}</span>
            </button>
          ))}


          {/* Smart playlists */}

          {/* Utility items */}
          <div className={`my-2 mx-4 border-t ${light ? 'border-zinc-200' : 'border-zinc-800'}`} />
          <button onClick={handleSettings} className={`flex items-center gap-3 px-4 py-3 w-full ${light ? 'text-zinc-700 active:bg-zinc-100' : 'text-zinc-300 active:bg-zinc-800'}`}>
            <Settings className="w-5 h-5 flex-shrink-0" />
            <span>Settings</span>
          </button>
        </div>
      </div>
    </div>
  );
}
