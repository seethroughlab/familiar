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
  backupApi,
  type RestorePreviewResponse,
  type RestoreExecuteResponse,
} from '../../api';

import { createLogger } from '../../utils/logger';

const log = createLogger('DataManagement');

type BackupState = 'idle' | 'exporting' | 'success' | 'error';
type RestoreState = 'idle' | 'uploading' | 'previewing' | 'ready' | 'restoring' | 'success' | 'error';

interface ProfileExportOptions {
  include_play_history: boolean;
  include_favorites: boolean;
  include_playlists: boolean;
  include_smart_playlists: boolean;
  include_proposed_changes: boolean;
}

interface LibraryExportOptions {
  include_library_analysis: boolean;
  include_embeddings: boolean;
  include_acoustid: boolean;
}

interface ProfileImportOptions {
  import_play_history: boolean;
  import_favorites: boolean;
  import_playlists: boolean;
  import_smart_playlists: boolean;
  import_proposed_changes: boolean;
  import_user_overrides: boolean;
}

interface LibraryImportOptions {
  apply_analysis: boolean;
  apply_embeddings: boolean;
  apply_library_user_overrides: boolean;
}

export function DataManagement() {
  // Backup (export) state
  const [backupState, setBackupState] = useState<BackupState>('idle');
  const [backupError, setBackupError] = useState<string | null>(null);
  const [backupProgress, setBackupProgress] = useState<number>(0);

  // Export options
  const [profileExportOptions, setProfileExportOptions] = useState<ProfileExportOptions>({
    include_play_history: true,
    include_favorites: true,
    include_playlists: true,
    include_smart_playlists: true,
    include_proposed_changes: true,
  });

  const [libraryExportOptions, setLibraryExportOptions] = useState<LibraryExportOptions>({
    include_library_analysis: false,
    include_embeddings: true,
    include_acoustid: true,
  });

  const [compressBackup, setCompressBackup] = useState(true);

  // Restore (import) state
  const [restoreState, setRestoreState] = useState<RestoreState>('idle');
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreProgress, setRestoreProgress] = useState<number>(0);
  const [restorePreview, setRestorePreview] = useState<RestorePreviewResponse | null>(null);
  const [restoreResult, setRestoreResult] = useState<RestoreExecuteResponse | null>(null);

  // Import options
  const [profileImportMode, setProfileImportMode] = useState<'merge' | 'overwrite'>('merge');
  const [profileImportOptions, setProfileImportOptions] = useState<ProfileImportOptions>({
    import_play_history: true,
    import_favorites: true,
    import_playlists: true,
    import_smart_playlists: true,
    import_proposed_changes: true,
    import_user_overrides: true,
  });

  const [libraryImportMode, setLibraryImportMode] = useState<'match_only' | 'merge' | 'replace'>('match_only');
  const [libraryImportOptions, setLibraryImportOptions] = useState<LibraryImportOptions>({
    apply_analysis: true,
    apply_embeddings: true,
    apply_library_user_overrides: true,
  });

  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ==================== BACKUP HANDLERS ====================

  const handleBackup = async () => {
    setBackupState('exporting');
    setBackupError(null);
    setBackupProgress(0);

    try {
      await backupApi.downloadBackup(
        {
          ...profileExportOptions,
          ...libraryExportOptions,
          compress: compressBackup,
        },
        (loaded, total) => {
          setBackupProgress(Math.round((loaded / total) * 100));
        }
      );
      setBackupState('success');
      setTimeout(() => setBackupState('idle'), 3000);
    } catch (error) {
      log.error('Backup failed:', error);
      setBackupError(error instanceof Error ? error.message : 'Backup failed');
      setBackupState('error');
    }
  };

  const toggleProfileExportOption = (key: keyof ProfileExportOptions) => {
    setProfileExportOptions((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const toggleLibraryExportOption = (key: keyof LibraryExportOptions) => {
    setLibraryExportOptions((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // ==================== RESTORE HANDLERS ====================

  const handleFile = useCallback(async (file: File) => {
    if (!file.name.endsWith('.json') && !file.name.endsWith('.json.gz')) {
      setRestoreError('Please select a JSON or gzipped JSON file');
      setRestoreState('error');
      return;
    }

    setRestoreState('uploading');
    setRestoreError(null);
    setRestorePreview(null);
    setRestoreProgress(0);

    try {
      setRestoreState('previewing');
      const preview = await backupApi.previewRestore(file, (loaded, total) => {
        setRestoreProgress(Math.round((loaded / total) * 100));
      });
      setRestorePreview(preview);
      setRestoreState('ready');
    } catch (error) {
      log.error('Restore preview failed:', error);
      setRestoreError(error instanceof Error ? error.message : 'Failed to read file');
      setRestoreState('error');
    }
  }, []);

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

  const executeRestore = async () => {
    if (!restorePreview) return;

    setRestoreState('restoring');
    setRestoreError(null);

    try {
      const result = await backupApi.executeRestore({
        session_id: restorePreview.session_id,
        mode: profileImportMode,
        ...profileImportOptions,
        library_mode: libraryImportMode,
        ...libraryImportOptions,
      });
      setRestoreResult(result);
      setRestoreState('success');
    } catch (error) {
      log.error('Restore failed:', error);
      setRestoreError(error instanceof Error ? error.message : 'Restore failed');
      setRestoreState('error');
    }
  };

  const resetRestore = () => {
    setRestoreState('idle');
    setRestoreError(null);
    setRestorePreview(null);
    setRestoreResult(null);
    setRestoreProgress(0);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const toggleProfileImportOption = (key: keyof ProfileImportOptions) => {
    setProfileImportOptions((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const toggleLibraryImportOption = (key: keyof LibraryImportOptions) => {
    setLibraryImportOptions((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Check if any profile data is selected for export
  const hasProfileDataSelected = Object.values(profileExportOptions).some(Boolean);
  const hasLibraryDataSelected = libraryExportOptions.include_library_analysis;

  return (
    <div className="space-y-6">
      {/* Unified Backup & Restore Section */}
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-3 mb-2">
          <HardDrive className="w-5 h-5 text-zinc-400" />
          <div>
            <h4 className="font-medium text-white">Backup & Restore</h4>
            <p className="text-sm text-zinc-400">
              Create a backup of your Familiar data for migration or safekeeping
            </p>
          </div>
        </div>

        {/* ==================== EXPORT SECTION ==================== */}
        <div className="border-t border-zinc-700 mt-4 pt-4">
          <div className="flex items-center gap-2 mb-4">
            <Download className="w-4 h-4 text-zinc-400" />
            <span className="text-sm font-medium text-white uppercase tracking-wide">Export</span>
          </div>

          {/* Profile Data Section */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-zinc-300">Profile Data</span>
              <span className="text-xs text-zinc-500">~100 KB</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 ml-2">
              {Object.entries({
                include_play_history: 'Play History',
                include_favorites: 'Favorites',
                include_playlists: 'Playlists',
                include_smart_playlists: 'Smart Playlists',
                include_proposed_changes: 'Pending Changes',
              }).map(([key, label]) => (
                <label
                  key={key}
                  className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={profileExportOptions[key as keyof ProfileExportOptions]}
                    onChange={() => toggleProfileExportOption(key as keyof ProfileExportOptions)}
                    className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>

          {/* Library Analysis Section */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-zinc-300">Library Analysis</span>
              <span className="text-xs text-zinc-500">~50-500 MB</span>
            </div>
            <div className="space-y-2 ml-2">
              <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={libraryExportOptions.include_library_analysis}
                  onChange={() => toggleLibraryExportOption('include_library_analysis')}
                  className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                />
                Audio analysis & embeddings
              </label>

              {libraryExportOptions.include_library_analysis && (
                <div className="ml-6 space-y-2">
                  <label className="flex items-center gap-2 text-sm text-zinc-400 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={libraryExportOptions.include_acoustid}
                      onChange={() => toggleLibraryExportOption('include_acoustid')}
                      className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                    />
                    Audio fingerprints
                  </label>
                </div>
              )}

              <p className="text-xs text-zinc-500 flex items-start gap-1.5 ml-6">
                <Info className="w-3 h-3 mt-0.5 flex-shrink-0" />
                Include when migrating to avoid re-analyzing your library
              </p>
            </div>
          </div>

          {/* Compress Option */}
          <div className="mb-4 ml-2">
            <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
              <input
                type="checkbox"
                checked={compressBackup}
                onChange={() => setCompressBackup(!compressBackup)}
                className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
              />
              Compress file (recommended)
            </label>
          </div>

          {/* Export Button */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleBackup}
              disabled={backupState === 'exporting' || (!hasProfileDataSelected && !hasLibraryDataSelected)}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-md flex items-center gap-2 text-sm font-medium"
            >
              {backupState === 'exporting' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <FileArchive className="w-4 h-4" />
              )}
              {backupState === 'exporting'
                ? backupProgress > 0
                  ? `Exporting... ${backupProgress}%`
                  : 'Preparing...'
                : 'Create Backup'}
            </button>

            {backupState === 'success' && (
              <span className="flex items-center gap-1 text-sm text-success">
                <CheckCircle className="w-4 h-4" />
                Download started
              </span>
            )}

            {backupState === 'error' && (
              <span className="flex items-center gap-1 text-sm text-danger">
                <AlertCircle className="w-4 h-4" />
                {backupError}
              </span>
            )}
          </div>
        </div>

        {/* ==================== RESTORE SECTION ==================== */}
        <div className="border-t border-zinc-700 mt-6 pt-4">
          <div className="flex items-center gap-2 mb-4">
            <Upload className="w-4 h-4 text-zinc-400" />
            <span className="text-sm font-medium text-white uppercase tracking-wide">Restore</span>
          </div>

          {/* File Drop Zone - shown when idle or error */}
          {(restoreState === 'idle' || restoreState === 'error') && (
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              className={`
                border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer
                ${dragActive
                  ? 'border-blue-500 bg-blue-500/10'
                  : 'border-zinc-600 hover:border-zinc-500'
                }
              `}
              onClick={() => fileInputRef.current?.click()}
            >
              <FileJson className="w-8 h-8 text-zinc-500 mx-auto mb-2" />
              <p className="text-sm text-zinc-400 mb-1">
                Drop a backup file here, or click to browse
              </p>
              <p className="text-xs text-zinc-500">
                .json or .json.gz files
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,.json.gz"
                onChange={handleFileInput}
                className="hidden"
              />
            </div>
          )}

          {/* Error Message */}
          {restoreState === 'error' && restoreError && (
            <div className="mt-3 p-3 bg-danger-surface/20 border border-danger-muted rounded-lg flex items-start gap-2">
              <AlertCircle className="w-5 h-5 text-danger flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm text-danger">{restoreError}</p>
                <button
                  onClick={resetRestore}
                  className="mt-2 text-xs text-danger hover:text-danger"
                >
                  Try again
                </button>
              </div>
            </div>
          )}

          {/* Uploading/Previewing State */}
          {(restoreState === 'uploading' || restoreState === 'previewing') && (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
              <span className="ml-2 text-zinc-400">
                {restoreState === 'uploading'
                  ? `Uploading... ${restoreProgress}%`
                  : 'Analyzing file...'}
              </span>
            </div>
          )}

          {/* Preview Ready */}
          {restoreState === 'ready' && restorePreview && (
            <div className="space-y-4">
              {/* File Info */}
              <div className="flex items-center justify-between p-3 bg-zinc-700/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <FileArchive className="w-8 h-8 text-blue-400" />
                  <div>
                    <p className="text-sm font-medium text-white">
                      {restorePreview.profile_name || 'Familiar Backup'}
                    </p>
                    <p className="text-xs text-zinc-400">
                      {restorePreview.exported_at && (
                        <>Exported {new Date(restorePreview.exported_at).toLocaleDateString()}</>
                      )}
                      {restorePreview.familiar_version && (
                        <> • v{restorePreview.familiar_version}</>
                      )}
                    </p>
                  </div>
                </div>
                <button
                  onClick={resetRestore}
                  className="p-1.5 text-zinc-400 hover:text-white rounded"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Warnings */}
              {restorePreview.warnings.length > 0 && (
                <div className="p-3 bg-warning-surface/20 border border-warning-muted rounded-lg">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="w-5 h-5 text-warning flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm font-medium text-warning-subtle">Warnings</p>
                      <ul className="mt-1 text-xs text-warning-subtle/80 space-y-1">
                        {restorePreview.warnings.map((warning, i) => (
                          <li key={i}>{warning}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              )}

              {/* Profile Data Section */}
              {restorePreview.summary.has_profile_data && (
                <div className="p-3 bg-zinc-700/50 rounded-lg">
                  <div className="flex items-start gap-2 mb-3">
                    <Info className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm font-medium text-white">Profile Data</p>
                      {restorePreview.profile_matching.total > 0 && (
                        <p className="text-xs text-zinc-400">
                          {restorePreview.profile_matching.matched} of {restorePreview.profile_matching.total} tracks matched
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Profile Data Summary */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs mb-3">
                    <div className="bg-zinc-600/50 rounded p-2">
                      <div className="text-white font-medium">
                        {restorePreview.summary.profile?.play_history_count || 0}
                      </div>
                      <div className="text-zinc-500">Plays</div>
                    </div>
                    <div className="bg-zinc-600/50 rounded p-2">
                      <div className="text-white font-medium">
                        {restorePreview.summary.profile?.favorites_count || 0}
                      </div>
                      <div className="text-zinc-500">Favorites</div>
                    </div>
                    <div className="bg-zinc-600/50 rounded p-2">
                      <div className="text-white font-medium">
                        {restorePreview.summary.profile?.playlists_count || 0}
                      </div>
                      <div className="text-zinc-500">Playlists</div>
                    </div>
                    <div className="bg-zinc-600/50 rounded p-2">
                      <div className="text-white font-medium">
                        {restorePreview.summary.profile?.smart_playlists_count || 0}
                      </div>
                      <div className="text-zinc-500">Smart</div>
                    </div>
                  </div>

                  {/* Profile Import Options */}
                  <div className="grid grid-cols-2 gap-2 mb-3">
                    {Object.entries({
                      import_play_history: 'Play History',
                      import_favorites: 'Favorites',
                      import_playlists: 'Playlists',
                      import_smart_playlists: 'Smart Playlists',
                      import_user_overrides: 'User Overrides',
                    }).map(([key, label]) => (
                      <label
                        key={key}
                        className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={profileImportOptions[key as keyof ProfileImportOptions]}
                          onChange={() => toggleProfileImportOption(key as keyof ProfileImportOptions)}
                          className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                        />
                        {label}
                      </label>
                    ))}
                  </div>

                  {/* Profile Import Mode */}
                  <div className="flex items-center gap-4">
                    <span className="text-sm text-zinc-400">Mode:</span>
                    <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                      <input
                        type="radio"
                        name="profileImportMode"
                        checked={profileImportMode === 'merge'}
                        onChange={() => setProfileImportMode('merge')}
                        className="w-4 h-4 border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                      />
                      Merge (recommended)
                    </label>
                    <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                      <input
                        type="radio"
                        name="profileImportMode"
                        checked={profileImportMode === 'overwrite'}
                        onChange={() => setProfileImportMode('overwrite')}
                        className="w-4 h-4 border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-800"
                      />
                      Overwrite
                    </label>
                  </div>
                </div>
              )}

              {/* Library Data Section */}
              {restorePreview.summary.has_library_data && (
                <div className="p-3 bg-zinc-700/50 rounded-lg">
                  <div className="flex items-start gap-2 mb-3">
                    <HardDrive className="w-5 h-5 text-purple-400 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm font-medium text-white">Library Analysis</p>
                      <p className="text-xs text-zinc-400">
                        {restorePreview.library_matching.matched.toLocaleString()} of{' '}
                        {restorePreview.library_matching.total.toLocaleString()} tracks matched
                      </p>
                    </div>
                  </div>

                  {/* Library Data Summary */}
                  <div className="grid grid-cols-3 gap-2 text-center text-xs mb-3">
                    <div className="bg-zinc-600/50 rounded p-2">
                      <div className="text-white font-medium">
                        {(restorePreview.summary.library?.tracks_with_analysis || 0).toLocaleString()}
                      </div>
                      <div className="text-zinc-500">With Analysis</div>
                    </div>
                    <div className="bg-zinc-600/50 rounded p-2">
                      <div className="text-white font-medium">
                        {(restorePreview.summary.library?.tracks_with_embeddings || 0).toLocaleString()}
                      </div>
                      <div className="text-zinc-500">With Embeddings</div>
                    </div>
                    <div className="bg-zinc-600/50 rounded p-2">
                      <div className="text-white font-medium">
                        {(restorePreview.summary.library?.tracks_with_user_overrides || 0).toLocaleString()}
                      </div>
                      <div className="text-zinc-500">User Overrides</div>
                    </div>
                  </div>

                  {/* Library Import Options */}
                  <div className="grid grid-cols-2 gap-2 mb-3">
                    {Object.entries({
                      apply_analysis: 'Analysis Features',
                      apply_embeddings: 'Audio Embeddings',
                      apply_library_user_overrides: 'User Overrides',
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

                  {/* Library Import Mode */}
                  <div className="flex flex-wrap items-center gap-4">
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
                      Merge
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
              )}

              {/* Restore Button */}
              <div className="flex items-center gap-3">
                <button
                  onClick={executeRestore}
                  className="px-4 py-2 bg-accent hover:bg-accent rounded-md flex items-center gap-2 text-sm font-medium"
                >
                  <Upload className="w-4 h-4" />
                  Restore Backup
                </button>
                <button
                  onClick={resetRestore}
                  className="px-4 py-2 text-zinc-400 hover:text-white text-sm"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Restoring State */}
          {restoreState === 'restoring' && (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="w-6 h-6 text-success animate-spin" />
              <span className="ml-2 text-zinc-400">Restoring data...</span>
            </div>
          )}

          {/* Restore Success */}
          {restoreState === 'success' && restoreResult && (
            <div className="space-y-4">
              <div className="p-4 bg-success-surface/20 border border-success-muted rounded-lg">
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-5 h-5 text-success" />
                  <p className="text-sm font-medium text-success">Restore completed</p>
                </div>
              </div>

              {/* Profile Results */}
              {restoreResult.results.profile && (
                <div>
                  <p className="text-xs text-zinc-400 uppercase tracking-wide mb-2">Profile Data</p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-center text-xs">
                    {Object.entries({
                      play_history: 'Plays',
                      favorites: 'Favorites',
                      playlists: 'Playlists',
                      smart_playlists: 'Smart',
                      user_overrides: 'Overrides',
                    }).map(([key, label]) => {
                      const result = restoreResult.results.profile?.[key as keyof typeof restoreResult.results.profile];
                      if (typeof result === 'object' && result !== null && 'imported' in result) {
                        return (
                          <div key={key} className="bg-zinc-700/50 rounded p-2">
                            <div className="text-success font-medium">{result.imported}</div>
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
                </div>
              )}

              {/* Library Results */}
              {restoreResult.results.library && (
                <div>
                  <p className="text-xs text-zinc-400 uppercase tracking-wide mb-2">Library Analysis</p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
                    <div className="bg-zinc-700/50 rounded p-2">
                      <div className="text-success font-medium">
                        {restoreResult.results.library.analysis_imported}
                      </div>
                      <div className="text-zinc-500">Analysis</div>
                    </div>
                    <div className="bg-zinc-700/50 rounded p-2">
                      <div className="text-success font-medium">
                        {restoreResult.results.library.embeddings_imported}
                      </div>
                      <div className="text-zinc-500">Embeddings</div>
                    </div>
                    <div className="bg-zinc-700/50 rounded p-2">
                      <div className="text-success font-medium">
                        {restoreResult.results.library.user_overrides_imported}
                      </div>
                      <div className="text-zinc-500">Overrides</div>
                    </div>
                    <div className="bg-zinc-700/50 rounded p-2">
                      <div className="text-zinc-400 font-medium">
                        {restoreResult.results.library.skipped}
                      </div>
                      <div className="text-zinc-500">Skipped</div>
                    </div>
                  </div>

                  {/* Library Errors */}
                  {restoreResult.results.library.errors.length > 0 && (
                    <div className="mt-3 p-3 bg-warning-surface/20 border border-warning-muted rounded-lg">
                      <p className="text-sm font-medium text-warning-subtle mb-2">Some items had errors:</p>
                      <ul className="text-xs text-warning-subtle/80 space-y-1">
                        {restoreResult.results.library.errors.slice(0, 10).map((err, i) => (
                          <li key={i}>{err}</li>
                        ))}
                        {restoreResult.results.library.errors.length > 10 && (
                          <li>...and {restoreResult.results.library.errors.length - 10} more</li>
                        )}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              <button
                onClick={resetRestore}
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
