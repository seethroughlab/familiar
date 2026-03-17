/**
 * Active session mutex — determines which system owns the audio engine.
 *
 * 'normal' = standard player (playerStore + useAudioEngine)
 * 'ambient' = ambient coordinator
 */
import { create } from 'zustand';

interface ActiveSessionState {
  activeSession: 'normal' | 'ambient';
  setActiveSession: (session: 'normal' | 'ambient') => void;
}

export const useActiveSessionStore = create<ActiveSessionState>()((set) => ({
  activeSession: 'normal',
  setActiveSession: (session) => set({ activeSession: session }),
}));
