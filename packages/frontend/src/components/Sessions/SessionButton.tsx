import { Users } from 'lucide-react';

interface SessionButtonProps {
  isInSession: boolean;
  participantCount: number;
  onClick: () => void;
}

export function SessionButton({ isInSession, participantCount, onClick }: SessionButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`relative p-2 rounded-md transition-colors ${
        isInSession
          ? 'bg-green-600/20 text-green-500 hover:bg-green-600/30'
          : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
      }`}
      title={isInSession ? `In session (${participantCount} listeners)` : 'Start listening session'}
    >
      <Users className="w-5 h-5" />
      {isInSession && participantCount > 1 && (
        <span className="absolute -top-1 -right-1 w-4 h-4 bg-green-500 text-black text-xs font-bold rounded-full flex items-center justify-center">
          {participantCount}
        </span>
      )}
    </button>
  );
}
