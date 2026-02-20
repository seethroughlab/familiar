/**
 * Shared context menu primitives.
 *
 * ContextMenuContainer — fixed-position wrapper with click-outside/escape dismissal,
 *   viewport-aware repositioning, and mobile centering.
 * MenuItem — button with icon/label/onClick/disabled/iconClassName.
 * MenuDivider — border divider.
 * MenuHeader — info header block (title + subtitle).
 */
import { useEffect, useRef } from 'react';

interface ContextMenuContainerProps {
  position: { x: number; y: number };
  onClose: () => void;
  children: React.ReactNode;
}

export function ContextMenuContainer({
  position,
  onClose,
  children,
}: ContextMenuContainerProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  // Close on click outside or Escape
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  // Viewport-aware repositioning + mobile centering
  useEffect(() => {
    if (menuRef.current) {
      const rect = menuRef.current.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const isMobile = viewportWidth < 768;

      if (isMobile) {
        const padding = 16;
        const menuWidth = Math.min(rect.width, viewportWidth - padding * 2);
        menuRef.current.style.left = `${(viewportWidth - menuWidth) / 2}px`;
        menuRef.current.style.width = `${menuWidth}px`;

        if (rect.bottom > viewportHeight) {
          menuRef.current.style.top = `${Math.max(padding, viewportHeight - rect.height - padding)}px`;
        }
      } else {
        if (rect.right > viewportWidth) {
          menuRef.current.style.left = `${position.x - rect.width}px`;
        }

        if (rect.bottom > viewportHeight) {
          menuRef.current.style.top = `${position.y - rect.height}px`;
        }
      }
    }
  }, [position]);

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[200px] py-1 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl"
      style={{
        left: position.x,
        top: position.y,
      }}
    >
      {children}
    </div>
  );
}

interface MenuItemProps {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  iconClassName?: string;
}

export function MenuItem({ icon, label, onClick, disabled, iconClassName }: MenuItemProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full flex items-center gap-3 px-3 py-2 text-sm text-left hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
    >
      <span className={iconClassName || "text-zinc-400"}>{icon}</span>
      <span>{label}</span>
    </button>
  );
}

export function MenuDivider() {
  return <div className="my-1 border-t border-zinc-700" />;
}

interface MenuHeaderProps {
  title: string;
  subtitle?: string;
}

export function MenuHeader({ title, subtitle }: MenuHeaderProps) {
  return (
    <div className="px-3 py-2 border-b border-zinc-700">
      <div className="text-sm font-medium text-white truncate">{title}</div>
      {subtitle && (
        <div className="text-xs text-zinc-400 truncate">{subtitle}</div>
      )}
    </div>
  );
}
