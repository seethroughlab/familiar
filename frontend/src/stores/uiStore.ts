import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface UIState {
  /** Which right panel is open, if any. Queue and Chat are mutually exclusive. */
  rightPanel: 'queue' | 'chat' | null;
  /** Whether the settings modal is showing */
  showSettings: boolean;
  /** Whether the sidebar is collapsed to icon-only mode */
  sidebarCollapsed: boolean;
  /** Whether the full player overlay is showing */
  showFullPlayer: boolean;

  // Actions
  toggleRightPanel: (panel: 'queue' | 'chat') => void;
  closeRightPanel: () => void;
  setShowSettings: (show: boolean) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setShowFullPlayer: (show: boolean) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set, get) => ({
      rightPanel: null,
      showSettings: false,
      sidebarCollapsed: false,
      showFullPlayer: false,

      toggleRightPanel: (panel) => {
        const current = get().rightPanel;
        set({ rightPanel: current === panel ? null : panel });
      },
      closeRightPanel: () => set({ rightPanel: null }),
      setShowSettings: (show) => set({ showSettings: show }),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      setShowFullPlayer: (show) => set({ showFullPlayer: show }),
    }),
    {
      name: 'familiar-ui',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
      }),
    }
  )
);
