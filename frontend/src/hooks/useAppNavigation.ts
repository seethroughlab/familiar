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
        'mood-grid': '/library/mood-grid',
        'ego-music-map': '/library/music-map',
        'umap-explorer': '/library/explorer',
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
   * Navigate to an artist's detail page
   */
  const navigateToArtist = useCallback(
    (artistName: string) => {
      navigate(`/library/artists/${encodeURIComponent(artistName)}`);
    },
    [navigate]
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
   * Navigate to album detail view
   */
  const navigateToAlbumDetail = useCallback(
    (artist: string, album: string) => {
      navigate(`/library/albums/${encodeURIComponent(artist)}/${encodeURIComponent(album)}`);
    },
    [navigate]
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
   * Navigate to a mood filter (energy/valence quadrant)
   */
  const navigateToMood = useCallback(
    (energyMin: number, energyMax: number, valenceMin: number, valenceMax: number) => {
      navigateToLibrary({
        browser: 'track-list',
        energyMin,
        energyMax,
        valenceMin,
        valenceMax,
      });
    },
    [navigateToLibrary]
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
   * Navigate to a specific playlist
   */
  const navigateToPlaylist = useCallback(
    (playlistId: string) => {
      navigate(`/playlists/${encodeURIComponent(playlistId)}`);
    },
    [navigate]
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
    navigateToAlbumDetail,
    navigateToYear,
    navigateToYearRange,
    navigateToMood,
    navigateToGenre,
    navigateToPlaylist,
    navigateToSmartPlaylist,
    navigateToFavorites,
    navigateToDownloads,
    updateParams,
    clearParams,
  };
}
