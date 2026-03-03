import { useState, useCallback } from 'react';
import { Upload, FileJson, Loader2, Check, X, AlertCircle } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { playlistSharingApi } from '../../api';
import type { PlaylistImportResult } from '../../api';
import type { FamiliarPlaylist } from '../../types';

interface Props {
  onImportComplete?: (result: PlaylistImportResult) => void;
  onClose?: () => void;
}

export function PlaylistImport({ onImportComplete, onClose }: Props) {
  const queryClient = useQueryClient();
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState<FamiliarPlaylist | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  const importMutation = useMutation({
    mutationFn: playlistSharingApi.importPlaylist,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['smart-playlists'] });
      onImportComplete?.(result);
    },
  });

  const handleFile = useCallback((f: File) => {
    setParseError(null);
    setFile(f);

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const content = JSON.parse(e.target?.result as string) as FamiliarPlaylist;

        // Validate format
        if (content.format !== 'familiar-playlist') {
          setParseError('Invalid file format. Expected a .familiar playlist file.');
          return;
        }

        setPreview(content);
      } catch {
        setParseError('Failed to parse file. Make sure it\'s a valid .familiar file.');
      }
    };
    reader.readAsText(f);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);

    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      handleFile(droppedFile);
    }
  }, [handleFile]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      handleFile(selectedFile);
    }
  }, [handleFile]);

  const handleImport = () => {
    if (file) {
      importMutation.mutate(file);
    }
  };

  const reset = () => {
    setPreview(null);
    setFile(null);
    setParseError(null);
    importMutation.reset();
  };

  // Success view
  if (importMutation.isSuccess) {
    const result = importMutation.data;
    return (
      <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
        <div className="bg-zinc-900 rounded-xl w-full max-w-md p-6 space-y-4">
          <div className="flex items-center gap-3 text-green-500">
            <Check className="w-8 h-8" />
            <h2 className="text-xl font-semibold">Import Complete!</h2>
          </div>

          <div className="space-y-2 text-sm">
            <p><span className="text-zinc-400">Playlist:</span> {result.playlist_name}</p>
            <p><span className="text-zinc-400">Tracks matched:</span> {result.matched_tracks} / {result.total_tracks}</p>
            {result.unmatched_tracks > 0 && (
              <p className="text-yellow-500">
                {result.unmatched_tracks} tracks could not be matched to your library
              </p>
            )}
          </div>

          <div className="flex gap-2 pt-2">
            <button
              onClick={() => {
                reset();
                onClose?.();
              }}
              className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg transition-colors"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 rounded-xl w-full max-w-lg p-6 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold flex items-center gap-2">
            <Upload className="w-5 h-5" />
            Import Playlist
          </h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-zinc-800 rounded-md transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Drop zone or preview */}
        {!preview ? (
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            className={`
              border-2 border-dashed rounded-xl p-8 text-center transition-colors
              ${dragOver ? 'border-green-500 bg-green-500/10' : 'border-zinc-700 hover:border-zinc-600'}
            `}
          >
            <FileJson className={`w-12 h-12 mx-auto mb-4 ${dragOver ? 'text-green-500' : 'text-zinc-500'}`} />
            <p className="text-zinc-300 mb-2">Drop a .familiar file here</p>
            <p className="text-zinc-500 text-sm mb-4">or</p>
            <label className="inline-block px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg cursor-pointer transition-colors">
              Browse files
              <input
                type="file"
                accept=".familiar,.json"
                onChange={handleFileInput}
                className="hidden"
              />
            </label>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Preview */}
            <div className="bg-zinc-800/50 rounded-lg p-4 space-y-2">
              <div className="flex items-center gap-2">
                <FileJson className="w-5 h-5 text-green-500" />
                <span className="font-medium">{preview.playlist.name}</span>
              </div>
              {preview.playlist.description && (
                <p className="text-sm text-zinc-400">{preview.playlist.description}</p>
              )}
              <div className="flex gap-4 text-sm text-zinc-500">
                <span>{preview.playlist.tracks.length} tracks</span>
                <span>{preview.playlist.type === 'smart' ? 'Smart playlist' : 'Static playlist'}</span>
              </div>
              {preview.playlist.type === 'smart' && preview.playlist.rules && (
                <p className="text-xs text-zinc-600">
                  {preview.playlist.rules.length} rules ({preview.playlist.match_mode} match)
                </p>
              )}
            </div>

            {/* Track preview */}
            <div className="max-h-48 overflow-y-auto bg-zinc-800/30 rounded-lg">
              <div className="text-xs text-zinc-500 px-3 py-2 border-b border-zinc-700">
                Tracks to import:
              </div>
              {preview.playlist.tracks.slice(0, 20).map((track, i) => (
                <div
                  key={i}
                  className="px-3 py-1.5 text-sm border-b border-zinc-800 last:border-0"
                >
                  <span className="text-zinc-300">{track.title}</span>
                  <span className="text-zinc-500"> - {track.artist}</span>
                </div>
              ))}
              {preview.playlist.tracks.length > 20 && (
                <div className="px-3 py-2 text-xs text-zinc-500">
                  ...and {preview.playlist.tracks.length - 20} more tracks
                </div>
              )}
            </div>

            {/* Import error */}
            {importMutation.isError && (
              <div className="flex items-center gap-2 text-red-400 text-sm bg-red-500/10 rounded-lg p-3">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span>Import failed. The backend endpoint may not be available yet.</span>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2">
              <button
                onClick={reset}
                className="flex-1 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleImport}
                disabled={importMutation.isPending}
                className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {importMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Importing...
                  </>
                ) : (
                  'Import'
                )}
              </button>
            </div>
          </div>
        )}

        {/* Parse error */}
        {parseError && (
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4" />
            {parseError}
          </div>
        )}
      </div>
    </div>
  );
}
