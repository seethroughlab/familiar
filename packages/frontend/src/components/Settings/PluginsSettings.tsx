import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { pluginsApi, type Plugin, type PluginType } from '../../api';
import { pluginLoader } from '../../services/pluginLoader';
import {
  Puzzle,
  Loader2,
  ExternalLink,
  Trash2,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  Download,
  Activity,
  Layers,
} from 'lucide-react';

export function PluginsSettings() {
  const queryClient = useQueryClient();
  const [installUrl, setInstallUrl] = useState('');
  const [installError, setInstallError] = useState<string | null>(null);
  const [checkingUpdates, setCheckingUpdates] = useState<Set<string>>(new Set());

  // Fetch installed plugins
  const { data: pluginsData, isLoading } = useQuery({
    queryKey: ['plugins'],
    queryFn: () => pluginsApi.list(),
    refetchOnWindowFocus: false,
  });

  const plugins = pluginsData?.plugins ?? [];

  // Install plugin mutation
  const installMutation = useMutation({
    mutationFn: (url: string) => pluginsApi.install(url),
    onSuccess: async (data) => {
      if (data.success) {
        setInstallUrl('');
        setInstallError(null);
        queryClient.invalidateQueries({ queryKey: ['plugins'] });
        // Reload all plugins to pick up the new one
        await pluginLoader.loadAllPlugins();
      } else {
        setInstallError(data.error || 'Installation failed');
      }
    },
    onError: (error: Error) => {
      setInstallError(error.message);
    },
  });

  // Toggle enabled mutation
  const toggleEnabledMutation = useMutation({
    mutationFn: ({ pluginId, enabled }: { pluginId: string; enabled: boolean }) =>
      pluginsApi.update(pluginId, { enabled }),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['plugins'] });
      // Reload plugins when enabling/disabling
      // Note: Full page refresh may be needed for disabling to take effect
      await pluginLoader.loadAllPlugins();
    },
  });

  // Uninstall mutation
  const uninstallMutation = useMutation({
    mutationFn: (pluginId: string) => pluginsApi.uninstall(pluginId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plugins'] });
      // Note: Full page refresh may be needed to fully unload a plugin
    },
  });

  // Update version mutation
  const updateVersionMutation = useMutation({
    mutationFn: (pluginId: string) => pluginsApi.updateVersion(pluginId),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['plugins'] });
      await pluginLoader.loadAllPlugins();
    },
  });

  // Check for update
  const handleCheckUpdate = async (pluginId: string) => {
    setCheckingUpdates((prev) => new Set(prev).add(pluginId));
    try {
      const result = await pluginsApi.checkUpdate(pluginId);
      if (result.has_update) {
        // Trigger update
        await updateVersionMutation.mutateAsync(pluginId);
      }
    } finally {
      setCheckingUpdates((prev) => {
        const next = new Set(prev);
        next.delete(pluginId);
        return next;
      });
    }
  };

  const handleInstall = (e: React.FormEvent) => {
    e.preventDefault();
    if (!installUrl.trim()) return;
    setInstallError(null);
    installMutation.mutate(installUrl.trim());
  };

  const getTypeIcon = (type: PluginType) => {
    switch (type) {
      case 'visualizer':
        return <Activity className="w-4 h-4" />;
      case 'browser':
        return <Layers className="w-4 h-4" />;
      default:
        return <Puzzle className="w-4 h-4" />;
    }
  };

  const getTypeLabel = (type: PluginType) => {
    switch (type) {
      case 'visualizer':
        return 'Visualizer';
      case 'browser':
        return 'Library Browser';
      default:
        return type;
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Install new plugin */}
      <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-white rounded-lg p-4">
        <div className="flex items-center gap-3 mb-4">
          <Download className="w-5 h-5 text-blue-400" />
          <div>
            <h4 className="font-medium text-white dark:text-white light:text-zinc-900">
              Install Plugin
            </h4>
            <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
              Add visualizers or library browsers from GitHub
            </p>
          </div>
        </div>

        <form onSubmit={handleInstall} className="flex gap-2">
          <input
            type="text"
            value={installUrl}
            onChange={(e) => setInstallUrl(e.target.value)}
            placeholder="https://github.com/user/plugin-repo"
            className="flex-1 px-3 py-2 bg-zinc-900 dark:bg-zinc-900 light:bg-zinc-100 border border-zinc-700 dark:border-zinc-700 light:border-zinc-300 rounded-md text-base text-white dark:text-white light:text-zinc-900 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <button
            type="submit"
            disabled={installMutation.isPending || !installUrl.trim()}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-md disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {installMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            Install
          </button>
        </form>

        {installError && (
          <div className="mt-3 flex items-start gap-2 p-3 bg-red-900/20 border border-red-800 rounded-lg">
            <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-red-400">{installError}</p>
          </div>
        )}
      </div>

      {/* Installed plugins list */}
      <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-white rounded-lg p-4">
        <div className="flex items-center gap-3 mb-4">
          <Puzzle className="w-5 h-5 text-purple-400" />
          <div>
            <h4 className="font-medium text-white dark:text-white light:text-zinc-900">
              Installed Plugins
            </h4>
            <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
              {plugins.length === 0
                ? 'No plugins installed yet'
                : `${plugins.length} plugin${plugins.length !== 1 ? 's' : ''} installed`}
            </p>
          </div>
        </div>

        {plugins.length === 0 ? (
          <div className="text-center py-8 text-zinc-500">
            <Puzzle className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No plugins installed</p>
            <p className="text-sm mt-1">
              Install a visualizer or library browser from GitHub above
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {plugins.map((plugin) => (
              <PluginCard
                key={plugin.id}
                plugin={plugin}
                onToggleEnabled={(enabled) =>
                  toggleEnabledMutation.mutate({
                    pluginId: plugin.plugin_id,
                    enabled,
                  })
                }
                onCheckUpdate={() => handleCheckUpdate(plugin.plugin_id)}
                onUninstall={() => {
                  if (confirm(`Uninstall ${plugin.name}?`)) {
                    uninstallMutation.mutate(plugin.plugin_id);
                  }
                }}
                isUpdating={
                  checkingUpdates.has(plugin.plugin_id) ||
                  updateVersionMutation.isPending
                }
                isToggling={toggleEnabledMutation.isPending}
                isUninstalling={uninstallMutation.isPending}
                getTypeIcon={getTypeIcon}
                getTypeLabel={getTypeLabel}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface PluginCardProps {
  plugin: Plugin;
  onToggleEnabled: (enabled: boolean) => void;
  onCheckUpdate: () => void;
  onUninstall: () => void;
  isUpdating: boolean;
  isToggling: boolean;
  isUninstalling: boolean;
  getTypeIcon: (type: PluginType) => React.ReactNode;
  getTypeLabel: (type: PluginType) => string;
}

function PluginCard({
  plugin,
  onToggleEnabled,
  onCheckUpdate,
  onUninstall,
  isUpdating,
  isToggling,
  isUninstalling,
  getTypeIcon,
  getTypeLabel,
}: PluginCardProps) {
  return (
    <div
      className={`border rounded-lg p-4 transition-colors ${
        plugin.enabled
          ? 'border-zinc-700 dark:border-zinc-700 light:border-zinc-300 bg-zinc-900/30 dark:bg-zinc-900/30 light:bg-zinc-50'
          : 'border-zinc-800 dark:border-zinc-800 light:border-zinc-200 bg-zinc-900/10 dark:bg-zinc-900/10 light:bg-zinc-100 opacity-60'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h5 className="font-medium text-white dark:text-white light:text-zinc-900 truncate">
              {plugin.name}
            </h5>
            <span className="text-xs text-zinc-500">v{plugin.version}</span>
            {plugin.enabled ? (
              <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
            ) : null}
          </div>

          <div className="flex items-center gap-2 mt-1">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-zinc-700 dark:bg-zinc-700 light:bg-zinc-200 text-zinc-300 dark:text-zinc-300 light:text-zinc-600">
              {getTypeIcon(plugin.type)}
              {getTypeLabel(plugin.type)}
            </span>
            {plugin.author?.name && (
              <span className="text-xs text-zinc-500">
                by{' '}
                {plugin.author.url ? (
                  <a
                    href={plugin.author.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:underline"
                  >
                    {plugin.author.name}
                  </a>
                ) : (
                  plugin.author.name
                )}
              </span>
            )}
          </div>

          {plugin.description && (
            <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600 mt-2 line-clamp-2">
              {plugin.description}
            </p>
          )}

          {plugin.load_error && (
            <div className="flex items-start gap-2 mt-2 p-2 bg-red-900/20 border border-red-800 rounded">
              <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-red-400">{plugin.load_error}</p>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Toggle enabled */}
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={plugin.enabled}
              onChange={(e) => onToggleEnabled(e.target.checked)}
              disabled={isToggling}
              className="sr-only peer"
            />
            <div className="w-9 h-5 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-500 peer-disabled:opacity-50"></div>
          </label>

          {/* Check for updates */}
          <button
            onClick={onCheckUpdate}
            disabled={isUpdating}
            className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Check for updates"
          >
            {isUpdating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
          </button>

          {/* Open repository */}
          <a
            href={plugin.repository_url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-md transition-colors"
            title="View source"
          >
            <ExternalLink className="w-4 h-4" />
          </a>

          {/* Uninstall */}
          <button
            onClick={onUninstall}
            disabled={isUninstalling}
            className="p-2 text-zinc-400 hover:text-red-400 hover:bg-zinc-700 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Uninstall"
          >
            {isUninstalling ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Trash2 className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
