/* @vitest-environment jsdom */
/**
 * What the profile picker says and how it is announced (found by the v0.2.0-beta24
 * release-checklist pass).
 *
 * A browser without the server's token was shown "Failed to load profiles" beside "Add Profile",
 * which reads as a server with no profiles. The colour swatches were unnamed buttons, and the
 * "Profile Name" label was tied to nothing, so a screen reader heard "button" eight times and an
 * unnamed text field. axe passed all of it: a placeholder counts as a name to axe, and the dialog
 * is closed when the accessibility spec runs.
 */
import { render, screen, cleanup } from '@testing-library/react';
import { AxiosError, AxiosHeaders } from 'axios';
import { describe, expect, it, vi, afterEach } from 'vitest';

const listProfiles = vi.fn();
vi.mock('../../../services/profileService', () => ({
  listProfiles: () => listProfiles(),
  createProfile: vi.fn(),
  selectProfile: vi.fn(),
}));
vi.mock('../../../panels/server/ServerTokenSettings', () => ({
  ServerTokenSettings: () => <div data-testid="token-form" />,
}));

import { ProfileSelector } from '../ProfileSelector';

afterEach(() => {
  cleanup();
  listProfiles.mockReset();
});

function refusal(status: number, code: string): AxiosError {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError('refused', String(status), config, undefined, {
    status,
    statusText: '',
    headers: {},
    config,
    data: { code },
  });
}

describe('ProfileSelector', () => {
  it('asks for the token, not for a profile, when the server wants its token', async () => {
    listProfiles.mockRejectedValue(refusal(401, 'SERVER_TOKEN_REQUIRED'));
    render(<ProfileSelector onProfileSelected={() => {}} />);

    expect(await screen.findByRole('heading', { name: 'Sign in to this server' })).toBeTruthy();
    expect(screen.getByTestId('token-form')).toBeTruthy();
    expect(screen.queryByText('Failed to load profiles')).toBeNull();
    expect(screen.queryByText('Add Profile')).toBeNull();
  });

  it('still says profiles failed to load for any other failure', async () => {
    listProfiles.mockRejectedValue(refusal(500, 'INTERNAL_ERROR'));
    render(<ProfileSelector onProfileSelected={() => {}} />);

    expect(await screen.findByText('Failed to load profiles')).toBeTruthy();
    expect(screen.queryByTestId('token-form')).toBeNull();
  });

  it('names the create form: its field, its colours and which colour is chosen', async () => {
    listProfiles.mockResolvedValue([]);
    render(<ProfileSelector onProfileSelected={() => {}} />);
    await screen.findByRole('heading', { name: "Who's listening?" });

    expect(screen.getByLabelText('Profile Name').tagName).toBe('INPUT');

    const group = screen.getByRole('group', { name: 'Profile Color', hidden: true });
    const swatches = Array.from(group.querySelectorAll('button'));
    expect(swatches.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Blue', 'Green', 'Purple', 'Amber', 'Red', 'Pink', 'Cyan', 'Orange',
    ]);
    expect(swatches.filter((b) => b.getAttribute('aria-pressed') === 'true')).toHaveLength(1);
  });
});
