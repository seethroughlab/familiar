/**
 * MobileBottomNav - Bottom navigation bar for mobile screens.
 *
 * Fixed at the bottom of the screen (below PlayerBar).
 * Shows on screens < md (768px), hidden on desktop where sidebar handles nav.
 */
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { List, Users, Heart, MessageSquare, MoreHorizontal } from 'lucide-react';
import { useUIStore } from '../../stores/uiStore';
import { useThemeStore } from '../../stores/themeStore';
import { MobileMoreSheet } from './MobileMoreSheet';

const NAV_ITEMS = [
  { path: '/library/tracks', label: 'Tracks', icon: List, match: '/library/tracks' },
  { path: '/library/artists', label: 'Artists', icon: Users, match: '/library/artists' },
  { path: '/favorites', label: 'Favorites', icon: Heart, match: '/favorites' },
] as const;

export function MobileBottomNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const resolvedTheme = useThemeStore((s) => s.resolvedTheme);
  const showFullPlayer = useUIStore((s) => s.showFullPlayer);
  const rightPanel = useUIStore((s) => s.rightPanel);
  const toggleRightPanel = useUIStore((s) => s.toggleRightPanel);
  const [showMore, setShowMore] = useState(false);

  // Hide when full player is open
  if (showFullPlayer) return null;

  const light = resolvedTheme === 'light';

  const isActive = (match: string) => location.pathname.startsWith(match);
  const isMoreActive = !NAV_ITEMS.some(item => isActive(item.match));

  return (
    <>
      <nav
        className={`fixed bottom-0 left-0 right-0 z-20 md:hidden flex items-center justify-around pb-safe-bottom ${
          light ? 'bg-white border-t border-zinc-200' : 'bg-zinc-950 border-t border-zinc-800'
        }`}
      >
        {NAV_ITEMS.map((item) => {
          const active = isActive(item.match);
          return (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`flex flex-col items-center gap-0.5 py-2 px-4 min-w-[64px] transition-colors ${
                active
                  ? 'text-green-500'
                  : light ? 'text-zinc-500' : 'text-zinc-400'
              }`}
            >
              <item.icon className="w-5 h-5" />
              <span className="text-[10px] font-medium">{item.label}</span>
            </button>
          );
        })}
        <button
          onClick={() => toggleRightPanel('chat')}
          className={`flex flex-col items-center gap-0.5 py-2 px-4 min-w-[64px] transition-colors ${
            rightPanel === 'chat'
              ? 'text-green-500'
              : light ? 'text-zinc-500' : 'text-zinc-400'
          }`}
        >
          <MessageSquare className="w-5 h-5" />
          <span className="text-[10px] font-medium">Chat</span>
        </button>
        <button
          onClick={() => setShowMore(true)}
          className={`flex flex-col items-center gap-0.5 py-2 px-4 min-w-[64px] transition-colors ${
            isMoreActive || showMore
              ? 'text-green-500'
              : light ? 'text-zinc-500' : 'text-zinc-400'
          }`}
        >
          <MoreHorizontal className="w-5 h-5" />
          <span className="text-[10px] font-medium">More</span>
        </button>
      </nav>

      {showMore && <MobileMoreSheet onClose={() => setShowMore(false)} />}
    </>
  );
}
