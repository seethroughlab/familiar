import { useState, useEffect } from 'react';
import { Server, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { clearApiOrigin, getApiOrigin, getDefaultApiOrigin, setApiOrigin } from '../../api/base';

type TestStatus = 'idle' | 'testing' | 'success' | 'error';

interface ServerSettingsProps {
  onConnected?: () => void;
}

export function ServerSettings({ onConnected }: ServerSettingsProps = {}) {
  const [url, setUrl] = useState(() => getApiOrigin() || getDefaultApiOrigin() || '');
  const [status, setStatus] = useState<TestStatus>('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const [confirmingChange, setConfirmingChange] = useState(false);

  // Sync from stored value on mount; fall back to the baked default so the
  // user sees a pre-filled URL on first launch of a release build but still
  // has to tap "Test" to confirm + persist.
  useEffect(() => {
    setUrl(getApiOrigin() || getDefaultApiOrigin() || '');
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
      // eslint-disable-next-line no-restricted-globals -- Connection test with custom URL and timeout
      // 20s timeout — covers cold-booting hosts (e.g. Fly machines scaled to
      // zero) without making a truly-dead server feel infinite.
      const res = await fetch(`${trimmed}/api/v1/health`, {
        signal: AbortSignal.timeout(20000),
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

  const changeServer = async () => {
    await clearApiOrigin();
    setConfirmingChange(false);
    window.dispatchEvent(new CustomEvent('server-reset'));
  };

  // Only expose the Change Server affordance after a URL has been saved —
  // there's nothing to change until then.
  const hasStoredUrl = !!getApiOrigin();

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

      {hasStoredUrl && !confirmingChange && (
        <button
          onClick={() => setConfirmingChange(true)}
          className="mt-4 text-sm text-zinc-400 hover:text-white underline underline-offset-2 transition-colors"
        >
          Change server
        </button>
      )}

      {confirmingChange && (
        <div className="mt-4 p-3 bg-zinc-900/60 border border-zinc-700 rounded-lg">
          <p className="text-sm text-white font-medium mb-1">Change server?</p>
          <p className="text-sm text-zinc-400 mb-3">
            Your downloaded tracks and cached library will stay on this device
            but won't be visible on a different Familiar server. Your account
            on this server isn't affected.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setConfirmingChange(false)}
              className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-white text-sm rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={changeServer}
              className="px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white text-sm rounded-lg transition-colors"
            >
              Change server
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
