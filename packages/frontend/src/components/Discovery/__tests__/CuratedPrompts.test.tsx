import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CuratedPrompts } from '../CuratedPrompts';
import { useUIStore } from '../../../stores/uiStore';
import type { CuratedPrompt } from '../../../api/library';

/**
 * Written against a real bug Jeff reported: in the embedded Discover surface, the "Listening Ideas"
 * cards did nothing at all when pressed.
 *
 * A prompt is a message for the chat and has no other destination — `triggerChat` sets
 * `rightPanel: 'chat'`, and only `AppShell` renders that panel. The embed (ADR-0017) mounts Discover
 * without a shell on purpose, so the state changed and nothing observed it. The third bug of this
 * exact shape: an affordance in the embedded page whose destination isn't there.
 *
 * These pin both halves — that the section is present and live where chat exists, and gone where it
 * doesn't — because either one alone regresses quietly.
 */
describe('CuratedPrompts', () => {
  const prompts: CuratedPrompt[] = [
    { prompt: 'What IDM gems am I sleeping on?', icon: 'sparkles' },
  ] as CuratedPrompt[];

  beforeEach(() => {
    useUIStore.setState({ chatSurfaceAvailable: true, pendingChatMessage: null, rightPanel: null });
  });

  it('offers the prompt to the chat where there is one', () => {
    render(<CuratedPrompts prompts={prompts} loading={false} onRefresh={() => {}} />);

    fireEvent.click(screen.getByText('What IDM gems am I sleeping on?'));

    expect(useUIStore.getState().pendingChatMessage).toBe('What IDM gems am I sleeping on?');
    expect(useUIStore.getState().rightPanel).toBe('chat');
  });

  /**
   * The bug. Rendering these on a surface that cannot open chat shows a row of suggestions that
   * cannot be taken up — worse than showing nothing, because it reads as broken rather than absent.
   */
  it('renders nothing when the surface has no chat to open', () => {
    useUIStore.setState({ chatSurfaceAvailable: false });

    const { container } = render(
      <CuratedPrompts prompts={prompts} loading={false} onRefresh={() => {}} />,
    );

    expect(container.innerHTML).toBe('');
    expect(screen.queryByText('Listening Ideas')).toBeNull();
  });

  /** Loading is the state the embed hit first, and it drew the header before any prompt arrived. */
  it('stays hidden while loading, rather than flashing an empty header', () => {
    useUIStore.setState({ chatSurfaceAvailable: false });

    const { container } = render(<CuratedPrompts prompts={[]} loading onRefresh={() => {}} />);

    expect(container.innerHTML).toBe('');
  });
});
