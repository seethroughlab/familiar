/* @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { classifyRecentDestination } from '../homeRouteRecents';

describe('classifyRecentDestination', () => {
  it('ignores home and unsupported routes', () => {
    expect(classifyRecentDestination('/home')).toBeNull();
    expect(classifyRecentDestination('/unknown')).toBeNull();
  });

  it('classifies supported browser and collection routes', () => {
    expect(classifyRecentDestination('/library/tracks')).toEqual({
      route: '/library/tracks',
      label: 'Tracks',
      type: 'browser',
    });
    expect(classifyRecentDestination('/favorites')).toEqual({
      route: '/favorites',
      label: 'Favorites',
      type: 'favorites',
    });
  });

  it('extracts detail labels from artist and album routes', () => {
    expect(classifyRecentDestination('/library/artists/Brian%20Eno')).toEqual({
      route: '/library/artists/Brian%20Eno',
      label: 'Brian Eno',
      subtitle: 'Artist',
      type: 'artist',
    });
    expect(
      classifyRecentDestination('/library/albums/Cocteau%20Twins/Heaven%20or%20Las%20Vegas')
    ).toEqual({
      route: '/library/albums/Cocteau%20Twins/Heaven%20or%20Las%20Vegas',
      label: 'Heaven or Las Vegas',
      subtitle: 'Cocteau Twins',
      type: 'album',
    });
  });
});
