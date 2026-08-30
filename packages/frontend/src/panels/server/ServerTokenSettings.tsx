import { useState, useEffect } from 'react';
import { KeyRound, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { getApiUrl, getServerToken, setServerToken } from '../../api/base';

type TestStatus = 'idle' | 'testing' | 'success' | 'error';

/**
 * The server token (ADR-0045).
 *
 * Lives beside Backend Server rather than under a security heading, because it answers the same
 * question — how this client reaches that server — and because the two fail together: a wrong
 * token and a wrong URL both look like "nothing loads".
 *
 * Saving *verifies* rather than trusting the paste. A token is a 43-character opaque string, so a
 * truncated copy is invisible by eye, and storing one that does not work would turn every later
 * screen into an unexplained 401. `/api/v1/settings` is the probe because it is behind the gate and
 * needs no profile — `/api/v1/health` is deliberately public and would pass with any token at all.
 */
export function ServerTokenSettings() {
  const [token, setToken] = useState(() => getServerToken());
  const [status, setStatus] = useState<TestStatus>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    setToken(getServerToken());
  }, []);

  const saveAndVerify = async () => {
    const trimmed = token.trim();
    setStatus('testing');
    setErrorMsg('');

    // Persist first: the probe goes through the axios interceptor, which reads the stored value.
    await setServerToken(trimmed);

    try {
      // eslint-disable-next-line no-restricted-globals -- probing the gate directly, pre-interceptor
      const res = await fetch(getApiUrl('/settings'), {
        headers: trimmed ? { 'X-Familiar-Token': trimmed } : {},
        signal: AbortSignal.timeout(20000),
      });
      if (res.ok) {
        setStatus('success');
      } else if (res.status === 401) {
        setStatus('error');
        setErrorMsg(
          trimmed
            ? 'The server rejected that token. Check it in the admin UI on the server.'
            : 'This server requires a token. Get one from its admin UI.',
        );
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
        <KeyRound className="w-5 h-5 text-warning" />
        <div>
          <h4 className="font-medium text-white">Server Token</h4>
          <p className="text-sm text-zinc-400">
            Only needed if your server has authentication turned on. Leave empty otherwise.
          </p>
        </div>
      </div>

      <div className="flex gap-2">
        <input
          type="password"
          value={token}
          onChange={(e) => {
            setToken(e.target.value);
            setStatus('idle');
          }}
          placeholder="Paste the token from your server's admin page"
          autoComplete="off"
          spellCheck={false}
          className="flex-1 px-3 py-2 bg-zinc-700 border border-zinc-600 rounded-lg text-white placeholder-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
        />
        <button
          onClick={saveAndVerify}
          disabled={status === 'testing'}
          className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:bg-zinc-700 text-white text-sm rounded-lg transition-colors flex items-center gap-2"
        >
          {status === 'testing' ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : status === 'success' ? (
            <CheckCircle className="w-4 h-4 text-success" />
          ) : status === 'error' ? (
            <XCircle className="w-4 h-4 text-danger" />
          ) : null}
          Save
        </button>
      </div>

      {status === 'success' && (
        <p className="mt-2 text-sm text-success">
          {token.trim() ? 'Token accepted and saved.' : 'Saved. This server needs no token.'}
        </p>
      )}
      {status === 'error' && errorMsg && (
        <p className="mt-2 text-sm text-danger">{errorMsg}</p>
      )}
    </div>
  );
}
