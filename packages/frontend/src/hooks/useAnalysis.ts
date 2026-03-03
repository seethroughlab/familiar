import { useCallback } from 'react';
import { analysisApi } from '../api/analysis';
import { showLoading, showSuccess, showError, dismissToast } from '../stores/toastStore';
import type { Track } from '../types';

/**
 * Hook for triggering analysis and downloading reports.
 * Handles the trigger -> poll -> download flow with toast progress.
 */
export function useAnalysis() {
  const downloadAnalysis = useCallback(async (track: Track) => {
    const label = `${track.artist || 'Unknown'} - ${track.title || 'Unknown'}`;
    const toastId = showLoading(`Analyzing ${label}...`);

    try {
      // Trigger analysis (returns immediately if cached)
      const { data } = await analysisApi.trigger(track.id);

      if (data.status === 'ready') {
        // Already cached — download immediately
        dismissToast(toastId);
        await analysisApi.downloadReport(track.id);
        showSuccess('Analysis downloaded');
        return;
      }

      // Processing — poll until ready
      for (let i = 0; i < 90; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const { data: status } = await analysisApi.getStatus(track.id);
        if ('status' in status && status.status === 'processing') {
          continue; // still processing
        }
        // Analysis ready — download report
        dismissToast(toastId);
        await analysisApi.downloadReport(track.id);
        showSuccess('Analysis downloaded');
        return;
      }

      dismissToast(toastId);
      showError('Analysis timed out — try again later');
    } catch (err) {
      dismissToast(toastId);
      const msg = err instanceof Error ? err.message : 'Unknown error';
      showError(`Analysis failed: ${msg}`);
    }
  }, []);

  const downloadBulkAnalysis = useCallback(async (trackIds: string[]) => {
    if (trackIds.length === 0) return;

    const toastId = showLoading(`Analyzing ${trackIds.length} tracks...`);

    try {
      const { data } = await analysisApi.triggerBulk(trackIds);
      const taskId = data.task_id;

      // Poll progress
      for (let i = 0; i < 180; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        try {
          const { data: progress } = await analysisApi.getBulkStatus(taskId);

          dismissToast(toastId);
          if (progress.status === 'completed') {
            // Download combined report
            await analysisApi.downloadBulkReport(taskId);
            showSuccess(`Analysis downloaded (${progress.completed} tracks)`);
            return;
          }

          // Update progress toast
          showLoading(`Analyzing tracks... ${progress.completed}/${progress.total}`, { id: toastId });
        } catch {
          // Continue polling
        }
      }

      dismissToast(toastId);
      showError('Bulk analysis timed out');
    } catch (err) {
      dismissToast(toastId);
      const msg = err instanceof Error ? err.message : 'Unknown error';
      showError(`Bulk analysis failed: ${msg}`);
    }
  }, []);

  return { downloadAnalysis, downloadBulkAnalysis };
}
