/* @vitest-environment jsdom */
/**
 * The token field has a name (found by the v0.2.0-beta24 release-checklist pass).
 *
 * Its only name was its placeholder, which disappears once a token is filled in, the field's
 * normal state, leaving a screen reader an unnamed password field. A saved token also had no
 * way to tell a waiting screen to retry; the profile picker's sign-in state needs that.
 */
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, afterEach } from 'vitest';

vi.mock('../../../api/base', () => ({
  getApiUrl: (path: string) => `/api/v1${path}`,
  getServerToken: () => 'a-saved-token',
  setServerToken: vi.fn(async () => {}),
}));

import { ServerTokenSettings } from '../ServerTokenSettings';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('ServerTokenSettings', () => {
  it('labels the token field, so a filled field is still announced by name', () => {
    render(<ServerTokenSettings />);
    const field = screen.getByLabelText('Server Token') as HTMLInputElement;
    expect(field.type).toBe('password');
    expect(field.value).toBe('a-saved-token');
    expect(field.getAttribute('aria-describedby')).toBeTruthy();
  });

  it('tells its host when the server accepts the token', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
    const onAccepted = vi.fn();
    render(<ServerTokenSettings onAccepted={onAccepted} />);

    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(onAccepted).toHaveBeenCalledTimes(1));
  });

  it('does not when the server rejects it', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })));
    const onAccepted = vi.fn();
    render(<ServerTokenSettings onAccepted={onAccepted} />);

    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(await screen.findByText(/rejected that token/)).toBeTruthy();
    expect(onAccepted).not.toHaveBeenCalled();
  });
});
