import { Loader2 } from 'lucide-react';

interface DiscoveryLoadingProps {
  message?: string;
  className?: string;
}

/**
 * Loading state for discovery panels
 */
export function DiscoveryLoading({
  message = 'Loading recommendations...',
  className = '',
}: DiscoveryLoadingProps) {
  return (
    <div className={`flex items-center justify-center py-8 ${className}`}>
      <Loader2 className="w-5 h-5 animate-spin text-purple-400" />
      <span className="ml-2 text-sm text-zinc-400">{message}</span>
    </div>
  );
}
