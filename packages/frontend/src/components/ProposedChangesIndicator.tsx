import { useQuery } from '@tanstack/react-query';
import { FileEdit } from 'lucide-react';
import { proposedChangesApi } from '../api';
import { queryKeys } from '../api/queryKeys';
import { useAppNavigation } from '../hooks/useAppNavigation';

export function ProposedChangesIndicator() {
  const { navigateToLibrary } = useAppNavigation();

  // Fetch pending changes count
  const { data: stats } = useQuery({
    queryKey: queryKeys.proposedChanges.stats,
    queryFn: () => proposedChangesApi.getStats(),
    refetchInterval: 30000, // Check every 30 seconds
  });

  const pendingCount = stats?.pending ?? 0;

  // Don't render if no pending changes
  if (pendingCount === 0) {
    return null;
  }

  const handleClick = () => {
    // Navigate to the proposed-changes view in the library using React Router
    navigateToLibrary({ browser: 'proposed-changes' });
  };

  return (
    <button
      onClick={handleClick}
      className="p-2 rounded-lg transition-colors text-amber-400 hover:text-amber-300 hover:bg-amber-900/30 relative"
      title={`${pendingCount} proposed change${pendingCount !== 1 ? 's' : ''} pending review - click to review`}
    >
      <FileEdit className="w-5 h-5" />
      <span className="absolute -top-1 -right-1 min-w-[1rem] h-4 px-1 bg-amber-500 text-white text-xs rounded-full flex items-center justify-center font-medium">
        {pendingCount > 99 ? '99+' : pendingCount}
      </span>
    </button>
  );
}
