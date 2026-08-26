import { Radio, Fingerprint, CheckCircle, XCircle, Server } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { appSettingsApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';

export function ApiKeyStatus() {
  const { data: settings, isLoading } = useQuery({
    queryKey: queryKeys.appSettings.all,
    queryFn: appSettingsApi.get,
  });

  if (isLoading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="animate-pulse h-16 bg-zinc-700/50 rounded" />
      </div>
    );
  }

  const services = [
    { name: 'Last.fm', desc: 'Scrobbling', configured: settings?.lastfm_configured, icon: Radio, color: 'text-red-400' },
    { name: 'AcoustID', desc: 'Fingerprinting', configured: settings?.acoustid_configured, icon: Fingerprint, color: 'text-blue-400' },
  ];

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 space-y-3">
      <div className="flex items-center gap-3">
        <Server className="w-5 h-5 text-blue-400" />
        <div>
          <h4 className="font-medium text-white">API Keys</h4>
          <p className="text-sm text-zinc-400">
            Configured via environment variables
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {services.map((svc) => (
          <div key={svc.name} className="flex items-center gap-3 p-3 bg-zinc-900/50 rounded-lg">
            <svc.icon className={`w-5 h-5 ${svc.configured ? svc.color : 'text-zinc-500'}`} />
            <div className="flex-1 min-w-0">
              <p className="text-sm text-white">{svc.name}</p>
              <p className="text-xs text-zinc-500">{svc.desc}</p>
            </div>
            {svc.configured ? (
              <CheckCircle className="w-5 h-5 text-green-400 flex-shrink-0" />
            ) : (
              <XCircle className="w-5 h-5 text-zinc-500 flex-shrink-0" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
