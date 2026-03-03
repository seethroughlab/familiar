import { useEffect } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import { useHealthStore } from '../stores/healthStore';

export function WorkerAlert() {
  const { workerAlert, dismissWorkerAlert, startPolling, stopPolling } = useHealthStore();

  // Start polling on mount, stop on unmount
  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  if (!workerAlert) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-yellow-900/95 border-b border-yellow-700 px-4 py-3 shadow-lg">
      <div className="max-w-4xl mx-auto flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-yellow-400 flex-shrink-0" />
          <div>
            <p className="text-yellow-100 font-medium">Background Processing Stopped</p>
            <p className="text-yellow-200/80 text-sm">{workerAlert}</p>
          </div>
        </div>
        <button
          onClick={dismissWorkerAlert}
          className="p-1.5 hover:bg-yellow-800 rounded transition-colors"
          title="Dismiss"
        >
          <X className="w-4 h-4 text-yellow-300" />
        </button>
      </div>
    </div>
  );
}
