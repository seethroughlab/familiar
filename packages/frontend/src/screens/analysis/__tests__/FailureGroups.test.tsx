/* @vitest-environment jsdom */
/** ADR-0174 points 4 and 5: the summary first, the raw detail behind a disclosure. */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { FailureGroup } from '../../../api/system';
import { FailureGroups } from '../FailureGroups';

const group: FailureGroup = {
  kind: 'undecodable',
  task: 'extract_features',
  summary: 'The audio file could not be decoded',
  next_action: 'Check the file plays elsewhere, then replace or re-rip it.',
  count: 3,
  affected: 2,
  last_at: '2026-11-09T10:00:00',
  examples: [{ error: 'could not decode /music/a.mp3', track: 'Cranes - Paris & Rome', timestamp: '2026-11-09T10:00:00' }],
};

describe('FailureGroups', () => {
  afterEach(cleanup);

  it('renders nothing without failures', () => {
    const { container } = render(<FailureGroups groups={[]} />);
    expect(container.innerHTML).toBe('');
  });

  it('leads with what failed, how much, and what to do', () => {
    render(<FailureGroups groups={[group]} />);
    expect(screen.getByText('The audio file could not be decoded')).toBeTruthy();
    expect(screen.getByText(/3 times · 2 affected/)).toBeTruthy();
    expect(screen.getByText(/Feature extraction/)).toBeTruthy();
    expect(screen.getByText(group.next_action)).toBeTruthy();
  });

  it('keeps the raw message behind the disclosure, with a copy action', () => {
    render(<FailureGroups groups={[group]} />);
    const details = screen.getByText('Details').closest('details');
    expect(details?.open).toBe(false);
    expect(details?.textContent).toContain('could not decode /music/a.mp3');
    expect(screen.getByRole('button', { name: /copy the details/i })).toBeTruthy();
  });
});
