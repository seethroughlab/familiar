/**
 * Tests for useRetryableOperation hook - retry logic with error feedback.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { act } from 'react';

// Mock toast store
vi.mock('../../stores/toastStore', () => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showWarning: vi.fn(),
}));

// Mock error notifications
vi.mock('../../utils/errorNotifications', () => ({
  getUserFriendlyMessage: vi.fn((error: unknown, _context?: string) =>
    error instanceof Error ? error.message : String(error)
  ),
}));

import { useRetryableOperation } from '../useRetryableOperation';
import { showError } from '../../stores/toastStore';

describe('useRetryableOperation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('execute', () => {
    it('should execute operation successfully', async () => {
      const operation = vi.fn().mockResolvedValue('result');
      const { result } = renderHook(() => useRetryableOperation(operation));

      let returnValue: unknown = null;
      await act(async () => {
        returnValue = await result.current.execute();
      });

      expect(returnValue).toBe('result');
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.retryCount).toBe(0);
    });

    it('should set loading state during execution', async () => {
      let resolveOp: (v: string) => void;
      const operation = vi.fn(() => new Promise<string>((r) => { resolveOp = r; }));

      const { result } = renderHook(() => useRetryableOperation(operation));

      // Start execution without awaiting
      let executePromise: Promise<unknown>;
      act(() => {
        executePromise = result.current.execute();
      });

      expect(result.current.isLoading).toBe(true);

      await act(async () => {
        resolveOp!('done');
        await executePromise;
      });

      expect(result.current.isLoading).toBe(false);
    });

    it('should handle operation failure', async () => {
      const error = new Error('Operation failed');
      const operation = vi.fn().mockRejectedValue(error);

      const { result } = renderHook(() => useRetryableOperation(operation));

      await act(async () => {
        await result.current.execute();
      });

      expect(result.current.error).toBe(error);
      expect(result.current.isLoading).toBe(false);
    });

    it('should show toast on failure by default', async () => {
      const operation = vi.fn().mockRejectedValue(new Error('Boom'));

      const { result } = renderHook(() => useRetryableOperation(operation));

      await act(async () => {
        await result.current.execute();
      });

      expect(showError).toHaveBeenCalled();
    });

    it('should not show toast when showToast is false', async () => {
      const operation = vi.fn().mockRejectedValue(new Error('Boom'));

      const { result } = renderHook(() =>
        useRetryableOperation(operation, { showToast: false })
      );

      await act(async () => {
        await result.current.execute();
      });

      expect(showError).not.toHaveBeenCalled();
    });

    it('should call onSuccess callback', async () => {
      const onSuccess = vi.fn();
      const operation = vi.fn().mockResolvedValue('ok');

      const { result } = renderHook(() =>
        useRetryableOperation(operation, { onSuccess })
      );

      await act(async () => {
        await result.current.execute();
      });

      expect(onSuccess).toHaveBeenCalledOnce();
    });

    it('should convert non-Error to Error', async () => {
      const operation = vi.fn().mockRejectedValue('string error');

      const { result } = renderHook(() => useRetryableOperation(operation));

      await act(async () => {
        await result.current.execute();
      });

      expect(result.current.error).toBeInstanceOf(Error);
      expect(result.current.error?.message).toBe('string error');
    });
  });

  describe('retry', () => {
    it('should increment retry count', async () => {
      const operation = vi.fn().mockRejectedValue(new Error('Fail'));

      const { result } = renderHook(() =>
        useRetryableOperation(operation, { maxRetries: 5 })
      );

      await act(async () => {
        await result.current.execute();
      });
      expect(result.current.retryCount).toBe(0);

      await act(async () => {
        await result.current.retry();
      });
      expect(result.current.retryCount).toBe(1);

      await act(async () => {
        await result.current.retry();
      });
      expect(result.current.retryCount).toBe(2);
    });

    it('should succeed on retry after initial failure', async () => {
      const operation = vi.fn()
        .mockRejectedValueOnce(new Error('Fail'))
        .mockResolvedValueOnce('success');

      const { result } = renderHook(() => useRetryableOperation(operation));

      await act(async () => {
        await result.current.execute();
      });
      expect(result.current.error).toBeTruthy();

      await act(async () => {
        await result.current.retry();
      });
      expect(result.current.error).toBeNull();
      expect(result.current.retryCount).toBe(0); // Reset on success
    });

    it('should stop retrying after maxRetries', async () => {
      const operation = vi.fn().mockRejectedValue(new Error('Fail'));
      const onFailure = vi.fn();

      const { result } = renderHook(() =>
        useRetryableOperation(operation, { maxRetries: 2, onFailure })
      );

      // Execute (retryCount = 0)
      await act(async () => { await result.current.execute(); });

      // Retry 1 (retryCount = 1)
      await act(async () => { await result.current.retry(); });

      // Retry 2 (retryCount = 2)
      await act(async () => { await result.current.retry(); });

      // Retry 3 - should be blocked (maxRetries = 2)
      const callsBefore = operation.mock.calls.length;
      await act(async () => { await result.current.retry(); });

      // Operation should not have been called again
      expect(operation.mock.calls.length).toBe(callsBefore);
      expect(onFailure).toHaveBeenCalledOnce();
    });

    it('canRetry should reflect remaining retries', async () => {
      const operation = vi.fn().mockRejectedValue(new Error('Fail'));

      const { result } = renderHook(() =>
        useRetryableOperation(operation, { maxRetries: 1 })
      );

      expect(result.current.canRetry).toBe(true);

      await act(async () => { await result.current.execute(); });
      expect(result.current.canRetry).toBe(true); // retryCount=0, maxRetries=1

      await act(async () => { await result.current.retry(); });
      expect(result.current.canRetry).toBe(false); // retryCount=1, maxRetries=1
    });
  });

  describe('reset', () => {
    it('should reset all state', async () => {
      const operation = vi.fn().mockRejectedValue(new Error('Fail'));

      const { result } = renderHook(() => useRetryableOperation(operation));

      await act(async () => { await result.current.execute(); });
      expect(result.current.error).toBeTruthy();

      act(() => { result.current.reset(); });

      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.retryCount).toBe(0);
      expect(result.current.canRetry).toBe(true);
    });
  });
});
