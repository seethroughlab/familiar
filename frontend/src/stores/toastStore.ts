/**
 * Toast notification store using Sonner.
 * Integrates with apiErrorTracker for centralized error reporting.
 */
import { toast, type ExternalToast } from 'sonner';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface ToastOptions extends ExternalToast {
  type?: ToastType;
}

/**
 * Show a toast notification.
 */
export function showToast(message: string, options: ToastOptions = {}) {
  const { type = 'info', ...rest } = options;

  switch (type) {
    case 'success':
      return toast.success(message, rest);
    case 'error':
      return toast.error(message, rest);
    case 'warning':
      return toast.warning(message, rest);
    case 'info':
    default:
      return toast(message, rest);
  }
}

/**
 * Show a success toast.
 */
export function showSuccess(message: string, options?: ExternalToast) {
  return toast.success(message, options);
}

/**
 * Show an error toast.
 */
export function showError(message: string, options?: ExternalToast) {
  return toast.error(message, options);
}

/**
 * Show a warning toast.
 */
export function showWarning(message: string, options?: ExternalToast) {
  return toast.warning(message, options);
}

/**
 * Show an info toast.
 */
export function showInfo(message: string, options?: ExternalToast) {
  return toast(message, options);
}

/**
 * Show a loading toast that can be updated.
 */
export function showLoading(message: string, options?: ExternalToast) {
  return toast.loading(message, options);
}

/**
 * Dismiss a specific toast or all toasts.
 */
export function dismissToast(toastId?: string | number) {
  if (toastId) {
    toast.dismiss(toastId);
  } else {
    toast.dismiss();
  }
}

/**
 * Show a promise toast that updates based on promise state.
 */
export function showPromise<T>(
  promise: Promise<T>,
  messages: {
    loading: string;
    success: string | ((data: T) => string);
    error: string | ((err: unknown) => string);
  }
) {
  return toast.promise(promise, messages);
}
