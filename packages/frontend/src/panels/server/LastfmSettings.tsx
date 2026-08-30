import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Radio, Loader2, User, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
import { lastfmApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';

export function LastfmSettings() {
  const queryClient = useQueryClient();

  const { data: status, isLoading } = useQuery({
    queryKey: queryKeys.lastfmStatus.all,
    queryFn: lastfmApi.getStatus,
  });

  const connectMutation = useMutation({
    mutationFn: lastfmApi.getAuthUrl,
    onSuccess: (data) => {
      window.location.href = data.auth_url;
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: lastfmApi.disconnect,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.lastfmStatus.all });
    },
  });

  if (isLoading) {
    return (
      <div className="p-4">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (!status?.configured) {
    return (
      <div className="bg-zinc-800 rounded-lg p-4">
        <div className="flex items-center gap-3 mb-3">
          <Radio className="w-6 h-6 text-red-500" />
          <h3 className="font-medium">Last.fm</h3>
        </div>
        <div className="flex items-start gap-2 p-3 bg-amber-900/20 border border-amber-800 rounded-lg">
          <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm text-amber-400">Last.fm API not configured</p>
            <p className="text-xs text-zinc-500 mt-1">
              Set LASTFM_API_KEY and LASTFM_API_SECRET in docker/.env to enable scrobbling.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-zinc-800 rounded-lg p-4">
      <div className="flex items-center gap-3 mb-3">
        <Radio className="w-6 h-6 text-red-500" />
        <h3 className="font-medium">Last.fm Scrobbling</h3>
      </div>

      {status.connected ? (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-green-400">
            <CheckCircle className="w-5 h-5" />
            <span>Connected as {status.username}</span>
          </div>

          <p className="text-sm text-zinc-400">
            Your listening activity is being scrobbled to Last.fm automatically.
          </p>

          <div className="flex gap-3">
            <a
              href={`https://www.last.fm/user/${status.username}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-3 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-lg text-sm transition-colors"
            >
              <User className="w-4 h-4" />
              View Profile
            </a>
            <button
              onClick={() => disconnectMutation.mutate()}
              disabled={disconnectMutation.isPending}
              className="px-3 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg text-sm transition-colors"
            >
              {disconnectMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                'Disconnect'
              )}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-zinc-400">
            <XCircle className="w-5 h-5" />
            <span>Not connected</span>
          </div>

          <p className="text-sm text-zinc-400">
            Connect your Last.fm account to scrobble your listening history.
          </p>

          <button
            onClick={() => connectMutation.mutate()}
            disabled={connectMutation.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-500 rounded-lg text-sm font-medium transition-colors"
          >
            {connectMutation.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Connecting...
              </>
            ) : (
              <>
                <Radio className="w-4 h-4" />
                Connect Last.fm
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
