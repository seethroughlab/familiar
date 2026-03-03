import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Server, Loader2, CheckCircle, Copy, Check, RefreshCw, Trash2, Eye, EyeOff } from 'lucide-react';
import { subsonicApi } from '../../api';

export function SubsonicSettings() {
  const queryClient = useQueryClient();
  const [showPassword, setShowPassword] = useState(false);
  const [generatedPassword, setGeneratedPassword] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const { data: status, isLoading } = useQuery({
    queryKey: ['subsonic-status'],
    queryFn: subsonicApi.getStatus,
  });

  const generateMutation = useMutation({
    mutationFn: subsonicApi.generateCredentials,
    onSuccess: (data) => {
      setGeneratedPassword(data.password ?? null);
      setShowPassword(true);
      queryClient.invalidateQueries({ queryKey: ['subsonic-status'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: subsonicApi.deleteCredentials,
    onSuccess: () => {
      setGeneratedPassword(null);
      setShowPassword(false);
      queryClient.invalidateQueries({ queryKey: ['subsonic-status'] });
    },
  });

  const copyToClipboard = async (text: string, label: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  };

  const serverUrl = `${window.location.protocol}//${window.location.host}`;

  if (isLoading) {
    return (
      <div className="p-4">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  return (
    <div className="bg-zinc-800 rounded-lg p-4">
      <div className="flex items-center gap-3 mb-3">
        <Server className="w-6 h-6 text-blue-400" />
        <div>
          <h3 className="font-medium">Subsonic API</h3>
          <p className="text-xs text-zinc-500">
            Connect native music apps (Symfonium, play:Sub, Amperfy) for CarPlay/Android Auto
          </p>
        </div>
      </div>

      {status?.configured ? (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-green-400">
            <CheckCircle className="w-5 h-5" />
            <span>Credentials configured</span>
          </div>

          <div className="space-y-3 bg-zinc-900 rounded-lg p-3">
            <div>
              <label className="text-xs text-zinc-500 block mb-1">Server URL</label>
              <div className="flex items-center gap-2">
                <code className="text-sm text-zinc-300 flex-1 truncate">{serverUrl}</code>
                <button
                  onClick={() => copyToClipboard(serverUrl, 'url')}
                  className="p-1.5 hover:bg-zinc-700 rounded transition-colors"
                  title="Copy"
                >
                  {copied === 'url' ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4 text-zinc-400" />}
                </button>
              </div>
            </div>

            <div>
              <label className="text-xs text-zinc-500 block mb-1">Username</label>
              <div className="flex items-center gap-2">
                <code className="text-sm text-zinc-300 flex-1">{status.username}</code>
                <button
                  onClick={() => copyToClipboard(status.username!, 'username')}
                  className="p-1.5 hover:bg-zinc-700 rounded transition-colors"
                  title="Copy"
                >
                  {copied === 'username' ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4 text-zinc-400" />}
                </button>
              </div>
            </div>

            {generatedPassword && (
              <div>
                <label className="text-xs text-zinc-500 block mb-1">
                  Password <span className="text-amber-400">(save this — shown once)</span>
                </label>
                <div className="flex items-center gap-2">
                  <code className="text-sm text-zinc-300 flex-1 font-mono">
                    {showPassword ? generatedPassword : '\u2022'.repeat(16)}
                  </code>
                  <button
                    onClick={() => setShowPassword(!showPassword)}
                    className="p-1.5 hover:bg-zinc-700 rounded transition-colors"
                    title={showPassword ? 'Hide' : 'Show'}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4 text-zinc-400" /> : <Eye className="w-4 h-4 text-zinc-400" />}
                  </button>
                  <button
                    onClick={() => copyToClipboard(generatedPassword, 'password')}
                    className="p-1.5 hover:bg-zinc-700 rounded transition-colors"
                    title="Copy"
                  >
                    {copied === 'password' ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4 text-zinc-400" />}
                  </button>
                </div>
              </div>
            )}
          </div>

          <p className="text-xs text-zinc-500">
            In your Subsonic client, add a server with the URL, username, and password above.
            Use "Subsonic" or "Open Subsonic" as the server type.
          </p>

          <div className="flex gap-3">
            <button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
              className="inline-flex items-center gap-2 px-3 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-lg text-sm transition-colors"
            >
              {generateMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              Regenerate
            </button>
            <button
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              className="inline-flex items-center gap-2 px-3 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg text-sm transition-colors"
            >
              {deleteMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
              Remove
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-zinc-400">
            Generate credentials to connect Subsonic-compatible apps like Symfonium, play:Sub,
            or Amperfy. These apps support CarPlay and Android Auto.
          </p>

          <button
            onClick={() => generateMutation.mutate()}
            disabled={generateMutation.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium transition-colors"
          >
            {generateMutation.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Generating...
              </>
            ) : (
              <>
                <Server className="w-4 h-4" />
                Generate Credentials
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
