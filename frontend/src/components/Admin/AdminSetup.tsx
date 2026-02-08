/**
 * Admin setup page for configuring global API keys.
 *
 * Accessible at /admin for initial setup or reconfiguration.
 * API keys configured here are app-wide, not per-profile.
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Settings,
  Cloud,
  Music2,
  Radio,
  Fingerprint,
  CheckCircle,
  XCircle,
  ArrowLeft,
  Loader2,
  Server,
  Upload,
  Database,
} from 'lucide-react';

import { S3BackupSettings } from '../Settings/S3BackupSettings';
import { getApiUrl } from '../../api/base';

import { createLogger } from '../../utils/logger';

const log = createLogger('AdminSetup');

interface SettingsData {
  spotify_configured: boolean;
  lastfm_configured: boolean;
  anthropic_configured: boolean;
  acoustid_configured: boolean;
  community_cache_enabled: boolean;
  community_cache_contribute: boolean;
  community_cache_url: string;
}

export function AdminSetup() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState<SettingsData | null>(null);

  // Per-section saving states
  const [savingCommunityCache, setSavingCommunityCache] = useState(false);

  useEffect(() => {
    loadSettings();
  }, []);

  async function loadSettings() {
    try {
      setLoading(true);
      const response = await fetch(getApiUrl('/settings'));
      if (response.ok) {
        const data = await response.json();
        setSettings(data);
      }
    } catch (err) {
      log.error('Failed to load settings:', err);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <Loader2 className="w-12 h-12 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 py-12 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <button
            onClick={() => navigate('/')}
            className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-3">
            <Settings className="w-8 h-8 text-blue-500" />
            <div>
              <h1 className="text-2xl font-bold text-white">Admin Setup</h1>
              <p className="text-zinc-400 text-sm">Configure global API keys</p>
            </div>
          </div>
        </div>

        <div className="space-y-6">
          {/* Environment Variables Info */}
          <section className="bg-blue-900/20 border border-blue-800 rounded-xl p-4">
            <div className="flex items-start gap-3">
              <Server className="w-5 h-5 text-blue-400 mt-0.5" />
              <div>
                <p className="text-sm text-blue-300">API keys are configured via environment variables</p>
                <p className="text-xs text-blue-400/70 mt-1">
                  Edit <code className="bg-blue-900/50 px-1 rounded">docker/.env</code> and restart the container to update credentials.
                </p>
              </div>
            </div>
          </section>

          {/* API Status Overview */}
          <section className="bg-zinc-900 rounded-xl p-6">
            <h2 className="text-lg font-medium text-white mb-4">Service Status</h2>
            <div className="grid grid-cols-2 gap-4">
              {/* Anthropic */}
              <div className="flex items-center gap-3 p-3 bg-zinc-800 rounded-lg">
                <Cloud className={`w-5 h-5 ${settings?.anthropic_configured ? 'text-purple-400' : 'text-zinc-500'}`} />
                <div className="flex-1">
                  <p className="text-sm text-white">Claude API</p>
                  <p className="text-xs text-zinc-500">AI assistant</p>
                </div>
                {settings?.anthropic_configured ? (
                  <CheckCircle className="w-5 h-5 text-green-400" />
                ) : (
                  <XCircle className="w-5 h-5 text-zinc-500" />
                )}
              </div>

              {/* Spotify */}
              <div className="flex items-center gap-3 p-3 bg-zinc-800 rounded-lg">
                <Music2 className={`w-5 h-5 ${settings?.spotify_configured ? 'text-green-400' : 'text-zinc-500'}`} />
                <div className="flex-1">
                  <p className="text-sm text-white">Spotify</p>
                  <p className="text-xs text-zinc-500">Sync favorites</p>
                </div>
                {settings?.spotify_configured ? (
                  <CheckCircle className="w-5 h-5 text-green-400" />
                ) : (
                  <XCircle className="w-5 h-5 text-zinc-500" />
                )}
              </div>

              {/* Last.fm */}
              <div className="flex items-center gap-3 p-3 bg-zinc-800 rounded-lg">
                <Radio className={`w-5 h-5 ${settings?.lastfm_configured ? 'text-red-400' : 'text-zinc-500'}`} />
                <div className="flex-1">
                  <p className="text-sm text-white">Last.fm</p>
                  <p className="text-xs text-zinc-500">Scrobbling</p>
                </div>
                {settings?.lastfm_configured ? (
                  <CheckCircle className="w-5 h-5 text-green-400" />
                ) : (
                  <XCircle className="w-5 h-5 text-zinc-500" />
                )}
              </div>

              {/* AcoustID */}
              <div className="flex items-center gap-3 p-3 bg-zinc-800 rounded-lg">
                <Fingerprint className={`w-5 h-5 ${settings?.acoustid_configured ? 'text-blue-400' : 'text-zinc-500'}`} />
                <div className="flex-1">
                  <p className="text-sm text-white">AcoustID</p>
                  <p className="text-xs text-zinc-500">Fingerprinting</p>
                </div>
                {settings?.acoustid_configured ? (
                  <CheckCircle className="w-5 h-5 text-green-400" />
                ) : (
                  <XCircle className="w-5 h-5 text-zinc-500" />
                )}
              </div>
            </div>
          </section>

          {/* Community Cache */}
          <section className="bg-zinc-900 rounded-xl p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 rounded-lg bg-cyan-500/20">
                <Database className="w-5 h-5 text-cyan-400" />
              </div>
              <div className="flex-1">
                <h2 className="font-medium text-white">Community Cache</h2>
                <p className="text-sm text-zinc-500">Share analysis data with other Familiar users</p>
              </div>
            </div>

            <div className="space-y-4">
              {/* Lookup toggle */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Cloud className="w-5 h-5 text-blue-400" />
                  <div>
                    <p className="text-sm text-white">Use community cache</p>
                    <p className="text-xs text-zinc-500">Look up pre-computed features and embeddings</p>
                  </div>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings?.community_cache_enabled ?? true}
                    onChange={async (e) => {
                      setSavingCommunityCache(true);
                      try {
                        const response = await fetch(getApiUrl('/settings'), {
                          method: 'PUT',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ community_cache_enabled: e.target.checked }),
                        });
                        if (response.ok) {
                          const data = await response.json();
                          setSettings(data);
                        }
                      } finally {
                        setSavingCommunityCache(false);
                      }
                    }}
                    disabled={savingCommunityCache}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500 peer-disabled:opacity-50" />
                </label>
              </div>

              {/* Contribute toggle */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Upload className="w-5 h-5 text-green-400" />
                  <div>
                    <p className="text-sm text-white">Contribute to cache</p>
                    <p className="text-xs text-zinc-500">Share your computed features and embeddings (anonymous)</p>
                  </div>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings?.community_cache_contribute ?? false}
                    onChange={async (e) => {
                      setSavingCommunityCache(true);
                      try {
                        const response = await fetch(getApiUrl('/settings'), {
                          method: 'PUT',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ community_cache_contribute: e.target.checked }),
                        });
                        if (response.ok) {
                          const data = await response.json();
                          setSettings(data);
                        }
                      } finally {
                        setSavingCommunityCache(false);
                      }
                    }}
                    disabled={savingCommunityCache}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-green-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-green-500 peer-disabled:opacity-50" />
                </label>
              </div>

              {/* Privacy note */}
              <p className="text-xs text-zinc-500">
                Only audio fingerprint hashes are shared — no filenames, metadata, or personal info.
                Helps speed up analysis for everyone in the community.
              </p>
            </div>
          </section>

          {/* Cloud Backup */}
          <section>
            <S3BackupSettings />
          </section>

          {/* Info */}
          <p className="text-sm text-zinc-500 text-center">
            These settings are global and apply to all profiles.
            Individual users connect their own Spotify and Last.fm accounts via Settings.
          </p>
        </div>
      </div>
    </div>
  );
}
