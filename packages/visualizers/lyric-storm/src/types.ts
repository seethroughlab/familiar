/** What a visualizer is handed. The plugin's own copy — the host lends nothing (ADR-0087 point 2). */
export interface VisualizerProps {
  currentTime: number;
  duration: number;
  isPlaying: boolean;
  track: { id: string; title?: string | null; artist?: string | null } | null;
  features: Record<string, unknown> | null;
  artworkUrl: string | null;
  lyrics: unknown[] | null;
}
