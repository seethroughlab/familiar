import { useState, useEffect } from 'react';
import {
  Download,
  CheckCircle,
  XCircle,
  Loader2,
  Info,
} from 'lucide-react';
import { appSettingsApi, torrentSearchApi } from '../../api';
import type { TorrentConnectionStatus } from '../../api';

interface Props {
  initialEnabled?: boolean;
  initialProvider?: string;
  initialUrl?: string;
  initialPreferLossless?: boolean;
  initialConfigured?: boolean;
  initialDownloadClientUrl?: string;
  onSaved?: () => void;
}

export function TorrentSearchSettings({
  initialEnabled = false,
  initialProvider = 'jackett',
  initialUrl = '',
  initialPreferLossless = true,
  initialConfigured = false,
  initialDownloadClientUrl = '',
  onSaved,
}: Props) {
  const [enabled, setEnabled] = useState(initialEnabled);
  const [provider, setProvider] = useState(initialProvider);
  const [url, setUrl] = useState(initialUrl);
  const [apiKey, setApiKey] = useState('');
  const [preferLossless, setPreferLossless] = useState(initialPreferLossless);
  const [downloadClientUrl, setDownloadClientUrl] = useState(initialDownloadClientUrl);
  const [saving, setSaving] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<TorrentConnectionStatus | null>(null);
  const [testing, setTesting] = useState(false);

  // Update state when initial values change (e.g. after parent reloads settings)
  useEffect(() => {
    setEnabled(initialEnabled);
    setProvider(initialProvider);
    setUrl(initialUrl);
    setPreferLossless(initialPreferLossless);
    setDownloadClientUrl(initialDownloadClientUrl);
  }, [initialEnabled, initialProvider, initialUrl, initialPreferLossless, initialDownloadClientUrl]);

  // Auto-test on mount when already configured
  useEffect(() => {
    if (initialConfigured) {
      torrentSearchApi.getStatus().then(setConnectionStatus).catch(() => {});
    }
  }, [initialConfigured]);

  async function handleSave() {
    setSaving(true);
    try {
      const update: Record<string, unknown> = {
        torrent_search_enabled: enabled,
        torrent_search_provider: provider,
        torrent_search_url: url || undefined,
        torrent_search_prefer_lossless: preferLossless,
        download_client_url: downloadClientUrl || undefined,
      };
      // Only send API key if user typed a new one
      if (apiKey) {
        update.torrent_search_api_key = apiKey;
      }
      await appSettingsApi.update(update);
      setApiKey('');
      onSaved?.();

      // Test connection after save if enabled
      if (enabled && url) {
        setTesting(true);
        try {
          const status = await torrentSearchApi.testConnection();
          setConnectionStatus(status);
        } catch {
          setConnectionStatus({ ok: false, provider, error: 'Test failed' });
        } finally {
          setTesting(false);
        }
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleTestConnection() {
    setTesting(true);
    try {
      const status = await torrentSearchApi.testConnection();
      setConnectionStatus(status);
    } catch {
      setConnectionStatus({ ok: false, provider, error: 'Test request failed' });
    } finally {
      setTesting(false);
    }
  }

  const placeholder = provider === 'prowlarr'
    ? 'http://localhost:9696'
    : 'http://localhost:9117';

  return (
    <div className="bg-zinc-900 rounded-xl p-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 rounded-lg bg-violet-500/20">
          <Download className="w-5 h-5 text-violet-400" />
        </div>
        <div className="flex-1">
          <h2 className="font-medium text-white">Torrent Search</h2>
          <p className="text-sm text-zinc-500">Search via Jackett or Prowlarr</p>
        </div>
        {connectionStatus && (
          connectionStatus.ok ? (
            <CheckCircle className="w-5 h-5 text-green-400" />
          ) : (
            <XCircle className="w-5 h-5 text-red-400" />
          )
        )}
      </div>

      <div className="space-y-4">
        {/* Enable toggle */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-white">Enable torrent search</p>
            <p className="text-xs text-zinc-500">Show download buttons for missing tracks</p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-violet-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-violet-500" />
          </label>
        </div>

        {enabled && (
          <>
            {/* Provider selection */}
            <div>
              <label className="text-sm text-zinc-400 mb-2 block">Provider</label>
              <div className="flex gap-3">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="torrent-provider"
                    value="jackett"
                    checked={provider === 'jackett'}
                    onChange={() => setProvider('jackett')}
                    className="accent-violet-500"
                  />
                  <span className="text-sm text-white">Jackett</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="torrent-provider"
                    value="prowlarr"
                    checked={provider === 'prowlarr'}
                    onChange={() => setProvider('prowlarr')}
                    className="accent-violet-500"
                  />
                  <span className="text-sm text-white">Prowlarr</span>
                </label>
              </div>
            </div>

            {/* URL input */}
            <div>
              <label className="text-sm text-zinc-400 mb-1 block">
                {provider === 'prowlarr' ? 'Prowlarr' : 'Jackett'} URL
              </label>
              <input
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={placeholder}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
              />
            </div>

            {/* API Key */}
            <div>
              <label className="text-sm text-zinc-400 mb-1 block">API Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={initialConfigured ? '••••••••' : 'Enter API key'}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
              />
            </div>

            {/* Prefer lossless */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white">Prefer lossless (FLAC)</p>
                <p className="text-xs text-zinc-500">Prioritize lossless results over MP3</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={preferLossless}
                  onChange={(e) => setPreferLossless(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-violet-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-violet-500" />
              </label>
            </div>

            {/* Download client */}
            <div>
              <label className="text-sm text-zinc-400 mb-1 block">Transmission URL</label>
              <input
                type="text"
                value={downloadClientUrl}
                onChange={(e) => setDownloadClientUrl(e.target.value)}
                placeholder="http://localhost:9091"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
              />
              <p className="text-xs text-zinc-500 mt-1">Send downloads directly to Transmission</p>
            </div>

            {/* Info note */}
            <div className="flex items-start gap-2 p-3 bg-violet-900/20 border border-violet-800/50 rounded-lg">
              <Info className="w-4 h-4 text-violet-400 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-violet-300">
                Purchasing music directly supports artists. Torrent search is provided as a
                convenience for finding music that may be unavailable through normal purchase channels.
              </p>
            </div>

            {/* Connection status error */}
            {connectionStatus && !connectionStatus.ok && connectionStatus.error !== 'Not configured' && (
              <div className="text-sm text-red-400 bg-red-900/20 border border-red-800/50 rounded-lg px-3 py-2">
                {connectionStatus.error}
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors flex items-center gap-2"
              >
                {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                Save
              </button>
              {initialConfigured && (
                <button
                  onClick={handleTestConnection}
                  disabled={testing}
                  className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 text-white text-sm rounded-lg transition-colors flex items-center gap-2"
                >
                  {testing && <Loader2 className="w-4 h-4 animate-spin" />}
                  Test Connection
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
