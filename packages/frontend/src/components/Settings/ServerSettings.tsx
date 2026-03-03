import { useState, useEffect } from 'react';
import { Server, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { getApiOrigin, setApiOrigin } from '../../api/base';

type TestStatus = 'idle' | 'testing' | 'success' | 'error';

interface ServerSettingsProps {
  onConnected?: () => void;
}

export function ServerSettings({ onConnected }: ServerSettingsProps = {}) {
  const [url, setUrl] = useState(() => getApiOrigin() || '');
  const [status, setStatus] = useState<TestStatus>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  // Sync from stored value on mount
  useEffect(() => {
    setUrl(getApiOrigin() || '');
  }, []);

  const testConnection = async () => {
    const trimmed = url.replace(/\/+$/, '');
    if (!trimmed) {
      setStatus('error');
      setErrorMsg('Enter a URL first');
      return;
    }

    setStatus('testing');
    setErrorMsg('');

    try {
      const res = await fetch(`${trimmed}/api/v1/health`, {
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        setStatus('success');
        // Persist on successful test
        await setApiOrigin(trimmed);
        onConnected?.();
      } else {
        setStatus('error');
        setErrorMsg(`Server returned ${res.status}`);
      }
    } catch (e) {
      setStatus('error');
      setErrorMsg(e instanceof Error ? e.message : 'Connection failed');
    }
  };

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4">
      <div className="flex items-center gap-3 mb-4">
        <Server className="w-5 h-5 text-blue-400" />
        <div>
          <h4 className="font-medium text-white">Backend Server</h4>
          <p className="text-sm text-zinc-400">
            URL of your Familiar server (e.g. http://192.168.1.100:4400)
          </p>
        </div>
      </div>

      <div className="flex gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setStatus('idle');
          }}
          placeholder="http://your-server:4400"
          className="flex-1 px-3 py-2 bg-zinc-700 border border-zinc-600 rounded-lg text-white placeholder-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={testConnection}
          disabled={status === 'testing'}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 text-white text-sm rounded-lg transition-colors flex items-center gap-2"
        >
          {status === 'testing' ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : status === 'success' ? (
            <CheckCircle className="w-4 h-4 text-green-400" />
          ) : status === 'error' ? (
            <XCircle className="w-4 h-4 text-red-400" />
          ) : null}
          Test
        </button>
      </div>

      {status === 'success' && (
        <p className="mt-2 text-sm text-green-400">Connected and saved.</p>
      )}
      {status === 'error' && errorMsg && (
        <p className="mt-2 text-sm text-red-400">{errorMsg}</p>
      )}
    </div>
  );
}
