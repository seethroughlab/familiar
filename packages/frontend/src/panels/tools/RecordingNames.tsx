/**
 * Naming recordings through AcoustID (ADR-0115). Its own switch, off by default: this sends every
 * unnamed fingerprint to AcoustID once, unprompted, which is a different posture from the
 * per-track lookup a person asks for.
 *
 * This panel was the Community Cache panel until ADR-0159 removed the Clapback commons; the
 * AcoustID switch is the part that stayed.
 */
import { Fingerprint } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { appSettingsApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';

export function RecordingNames() {
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

  if (isLoading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="animate-pulse h-16 bg-zinc-700/50 rounded" />
      </div>
    );
  }

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Fingerprint className="w-5 h-5 text-accent" />
          <div>
            <p className="text-sm text-white">Name recordings through AcoustID</p>
            <p className="text-xs text-zinc-500">
              Send stored fingerprints to AcoustID to find each track's MusicBrainz recording id
            </p>
          </div>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={settings?.recording_backfill_enabled ?? false}
            onChange={(e) => updateMutation.mutate({ recording_backfill_enabled: e.target.checked })}
            disabled={updateMutation.isPending}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500 peer-disabled:opacity-50" />
        </label>
      </div>

      <p className="text-xs text-zinc-500">
        Sends the fingerprint itself to AcoustID, with nothing else attached.
      </p>
    </div>
  );
}
