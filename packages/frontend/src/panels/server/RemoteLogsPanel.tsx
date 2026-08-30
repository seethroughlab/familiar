import { useState, useEffect, useCallback, useRef } from 'react';
import { Radio, RefreshCw, Trash2, Send, ToggleLeft, ToggleRight } from 'lucide-react';
import { frontendLogsApi, type FrontendLogEntry } from '../../api';
import { flushNow, getPendingCount, clearLocalLogs } from '../../services/remoteLogService';

export function RemoteLogsPanel() {
  const [expanded, setExpanded] = useState(false);
  const [enabled, setEnabled] = useState(() => {
    try { return localStorage.getItem('remoteLogging') !== 'false'; }
    catch { return true; }
  });
  const [pendingCount, setPendingCount] = useState(0);
  const [entries, setEntries] = useState<FrontendLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [flushing, setFlushing] = useState(false);
  const [levelFilter, setLevelFilter] = useState('');
  const [namespaceFilter, setNamespaceFilter] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const toggleEnabled = () => {
    const next = !enabled;
    setEnabled(next);
    try { localStorage.setItem('remoteLogging', next ? 'true' : 'false'); }
    catch { /* ignore */ }
  };

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await frontendLogsApi.list({
        level: levelFilter || undefined,
        namespace: namespaceFilter || undefined,
        limit: 100,
      });
      setEntries(data.entries);
      setTotal(data.total);
    } catch { /* silent */ }
    setLoading(false);
  }, [levelFilter, namespaceFilter]);

  const handleFlush = async () => {
    setFlushing(true);
    try {
      await flushNow();
      // Small delay to let backend process
      await new Promise((r) => setTimeout(r, 500));
      await fetchLogs();
      setPendingCount(await getPendingCount());
    } catch { /* silent */ }
    setFlushing(false);
  };

  const handleClear = async () => {
    try {
      await frontendLogsApi.clear();
      await clearLocalLogs();
      setEntries([]);
      setTotal(0);
      setPendingCount(0);
    } catch { /* silent */ }
  };

  // Refresh pending count and logs when expanded
  useEffect(() => {
    if (!expanded) return;
    fetchLogs();
    getPendingCount().then(setPendingCount).catch(() => {});
  }, [expanded, fetchLogs]);

  // Auto-refresh
  useEffect(() => {
    if (autoRefreshRef.current) {
      clearInterval(autoRefreshRef.current);
      autoRefreshRef.current = null;
    }
    if (autoRefresh && expanded) {
      autoRefreshRef.current = setInterval(() => {
        fetchLogs();
        getPendingCount().then(setPendingCount).catch(() => {});
      }, 5000);
    }
    return () => {
      if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
    };
  }, [autoRefresh, expanded, fetchLogs]);

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'error': return 'text-danger';
      case 'warn': return 'text-warning';
      case 'info': return 'text-blue-400';
      case 'debug': return 'text-zinc-500';
      default: return 'text-zinc-300';
    }
  };

  const getLevelBg = (level: string) => {
    switch (level) {
      case 'error': return 'bg-red-500/10';
      case 'warn': return 'bg-yellow-500/10';
      default: return '';
    }
  };

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3"
      >
        <Radio className="w-5 h-5 text-blue-400" />
        <div className="flex-1 text-left">
          <h4 className="font-medium text-white">
            Remote Logs
          </h4>
          <p className="text-sm text-zinc-400">
            Frontend logs shipped to backend for remote diagnosis
          </p>
        </div>
        <span className="text-zinc-400">{expanded ? '▼' : '▶'}</span>
      </button>

      {expanded && (
        <div className="mt-4 space-y-4">
          {/* Controls */}
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={toggleEnabled}
              className="flex items-center gap-2 px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs rounded"
            >
              {enabled ? <ToggleRight className="w-4 h-4 text-success" /> : <ToggleLeft className="w-4 h-4 text-zinc-500" />}
              {enabled ? 'Enabled' : 'Disabled'}
            </button>
            <button
              onClick={handleFlush}
              disabled={flushing}
              className="flex items-center gap-2 px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs rounded disabled:opacity-50"
            >
              <Send className="w-3.5 h-3.5" />
              {flushing ? 'Flushing...' : 'Flush Now'}
            </button>
            <button
              onClick={() => fetchLogs()}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 text-xs rounded disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
            <button
              onClick={handleClear}
              className="flex items-center gap-2 px-3 py-1.5 bg-zinc-700 hover:bg-red-700 text-zinc-200 text-xs rounded"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Clear All
            </button>
            <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded"
              />
              Auto-refresh
            </label>
          </div>

          {/* Stats */}
          <div className="flex gap-4 text-xs font-mono text-zinc-400">
            <span>Pending local: <span className="text-zinc-200">{pendingCount}</span></span>
            <span>Remote total: <span className="text-zinc-200">{total}</span></span>
          </div>

          {/* Filters */}
          <div className="flex gap-2">
            <select
              value={levelFilter}
              onChange={(e) => setLevelFilter(e.target.value)}
              className="bg-zinc-800 text-zinc-200 text-xs rounded px-2 py-1.5 border border-zinc-700"
            >
              <option value="">All levels</option>
              <option value="error">error</option>
              <option value="warn">warn</option>
              <option value="info">info</option>
              <option value="debug">debug</option>
            </select>
            <input
              type="text"
              value={namespaceFilter}
              onChange={(e) => setNamespaceFilter(e.target.value)}
              placeholder="Filter namespace..."
              className="bg-zinc-800 text-zinc-200 text-xs rounded px-2 py-1.5 border border-zinc-700 flex-1"
            />
          </div>

          {/* Log entries */}
          <div className="bg-zinc-900/50 rounded-lg max-h-80 overflow-y-auto">
            {entries.length === 0 ? (
              <div className="text-zinc-500 text-xs italic p-3">
                {loading ? 'Loading...' : 'No remote log entries'}
              </div>
            ) : (
              <div className="divide-y divide-zinc-800/50">
                {entries.map((entry) => (
                  <div key={entry.id} className={`px-3 py-1.5 text-xs font-mono ${getLevelBg(entry.level)}`}>
                    <span className="text-zinc-500">
                      {entry.client_ts ? new Date(entry.client_ts).toLocaleTimeString() : '?'}
                    </span>{' '}
                    <span className={getLevelColor(entry.level)}>
                      {entry.level.toUpperCase().padEnd(5)}
                    </span>{' '}
                    <span className="text-zinc-400">[{entry.namespace}]</span>{' '}
                    <span className="text-zinc-200 break-all">{entry.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
