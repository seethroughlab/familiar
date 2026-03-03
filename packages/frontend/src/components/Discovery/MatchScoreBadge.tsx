interface MatchScoreBadgeProps {
  score: number;  // 0-1 value
  inLibrary?: boolean;
  className?: string;
}

/**
 * Displays a match score as a percentage badge
 * - In-library items: emerald/green color
 * - External items: muted zinc color
 */
export function MatchScoreBadge({ score, inLibrary = false, className = '' }: MatchScoreBadgeProps) {
  const percentage = Math.round(score * 100);

  return (
    <span
      className={`text-xs ${
        inLibrary ? 'text-emerald-500' : 'text-zinc-500'
      } ${className}`}
    >
      {percentage}%{inLibrary && ' match'}
    </span>
  );
}
