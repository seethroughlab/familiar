import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle, Loader2, Share2, XCircle } from 'lucide-react';
import { appSettingsApi, soulseekApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';

/**
 * Soulseek, through a slskd the operator runs (ADR-0116).
 *
 * Familiar does not speak Soulseek. It needs the address of a slskd instance and, if that
 * instance has one, its API key. Nothing here is required: leave the URL empty and the feature
 * does not exist on this server — the MCP tools are not listed, rather than listed and failing.
 *
 * Saving *probes* rather than trusting the paste, for the same reason the token panel does. The
 * three ways a paste goes wrong — nothing listening, wrong key, some other service on that port —
 * each get their own sentence from the server, so the operator is told what to fix.
 */
export function SoulseekSettings() {
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery({
    queryKey: queryKeys.appSettings.all,
    queryFn: appSettingsApi.get,
  });
  const { data: status, isFetching: probing } = useQuery({
    queryKey: queryKeys.soulseekStatus.all,
    queryFn: soulseekApi.status,
    enabled: !!settings?.soulseek_configured,
  });

  const [url, setUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settings && !dirty) {
      setUrl(settings.soulseek_url ?? '');
    }
  }, [settings, dirty]);

  const save = useMutation({
    mutationFn: async () => {
      const update: { soulseek_url: string; soulseek_api_key?: string } = {
        soulseek_url: url.trim(),
      };
      // The key field shows as empty even when one is stored (it comes back masked), so an empty
      // box means "leave it", and clearing the URL clears the key with it.
      if (apiKey.trim()) update.soulseek_api_key = apiKey.trim();
      if (!url.trim()) update.soulseek_api_key = '';
      return appSettingsApi.update(update);
    },
    onSuccess: () => {
      setDirty(false);
      setApiKey('');
      queryClient.invalidateQueries({ queryKey: queryKeys.appSettings.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.soulseekStatus.all });
    },
  });

  if (isLoading) {
    return (
      <div className="bg-zinc-800 rounded-lg p-4">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  const configured = !!settings?.soulseek_configured;
  const hasStoredKey = !!settings?.soulseek_api_key;

  return (
    <div className="bg-zinc-800 rounded-lg p-4">
      <div className="flex items-center gap-3 mb-3">
        <Share2 className={`w-6 h-6 ${configured ? 'text-success' : 'text-zinc-500'}`} />
        <div>
          <h3 className="font-medium">Soulseek</h3>
          <p className="text-sm text-zinc-400">
            Lets your assistant find and fetch music you don't have, through a{' '}
            <a
              href="https://github.com/slskd/slskd"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-zinc-200"
            >
              slskd
            </a>{' '}
            you run. Leave empty if you don't.
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <input
          type="url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setDirty(true);
          }}
          placeholder="http://slskd:5030 — as reachable from the Familiar server"
          autoComplete="off"
          spellCheck={false}
          className="w-full px-3 py-2 bg-zinc-700 border border-zinc-600 rounded-lg text-white placeholder-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-success"
        />
        <div className="flex gap-2">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              setDirty(true);
            }}
            placeholder={hasStoredKey ? 'API key saved — paste to replace' : 'API key (from slskd.yml web.authentication.api_keys)'}
            autoComplete="off"
            spellCheck={false}
            className="flex-1 px-3 py-2 bg-zinc-700 border border-zinc-600 rounded-lg text-white placeholder-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-success"
          />
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || !dirty}
            className="px-4 py-2 bg-success-strong hover:bg-success-strong disabled:bg-zinc-700 text-white text-sm rounded-lg transition-colors flex items-center gap-2"
          >
            {save.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Save
          </button>
        </div>
      </div>

      {save.isError && (
        <p className="mt-2 text-sm text-danger">
          {save.error instanceof Error ? save.error.message : 'Could not save'}
        </p>
      )}

      {configured && (
        <div className="mt-3 text-sm">
          {probing ? (
            <span className="flex items-center gap-2 text-zinc-400">
              <Loader2 className="w-4 h-4 animate-spin" /> Checking {settings?.soulseek_url}…
            </span>
          ) : status?.logged_in ? (
            <span className="flex items-center gap-2 text-success">
              <CheckCircle className="w-4 h-4" />
              Connected as {status.username}
              {status.version ? ` · slskd ${status.version}` : ''}
              {status.shared_files != null ? ` · sharing ${status.shared_files.toLocaleString()} files` : ''}
            </span>
          ) : (
            <span className="flex items-start gap-2 text-warning">
              <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{status?.error ?? 'Not reachable'}</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
