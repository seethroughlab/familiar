/**
 * API Error Tracker
 *
 * Centralized tracking of API errors for debugging and user visibility.
 * Provides a buffer of recent errors, subscription system for UI updates,
 * and error categorization.
 */

export type ErrorCategory =
  | 'network' // Connection/timeout errors
  | 'auth' // 401/403 errors
  | 'validation' // 400 errors
  | 'server' // 500 errors
  | 'external' // 503 external service errors
  | 'unknown';

export type ErrorSeverity = 'error' | 'warning' | 'info';

export interface TrackedError {
  id: string;
  timestamp: Date;
  category: ErrorCategory;
  severity: ErrorSeverity;
  message: string;
  endpoint: string;
  method: string;
  statusCode: number | null;
  context?: string;
  details?: unknown;
}

type ErrorListener = (errors: TrackedError[]) => void;

const MAX_ERRORS = 100;

class ApiErrorTracker {
  private errors: TrackedError[] = [];
  private listeners: Set<ErrorListener> = new Set();
  private nextId = 1;

  /**
   * Track a new API error.
   */
  track(
    error: {
      message: string;
      endpoint: string;
      method: string;
      statusCode?: number | null;
      context?: string;
      details?: unknown;
    },
    category?: ErrorCategory,
    severity?: ErrorSeverity
  ): TrackedError {
    const resolvedCategory = category ?? this.categorizeError(error.statusCode ?? null, error.message);
    const resolvedSeverity = severity ?? this.determineSeverity(resolvedCategory);

    const trackedError: TrackedError = {
      id: `err-${this.nextId++}`,
      timestamp: new Date(),
      category: resolvedCategory,
      severity: resolvedSeverity,
      message: error.message,
      endpoint: error.endpoint,
      method: error.method,
      statusCode: error.statusCode ?? null,
      context: error.context,
      details: error.details,
    };

    // Add to beginning (most recent first)
    this.errors.unshift(trackedError);

    // Trim to max size
    if (this.errors.length > MAX_ERRORS) {
      this.errors = this.errors.slice(0, MAX_ERRORS);
    }

    // Notify listeners
    this.notifyListeners();

    return trackedError;
  }

  /**
   * Get all tracked errors.
   */
  getErrors(): TrackedError[] {
    return [...this.errors];
  }

  /**
   * Get errors by category.
   */
  getErrorsByCategory(category: ErrorCategory): TrackedError[] {
    return this.errors.filter((e) => e.category === category);
  }

  /**
   * Get errors since a specific time.
   */
  getRecentErrors(since: Date): TrackedError[] {
    return this.errors.filter((e) => e.timestamp >= since);
  }

  /**
   * Get error count by severity.
   */
  getCountBySeverity(): Record<ErrorSeverity, number> {
    const counts: Record<ErrorSeverity, number> = {
      error: 0,
      warning: 0,
      info: 0,
    };
    for (const err of this.errors) {
      counts[err.severity]++;
    }
    return counts;
  }

  /**
   * Clear all tracked errors.
   */
  clear(): void {
    this.errors = [];
    this.notifyListeners();
  }

  /**
   * Subscribe to error updates.
   */
  subscribe(listener: ErrorListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notifyListeners(): void {
    const errorsCopy = [...this.errors];
    for (const listener of this.listeners) {
      try {
        listener(errorsCopy);
      } catch {
        // Don't let listener errors break the tracker
      }
    }
  }

  private categorizeError(statusCode: number | null, message: string): ErrorCategory {
    if (statusCode === null) {
      // Network-level error (no response)
      if (message.toLowerCase().includes('network') || message.toLowerCase().includes('timeout')) {
        return 'network';
      }
      return 'unknown';
    }

    if (statusCode === 401 || statusCode === 403) {
      return 'auth';
    }

    if (statusCode === 400 || statusCode === 422) {
      return 'validation';
    }

    if (statusCode === 503) {
      return 'external';
    }

    if (statusCode >= 500) {
      return 'server';
    }

    return 'unknown';
  }

  private determineSeverity(category: ErrorCategory): ErrorSeverity {
    switch (category) {
      case 'auth':
      case 'server':
        return 'error';
      case 'network':
      case 'external':
        return 'warning';
      case 'validation':
      case 'unknown':
      default:
        return 'info';
    }
  }
}

// Global singleton instance
export const apiErrorTracker = new ApiErrorTracker();

/**
 * Helper to extract error info from Axios errors.
 */
export function extractAxiosError(error: unknown): {
  message: string;
  statusCode: number | null;
  endpoint: string;
  method: string;
  details?: unknown;
} {
  // Check if it's an Axios error with response
  if (
    error &&
    typeof error === 'object' &&
    'response' in error &&
    error.response &&
    typeof error.response === 'object'
  ) {
    const response = error.response as {
      status?: number;
      data?: { detail?: string; message?: string };
      config?: { url?: string; method?: string };
    };

    const config = (error as { config?: { url?: string; method?: string } }).config;

    return {
      message:
        response.data?.detail ||
        response.data?.message ||
        `Request failed with status ${response.status}`,
      statusCode: response.status ?? null,
      endpoint: config?.url || 'unknown',
      method: (config?.method || 'unknown').toUpperCase(),
      details: response.data,
    };
  }

  // Check if it's an Axios error without response (network error)
  if (
    error &&
    typeof error === 'object' &&
    'config' in error &&
    error.config &&
    typeof error.config === 'object'
  ) {
    const config = error.config as { url?: string; method?: string };
    const message =
      error instanceof Error ? error.message : 'Network error - no response received';

    return {
      message,
      statusCode: null,
      endpoint: config.url || 'unknown',
      method: (config.method || 'unknown').toUpperCase(),
    };
  }

  // Fallback for unknown error types
  return {
    message: error instanceof Error ? error.message : String(error),
    statusCode: null,
    endpoint: 'unknown',
    method: 'unknown',
  };
}
