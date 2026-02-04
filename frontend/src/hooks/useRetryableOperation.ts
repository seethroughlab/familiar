/**
 * Hook for operations that can be retried on failure.
 */
import { useState, useCallback } from 'react';
import { showError } from '../stores/toastStore';
import { getUserFriendlyMessage } from '../utils/errorNotifications';

interface RetryableState {
  isLoading: boolean;
  error: Error | null;
  retryCount: number;
}

interface UseRetryableOperationOptions {
  /** Maximum number of retries */
  maxRetries?: number;
  /** Operation name for error messages (e.g., "sync data") */
  operationName?: string;
  /** Whether to show toast on error */
  showToast?: boolean;
  /** Callback when operation succeeds */
  onSuccess?: () => void;
  /** Callback when all retries are exhausted */
  onFailure?: (error: Error) => void;
}

/**
 * Hook for handling operations that can be retried with error feedback.
 */
export function useRetryableOperation<T>(
  operation: () => Promise<T>,
  options: UseRetryableOperationOptions = {}
) {
  const {
    maxRetries = 3,
    operationName,
    showToast = true,
    onSuccess,
    onFailure,
  } = options;

  const [state, setState] = useState<RetryableState>({
    isLoading: false,
    error: null,
    retryCount: 0,
  });

  const executeInternal = useCallback(async (currentRetryCount: number): Promise<T | null> => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const result = await operation();
      setState({ isLoading: false, error: null, retryCount: 0 });
      onSuccess?.();
      return result;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setState({
        isLoading: false,
        error,
        retryCount: currentRetryCount,
      });

      if (showToast) {
        const message = getUserFriendlyMessage(error, operationName);

        showError(operationName ? `Failed to ${operationName}` : message, {
          description: operationName ? message : undefined,
        });
      }

      return null;
    }
  }, [operation, operationName, showToast, onSuccess]);

  const execute = useCallback(async (): Promise<T | null> => {
    return executeInternal(0);
  }, [executeInternal]);

  const retry = useCallback(async (): Promise<T | null> => {
    const newRetryCount = state.retryCount + 1;

    if (newRetryCount > maxRetries) {
      if (state.error) {
        onFailure?.(state.error);
      }
      showError('Maximum retries reached', {
        description: 'Please try again later',
      });
      return null;
    }

    return executeInternal(newRetryCount);
  }, [state.retryCount, state.error, maxRetries, executeInternal, onFailure]);

  const reset = useCallback(() => {
    setState({
      isLoading: false,
      error: null,
      retryCount: 0,
    });
  }, []);

  return {
    ...state,
    execute,
    retry,
    reset,
    canRetry: state.retryCount < maxRetries,
  };
}
