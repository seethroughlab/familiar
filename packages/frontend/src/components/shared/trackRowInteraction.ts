export type TrackRowIntent =
  | 'play'
  | 'select-single'
  | 'select-toggle'
  | 'select-range';

interface ResolveTrackRowIntentOptions {
  isMobile: boolean;
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
}

export function resolveTrackRowIntent({
  isMobile,
  shiftKey,
  metaKey,
  ctrlKey,
}: ResolveTrackRowIntentOptions): TrackRowIntent {
  if (isMobile) {
    return 'play';
  }

  if (shiftKey) {
    return 'select-range';
  }

  if (metaKey || ctrlKey) {
    return 'select-toggle';
  }

  return 'select-single';
}
