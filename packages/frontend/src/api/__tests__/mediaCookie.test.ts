import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * The media cookie (ADR-0176 point 3): the web admin's `<img>` artwork carries it, since an image
 * cannot send the token header. What breaks it quietly is timing — the server only issues or clears
 * it for a caller presenting the token, so each request must go out while the right token is held.
 */

const calls: { op: 'issue' | 'clear'; tokenAtCall: string }[] = [];
let failIssue = false;

vi.mock('@familiar/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@familiar/api-client')>();
  // Read lazily: importing `../base` here would cycle, since it imports this very module.
  const getServerToken = async () => (await import('../base')).getServerToken();
  return {
    ...actual,
    authIssueMediaCookie: vi.fn(async () => {
      calls.push({ op: 'issue', tokenAtCall: await getServerToken() });
      if (failIssue) throw new Error('network down');
      return { data: { issued: true } };
    }),
    authClearMediaCookie: vi.fn(async () => {
      calls.push({ op: 'clear', tokenAtCall: await getServerToken() });
      return { data: { issued: false } };
    }),
  };
});

const { setServerToken, syncMediaCookie } = await import('../base');

describe('media cookie', () => {
  beforeEach(async () => {
    localStorage.clear();
    await setServerToken('');
    calls.length = 0;
    failIssue = false;
  });

  it('is issued once a token is set, with that token', async () => {
    await setServerToken('tok-new');
    expect(calls).toEqual([{ op: 'issue', tokenAtCall: 'tok-new' }]);
  });

  it('is cleared before the token is forgotten, while the server still lets the request in', async () => {
    await setServerToken('tok-old');
    calls.length = 0;
    await setServerToken('');
    expect(calls).toEqual([{ op: 'clear', tokenAtCall: 'tok-old' }]);
  });

  it('is not asked for without a token', async () => {
    await syncMediaCookie();
    expect(calls).toEqual([]);
  });

  it('never breaks sign-in when the server will not issue one', async () => {
    failIssue = true;
    await expect(setServerToken('tok-x')).resolves.toBeUndefined();
    expect(calls.map((c) => c.op)).toEqual(['issue']);
  });
});
