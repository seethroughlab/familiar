/**
 * Utilities for showing contextual error notifications to users.
 * Maps technical errors to user-friendly messages.
 */
import { showError, showWarning, showSuccess } from '../stores/toastStore';
import { AppError } from './appError';
import type { ExternalToast } from 'sonner';

/**
 * Standard error message templates by category.
 */
const ERROR_MESSAGES = {
  network: 'Check your internet connection and try again',
  server: 'Something went wrong. Please try again later.',
  validation: 'Please check your input and try again',
  external: (service: string) => `The ${service} service is temporarily unavailable`,
  notFound: 'The requested item could not be found',
  unauthorized: 'Please sign in to continue',
  forbidden: 'You do not have permission to perform this action',
  timeout: 'The request timed out. Please try again.',
} as const;

/**
 * Extract a user-friendly message from an error.
 */
export function getUserFriendlyMessage(
  error: unknown,
  context?: string
): string {
  // Fast path for normalized AppError
  if (error instanceof AppError) {
    if (error.statusCode === 401) return ERROR_MESSAGES.unauthorized;
    if (error.statusCode === 403) return ERROR_MESSAGES.forbidden;
    if (error.statusCode === 404) return ERROR_MESSAGES.notFound;
    if (error.category === 'network') return ERROR_MESSAGES.network;
    if (error.statusCode && error.statusCode >= 500) return ERROR_MESSAGES.server;
    return error.message;
  }

  // Handle axios/fetch errors
  if (error && typeof error === 'object') {
    const e = error as Record<string, unknown>;

    // Check for API error response with detail
    if (e.response && typeof e.response === 'object') {
      const response = e.response as Record<string, unknown>;
      const data = response.data as Record<string, unknown> | undefined;

      // Extract detail message from API response
      if (data?.detail && typeof data.detail === 'string') {
        return data.detail;
      }

      // Map status codes
      const status = response.status as number | undefined;
      if (status) {
        if (status === 401) return ERROR_MESSAGES.unauthorized;
        if (status === 403) return ERROR_MESSAGES.forbidden;
        if (status === 404) return ERROR_MESSAGES.notFound;
        if (status >= 500) return ERROR_MESSAGES.server;
      }
    }

    // Check for network errors
    if (e.code === 'ERR_NETWORK' || e.message === 'Network Error') {
      return ERROR_MESSAGES.network;
    }

    // Check for timeout
    if (e.code === 'ECONNABORTED' || e.message === 'timeout') {
      return ERROR_MESSAGES.timeout;
    }

    // Error message property
    if (e.message && typeof e.message === 'string') {
      // Don't expose technical messages
      if (e.message.includes('fetch') || e.message.includes('network')) {
        return ERROR_MESSAGES.network;
      }
      // Return message if it looks user-friendly (no stack traces, etc.)
      if (!e.message.includes('\n') && e.message.length < 200) {
        return e.message;
      }
    }
  }

  // String error
  if (typeof error === 'string') {
    return error;
  }

  // Default with context
  if (context) {
    return `Failed to ${context}. Please try again.`;
  }

  return ERROR_MESSAGES.server;
}

/**
 * Show an error notification for a failed operation.
 */
export function notifyError(
  error: unknown,
  options: {
    /** Operation being performed (e.g., "save profile", "load tracks") */
    operation?: string;
    /** Custom title for the toast */
    title?: string;
    /** Custom message to show instead of auto-generated one */
    message?: string;
    /** Additional toast options */
    toastOptions?: ExternalToast;
  } = {}
) {
  const { operation, title, message, toastOptions } = options;

  const displayMessage =
    message || getUserFriendlyMessage(error, operation);

  // Use description for longer messages
  if (title) {
    showError(title, {
      description: displayMessage,
      ...toastOptions,
    });
  } else if (operation) {
    showError(`Failed to ${operation}`, {
      description: displayMessage !== `Failed to ${operation}. Please try again.`
        ? displayMessage
        : undefined,
      ...toastOptions,
    });
  } else {
    showError(displayMessage, toastOptions);
  }
}

/**
 * Show a warning notification.
 */
export function notifyWarning(message: string, options?: ExternalToast) {
  showWarning(message, options);
}

/**
 * Show a success notification.
 */
export function notifySuccess(message: string, options?: ExternalToast) {
  showSuccess(message, options);
}

/**
 * Show an offline warning.
 */
export function notifyOffline(operation: string) {
  showWarning(`Cannot ${operation} while offline`, {
    description: 'Connect to the internet and try again',
  });
}

/**
 * Show a "not available offline" warning.
 */
export function notifyNotAvailableOffline(feature: string) {
  showWarning(`${feature} is not available offline`);
}

/**
 * Show an external service error.
 */
export function notifyExternalServiceError(service: string, options?: ExternalToast) {
  showError(`${service} is temporarily unavailable`, {
    description: 'Please try again later',
    ...options,
  });
}
