/**
 * Unified error class for normalized error handling across the app.
 *
 * Consumers can use `toAppError(error)` to normalize any caught error
 * (AxiosError, fetch Response, plain Error, string, etc.) into a
 * structured AppError with category, severity, and status code.
 */
import { extractAxiosError } from './apiErrorTracker';
import { categorizeError, determineSeverity } from './apiErrorTracker';
import type { ErrorCategory, ErrorSeverity } from './apiErrorTracker';

export type { ErrorCategory, ErrorSeverity };

export class AppError extends Error {
  readonly category: ErrorCategory;
  readonly severity: ErrorSeverity;
  readonly statusCode: number | null;
  readonly endpoint: string;
  readonly method: string;
  readonly details?: unknown;

  constructor(info: {
    message: string;
    statusCode: number | null;
    endpoint: string;
    method: string;
    details?: unknown;
    category?: ErrorCategory;
    severity?: ErrorSeverity;
  }) {
    super(info.message);
    this.name = 'AppError';
    this.statusCode = info.statusCode;
    this.endpoint = info.endpoint;
    this.method = info.method;
    this.details = info.details;
    this.category = info.category ?? categorizeError(info.statusCode, info.message);
    this.severity = info.severity ?? determineSeverity(this.category);
  }
}

/** Normalize any error into an AppError. */
export function toAppError(error: unknown): AppError {
  if (error instanceof AppError) return error;
  const info = extractAxiosError(error);
  return new AppError(info);
}
