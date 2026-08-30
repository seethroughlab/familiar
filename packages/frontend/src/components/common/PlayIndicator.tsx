/**
 * Shared play indicator component for track rows.
 * Shows animated bars (playing), spinner (loading), or track number.
 * Hover state shows Play/Pause icons.
 */
import { Play, Pause, Loader2 } from 'lucide-react';

interface PlayIndicatorProps {
  /** Whether this row's audio is still loading. Optional; no surface currently knows. */
  isLoadingAudio?: boolean;
  isCurrent: boolean;
  isPlaying: boolean;
  index: number; // 1-based display number
}

export function PlayIndicator({ isCurrent, isPlaying, index , isLoadingAudio}: PlayIndicatorProps) {
  // Was a `playerStore` selector. Every other input to this component is already a prop, and this
  // one is the reason a row list on `/embed` — where no player store is mounted — dragged the whole
  // player graph in behind it. It read `false` there forever.
  const isLoading = isCurrent && (isLoadingAudio ?? false);

  return (
    <>
      {/* Default state (no hover) */}
      <span className="group-hover:hidden text-zinc-400">
        {isLoading ? (
          <Loader2 className="w-4 h-4 animate-spin text-success mx-auto" />
        ) : isCurrent && isPlaying ? (
          <div className="flex justify-center gap-0.5">
            <div className="w-0.5 h-3 bg-green-500 animate-pulse" />
            <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.2s]" />
            <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.4s]" />
          </div>
        ) : isCurrent ? (
          <span className="text-sm text-success">{index}</span>
        ) : (
          <span className="text-sm">{index}</span>
        )}
      </span>

      {/* Hover state */}
      {isCurrent && (isPlaying || isLoading) ? (
        <Pause
          className="hidden group-hover:block w-4 h-4 mx-auto"
          fill="currentColor"
        />
      ) : (
        <Play
          className="hidden group-hover:block w-4 h-4 mx-auto"
          fill="currentColor"
        />
      )}
    </>
  );
}

/**
 * Mobile-aware play indicator for MobileTrackCard components.
 * Uses md:group-hover responsive prefixes instead of plain group-hover.
 */
interface MobilePlayIndicatorProps {
  /** Whether this row's audio is still loading. Optional; no surface currently knows. */
  isLoadingAudio?: boolean;
  isCurrent: boolean;
  isPlaying: boolean;
  isSelected: boolean;
  index: number; // 1-based display number
}

export function MobilePlayIndicator({ isCurrent, isPlaying, isSelected, index, isLoadingAudio }: MobilePlayIndicatorProps) {
  // Was a `playerStore` selector. Every other input to this component is already a prop, and this
  // one is the reason a row list on `/embed` — where no player store is mounted — dragged the whole
  // player graph in behind it. It read `false` there forever.
  const isLoading = isCurrent && (isLoadingAudio ?? false);

  if (isLoading) {
    return (
      <>
        <Loader2 className="w-4 h-4 animate-spin text-success md:group-hover:hidden" />
        <Pause className="hidden md:group-hover:block w-4 h-4" fill="currentColor" />
      </>
    );
  }

  if (isCurrent && isPlaying) {
    return (
      <>
        {/* Equalizer animation - always show when playing */}
        <div className="flex gap-0.5 md:group-hover:hidden">
          <div className="w-0.5 h-3 bg-green-500 animate-pulse" />
          <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.2s]" />
          <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.4s]" />
        </div>
        {/* Desktop: pause on hover */}
        <Pause className="hidden md:group-hover:block w-4 h-4" fill="currentColor" />
      </>
    );
  }

  return (
    <>
      {/* Mobile: show play icon when selected, number otherwise */}
      {isSelected ? (
        <Play className="md:hidden w-4 h-4" fill="currentColor" />
      ) : (
        <span className="md:hidden text-sm">{index}</span>
      )}
      {/* Desktop: show number, play on hover */}
      <span className="hidden md:block md:group-hover:hidden text-sm">{index}</span>
      <Play className="hidden md:group-hover:block w-4 h-4" fill="currentColor" />
    </>
  );
}
