/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { getHomePreferences, getRecentDestinations, useHomeStore } from '../homeStore';

describe('homeStore', () => {
  beforeEach(() => {
    localStorage.clear();
    useHomeStore.setState({
      recentDestinationsByProfile: {},
      preferencesByProfile: {},
    });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('deduplicates recent destinations by route and keeps newest first', () => {
    const { addRecentDestination } = useHomeStore.getState();

    addRecentDestination('profile-a', {
      route: '/favorites',
      label: 'Favorites',
      type: 'favorites',
      timestamp: 100,
    });
    addRecentDestination('profile-a', {
      route: '/downloads',
      label: 'Downloads',
      type: 'downloads',
      timestamp: 200,
    });
    addRecentDestination('profile-a', {
      route: '/favorites',
      label: 'Favorites',
      type: 'favorites',
      timestamp: 300,
    });

    expect(getRecentDestinations('profile-a', useHomeStore.getState().recentDestinationsByProfile)).toEqual([
      {
        route: '/favorites',
        label: 'Favorites',
        type: 'favorites',
        timestamp: 300,
      },
      {
        route: '/downloads',
        label: 'Downloads',
        type: 'downloads',
        timestamp: 200,
      },
    ]);
  });

  it('maintains independent preferences per profile and restores defaults on reset', () => {
    const { setModuleEnabled, moveModule, resetPreferences } = useHomeStore.getState();

    setModuleEnabled('profile-a', 'prompts', false);
    moveModule('profile-a', 'discovery', 'up');

    const profileAPreferences = getHomePreferences(
      'profile-a',
      useHomeStore.getState().preferencesByProfile
    );
    expect(profileAPreferences.enabled.prompts).toBe(false);
    expect(profileAPreferences.order).toEqual([
      'resume',
      'prompts',
      'discovery',
      'quick-picks',
      'library-shortcuts',
    ]);

    resetPreferences('profile-a');
    expect(
      getHomePreferences('profile-a', useHomeStore.getState().preferencesByProfile)
    ).toEqual({
      order: ['resume', 'prompts', 'quick-picks', 'discovery', 'library-shortcuts'],
      enabled: {
        resume: true,
        prompts: true,
        'quick-picks': true,
        discovery: true,
        'library-shortcuts': true,
      },
    });
  });

  it('keeps at least one module enabled', () => {
    const { setModuleEnabled } = useHomeStore.getState();

    setModuleEnabled('profile-a', 'resume', false);
    setModuleEnabled('profile-a', 'prompts', false);
    setModuleEnabled('profile-a', 'quick-picks', false);
    setModuleEnabled('profile-a', 'discovery', false);
    setModuleEnabled('profile-a', 'library-shortcuts', false);

    const preferences = getHomePreferences(
      'profile-a',
      useHomeStore.getState().preferencesByProfile
    );
    expect(Object.values(preferences.enabled).some(Boolean)).toBe(true);
    expect(preferences.enabled.resume).toBe(true);
  });
});
