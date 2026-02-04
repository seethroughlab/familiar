import { useState, useCallback, useRef } from 'react';
import {
  Download,
  Upload,
  CheckCircle,
  AlertCircle,
  Loader2,
  FileJson,
  X,
  AlertTriangle,
  Info,
  HardDrive,
  FileArchive,
} from 'lucide-react';
import {
  exportImportApi,
  libraryExportApi,
  type ImportPreviewResponse,
  type ImportExecuteResponse,
  type LibraryImportPreviewResponse,
  type LibraryImportExecuteResponse,
} from '../../api/client';

type ExportState = 'idle' | 'exporting' | 'success' | 'error';
type ImportState = 'idle' | 'preview' | 'previewing' | 'ready' | 'importing' | 'success' | 'error';
type LibraryExportState = 'idle' | 'exporting' | 'success' | 'error';
type LibraryImportState = 'idle' | 'uploading' | 'previewing' | 'ready' | 'importing' | 'success' | 'error';

interface ExportOptions {
  include_play_history: boolean;
  include_favorites: boolean;
  include_playlists: boolean;
  include_smart_playlists: boolean;
  include_proposed_changes: boolean;
  include_external_tracks: boolean;
}

interface ImportOptions {
  import_play_history: boolean;
  import_favorites: boolean;
  import_playlists: boolean;
  import_smart_playlists: boolean;
  import_proposed_changes: boolean;
  import_user_overrides: boolean;
  import_external_tracks: boolean;
}

interface LibraryExportOptions {
  include_embeddings: boolean;
  include_acoustid: boolean;
  compress: boolean;
}

interface LibraryImportOptions {
  apply_analysis: boolean;
  apply_embeddings: boolean;
  apply_user_overrides: boolean;
}

export function DataManagement() {
  // Export state
  const [exportState, setExportState] = useState<ExportState>('idle');
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportOptions, setExportOptions] = useState<ExportOptions>({
    include_play_history: true,
    include_favorites: true,
    include_playlists: true,
    include_smart_playlists: true,
    include_proposed_changes: true,
    include_external_tracks: true,
  });

  // Import state
  const [importState, setImportState] = useState<ImportState>('idle');
  const [importError, setImportError] = useState<string | null>(null);
  const [importPreview, setImportPreview] = useState<ImportPreviewResponse | null>(null);
  const [importResult, setImportResult] = useState<ImportExecuteResponse | null>(null);
  const [importMode, setImportMode] = useState<'merge' | 'overwrite'>('merge');
  const [importOptions, setImportOptions] = useState<ImportOptions>({
    import_play_history: true,
    import_favorites: true,
    import_playlists: true,
    import_smart_playlists: true,
    import_proposed_changes: true,
    import_user_overrides: true,
    import_external_tracks: true,
  });
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Library export/import state
  const [libraryExportState, setLibraryExportState] = useState<LibraryExportState>('idle');
  const [libraryExportError, setLibraryExportError] = useState<string | null>(null);
  const [libraryExportProgress, setLibraryExportProgress] = useState<number>(0);
  const [libraryExportOptions, setLibraryExportOptions] = useState<LibraryExportOptions>({
    include_embeddings: true,
    include_acoustid: true,
    compress: true,
  });

  const [libraryImportState, setLibraryImportState] = useState<LibraryImportState>('idle');
  const [libraryImportError, setLibraryImportError] = useState<string | null>(null);
  const [libraryImportProgress, setLibraryImportProgress] = useState<number>(0);
  const [libraryImportPreview, setLibraryImportPreview] = useState<LibraryImportPreviewResponse | null>(null);
  const [libraryImportResult, setLibraryImportResult] = useState<LibraryImportExecuteResponse | null>(null);
  const [libraryImportMode, setLibraryImportMode] = useState<'match_only' | 'merge' | 'replace'>('match_only');
  const [libraryImportOptions, setLibraryImportOptions] = useState<LibraryImportOptions>({
    apply_analysis: true,
    apply_embeddings: true,
    apply_user_overrides: true,
  });
  const [libraryDragActive, setLibraryDragActive] = useState(false);
  const libraryFileInputRef = useRef<HTMLInputElement>(null);

  // Export handler
  const handleExport = async () => {
    setExportState('exporting');
    setExportError(null);

    try {
      // TODO: Get chat history from IndexedDB if needed
      await exportImportApi.downloadExport(exportOptions);
      setExportState('success');
      setTimeout(() => setExportState('idle'), 3000);
    } catch (error) {
      console.error('Export failed:', error);
      setExportError(error instanceof Error ? error.message : 'Export failed');
      setExportState('error');
    }
  };

  // Import file handler
  const handleFile = useCallback(async (file: File) => {
    if (!file.name.endsWith('.json')) {
      setImportError('Please select a JSON file');
      setImportState('error');
      return;
    }

    setImportState('previewing');
    setImportError(null);
    setImportPreview(null);

    try {
      const preview = await exportImportApi.previewImport(file);
      setImportPreview(preview);
      setImportState('ready');
    } catch (error) {
      console.error('Import preview failed:', error);
      setImportError(error instanceof Error ? error.message : 'Failed to read file');
      setImportState('error');
    }
  }, []);

  // Drag handlers
  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);

      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleFile(e.dataTransfer.files[0]);
      }
    },
    [handleFile]
  );

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFile(e.target.files[0]);
    }
  };

  // Execute import
  const executeImport = async () => {
    if (!importPreview) return;

    setImportState('importing');
    setImportError(null);

    try {
      const result = await exportImportApi.executeImport({
        session_id: importPreview.session_id,
        mode: importMode,
        ...importOptions,
      });
      setImportResult(result);
      setImportState('success');
    } catch (error) {
      console.error('Import failed:', error);
      setImportError(error instanceof Error ? error.message : 'Import failed');
      setImportState('error');
    }
  };

  // Reset import state
  const resetImport = () => {
    setImportState('idle');
    setImportError(null);
    setImportPreview(null);
    setImportResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const toggleExportOption = (key: keyof ExportOptions) => {
    setExportOptions((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const toggleImportOption = (key: keyof ImportOptions) => {
    setImportOptions((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Library export handler
  const handleLibraryExport = async () => {
    setLibraryExportState('exporting');
    setLibraryExportError(null);
    setLibraryExportProgress(0);

    try {
      await libraryExportApi.downloadExport(libraryExportOptions, (loaded, total) => {
        setLibraryExportProgress(Math.round((loaded / total) * 100));
      });
      setLibraryExportState('success');
      setTimeout(() => setLibraryExportState('idle'), 3000);
    } catch (error) {
      console.error('Library export failed:', error);
      setLibraryExportError(error instanceof Error ? error.message : 'Export failed');
      setLibraryExportState('error');
    }
  };

  // Library import file handler
  const handleLibraryFile = useCallback(async (file: File) => {
    if (!file.name.endsWith('.json') && !file.name.endsWith('.json.gz')) {
      setLibraryImportError('Please select a JSON or gzipped JSON file');
      setLibraryImportState('error');
      return;
    }

    setLibraryImportState('uploading');
    setLibraryImportError(null);
    setLibraryImportPreview(null);
    setLibraryImportProgress(0);

    try {
      setLibraryImportState('previewing');
      const preview = await libraryExportApi.previewImport(file, (loaded, total) => {
        setLibraryImportProgress(Math.round((loaded / total) * 100));
      });
      setLibraryImportPreview(preview);
      setLibraryImportState('ready');
    } catch (error) {
      console.error('Library import preview failed:', error);
      setLibraryImportError(error instanceof Error ? error.message : 'Failed to read file');
      setLibraryImportState('error');
    }
  }, []);

  // Library drag handlers
  const handleLibraryDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setLibraryDragActive(true);
    } else if (e.type === 'dragleave') {
      setLibraryDragActive(false);
    }
  }, []);

  const handleLibraryDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setLibraryDragActive(false);

      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleLibraryFile(e.dataTransfer.files[0]);
      }
    },
    [handleLibraryFile]
  );

  const handleLibraryFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleLibraryFile(e.target.files[0]);
    }
  };

  // Execute library import
  const executeLibraryImport = async () => {
    if (!libraryImportPreview) return;

    setLibraryImportState('importing');
    setLibraryImportError(null);

    try {
      const result = await libraryExportApi.executeImport({
        session_id: libraryImportPreview.session_id,
        mode: libraryImportMode,
        apply_analysis: libraryImportOptions.apply_analysis,
        apply_embeddings: libraryImportOptions.apply_embeddings,
        apply_user_overrides: libraryImportOptions.apply_user_overrides,
      });
      setLibraryImportResult(result);
      setLibraryImportState('success');
    } catch (error) {
      console.error('Library import failed:', error);
      setLibraryImportError(error instanceof Error ? error.message : 'Import failed');
      setLibraryImportState('error');
    }
  };

  // Reset library import state
  const resetLibraryImport = () => {
    setLibraryImportState('idle');
    setLibraryImportError(null);
    setLibraryImportPreview(null);
    setLibraryImportResult(null);
    setLibraryImportProgress(0);
    if (libraryFileInputRef.current) {
      libraryFileInputRef.current.value = '';
    }
  };

  const toggleLibraryExportOption = (key: keyof LibraryExportOptions) => {
    setLibraryExportOptions((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const toggleLibraryImportOption = (key: keyof LibraryImportOptions) => {
    setLibraryImportOptions((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="space-y-6">
      {/* Export Section */}
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-3 mb-4">
          <Download className="w-5 h-5 text-zinc-400" />
          <div>
            <h4 className="font-medium text-white">Export Data</h4>
            <p className="text-sm text-zinc-400">
              Download your playlists, favorites, and play history
            </p>
          </div>
        </div>

        {/* Export options */}
        <div className="grid grid-cols-2 gap-2 mb-4">
          {Object.entries({
            include_play_history: 'Play History',
            include_favorites: 'Favorites',
            include_playlists: 'Playlists',
            include_smart_playlists: 'Smart Playlists',
            include_proposed_changes: 'Pending Changes',
            include_external_tracks: 'Wishlist Items',
          }).map(([key, label]) => (
            <label
              key={key}
              className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer"
            >
              <input
                type="checkbox"
                checked={exportOptions[key as keyof ExportOptions]}
                onChange={() => toggleExportOption(key as keyof ExportOptions)}
                className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
              />
              {label}
            </label>
          ))}
        </div>

        {/* Export button and status */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleExport}
            disabled={exportState === 'exporting'}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-md flex items-center gap-2 text-sm font-medium"
          >
            {exportState === 'exporting' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            {exportState === 'exporting' ? 'Exporting...' : 'Export'}
          </button>

          {exportState === 'success' && (
            <span className="flex items-center gap-1 text-sm text-green-400">
              <CheckCircle className="w-4 h-4" />
              Download started
            </span>
          )}

          {exportState === 'error' && (
            <span className="flex items-center gap-1 text-sm text-red-400">
              <AlertCircle className="w-4 h-4" />
              {exportError}
            </span>
          )}
        </div>
      </div>

      {/* Import Section */}
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-3 mb-4">
          <Upload className="w-5 h-5 text-zinc-400" />
          <div>
            <h4 className="font-medium text-white">Import Data</h4>
            <p className="text-sm text-zinc-400">
              Restore data from a Familiar export file
            </p>
          </div>
        </div>

        {/* File drop zone - shown when idle or error */}
        {(importState === 'idle' || importState === 'error') && (
          <div
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            className={`
              border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer
              ${dragActive
                ? 'border-blue-500 bg-blue-500/10'
                : 'border-zinc-600 hover:border-zinc-500'
              }
            `}
            onClick={() => fileInputRef.current?.click()}
          >
            <FileJson className="w-10 h-10 text-zinc-500 mx-auto mb-3" />
            <p className="text-sm text-zinc-400 mb-1">
              Drop a Familiar export file here, or click to browse
            </p>
            <p className="text-xs text-zinc-500">
              JSON files only
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              onChange={handleFileInput}
              className="hidden"
            />
          </div>
        )}

        {/* Error message */}
        {importState === 'error' && importError && (
          <div className="mt-3 p-3 bg-red-900/20 border border-red-800 rounded-lg flex items-start gap-2">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm text-red-300">{importError}</p>
              <button
                onClick={resetImport}
                className="mt-2 text-xs text-red-400 hover:text-red-300"
              >
                Try again
              </button>
            </div>
          </div>
        )}

        {/* Previewing state */}
        {importState === 'previewing' && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
            <span className="ml-2 text-zinc-400">Analyzing file...</span>
          </div>
        )}

        {/* Preview ready */}
        {importState === 'ready' && importPreview && (
          <div className="space-y-4">
            {/* File info */}
            <div className="flex items-center justify-between p-3 bg-zinc-700/50 rounded-lg">
              <div className="flex items-center gap-3">
                <FileJson className="w-8 h-8 text-blue-400" />
                <div>
                  <p className="text-sm font-medium text-white">
                    {importPreview.profile_name || 'Unknown Profile'}
                  </p>
                  <p className="text-xs text-zinc-400">
                    Exported {importPreview.exported_at
                      ? new Date(importPreview.exported_at).toLocaleDateString()
                      : 'date unknown'}
                    {importPreview.familiar_version && ` (v${importPreview.familiar_version})`}
                  </p>
                </div>
              </div>
              <button
                onClick={resetImport}
                className="p-1.5 text-zinc-400 hover:text-white rounded"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Warnings */}
            {importPreview.warnings.length > 0 && (
              <div className="p-3 bg-yellow-900/20 border border-yellow-800 rounded-lg">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-yellow-300">Warnings</p>
                    <ul className="mt-1 text-xs text-yellow-200/80 space-y-1">
                      {importPreview.warnings.map((warning, i) => (
                        <li key={i}>{warning}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            )}

            {/* Matching stats */}
            <div className="p-3 bg-zinc-700/50 rounded-lg">
              <div className="flex items-start gap-2 mb-3">
                <Info className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-white">Track Matching</p>
                  <p className="text-xs text-zinc-400">
                    {importPreview.matching.matched} of {importPreview.matching.total} tracks matched to your library
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-2 text-center text-xs">
                <div className="bg-zinc-600/50 rounded p-2">
                  <div className="text-green-400 font-medium">
                    {importPreview.matching.by_method.isrc || 0}
                  </div>
                  <div className="text-zinc-500">ISRC</div>
                </div>
                <div className="bg-zinc-600/50 rounded p-2">
                  <div className="text-blue-400 font-medium">
                    {importPreview.matching.by_method.musicbrainz || 0}
                  </div>
                  <div className="text-zinc-500">MusicBrainz</div>
                </div>
                <div className="bg-zinc-600/50 rounded p-2">
                  <div className="text-purple-400 font-medium">
                    {importPreview.matching.by_method.exact || 0}
                  </div>
                  <div className="text-zinc-500">Exact</div>
                </div>
                <div className="bg-zinc-600/50 rounded p-2">
                  <div className="text-yellow-400 font-medium">
                    {importPreview.matching.by_method.fuzzy || 0}
                  </div>
                  <div className="text-zinc-500">Fuzzy</div>
                </div>
              </div>

              {/* Unmatched samples */}
              {importPreview.matching.unmatched_samples.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs text-zinc-400 mb-2">
                    Unmatched tracks (sample):
                  </p>
                  <div className="space-y-1">
                    {importPreview.matching.unmatched_samples.slice(0, 5).map((track, i) => (
                      <div key={i} className="text-xs text-zinc-500 truncate">
                        {track.artist} - {track.title}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Data summary */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
              <div className="bg-zinc-700/50 rounded p-2">
                <div className="text-white font-medium">
                  {importPreview.summary.play_history_count}
                </div>
                <div className="text-zinc-500">Plays</div>
              </div>
              <div className="bg-zinc-700/50 rounded p-2">
                <div className="text-white font-medium">
                  {importPreview.summary.favorites_count}
                </div>
                <div className="text-zinc-500">Favorites</div>
              </div>
              <div className="bg-zinc-700/50 rounded p-2">
                <div className="text-white font-medium">
                  {importPreview.summary.playlists_count}
                </div>
                <div className="text-zinc-500">Playlists</div>
              </div>
              <div className="bg-zinc-700/50 rounded p-2">
                <div className="text-white font-medium">
                  {importPreview.summary.smart_playlists_count}
                </div>
                <div className="text-zinc-500">Smart Playlists</div>
              </div>
            </div>

            {/* Import options */}
            <div>
              <p className="text-sm text-zinc-400 mb-2">Import options:</p>
              <div className="grid grid-cols-2 gap-2 mb-3">
                {Object.entries({
                  import_play_history: 'Play History',
                  import_favorites: 'Favorites',
                  import_playlists: 'Playlists',
                  import_smart_playlists: 'Smart Playlists',
                  import_user_overrides: 'User Overrides',
                  import_external_tracks: 'Wishlist Items',
                }).map(([key, label]) => (
                  <label
                    key={key}
                    className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={importOptions[key as keyof ImportOptions]}
                      onChange={() => toggleImportOption(key as keyof ImportOptions)}
                      className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                    />
                    {label}
                  </label>
                ))}
              </div>

              {/* Import mode */}
              <div className="flex items-center gap-4 mb-4">
                <span className="text-sm text-zinc-400">Mode:</span>
                <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                  <input
                    type="radio"
                    name="importMode"
                    checked={importMode === 'merge'}
                    onChange={() => setImportMode('merge')}
                    className="w-4 h-4 border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                  />
                  Merge (recommended)
                </label>
                <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                  <input
                    type="radio"
                    name="importMode"
                    checked={importMode === 'overwrite'}
                    onChange={() => setImportMode('overwrite')}
                    className="w-4 h-4 border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                  />
                  Overwrite
                </label>
              </div>
            </div>

            {/* Import button */}
            <div className="flex items-center gap-3">
              <button
                onClick={executeImport}
                className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-md flex items-center gap-2 text-sm font-medium"
              >
                <Upload className="w-4 h-4" />
                Import Data
              </button>
              <button
                onClick={resetImport}
                className="px-4 py-2 text-zinc-400 hover:text-white text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Importing state */}
        {importState === 'importing' && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 text-green-400 animate-spin" />
            <span className="ml-2 text-zinc-400">Importing data...</span>
          </div>
        )}

        {/* Import success */}
        {importState === 'success' && importResult && (
          <div className="space-y-4">
            <div className="p-4 bg-green-900/20 border border-green-800 rounded-lg">
              <div className="flex items-center gap-2">
                <CheckCircle className="w-5 h-5 text-green-400" />
                <p className="text-sm font-medium text-green-300">Import completed</p>
              </div>
            </div>

            {/* Results grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-center text-xs">
              {Object.entries({
                play_history: 'Plays',
                favorites: 'Favorites',
                playlists: 'Playlists',
                smart_playlists: 'Smart Playlists',
                user_overrides: 'Overrides',
                external_tracks: 'Wishlist',
              }).map(([key, label]) => {
                const result = importResult.results[key as keyof typeof importResult.results];
                if (typeof result === 'object' && 'imported' in result) {
                  return (
                    <div key={key} className="bg-zinc-700/50 rounded p-2">
                      <div className="text-green-400 font-medium">{result.imported}</div>
                      <div className="text-zinc-500">{label}</div>
                      {result.skipped > 0 && (
                        <div className="text-xs text-zinc-600">({result.skipped} skipped)</div>
                      )}
                    </div>
                  );
                }
                return null;
              })}
            </div>

            {/* Show any errors */}
            {Object.entries(importResult.results).some(
              ([_, v]) => typeof v === 'object' && 'errors' in v && (v as { errors: string[] }).errors.length > 0
            ) && (
              <div className="p-3 bg-yellow-900/20 border border-yellow-800 rounded-lg">
                <p className="text-sm font-medium text-yellow-300 mb-2">Some items had errors:</p>
                <ul className="text-xs text-yellow-200/80 space-y-1">
                  {Object.entries(importResult.results).map(([key, v]) => {
                    if (typeof v === 'object' && 'errors' in v) {
                      const errors = (v as { errors: string[] }).errors;
                      return errors.map((err, i) => (
                        <li key={`${key}-${i}`}>{err}</li>
                      ));
                    }
                    return null;
                  })}
                </ul>
              </div>
            )}

            <button
              onClick={resetImport}
              className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-md text-sm"
            >
              Done
            </button>
          </div>
        )}
      </div>

      {/* Library Migration Section */}
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-3 mb-2">
          <HardDrive className="w-5 h-5 text-zinc-400" />
          <div>
            <h4 className="font-medium text-white">Library Migration</h4>
            <p className="text-sm text-zinc-400">
              Export/import analysis data when migrating to a new machine
            </p>
          </div>
        </div>
        <p className="text-xs text-zinc-500 mb-4 ml-8">
          Includes audio embeddings, features, and fingerprints. Import after scanning your library on the new machine.
        </p>

        {/* Library Export */}
        <div className="border-t border-zinc-700 pt-4 mb-4">
          <div className="flex items-center gap-2 mb-3">
            <Download className="w-4 h-4 text-zinc-400" />
            <span className="text-sm font-medium text-white">Export Library</span>
          </div>

          {/* Export options */}
          <div className="grid grid-cols-2 gap-2 mb-3 ml-6">
            {Object.entries({
              include_embeddings: 'Audio Embeddings',
              include_acoustid: 'Fingerprints',
              compress: 'Compress (gzip)',
            }).map(([key, label]) => (
              <label
                key={key}
                className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={libraryExportOptions[key as keyof LibraryExportOptions]}
                  onChange={() => toggleLibraryExportOption(key as keyof LibraryExportOptions)}
                  className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                />
                {label}
              </label>
            ))}
          </div>

          <div className="flex items-center gap-3 ml-6">
            <button
              onClick={handleLibraryExport}
              disabled={libraryExportState === 'exporting'}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-md flex items-center gap-2 text-sm font-medium"
            >
              {libraryExportState === 'exporting' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <FileArchive className="w-4 h-4" />
              )}
              {libraryExportState === 'exporting'
                ? `Exporting... ${libraryExportProgress}%`
                : 'Export Library'}
            </button>

            {libraryExportState === 'success' && (
              <span className="flex items-center gap-1 text-sm text-green-400">
                <CheckCircle className="w-4 h-4" />
                Download started
              </span>
            )}

            {libraryExportState === 'error' && (
              <span className="flex items-center gap-1 text-sm text-red-400">
                <AlertCircle className="w-4 h-4" />
                {libraryExportError}
              </span>
            )}
          </div>
        </div>

        {/* Library Import */}
        <div className="border-t border-zinc-700 pt-4">
          <div className="flex items-center gap-2 mb-3">
            <Upload className="w-4 h-4 text-zinc-400" />
            <span className="text-sm font-medium text-white">Import Library</span>
          </div>

          {/* File drop zone - shown when idle or error */}
          {(libraryImportState === 'idle' || libraryImportState === 'error') && (
            <div
              onDragEnter={handleLibraryDrag}
              onDragLeave={handleLibraryDrag}
              onDragOver={handleLibraryDrag}
              onDrop={handleLibraryDrop}
              className={`
                ml-6 border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer
                ${libraryDragActive
                  ? 'border-blue-500 bg-blue-500/10'
                  : 'border-zinc-600 hover:border-zinc-500'
                }
              `}
              onClick={() => libraryFileInputRef.current?.click()}
            >
              <FileArchive className="w-8 h-8 text-zinc-500 mx-auto mb-2" />
              <p className="text-sm text-zinc-400 mb-1">
                Drop a library export file here, or click to browse
              </p>
              <p className="text-xs text-zinc-500">
                .json or .json.gz files
              </p>
              <input
                ref={libraryFileInputRef}
                type="file"
                accept=".json,.json.gz"
                onChange={handleLibraryFileInput}
                className="hidden"
              />
            </div>
          )}

          {/* Error message */}
          {libraryImportState === 'error' && libraryImportError && (
            <div className="ml-6 mt-3 p-3 bg-red-900/20 border border-red-800 rounded-lg flex items-start gap-2">
              <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm text-red-300">{libraryImportError}</p>
                <button
                  onClick={resetLibraryImport}
                  className="mt-2 text-xs text-red-400 hover:text-red-300"
                >
                  Try again
                </button>
              </div>
            </div>
          )}

          {/* Uploading/Previewing state */}
          {(libraryImportState === 'uploading' || libraryImportState === 'previewing') && (
            <div className="ml-6 flex items-center justify-center py-6">
              <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
              <span className="ml-2 text-zinc-400">
                {libraryImportState === 'uploading'
                  ? `Uploading... ${libraryImportProgress}%`
                  : 'Analyzing file...'}
              </span>
            </div>
          )}

          {/* Preview ready */}
          {libraryImportState === 'ready' && libraryImportPreview && (
            <div className="ml-6 space-y-4">
              {/* File info */}
              <div className="flex items-center justify-between p-3 bg-zinc-700/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <FileArchive className="w-8 h-8 text-blue-400" />
                  <div>
                    <p className="text-sm font-medium text-white">
                      Library Export
                    </p>
                    <p className="text-xs text-zinc-400">
                      {libraryImportPreview.summary.total_tracks.toLocaleString()} tracks
                      {libraryImportPreview.exported_at && (
                        <> • Exported {new Date(libraryImportPreview.exported_at).toLocaleDateString()}</>
                      )}
                      {libraryImportPreview.familiar_version && (
                        <> • v{libraryImportPreview.familiar_version}</>
                      )}
                    </p>
                  </div>
                </div>
                <button
                  onClick={resetLibraryImport}
                  className="p-1.5 text-zinc-400 hover:text-white rounded"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Warnings */}
              {libraryImportPreview.warnings.length > 0 && (
                <div className="p-3 bg-yellow-900/20 border border-yellow-800 rounded-lg">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm font-medium text-yellow-300">Warnings</p>
                      <ul className="mt-1 text-xs text-yellow-200/80 space-y-1">
                        {libraryImportPreview.warnings.map((warning, i) => (
                          <li key={i}>{warning}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              )}

              {/* Matching stats */}
              <div className="p-3 bg-zinc-700/50 rounded-lg">
                <div className="flex items-start gap-2 mb-3">
                  <Info className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-white">Track Matching</p>
                    <p className="text-xs text-zinc-400">
                      {libraryImportPreview.matching.matched.toLocaleString()} of{' '}
                      {libraryImportPreview.matching.total.toLocaleString()} tracks matched
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-center text-xs">
                  <div className="bg-zinc-600/50 rounded p-2">
                    <div className="text-green-400 font-medium">
                      {libraryImportPreview.matching.by_method.file_hash || 0}
                    </div>
                    <div className="text-zinc-500">File Hash</div>
                  </div>
                  <div className="bg-zinc-600/50 rounded p-2">
                    <div className="text-green-400 font-medium">
                      {libraryImportPreview.matching.by_method.acoustid || 0}
                    </div>
                    <div className="text-zinc-500">AcoustID</div>
                  </div>
                  <div className="bg-zinc-600/50 rounded p-2">
                    <div className="text-blue-400 font-medium">
                      {libraryImportPreview.matching.by_method.isrc || 0}
                    </div>
                    <div className="text-zinc-500">ISRC</div>
                  </div>
                  <div className="bg-zinc-600/50 rounded p-2">
                    <div className="text-blue-400 font-medium">
                      {libraryImportPreview.matching.by_method.musicbrainz || 0}
                    </div>
                    <div className="text-zinc-500">MusicBrainz</div>
                  </div>
                  <div className="bg-zinc-600/50 rounded p-2">
                    <div className="text-purple-400 font-medium">
                      {libraryImportPreview.matching.by_method.exact_with_duration || 0}
                    </div>
                    <div className="text-zinc-500">Exact</div>
                  </div>
                  <div className="bg-zinc-600/50 rounded p-2">
                    <div className="text-yellow-400 font-medium">
                      {libraryImportPreview.matching.by_method.fuzzy || 0}
                    </div>
                    <div className="text-zinc-500">Fuzzy</div>
                  </div>
                </div>

                {/* Unmatched samples */}
                {libraryImportPreview.matching.unmatched_samples.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-zinc-400 mb-2">
                      Unmatched tracks (not in local library):
                    </p>
                    <div className="space-y-1">
                      {libraryImportPreview.matching.unmatched_samples.slice(0, 5).map((track, i) => (
                        <div key={i} className="text-xs text-zinc-500 truncate">
                          {track.artist} - {track.title}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Data summary */}
              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <div className="bg-zinc-700/50 rounded p-2">
                  <div className="text-white font-medium">
                    {libraryImportPreview.summary.tracks_with_analysis.toLocaleString()}
                  </div>
                  <div className="text-zinc-500">With Analysis</div>
                </div>
                <div className="bg-zinc-700/50 rounded p-2">
                  <div className="text-white font-medium">
                    {libraryImportPreview.summary.tracks_with_embeddings.toLocaleString()}
                  </div>
                  <div className="text-zinc-500">With Embeddings</div>
                </div>
                <div className="bg-zinc-700/50 rounded p-2">
                  <div className="text-white font-medium">
                    {libraryImportPreview.summary.tracks_with_user_overrides.toLocaleString()}
                  </div>
                  <div className="text-zinc-500">User Overrides</div>
                </div>
              </div>

              {/* Import options */}
              <div>
                <p className="text-sm text-zinc-400 mb-2">Import options:</p>
                <div className="grid grid-cols-2 gap-2 mb-3">
                  {Object.entries({
                    apply_analysis: 'Analysis Features',
                    apply_embeddings: 'Audio Embeddings',
                    apply_user_overrides: 'User Overrides',
                  }).map(([key, label]) => (
                    <label
                      key={key}
                      className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={libraryImportOptions[key as keyof LibraryImportOptions]}
                        onChange={() => toggleLibraryImportOption(key as keyof LibraryImportOptions)}
                        className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                      />
                      {label}
                    </label>
                  ))}
                </div>

                {/* Import mode */}
                <div className="flex items-center gap-4 mb-4">
                  <span className="text-sm text-zinc-400">Mode:</span>
                  <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                    <input
                      type="radio"
                      name="libraryImportMode"
                      checked={libraryImportMode === 'match_only'}
                      onChange={() => setLibraryImportMode('match_only')}
                      className="w-4 h-4 border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                    />
                    Match only
                  </label>
                  <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                    <input
                      type="radio"
                      name="libraryImportMode"
                      checked={libraryImportMode === 'merge'}
                      onChange={() => setLibraryImportMode('merge')}
                      className="w-4 h-4 border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                    />
                    Merge (fill gaps)
                  </label>
                  <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                    <input
                      type="radio"
                      name="libraryImportMode"
                      checked={libraryImportMode === 'replace'}
                      onChange={() => setLibraryImportMode('replace')}
                      className="w-4 h-4 border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                    />
                    Replace
                  </label>
                </div>
              </div>

              {/* Import button */}
              <div className="flex items-center gap-3">
                <button
                  onClick={executeLibraryImport}
                  className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-md flex items-center gap-2 text-sm font-medium"
                >
                  <Upload className="w-4 h-4" />
                  Import Library Data
                </button>
                <button
                  onClick={resetLibraryImport}
                  className="px-4 py-2 text-zinc-400 hover:text-white text-sm"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Importing state */}
          {libraryImportState === 'importing' && (
            <div className="ml-6 flex items-center justify-center py-6">
              <Loader2 className="w-6 h-6 text-green-400 animate-spin" />
              <span className="ml-2 text-zinc-400">Importing library data...</span>
            </div>
          )}

          {/* Import success */}
          {libraryImportState === 'success' && libraryImportResult && (
            <div className="ml-6 space-y-4">
              <div className="p-4 bg-green-900/20 border border-green-800 rounded-lg">
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-5 h-5 text-green-400" />
                  <p className="text-sm font-medium text-green-300">Library import completed</p>
                </div>
              </div>

              {/* Results grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
                <div className="bg-zinc-700/50 rounded p-2">
                  <div className="text-green-400 font-medium">
                    {libraryImportResult.results.analysis_imported}
                  </div>
                  <div className="text-zinc-500">Analysis</div>
                </div>
                <div className="bg-zinc-700/50 rounded p-2">
                  <div className="text-green-400 font-medium">
                    {libraryImportResult.results.embeddings_imported}
                  </div>
                  <div className="text-zinc-500">Embeddings</div>
                </div>
                <div className="bg-zinc-700/50 rounded p-2">
                  <div className="text-green-400 font-medium">
                    {libraryImportResult.results.user_overrides_imported}
                  </div>
                  <div className="text-zinc-500">Overrides</div>
                </div>
                <div className="bg-zinc-700/50 rounded p-2">
                  <div className="text-zinc-400 font-medium">
                    {libraryImportResult.results.skipped}
                  </div>
                  <div className="text-zinc-500">Skipped</div>
                </div>
              </div>

              {/* Show any errors */}
              {libraryImportResult.results.errors.length > 0 && (
                <div className="p-3 bg-yellow-900/20 border border-yellow-800 rounded-lg">
                  <p className="text-sm font-medium text-yellow-300 mb-2">Some items had errors:</p>
                  <ul className="text-xs text-yellow-200/80 space-y-1">
                    {libraryImportResult.results.errors.slice(0, 10).map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                    {libraryImportResult.results.errors.length > 10 && (
                      <li>...and {libraryImportResult.results.errors.length - 10} more</li>
                    )}
                  </ul>
                </div>
              )}

              <button
                onClick={resetLibraryImport}
                className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-md text-sm"
              >
                Done
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
