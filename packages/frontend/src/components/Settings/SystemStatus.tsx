import { useState, useEffect, useCallback } from 'react';
import {
  CheckCircle,
  AlertCircle,
  AlertTriangle,
  Loader2,
  Server,
  Database,
  Activity,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Cpu,
  Bug,
  Copy,
  Check,
  ExternalLink,
  X,
  Download,
} from 'lucide-react';
import {
  healthApi,
  diagnosticsApi,
  updatesApi,
  appSettingsApi,
  type SystemHealth,
  type ServiceStatus,
  type ServiceDetails,
  type AnalysisServiceDetails,
  type BackgroundServiceDetails,
  type WorkerStatus,
  type DiagnosticsExport,
  type UpdateStatus,
} from '../../api';
import { useConnectivityStore } from '../../stores/connectivityStore';

import { createLogger } from '../../utils/logger';

const log = createLogger('SystemStatus');

export function SystemStatus() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isExpanded, setIsExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showReportModal, setShowReportModal] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsExport | null>(null);
  const [isLoadingDiagnostics, setIsLoadingDiagnostics] = useState(false);
  const [copied, setCopied] = useState(false);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [updateChannel, setUpdateChannel] = useState<string>('disabled');
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false);
  const connectivityCounters = useConnectivityStore((s) => s.counters);

  // Load update channel from settings
  useEffect(() => {
    appSettingsApi.get().then((s) => setUpdateChannel(s.update_channel)).catch(() => {});
  }, []);

  const fetchHealth = useCallback(async () => {
    try {
      setError(null);
      const [healthData, workerData] = await Promise.all([
        healthApi.getSystemHealth(),
        healthApi.getWorkerStatus(),
      ]);
      setHealth(healthData);
      setWorkerStatus(workerData);
      // Non-blocking update check
      updatesApi.getStatus().then(setUpdateStatus).catch(() => {});
    } catch (err) {
      setError('Failed to fetch system status');
      log.error('Failed to fetch system health:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Fetch on mount and poll every 10 seconds when expanded, 30 seconds otherwise
  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, isExpanded ? 10000 : 30000);
    return () => clearInterval(interval);
  }, [fetchHealth, isExpanded]);

  const handleReportIssue = async () => {
    setShowReportModal(true);
    setIsLoadingDiagnostics(true);
    setCopied(false);
    try {
      const data = await diagnosticsApi.export();
      setDiagnostics(data);
    } catch (err) {
      log.error('Failed to fetch diagnostics:', err);
    } finally {
      setIsLoadingDiagnostics(false);
    }
  };

  const formatDiagnosticsMarkdown = (diag: DiagnosticsExport): string => {
    const lines: string[] = [];

    lines.push('## Bug Report\n');
    lines.push('**Description:**');
    lines.push('[Please describe what happened and what you expected to happen]\n');

    lines.push('## System Information\n');
    lines.push(`- **Familiar Version:** ${diag.version}`);
    lines.push(`- **Deployment:** ${diag.deployment_mode}`);
    lines.push(`- **Exported:** ${new Date(diag.exported_at).toLocaleString()}`);

    // System info (OS, hardware, etc.)
    const sysInfo = diag.system_info as Record<string, unknown>;
    if (sysInfo) {
      if (sysInfo.os) lines.push(`- **OS:** ${sysInfo.os} ${sysInfo.os_version || ''}`);
      if (sysInfo.os_detail) lines.push(`- **Platform:** ${sysInfo.os_detail}`);
      if (sysInfo.architecture) lines.push(`- **Architecture:** ${sysInfo.architecture}`);
      if (sysInfo.python_version) lines.push(`- **Python:** ${sysInfo.python_version}`);
      if (sysInfo.cpu_count) lines.push(`- **CPU Cores:** ${sysInfo.cpu_count}`);
      if (sysInfo.memory_total_gb) {
        lines.push(`- **Memory:** ${sysInfo.memory_available_gb}GB available / ${sysInfo.memory_total_gb}GB total (${sysInfo.memory_percent_used}% used)`);
      }
      if (sysInfo.docker !== undefined) lines.push(`- **Docker:** ${sysInfo.docker ? 'Yes' : 'No'}`);
    }
    lines.push('');

    // System Health
    const health = diag.system_health as { status?: string; services?: Array<{ name: string; status: string; message?: string }>; warnings?: string[] };
    if (health && health.status) {
      lines.push('## System Health\n');
      lines.push(`**Status:** ${health.status}\n`);

      if (health.services && health.services.length > 0) {
        lines.push('| Service | Status | Message |');
        lines.push('|---------|--------|---------|');
        for (const svc of health.services) {
          lines.push(`| ${svc.name} | ${svc.status} | ${svc.message || '-'} |`);
        }
        lines.push('');
      }

      if (health.warnings && health.warnings.length > 0) {
        lines.push('**Warnings:**');
        for (const warning of health.warnings) {
          lines.push(`- ${warning}`);
        }
        lines.push('');
      }
    }

    // Library Stats
    const libStats = diag.library_stats as { total_tracks?: number; analyzed_tracks?: number; pending_analysis?: number };
    if (libStats && libStats.total_tracks !== undefined) {
      lines.push('## Library Statistics\n');
      lines.push(`- Total tracks: ${libStats.total_tracks?.toLocaleString() || 0}`);
      lines.push(`- Analyzed: ${libStats.analyzed_tracks?.toLocaleString() || 0}`);
      lines.push(`- Pending: ${libStats.pending_analysis?.toLocaleString() || 0}\n`);
    }

    // Settings Summary
    const settings = diag.settings_summary as Record<string, unknown>;
    if (settings && !settings.error) {
      lines.push('## Configuration\n');
      lines.push(`- Last.fm: ${settings.has_lastfm_key ? 'configured' : 'not configured'}`);
      lines.push(`- Library paths: ${settings.library_paths_count || 0}\n`);
    }

    const pendingLocalTotal = connectivityCounters.pending_sync_local_url_total;
    const pendingLocalRatio = pendingLocalTotal > 0
      ? connectivityCounters.pending_sync_local_url_local / pendingLocalTotal
      : null;
    lines.push('## Playback Canary (Client)\n');
    lines.push(`- remote_command_enablement_mismatch: ${connectivityCounters.remote_command_enablement_mismatch}`);
    lines.push(
      `- pending_sync_local_url_ratio: ${
        pendingLocalRatio === null
          ? 'n/a (no offline pending sync attempts yet)'
          : `${(pendingLocalRatio * 100).toFixed(1)}% (${connectivityCounters.pending_sync_local_url_local}/${pendingLocalTotal})`
      }`
    );
    lines.push('');

    // Recent Failures
    if (diag.recent_failures && diag.recent_failures.length > 0) {
      lines.push('<details>');
      lines.push(`<summary>Recent Errors (${diag.recent_failures.length})</summary>\n`);
      lines.push('```json');
      lines.push(JSON.stringify(diag.recent_failures, null, 2));
      lines.push('```');
      lines.push('</details>\n');
    }

    // Recent Logs
    if (diag.recent_logs && diag.recent_logs.length > 0) {
      lines.push('<details>');
      lines.push(`<summary>Recent Logs (${diag.recent_logs.length} entries)</summary>\n`);
      lines.push('```');
      for (const log of diag.recent_logs.slice(-50)) { // Last 50 for readability
        const entry = log as { timestamp?: string; level?: string; logger?: string; message?: string };
        const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : '';
        lines.push(`[${time}] ${entry.level} [${entry.logger}] ${entry.message}`);
      }
      lines.push('```');
      lines.push('</details>\n');
    }

    return lines.join('\n');
  };

  const handleCopy = async () => {
    if (!diagnostics) return;
    const markdown = formatDiagnosticsMarkdown(diagnostics);
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const openGitHubIssues = () => {
    window.open('https://github.com/seethroughlab/familiar/issues/new', '_blank');
  };

  const handleCheckNow = async () => {
    setIsCheckingUpdate(true);
    try {
      const result = await updatesApi.checkNow();
      setUpdateStatus(result);
    } catch (err) {
      log.error('Update check failed:', err);
    } finally {
      setIsCheckingUpdate(false);
    }
  };

  const handleChannelChange = async (channel: string) => {
    setUpdateChannel(channel);
    try {
      await appSettingsApi.update({ update_channel: channel });
      // Trigger a check if enabling
      if (channel !== 'disabled') {
        handleCheckNow();
      } else {
        setUpdateStatus(null);
      }
    } catch (err) {
      log.error('Failed to update channel:', err);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy':
        return <CheckCircle className="w-4 h-4 text-success" />;
      case 'degraded':
        return <AlertTriangle className="w-4 h-4 text-warning" />;
      case 'unhealthy':
        return <AlertCircle className="w-4 h-4 text-danger" />;
      default:
        return <Activity className="w-4 h-4 text-zinc-400" />;
    }
  };

  const getServiceIcon = (name: string) => {
    switch (name) {
      case 'database':
        return <Database className="w-4 h-4" />;
      case 'redis':
        return <Server className="w-4 h-4" />;
      case 'background_processing':
        return <Cpu className="w-4 h-4" />;
      case 'analysis':
        return <Activity className="w-4 h-4" />;
      default:
        return <Server className="w-4 h-4" />;
    }
  };

  const getServiceDisplayName = (name: string) => {
    switch (name) {
      case 'database':
        return 'Database';
      case 'redis':
        return 'Cache';
      case 'background_processing':
        return 'Processing';
      case 'analysis':
        return 'Analysis';
      default:
        return name;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy':
        return 'text-success';
      case 'degraded':
        return 'text-warning';
      case 'unhealthy':
        return 'text-danger';
      default:
        return 'text-zinc-400';
    }
  };

  const getStatusBgColor = (status: string) => {
    switch (status) {
      case 'healthy':
        return 'bg-green-900/20 border-green-800';
      case 'degraded':
        return 'bg-yellow-900/20 border-yellow-800';
      case 'unhealthy':
        return 'bg-red-900/20 border-red-800';
      default:
        return 'bg-zinc-800/50 border-zinc-700';
    }
  };

  const getStatusSummary = (services: ServiceStatus[], status: 'degraded' | 'unhealthy') => {
    // Filter out 'analysis' from problem services - it's shown in Library Status now
    const problemServices = services.filter(s =>
      s.name !== 'analysis' && (status === 'unhealthy' ? s.status === 'unhealthy' : s.status !== 'healthy')
    );

    if (problemServices.length === 0) {
      return status === 'unhealthy' ? 'Service issues detected' : 'All core services running';
    }

    const names = problemServices.map(s => {
      switch (s.name) {
        case 'database': return 'Database';
        case 'redis': return 'Cache';
        case 'background_processing': return 'Background processing';
        default: return s.name;
      }
    });

    if (names.length === 1) {
      const service = problemServices[0];
      if (service.name === 'background_processing' && service.status === 'unhealthy') {
        return 'Background processing stopped';
      }
      return `${names[0]} ${service.status === 'unhealthy' ? 'unavailable' : 'needs attention'}`;
    }

    return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]} need attention`;
  };

  if (isLoading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-3">
          <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
          <span className="text-zinc-400">Checking system status...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-danger" />
            <div>
              <h4 className="font-medium text-white">System Status Unavailable</h4>
              <p className="text-sm text-danger">{error}</p>
            </div>
          </div>
          <button
            onClick={fetchHealth}
            className="p-2 hover:bg-zinc-700 rounded transition-colors"
            title="Retry"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  if (!health) return null;

  const hasWarnings = Array.isArray(health.warnings) && health.warnings.length > 0;
  const pendingLocalTotal = connectivityCounters.pending_sync_local_url_total;
  const pendingLocalRatio = pendingLocalTotal > 0
    ? connectivityCounters.pending_sync_local_url_local / pendingLocalTotal
    : null;

  return (
    <div className={`rounded-lg p-4 border ${getStatusBgColor(health.status)}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {getStatusIcon(health.status)}
          <div>
            <h4 className="font-medium text-white">System Status</h4>
            <p className={`text-sm ${getStatusColor(health.status)}`}>
              {health.status === 'healthy' && 'All services running'}
              {health.status === 'degraded' && getStatusSummary(health.services, 'degraded')}
              {health.status === 'unhealthy' && getStatusSummary(health.services, 'unhealthy')}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchHealth}
            className="p-2 hover:bg-zinc-700/50 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-2 hover:bg-zinc-700/50 rounded transition-colors"
            title={isExpanded ? 'Collapse' : 'Expand'}
          >
            {isExpanded ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Service status badges (always visible) - filter out analysis (shown in Library Status) */}
      <div className="mt-3 flex flex-wrap gap-2">
        {Array.isArray(health.services) && health.services
          .filter((service) => service.name !== 'analysis')
          .map((service) => (
            <div
              key={service.name}
              className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
                service.status === 'healthy'
                  ? 'bg-green-900/30 text-success'
                  : service.status === 'degraded'
                  ? 'bg-yellow-900/30 text-yellow-300'
                  : 'bg-red-900/30 text-danger'
              }`}
            >
              {getServiceIcon(service.name)}
              <span>{getServiceDisplayName(service.name)}</span>
            </div>
          ))}
      </div>

      {/* Update available banner */}
      {updateStatus?.update_available && (
        <div className="mt-3 flex items-center justify-between p-3 bg-purple-900/20 border border-purple-800/50 rounded-lg">
          <div className="flex items-center gap-2">
            <Download className="w-4 h-4 text-purple-400" />
            <span className="text-sm text-purple-200">
              Version {updateStatus.latest_version} is available
            </span>
          </div>
          {updateStatus.release_url && (
            <a
              href={updateStatus.release_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300 transition-colors"
            >
              Release notes
              <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      )}

      {/* Warnings (always visible if present) */}
      {hasWarnings && (
        <div className="mt-3 space-y-2">
          {health.warnings.map((warning, i) => (
            <div
              key={i}
              className="flex items-start gap-2 p-2 bg-yellow-900/20 border border-yellow-800/50 rounded text-sm text-yellow-200"
            >
              <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{warning}</span>
            </div>
          ))}
        </div>
      )}

      {/* Expanded details */}
      {isExpanded && (
        <div className="mt-4 space-y-4">
          {/* Services (filter out analysis - shown in Library Status) */}
          <div className="space-y-2">
            <h5 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
              Services
            </h5>
            {Array.isArray(health.services) && health.services
              .filter((service) => service.name !== 'analysis')
              .map((service) => (
                <ServiceStatusRow key={service.name} service={service} />
              ))}
          </div>

          {/* Workers */}
          {workerStatus && Array.isArray(workerStatus.workers) && workerStatus.workers.length > 0 && (
            <div className="space-y-2">
              <h5 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
                Workers
              </h5>
              {workerStatus.workers.map((worker) => (
                <div key={worker.name} className="p-3 bg-zinc-800/50 rounded-lg">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-success" />
                      <span className="text-sm font-medium text-white">
                        {worker.name}
                      </span>
                    </div>
                    <span className="text-xs text-zinc-500">
                      {worker.concurrency && `${worker.concurrency} processes`}
                    </span>
                  </div>

                  {Array.isArray(worker.active_tasks) && worker.active_tasks.length > 0 ? (
                    <div className="mt-2 space-y-1">
                      {worker.active_tasks.map((task) => (
                        <div
                          key={task.id}
                          className="flex items-center gap-2 text-xs text-zinc-400"
                        >
                          <Loader2 className="w-3 h-3 animate-spin" />
                          <span className="truncate">{task.name}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-1 text-xs text-zinc-500">Idle</p>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Recent Failures */}
          {workerStatus && Array.isArray(workerStatus.recent_failures) && workerStatus.recent_failures.length > 0 && (
            <div className="space-y-2">
              <h5 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
                Recent Issues
              </h5>
              {workerStatus.recent_failures.slice(0, 5).map((failure, i) => (
                <div
                  key={i}
                  className="p-3 bg-red-900/20 border border-red-800/50 rounded-lg"
                >
                  <div className="flex items-start gap-2">
                    <AlertCircle className="w-4 h-4 text-danger mt-0.5 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm text-red-200 break-words">{failure.error}</p>
                      {failure.track && (
                        <p className="text-xs text-zinc-400 mt-1 truncate">
                          {failure.track}
                        </p>
                      )}
                      <p className="text-xs text-zinc-500 mt-1">
                        {new Date(failure.timestamp).toLocaleTimeString()}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Update Notifications */}
          <div className="space-y-2">
            <h5 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
              Update Notifications
            </h5>
            <div className="p-3 bg-zinc-800/50 rounded-lg space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm text-zinc-300">Release channel</label>
                <select
                  value={updateChannel}
                  onChange={(e) => handleChannelChange(e.target.value)}
                  className="bg-zinc-700 text-sm text-white rounded px-2 py-1 border border-zinc-600 focus:outline-none focus:border-purple-500"
                >
                  <option value="disabled">Disabled</option>
                  <option value="stable">Stable</option>
                  <option value="beta">Beta</option>
                  <option value="alpha">Alpha</option>
                </select>
              </div>
              {updateChannel !== 'disabled' && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-zinc-500">
                    {updateStatus?.checked_at
                      ? `Last checked ${new Date(updateStatus.checked_at).toLocaleString()}`
                      : 'Not checked yet'}
                  </span>
                  <button
                    onClick={handleCheckNow}
                    disabled={isCheckingUpdate}
                    className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-white transition-colors disabled:opacity-50"
                  >
                    {isCheckingUpdate ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <RefreshCw className="w-3 h-3" />
                    )}
                    Check Now
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Playback Canary */}
          <div className="space-y-2">
            <h5 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
              Playback Canary
            </h5>
            <div className="p-3 bg-zinc-800/50 rounded-lg space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-400">remote_command_enablement_mismatch</span>
                <span className={`font-mono ${connectivityCounters.remote_command_enablement_mismatch === 0 ? 'text-success' : 'text-yellow-300'}`}>
                  {connectivityCounters.remote_command_enablement_mismatch}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-400">pending_sync_local_url_ratio</span>
                <span className="font-mono text-zinc-200">
                  {pendingLocalRatio === null
                    ? 'n/a'
                    : `${(pendingLocalRatio * 100).toFixed(1)}% (${connectivityCounters.pending_sync_local_url_local}/${pendingLocalTotal})`}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Report Issue Button & Version */}
      <div className="mt-4 pt-4 border-t border-zinc-700 flex items-center justify-between">
        <button
          onClick={handleReportIssue}
          className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-400 hover:text-white hover:bg-zinc-700/50 rounded transition-colors"
        >
          <Bug className="w-4 h-4" />
          Report Issue
        </button>
        <span className="text-xs text-zinc-600">
          {health.version}
          {updateStatus?.update_available && updateStatus.latest_version && (
            <span className="text-purple-500 ml-1">
              ({updateStatus.latest_version} available)
            </span>
          )}
        </span>
      </div>

      {/* Report Issue Modal */}
      {showReportModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-zinc-900 rounded-xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col shadow-xl border border-zinc-700">
            {/* Modal Header */}
            <div className="flex items-center justify-between p-4 border-b border-zinc-700">
              <h3 className="text-lg font-medium text-white">Report Issue</h3>
              <button
                onClick={() => setShowReportModal(false)}
                className="p-2 hover:bg-zinc-700 rounded transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-auto p-4">
              {isLoadingDiagnostics ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
                </div>
              ) : diagnostics ? (
                <div className="space-y-4">
                  <p className="text-sm text-zinc-400">
                    Copy the diagnostic information below and paste it into a new GitHub issue.
                    Please add a description of the problem you encountered.
                  </p>
                  <div className="bg-zinc-800 rounded-lg p-4 max-h-[40vh] overflow-auto">
                    <pre className="text-xs text-zinc-300 whitespace-pre-wrap font-mono">
                      {formatDiagnosticsMarkdown(diagnostics)}
                    </pre>
                  </div>
                </div>
              ) : (
                <div className="text-center py-8 text-zinc-400">
                  Failed to load diagnostics
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-between p-4 border-t border-zinc-700 gap-3">
              <button
                onClick={openGitHubIssues}
                className="flex items-center gap-2 px-4 py-2 text-sm text-zinc-300 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors"
              >
                <ExternalLink className="w-4 h-4" />
                Open GitHub Issues
              </button>
              <button
                onClick={handleCopy}
                disabled={!diagnostics}
                className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors text-white font-medium"
              >
                {copied ? (
                  <>
                    <Check className="w-4 h-4" />
                    Copied!
                  </>
                ) : (
                  <>
                    <Copy className="w-4 h-4" />
                    Copy to Clipboard
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function isAnalysisDetails(d: ServiceDetails): d is AnalysisServiceDetails {
  return d != null && 'analyzed' in d && 'total' in d;
}

function isBackgroundDetails(d: ServiceDetails): d is BackgroundServiceDetails {
  return d != null && 'workers' in d;
}

function ServiceStatusRow({ service }: { service: ServiceStatus }) {
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy':
        return <CheckCircle className="w-4 h-4 text-success" />;
      case 'degraded':
        return <AlertTriangle className="w-4 h-4 text-warning" />;
      case 'unhealthy':
        return <AlertCircle className="w-4 h-4 text-danger" />;
      default:
        return <Activity className="w-4 h-4 text-zinc-400" />;
    }
  };

  const getServiceDisplayName = (name: string) => {
    switch (name) {
      case 'database':
        return 'Database';
      case 'redis':
        return 'Cache';
      case 'background_processing':
        return 'Background Processing';
      case 'analysis':
        return 'Track Analysis';
      default:
        return name;
    }
  };

  return (
    <div className="flex items-start justify-between p-3 bg-zinc-800/50 rounded-lg">
      <div className="flex items-start gap-3">
        {getStatusIcon(service.status)}
        <div>
          <h5 className="font-medium text-white text-sm">
            {getServiceDisplayName(service.name)}
          </h5>
          <p className="text-xs text-zinc-400">{service.message}</p>
          {service.details && (
            <div className="mt-1 text-xs text-zinc-500">
              {isAnalysisDetails(service.details) && (
                <span>
                  {service.details.analyzed.toLocaleString()} /{' '}
                  {service.details.total.toLocaleString()} tracks analyzed
                </span>
              )}
              {isBackgroundDetails(service.details) && service.details.workers && (
                <span>
                  {service.details.workers.length} worker(s)
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
