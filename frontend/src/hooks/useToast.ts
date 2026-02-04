/**
 * Convenience hook for toast notifications.
 */
import {
  showToast,
  showSuccess,
  showError,
  showWarning,
  showInfo,
  showLoading,
  dismissToast,
} from '../stores/toastStore';

/**
 * Hook providing access to toast notification functions.
 * Can be used in components that need toast functionality.
 */
export function useToast() {
  return {
    toast: showToast,
    success: showSuccess,
    error: showError,
    warning: showWarning,
    info: showInfo,
    loading: showLoading,
    dismiss: dismissToast,
  };
}
