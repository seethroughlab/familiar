/**
 * What happened to each drop-in visualizer plugin (ADR-0034 points 7 and 8).
 *
 * **Deliberately not persisted**, unlike its sibling `visualizerStore`. Everything in here is a
 * fact about the files present in this run — a refusal cached from last launch would still be shown
 * after the user fixed the manifest, which is worse than showing nothing.
 */
import { create } from 'zustand';
import type { PluginRefusal, VisualizerPluginSource } from '../services/visualizerPlugins';

export interface VisualizerPluginRecord {
  id: string | null;
  name: string | null;
  source: VisualizerPluginSource;
  status: 'loaded' | 'refused' | 'failed';
  /** Present for `refused` and `failed`. What a person reads in the picker. */
  detail?: string;
  refusal?: PluginRefusal;
  /**
   * Affinity declarations dropped while parsing the manifest (ADR-0064 point 3).
   *
   * **Belongs to a `loaded` plugin**, which is why it sits apart from `detail` and `refusal`: the
   * plugin works and is in the picker, and this is only the part of its manifest that did not. An
   * author whose typo vanished silently has no way to find it.
   */
  ignored?: string[];
}

interface VisualizerPluginState {
  records: VisualizerPluginRecord[];
  /** False until the loader has finished a pass, so the picker can tell "none" from "not yet". */
  scanned: boolean;

  setRecords: (records: VisualizerPluginRecord[]) => void;
  /**
   * Mark a loaded plugin as having crashed at render time (ADR-0034 point 8).
   *
   * The `ErrorBoundary` around the visualizer catches it; this is how the picker comes to say so
   * rather than leaving the user with a fallback square and no explanation. A plugin that is not in
   * the records — a built-in — is ignored rather than added, because a built-in crashing is a bug
   * here and not a plugin to be marked.
   */
  markFailed: (id: string, detail: string) => void;
}

export const useVisualizerPluginStore = create<VisualizerPluginState>()((set) => ({
  records: [],
  scanned: false,

  setRecords: (records) => set({ records, scanned: true }),

  markFailed: (id, detail) =>
    set((state) => ({
      records: state.records.map((record) =>
        record.id === id && record.status === 'loaded' ? { ...record, status: 'failed', detail } : record
      ),
    })),
}));
