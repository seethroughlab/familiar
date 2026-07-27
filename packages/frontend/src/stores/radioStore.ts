/**
 * Radio suggestions toggle (ADR-0005).
 *
 * Persisted and off by default. Radio inserts tracks the listener did not choose into a
 * queue they are already enjoying, so it is opt-in — defaulting it on would be the app
 * making that decision for them.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface RadioState {
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
}

export const useRadioStore = create<RadioState>()(
  persist(
    (set) => ({
      enabled: false,
      setEnabled: (enabled) => set({ enabled }),
    }),
    { name: 'familiar-radio' }
  )
);
