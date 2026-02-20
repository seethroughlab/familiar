import { useState } from 'react';
import { Download, Loader2, Check } from 'lucide-react';
import { smartPlaylistsApi } from '../../api';
import type { SmartPlaylist } from '../../api';
import type { FamiliarPlaylist } from '../../types';

import { createLogger } from '../../utils/logger';

const log = createLogger('PlaylistExport');

interface Props {
  playlist: SmartPlaylist;
  onExport?: () => void;
}

export function PlaylistExport({ playlist, onExport }: Props) {
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      // Fetch all tracks for the playlist
      const response = await smartPlaylistsApi.getTracks(playlist.id, 10000);

      // Build the .familiar file
      const familiarPlaylist: FamiliarPlaylist = {
        format: 'familiar-playlist',
        version: 1,
        exported_at: new Date().toISOString(),
        playlist: {
          name: playlist.name,
          description: playlist.description,
          type: 'smart',
          rules: playlist.rules,
          match_mode: playlist.match_mode,
          tracks: response.tracks.map(t => ({
            title: t.title || 'Unknown',
            artist: t.artist || 'Unknown',
            album: t.album,
            duration_seconds: t.duration_seconds,
            track_number: null,
          })),
        },
      };

      // Create and download the file
      const blob = new Blob([JSON.stringify(familiarPlaylist, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${playlist.name.replace(/[^a-z0-9]/gi, '_')}.familiar`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      setExported(true);
      setTimeout(() => setExported(false), 2000);
      onExport?.();
    } catch (error) {
      log.error('Export failed:', error);
    } finally {
      setExporting(false);
    }
  };

  return (
    <button
      onClick={handleExport}
      disabled={exporting}
      className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-zinc-700 rounded-md transition-colors disabled:opacity-50 w-full text-left"
    >
      {exporting ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : exported ? (
        <Check className="w-4 h-4 text-green-500" />
      ) : (
        <Download className="w-4 h-4" />
      )}
      {exported ? 'Exported!' : 'Export .familiar'}
    </button>
  );
}
