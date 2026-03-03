/**
 * Tests for apiErrorTracker - centralized API error tracking.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Re-create the tracker for each test since it's a singleton
// We import the class indirectly by importing and resetting the singleton
import { apiErrorTracker, extractAxiosError } from '../apiErrorTracker';
import type { ErrorCategory } from '../apiErrorTracker';

describe('apiErrorTracker', () => {
  beforeEach(() => {
    apiErrorTracker.clear();
  });

  describe('track', () => {
    it('should track an error and return it', () => {
      const result = apiErrorTracker.track({
        message: 'Server error',
        endpoint: '/api/tracks',
        method: 'GET',
        statusCode: 500,
      });

      expect(result.message).toBe('Server error');
      expect(result.endpoint).toBe('/api/tracks');
      expect(result.method).toBe('GET');
      expect(result.statusCode).toBe(500);
      expect(result.id).toMatch(/^err-/);
      expect(result.timestamp).toBeInstanceOf(Date);
    });

    it('should auto-categorize by status code', () => {
      const cases: Array<[number, ErrorCategory]> = [
        [401, 'auth'],
        [403, 'auth'],
        [400, 'validation'],
        [422, 'validation'],
        [500, 'server'],
        [502, 'server'],
        [503, 'external'],
      ];

      for (const [statusCode, expectedCategory] of cases) {
        const error = apiErrorTracker.track({
          message: 'Error',
          endpoint: '/api/test',
          method: 'GET',
          statusCode,
        });
        expect(error.category).toBe(expectedCategory);
      }
    });

    it('should categorize network errors by message when no status code', () => {
      const networkError = apiErrorTracker.track({
        message: 'Network error - no response',
        endpoint: '/api/test',
        method: 'GET',
        statusCode: null,
      });
      expect(networkError.category).toBe('network');

      const timeoutError = apiErrorTracker.track({
        message: 'Request timeout',
        endpoint: '/api/test',
        method: 'GET',
        statusCode: null,
      });
      expect(timeoutError.category).toBe('network');
    });

    it('should categorize as unknown when no status code and no matching message', () => {
      const error = apiErrorTracker.track({
        message: 'Something happened',
        endpoint: '/api/test',
        method: 'GET',
        statusCode: null,
      });
      expect(error.category).toBe('unknown');
    });

    it('should allow explicit category override', () => {
      const error = apiErrorTracker.track(
        { message: 'Custom', endpoint: '/api/test', method: 'GET', statusCode: 500 },
        'network'
      );
      expect(error.category).toBe('network');
    });

    it('should allow explicit severity override', () => {
      const error = apiErrorTracker.track(
        { message: 'Custom', endpoint: '/api/test', method: 'GET', statusCode: 500 },
        undefined,
        'info'
      );
      expect(error.severity).toBe('info');
    });

    it('should determine severity from category', () => {
      const severityCases: Array<[ErrorCategory, string]> = [
        ['auth', 'error'],
        ['server', 'error'],
        ['network', 'warning'],
        ['external', 'warning'],
        ['validation', 'info'],
        ['unknown', 'info'],
      ];

      for (const [category, expectedSeverity] of severityCases) {
        const error = apiErrorTracker.track(
          { message: 'Test', endpoint: '/api/test', method: 'GET' },
          category
        );
        expect(error.severity).toBe(expectedSeverity);
      }
    });

    it('should store most recent first', () => {
      apiErrorTracker.track({ message: 'First', endpoint: '/a', method: 'GET' });
      apiErrorTracker.track({ message: 'Second', endpoint: '/b', method: 'GET' });

      const errors = apiErrorTracker.getErrors();
      expect(errors[0].message).toBe('Second');
      expect(errors[1].message).toBe('First');
    });

    it('should trim to max 100 errors', () => {
      for (let i = 0; i < 110; i++) {
        apiErrorTracker.track({ message: `Error ${i}`, endpoint: '/api/test', method: 'GET' });
      }

      const errors = apiErrorTracker.getErrors();
      expect(errors.length).toBe(100);
      // Most recent should be first
      expect(errors[0].message).toBe('Error 109');
    });
  });

  describe('getErrors', () => {
    it('should return a copy (not a reference)', () => {
      apiErrorTracker.track({ message: 'Test', endpoint: '/api/test', method: 'GET' });
      const errors1 = apiErrorTracker.getErrors();
      const errors2 = apiErrorTracker.getErrors();
      expect(errors1).not.toBe(errors2);
      expect(errors1).toEqual(errors2);
    });
  });

  describe('getErrorsByCategory', () => {
    it('should filter by category', () => {
      apiErrorTracker.track({ message: 'Auth error', endpoint: '/a', method: 'GET', statusCode: 401 });
      apiErrorTracker.track({ message: 'Server error', endpoint: '/b', method: 'GET', statusCode: 500 });
      apiErrorTracker.track({ message: 'Auth error 2', endpoint: '/c', method: 'GET', statusCode: 403 });

      const authErrors = apiErrorTracker.getErrorsByCategory('auth');
      expect(authErrors).toHaveLength(2);
      expect(authErrors.every((e) => e.category === 'auth')).toBe(true);
    });
  });

  describe('getRecentErrors', () => {
    it('should return errors after the given date', () => {
      const past = new Date(Date.now() - 10000);
      apiErrorTracker.track({ message: 'Recent', endpoint: '/a', method: 'GET' });

      const recent = apiErrorTracker.getRecentErrors(past);
      expect(recent).toHaveLength(1);

      const future = new Date(Date.now() + 10000);
      const empty = apiErrorTracker.getRecentErrors(future);
      expect(empty).toHaveLength(0);
    });
  });

  describe('getCountBySeverity', () => {
    it('should count errors by severity', () => {
      apiErrorTracker.track({ message: 'E1', endpoint: '/a', method: 'GET', statusCode: 500 }); // error
      apiErrorTracker.track({ message: 'E2', endpoint: '/b', method: 'GET', statusCode: 401 }); // error
      apiErrorTracker.track({ message: 'W1', endpoint: '/c', method: 'GET' }, 'network');        // warning
      apiErrorTracker.track({ message: 'I1', endpoint: '/d', method: 'GET', statusCode: 400 }); // info

      const counts = apiErrorTracker.getCountBySeverity();
      expect(counts.error).toBe(2);
      expect(counts.warning).toBe(1);
      expect(counts.info).toBe(1);
    });

    it('should return zeros when empty', () => {
      const counts = apiErrorTracker.getCountBySeverity();
      expect(counts).toEqual({ error: 0, warning: 0, info: 0 });
    });
  });

  describe('clear', () => {
    it('should remove all errors', () => {
      apiErrorTracker.track({ message: 'Test', endpoint: '/a', method: 'GET' });
      apiErrorTracker.clear();
      expect(apiErrorTracker.getErrors()).toHaveLength(0);
    });
  });

  describe('subscribe', () => {
    it('should notify listeners on track', () => {
      const listener = vi.fn();
      apiErrorTracker.subscribe(listener);

      apiErrorTracker.track({ message: 'Test', endpoint: '/a', method: 'GET' });

      expect(listener).toHaveBeenCalledOnce();
      expect(listener).toHaveBeenCalledWith(expect.arrayContaining([
        expect.objectContaining({ message: 'Test' }),
      ]));
    });

    it('should notify listeners on clear', () => {
      const listener = vi.fn();
      apiErrorTracker.subscribe(listener);

      apiErrorTracker.clear();

      expect(listener).toHaveBeenCalledWith([]);
    });

    it('should unsubscribe when calling returned function', () => {
      const listener = vi.fn();
      const unsubscribe = apiErrorTracker.subscribe(listener);

      unsubscribe();
      apiErrorTracker.track({ message: 'Test', endpoint: '/a', method: 'GET' });

      expect(listener).not.toHaveBeenCalled();
    });

    it('should not break if listener throws', () => {
      const badListener = vi.fn(() => { throw new Error('Boom'); });
      const goodListener = vi.fn();

      apiErrorTracker.subscribe(badListener);
      apiErrorTracker.subscribe(goodListener);

      apiErrorTracker.track({ message: 'Test', endpoint: '/a', method: 'GET' });

      // Both listeners were called despite the first one throwing
      expect(badListener).toHaveBeenCalledOnce();
      expect(goodListener).toHaveBeenCalledOnce();
    });
  });
});

describe('extractAxiosError', () => {
  it('should extract from axios error with response', () => {
    const axiosError = {
      response: {
        status: 404,
        data: { detail: 'Track not found' },
      },
      config: {
        url: '/api/tracks/123',
        method: 'get',
      },
    };

    const result = extractAxiosError(axiosError);
    expect(result.message).toBe('Track not found');
    expect(result.statusCode).toBe(404);
    expect(result.endpoint).toBe('/api/tracks/123');
    expect(result.method).toBe('GET');
  });

  it('should extract from axios error with message field', () => {
    const axiosError = {
      response: {
        status: 500,
        data: { message: 'Internal server error' },
      },
      config: {
        url: '/api/test',
        method: 'post',
      },
    };

    const result = extractAxiosError(axiosError);
    expect(result.message).toBe('Internal server error');
  });

  it('should fallback to status code message when no detail or message', () => {
    const axiosError = {
      response: {
        status: 500,
        data: {},
      },
      config: { url: '/api/test', method: 'get' },
    };

    const result = extractAxiosError(axiosError);
    expect(result.message).toBe('Request failed with status 500');
  });

  it('should extract from axios network error (no response)', () => {
    const networkError = Object.assign(new Error('Network Error'), {
      config: {
        url: '/api/tracks',
        method: 'get',
      },
    });

    const result = extractAxiosError(networkError);
    expect(result.message).toBe('Network Error');
    expect(result.statusCode).toBeNull();
    expect(result.endpoint).toBe('/api/tracks');
    expect(result.method).toBe('GET');
  });

  it('should handle plain Error object', () => {
    const result = extractAxiosError(new Error('Something broke'));
    expect(result.message).toBe('Something broke');
    expect(result.statusCode).toBeNull();
    expect(result.endpoint).toBe('unknown');
  });

  it('should handle string error', () => {
    const result = extractAxiosError('string error');
    expect(result.message).toBe('string error');
  });

  it('should handle null/undefined', () => {
    const result = extractAxiosError(null);
    expect(result.message).toBe('null');
    expect(result.endpoint).toBe('unknown');
  });
});
