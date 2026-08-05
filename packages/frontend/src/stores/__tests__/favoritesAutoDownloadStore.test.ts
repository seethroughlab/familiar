/**
 * Favourites auto-download is per browser, per listener (ADR-0029 point 4).
 *
 * The seeding rules carry the weight here. This setting used to live on the server, so the first
 * load after the move has to copy the old value across — exactly once, and only when the server
 * actually answered.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useFavoritesAutoDownloadStore } from '../favoritesAutoDownloadStore';

const reset = () =>
  useFavoritesAutoDownloadStore.setState({ enabledByProfile: {}, seededProfiles: [] });

describe('favoritesAutoDownloadStore', () => {
  beforeEach(reset);

  it('defaults to off', () => {
    expect(useFavoritesAutoDownloadStore.getState().isEnabled('alice')).toBe(false);
  });

  it('keeps listeners apart', () => {
    const store = useFavoritesAutoDownloadStore.getState();
    store.setEnabled('alice', true);

    expect(useFavoritesAutoDownloadStore.getState().isEnabled('alice')).toBe(true);
    // Two people sharing a browser must not share the answer — the same reason the native key is
    // suffixed with the profile id.
    expect(useFavoritesAutoDownloadStore.getState().isEnabled('bob')).toBe(false);
  });

  it('treats no profile as off rather than throwing', () => {
    // Rendered before a profile resolves, `getCachedProfileId()` is null.
    const store = useFavoritesAutoDownloadStore.getState();
    expect(store.isEnabled(null)).toBe(false);
    expect(store.isEnabled(undefined)).toBe(false);
    expect(store.hasSeeded(null)).toBe(false);
  });

  it('seeds the server value once and then leaves it alone', () => {
    useFavoritesAutoDownloadStore.getState().seed('alice', true);
    expect(useFavoritesAutoDownloadStore.getState().isEnabled('alice')).toBe(true);
    expect(useFavoritesAutoDownloadStore.getState().hasSeeded('alice')).toBe(true);

    // The listener turns it off, then the app reloads and the seed runs again. It must not
    // resurrect the server's stale value — that would make the toggle appear to undo itself.
    useFavoritesAutoDownloadStore.getState().setEnabled('alice', false);
    useFavoritesAutoDownloadStore.getState().seed('alice', true);
    expect(useFavoritesAutoDownloadStore.getState().isEnabled('alice')).toBe(false);
  });

  it('seeds each listener separately', () => {
    useFavoritesAutoDownloadStore.getState().seed('alice', true);

    expect(useFavoritesAutoDownloadStore.getState().hasSeeded('bob')).toBe(false);
    useFavoritesAutoDownloadStore.getState().seed('bob', false);
    expect(useFavoritesAutoDownloadStore.getState().isEnabled('alice')).toBe(true);
    expect(useFavoritesAutoDownloadStore.getState().isEnabled('bob')).toBe(false);
  });

  it('records a seeded value of false, so an unset profile is not asked forever', () => {
    useFavoritesAutoDownloadStore.getState().seed('alice', false);
    expect(useFavoritesAutoDownloadStore.getState().hasSeeded('alice')).toBe(true);
    expect(useFavoritesAutoDownloadStore.getState().isEnabled('alice')).toBe(false);
  });
});
