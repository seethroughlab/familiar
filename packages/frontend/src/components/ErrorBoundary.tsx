import { Component, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { createLogger } from '../utils/logger';

const log = createLogger('ErrorBoundary');

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
  /** Name of the component/section for error reporting */
  name?: string;
  /** Whether this wraps a fullscreen component (uses full-height styling) */
  fullscreen?: boolean;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error boundary component that catches JavaScript errors in child components.
 * Displays a fallback UI instead of crashing the entire app.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Log error for debugging
    log.error(`${this.props.name ? `[${this.props.name}]` : ''}`, error, errorInfo);

    // Call optional error handler
    this.props.onError?.(error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      // Use custom fallback if provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Default fallback UI - visible on both light and dark backgrounds
      const containerClass = this.props.fullscreen
        ? "fixed inset-0 z-50 flex flex-col items-center justify-center p-8 text-center bg-zinc-900"
        : "flex flex-col items-center justify-center p-8 text-center bg-zinc-900/80 rounded-lg m-4";

      return (
        <div className={containerClass}>
          <AlertTriangle className="w-12 h-12 text-warning-strong mb-4" />
          <h2 className="text-lg font-semibold text-zinc-200 mb-2">
            Something went wrong
          </h2>
          <p className="text-sm text-zinc-400 mb-4 max-w-md">
            {this.props.name
              ? `The ${this.props.name} encountered an error. Try again, or reload the page if it persists.`
              : 'An unexpected error occurred. Try again, or reload the page if it persists.'}
          </p>
          <button
            onClick={this.handleRetry}
            className="flex items-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600
                       rounded-lg text-sm font-medium transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Try Again
          </button>
          {import.meta.env.DEV && this.state.error && (
            <pre className="mt-4 p-4 bg-zinc-950 rounded-lg text-left text-xs text-danger
                            max-w-full overflow-auto max-h-40">
              {this.state.error.message}
              {'\n\n'}
              {this.state.error.stack}
            </pre>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

interface SilentErrorBoundaryProps {
  children: ReactNode;
  /** Optional minimal fallback message (default: shows a small error indicator) */
  fallbackMessage?: string;
}

/**
 * Minimal error boundary for inline components.
 * Shows a small fallback UI instead of nothing, so users know something went wrong.
 */
export class SilentErrorBoundary extends Component<SilentErrorBoundaryProps, { hasError: boolean }> {
  constructor(props: SilentErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    log.error('[Silent]', error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      // Show minimal fallback UI instead of nothing
      return (
        <div className="text-xs text-zinc-500 p-2 text-center">
          <span>{this.props.fallbackMessage || 'Something went wrong.'}</span>
          <button
            onClick={this.handleRetry}
            className="ml-2 text-zinc-400 hover:text-white underline"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
