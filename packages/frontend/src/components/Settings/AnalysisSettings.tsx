import { Cpu, AlertTriangle, CheckCircle, Info } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { appSettingsApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';

/**
 * Settings for CLAP audio embeddings (Music Map, audio similarity).
 */
export function AnalysisSettings() {
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery({
    queryKey: queryKeys.appSettings.all,
    queryFn: appSettingsApi.get,
  });

  const updateMutation = useMutation({
    mutationFn: appSettingsApi.update,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.appSettings.all });
    },
  });

  const clapStatus = settings?.clap_status;
  const isEnabled = clapStatus?.enabled ?? false;
  const ramSufficient = clapStatus?.ram_sufficient ?? false;
  const ramGb = clapStatus?.ram_gb;
  const envOverride = clapStatus?.env_override ?? false;
  const explicitSetting = clapStatus?.explicit_setting;

  const handleToggle = (enabled: boolean) => {
    updateMutation.mutate({ clap_embeddings_enabled: enabled });
  };

  const handleResetToAuto = () => {
    updateMutation.mutate({ clap_embeddings_enabled: null });
  };

  if (isLoading) {
    return (
      <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4">
        <div className="animate-pulse h-16 bg-zinc-700/50 rounded" />
      </div>
    );
  }

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4 space-y-4">
      {/* Main toggle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Cpu className="w-5 h-5 text-purple-400" />
          <div>
            <h4 className="font-medium text-white dark:text-white light:text-zinc-900">
              CLAP Audio Embeddings
            </h4>
            <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
              Enable AI-powered audio similarity (Music Map)
            </p>
          </div>
        </div>

        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => handleToggle(e.target.checked)}
            disabled={updateMutation.isPending || envOverride || !ramSufficient}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-purple-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-purple-500 peer-disabled:opacity-50" />
        </label>
      </div>

      {/* Status indicator */}
      <div className={`flex items-start gap-2 p-3 rounded ${
        isEnabled
          ? 'bg-green-900/20 border border-green-800/50'
          : 'bg-zinc-700/30 dark:bg-zinc-700/30 light:bg-zinc-200/50'
      }`}>
        {isEnabled ? (
          <CheckCircle className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" />
        ) : (
          <Info className="w-4 h-4 text-zinc-400 mt-0.5 flex-shrink-0" />
        )}
        <div className="text-sm">
          <p className={isEnabled ? 'text-green-300' : 'text-zinc-400 dark:text-zinc-400 light:text-zinc-600'}>
            {clapStatus?.reason || 'Status unknown'}
          </p>
          {ramGb !== null && ramGb !== undefined && (
            <p className="text-xs text-zinc-500 mt-1">
              System RAM: {ramGb.toFixed(1)}GB (6GB+ recommended)
            </p>
          )}
        </div>
      </div>

      {/* RAM warning */}
      {!ramSufficient && ramGb !== null && ramGb !== undefined && (
        <div className="flex items-start gap-2 p-3 bg-yellow-900/20 border border-yellow-800/50 rounded">
          <AlertTriangle className="w-4 h-4 text-yellow-400 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-yellow-200">
            <p>Insufficient RAM for CLAP embeddings</p>
            <p className="text-xs text-yellow-300/70 mt-1">
              Your system has {ramGb.toFixed(1)}GB RAM. CLAP requires at least 6GB.
              Enabling may cause performance issues or crashes.
            </p>
          </div>
        </div>
      )}

      {/* Environment override warning */}
      {envOverride && (
        <div className="flex items-start gap-2 p-3 bg-blue-900/20 border border-blue-800/50 rounded">
          <Info className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-blue-200">
            <p>Controlled by environment variable</p>
            <p className="text-xs text-blue-300/70 mt-1">
              DISABLE_CLAP_EMBEDDINGS is set. Remove this environment variable to control via settings.
            </p>
          </div>
        </div>
      )}

      {/* Reset to auto button */}
      {explicitSetting !== null && explicitSetting !== undefined && !envOverride && (
        <button
          onClick={handleResetToAuto}
          disabled={updateMutation.isPending}
          className="text-xs text-zinc-500 hover:text-zinc-300 underline disabled:opacity-50"
        >
          Reset to automatic (based on RAM)
        </button>
      )}

      {/* Info text */}
      <p className="text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-500">
        CLAP embeddings enable the Music Map visualization and audio-based similarity search.
        They require ~2GB additional RAM during analysis.
      </p>
    </div>
  );
}
