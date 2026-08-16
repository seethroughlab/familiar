/**
 * useAppNavigation - Centralized navigation hook for path-based routing.
 *
 * Provides typed navigation methods that use React Router paths.
 */

import { useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

export function useAppNavigation() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  /**
   * Navigate to a library browser view with optional filters
   */
  const navigateToLibrary = useCallback(
    (params: {
      browser?: string;
      search?: string;
      artist?: string;
      album?: string;
      genre?: string;
      yearFrom?: number;
      yearTo?: number;
      energyMin?: number;
      energyMax?: number;
      valenceMin?: number;
      valenceMax?: number;
      downloadedOnly?: boolean;
    }) => {
      // Map browser IDs to paths
      const browserMap: Record<string, string> = {
        'track-list': '/library/tracks',
        'artist-list': '/library/artists',
        'album-grid': '/library/albums',
        'vibe-map': '/library/music-map',
        'discover': '/library/discover',
        'proposed-changes': '/library/proposed-changes',
      };

      const path = params.browser ? (browserMap[params.browser] || '/library/tracks') : '/library/tracks';
      const filterParams = new URLSearchParams();

      if (params.search) filterParams.set('search', params.search);
      if (params.artist) filterParams.set('artist', params.artist);
      if (params.album) filterParams.set('album', params.album);
      if (params.genre) filterParams.set('genre', params.genre);
      if (params.yearFrom !== undefined) filterParams.set('yearFrom', String(params.yearFrom));
      if (params.yearTo !== undefined) filterParams.set('yearTo', String(params.yearTo));
      if (params.energyMin !== undefined) filterParams.set('energyMin', String(params.energyMin));
      if (params.energyMax !== undefined) filterParams.set('energyMax', String(params.energyMax));
      if (params.valenceMin !== undefined) filterParams.set('valenceMin', String(params.valenceMin));
      if (params.valenceMax !== undefined) filterParams.set('valenceMax', String(params.valenceMax));
      if (params.downloadedOnly) filterParams.set('downloadedOnly', 'true');

      const qs = filterParams.toString();
      navigate(path + (qs ? `?${qs}` : ''));
    },
    [navigate]
  );

  /**
   * Show one artist's tracks in the fallback player.
   *
   * A filter on the flat list, not a detail page. ADR-0057 point 3 makes `/library/tracks` a flat
   * searchable list and puts browsing on the native clients, so the artist *screen* is gone — but
   * "show me this artist" is still how you find something to play from a list of 26,000, and it
   * costs a query parameter rather than a route.
   */
  const navigateToArtist = useCallback(
    (artistName: string) => {
      navigateToLibrary({ browser: 'track-list', artist: artistName });
    },
    [navigateToLibrary]
  );

  /**
   * Navigate to an album (filtered track list)
   */
  const navigateToAlbum = useCallback(
    (artist: string, album: string) => {
      navigateToLibrary({
        browser: 'track-list',
        artist,
        album,
      });
    },
    [navigateToLibrary]
  );

  /**
   * Navigate to a year filter
   */
  const navigateToYear = useCallback(
    (year: number) => {
      navigateToLibrary({
        browser: 'track-list',
        yearFrom: year,
        yearTo: year,
      });
    },
    [navigateToLibrary]
  );

  /**
   * Navigate to a year range filter
   */
  const navigateToYearRange = useCallback(
    (from: number, to: number) => {
      navigateToLibrary({
        browser: 'track-list',
        yearFrom: from,
        yearTo: to,
      });
    },
    [navigateToLibrary]
  );

  /**
   * Navigate to a mood/feature filter.
   * For energy/valence axes, uses legacy params for backward compat.
   * For other axes, uses generic fx/fy params.
   */
  const navigateToMood = useCallback(
    (xAxis: string, xMin: number, xMax: number, yAxis: string, yMin: number, yMax: number) => {
      if (xAxis === 'valence' && yAxis === 'energy') {
        // Legacy energy/valence path
        navigateToLibrary({
          browser: 'track-list',
          energyMin: yMin,
          energyMax: yMax,
          valenceMin: xMin,
          valenceMax: xMax,
        });
      } else {
        // Generic feature axes
        const params = new URLSearchParams();
        params.set('fx', xAxis);
        params.set('fxMin', String(xMin));
        params.set('fxMax', String(xMax));
        params.set('fy', yAxis);
        params.set('fyMin', String(yMin));
        params.set('fyMax', String(yMax));
        navigate(`/library/tracks?${params.toString()}`);
      }
    },
    [navigateToLibrary, navigate]
  );

  /**
   * Navigate to a genre filter
   */
  const navigateToGenre = useCallback(
    (genre: string) => {
      navigateToLibrary({
        browser: 'track-list',
        genre,
      });
    },
    [navigateToLibrary]
  );


  /**
   * Navigate to a smart playlist
   */
  const navigateToSmartPlaylist = useCallback(
    (smartPlaylistId: string) => {
      navigate(`/smart-playlists/${encodeURIComponent(smartPlaylistId)}`);
    },
    [navigate]
  );

  /**
   * Navigate to favorites view
   */
  const navigateToFavorites = useCallback(() => {
    navigate('/favorites');
  }, [navigate]);

  /**
   * Navigate to downloads view
   */
  const navigateToDownloads = useCallback(() => {
    navigate('/downloads');
  }, [navigate]);

  /**
   * Update URL params without changing path
   */
  const updateParams = useCallback(
    (updates: Record<string, string | number | boolean | undefined | null>) => {
      const newParams = new URLSearchParams(searchParams);

      for (const [key, value] of Object.entries(updates)) {
        if (value === undefined || value === null || value === '') {
          newParams.delete(key);
        } else if (typeof value === 'boolean') {
          if (value) {
            newParams.set(key, 'true');
          } else {
            newParams.delete(key);
          }
        } else {
          newParams.set(key, String(value));
        }
      }

      const paramString = newParams.toString();
      navigate(paramString ? `?${paramString}` : '.', { replace: true });
    },
    [navigate, searchParams]
  );

  /**
   * Clear specific params from the URL
   */
  const clearParams = useCallback(
    (keys: string[]) => {
      const newParams = new URLSearchParams(searchParams);
      for (const key of keys) {
        newParams.delete(key);
      }

      const paramString = newParams.toString();
      navigate(paramString ? `?${paramString}` : '.', { replace: true });
    },
    [navigate, searchParams]
  );

  return {
    navigateToLibrary,
    navigateToArtist,
    navigateToAlbum,
    navigateToYear,
    navigateToYearRange,
    navigateToMood,
    navigateToGenre,
    navigateToSmartPlaylist,
    navigateToFavorites,
    navigateToDownloads,
    updateParams,
    clearParams,
  };
}
