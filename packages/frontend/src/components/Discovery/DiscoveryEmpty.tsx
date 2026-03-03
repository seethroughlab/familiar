import { Sparkles } from 'lucide-react';

interface DiscoveryEmptyProps {
  message?: string;
  className?: string;
}

/**
 * Empty state for discovery panels
 */
export function DiscoveryEmpty({
  message = 'No recommendations available',
  className = '',
}: DiscoveryEmptyProps) {
  return (
    <div className={`flex flex-col items-center justify-center py-8 text-center ${className}`}>
      <Sparkles className="w-8 h-8 text-zinc-600 mb-2" />
      <p className="text-sm text-zinc-500">{message}</p>
    </div>
  );
}
