import { useEffect, useState, useRef } from 'react';
import { AlertTriangle, AlertCircle, X } from 'lucide-react';
import { useHealthStore } from '../stores/healthStore';

export function HealthIndicator() {
  const { status, warnings, startPolling, stopPolling } = useHealthStore();
  const [showPopover, setShowPopover] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Start polling on mount
  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  // Close popover when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(event.target as Node)) {
        setShowPopover(false);
      }
    }

    if (showPopover) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showPopover]);

  // Don't render anything if healthy
  if (status === 'healthy' || status === 'loading') {
    return null;
  }

  const isUnhealthy = status === 'unhealthy' || status === 'error';
  const Icon = isUnhealthy ? AlertCircle : AlertTriangle;
  const colorClasses = isUnhealthy
    ? 'text-red-400 hover:text-red-300 hover:bg-red-900/30'
    : 'text-yellow-400 hover:text-yellow-300 hover:bg-yellow-900/30';

  return (
    <div className="relative" ref={popoverRef}>
      <button
        onClick={() => setShowPopover(!showPopover)}
        className={`p-2 rounded-lg transition-colors ${colorClasses}`}
        title={isUnhealthy ? 'System issues detected' : 'Warnings'}
      >
        <Icon className="w-5 h-5" />
        {warnings.length > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">
            {warnings.length}
          </span>
        )}
      </button>

      {/* Popover */}
      {showPopover && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl z-[60]">
          <div className="p-3 border-b border-zinc-700 flex items-center justify-between">
            <h3 className="font-medium text-white flex items-center gap-2">
              <Icon className={`w-4 h-4 ${isUnhealthy ? 'text-red-400' : 'text-yellow-400'}`} />
              {isUnhealthy ? 'System Issues' : 'Warnings'}
            </h3>
            <button
              onClick={() => setShowPopover(false)}
              className="p-1 hover:bg-zinc-700 rounded transition-colors"
            >
              <X className="w-4 h-4 text-zinc-400" />
            </button>
          </div>

          <div className="p-3 space-y-2 max-h-64 overflow-y-auto">
            {warnings.length > 0 ? (
              warnings.map((warning, i) => (
                <div
                  key={i}
                  className={`p-2 rounded text-sm ${
                    isUnhealthy
                      ? 'bg-red-900/30 text-red-200'
                      : 'bg-yellow-900/30 text-yellow-200'
                  }`}
                >
                  {warning}
                </div>
              ))
            ) : (
              <p className="text-sm text-zinc-400">
                {isUnhealthy
                  ? 'A required service is not responding. View System Status in Settings for details.'
                  : 'System is operational but may need attention. View System Status in Settings for details.'}
              </p>
            )}
          </div>

          <div className="p-3 border-t border-zinc-700">
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                setShowPopover(false);
                // Navigate to settings - dispatch a custom event
                window.dispatchEvent(new CustomEvent('navigate-to-settings'));
              }}
              className="text-sm text-blue-400 hover:text-blue-300"
            >
              View System Status
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
