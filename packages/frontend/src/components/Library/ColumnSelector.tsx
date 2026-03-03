import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Columns, Check, RotateCcw } from 'lucide-react';
import { useColumnStore } from '../../stores/columnStore';
import { getBasicColumns, getAnalysisColumns } from './columnDefinitions';

export function ColumnSelector() {
  const [isOpen, setIsOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const { columns, toggleColumn, resetToDefaults } = useColumnStore();

  // Create a map for quick visibility lookup
  const visibilityMap = new Map(columns.map((col) => [col.id, col.visible]));

  // Close menu when clicking outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (
        buttonRef.current?.contains(e.target as Node) ||
        menuRef.current?.contains(e.target as Node)
      ) {
        return;
      }
      setIsOpen(false);
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  // Close on escape
  useEffect(() => {
    if (!isOpen) return;

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen]);

  const basicColumns = getBasicColumns();
  const analysisColumns = getAnalysisColumns();

  // Compute dropdown position from button rect
  const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null);
  useEffect(() => {
    if (!isOpen || !buttonRef.current) {
      setMenuPosition(null);
      return;
    }
    const rect = buttonRef.current.getBoundingClientRect();
    setMenuPosition({
      top: rect.bottom + 8,
      right: window.innerWidth - rect.right,
    });
  }, [isOpen]);

  const dropdownMenu = isOpen && menuPosition && createPortal(
    <div
      ref={menuRef}
      style={{ top: menuPosition.top, right: menuPosition.right }}
      className="fixed w-[calc(100vw-2rem)] sm:w-56 max-w-56 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50 py-2"
    >
      {/* Basic columns section */}
      <div className="px-3 py-1.5 text-xs font-medium text-zinc-500 uppercase tracking-wider">
        Basic
      </div>
      {basicColumns.map((colDef) => (
        <button
          key={colDef.id}
          onClick={() => toggleColumn(colDef.id)}
          className="w-full px-3 py-1.5 flex items-center gap-2 hover:bg-zinc-800 text-left text-sm"
        >
          <div
            className={`w-4 h-4 rounded border flex items-center justify-center ${
              visibilityMap.get(colDef.id)
                ? 'bg-green-500 border-green-500 text-black'
                : 'border-zinc-600'
            }`}
          >
            {visibilityMap.get(colDef.id) && <Check className="w-3 h-3" />}
          </div>
          <span className={visibilityMap.get(colDef.id) ? 'text-white' : 'text-zinc-400'}>
            {colDef.label}
          </span>
        </button>
      ))}

      {/* Analysis columns section */}
      <div className="border-t border-zinc-700 mt-2 pt-2">
        <div className="px-3 py-1.5 text-xs font-medium text-zinc-500 uppercase tracking-wider">
          Analysis
        </div>
        {analysisColumns.map((colDef) => (
          <button
            key={colDef.id}
            onClick={() => toggleColumn(colDef.id)}
            className="w-full px-3 py-1.5 flex items-center gap-2 hover:bg-zinc-800 text-left text-sm"
          >
            <div
              className={`w-4 h-4 rounded border flex items-center justify-center ${
                visibilityMap.get(colDef.id)
                  ? 'bg-green-500 border-green-500 text-black'
                  : 'border-zinc-600'
              }`}
            >
              {visibilityMap.get(colDef.id) && <Check className="w-3 h-3" />}
            </div>
            <span className={visibilityMap.get(colDef.id) ? 'text-white' : 'text-zinc-400'}>
              {colDef.label}
            </span>
          </button>
        ))}
      </div>

      {/* Reset button */}
      <div className="border-t border-zinc-700 mt-2 pt-2 px-3">
        <button
          onClick={() => {
            resetToDefaults();
            setIsOpen(false);
          }}
          className="w-full py-1.5 text-sm text-zinc-400 hover:text-white flex items-center justify-center gap-1.5"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Reset to defaults
        </button>
      </div>
    </div>,
    document.body
  );

  return (
    <>
      <button
        ref={buttonRef}
        onClick={() => setIsOpen(!isOpen)}
        className={`px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1.5 ${
          isOpen
            ? 'bg-zinc-700 text-white'
            : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
        }`}
        title="Configure columns"
      >
        <Columns className="w-4 h-4" />
        <span className="hidden sm:inline">Columns</span>
      </button>
      {dropdownMenu}
    </>
  );
}
