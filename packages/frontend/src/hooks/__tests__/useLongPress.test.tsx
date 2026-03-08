/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useLongPress } from '../useLongPress';

function LongPressHarness({
  onLongPress,
  onClick,
}: {
  onLongPress: (position: { x: number; y: number }) => void;
  onClick: () => void;
}) {
  const handlers = useLongPress(onLongPress, { delay: 100, hapticFeedback: false });

  return (
    <div data-testid="target" onClick={onClick} {...handlers}>
      target
    </div>
  );
}

describe('useLongPress', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('suppresses the follow-up click after a long press', () => {
    const onLongPress = vi.fn();
    const onClick = vi.fn();

    render(<LongPressHarness onLongPress={onLongPress} onClick={onClick} />);

    const target = screen.getByTestId('target');
    fireEvent.touchStart(target, {
      touches: [{ clientX: 12, clientY: 34 }],
    });

    vi.advanceTimersByTime(100);

    fireEvent.touchEnd(target);
    fireEvent.click(target);

    expect(onLongPress).toHaveBeenCalledWith({ x: 12, y: 34 });
    expect(onClick).not.toHaveBeenCalled();
  });

  it('allows a normal tap click through', () => {
    const onLongPress = vi.fn();
    const onClick = vi.fn();

    render(<LongPressHarness onLongPress={onLongPress} onClick={onClick} />);

    const target = screen.getByTestId('target');
    fireEvent.touchStart(target, {
      touches: [{ clientX: 12, clientY: 34 }],
    });
    vi.advanceTimersByTime(50);
    fireEvent.touchEnd(target);
    fireEvent.click(target);

    expect(onLongPress).not.toHaveBeenCalled();
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
