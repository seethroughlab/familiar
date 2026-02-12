import { useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';

/**
 * Drop-in replacement for useSearchParams that preserves the URL hash.
 * React Router's setSearchParams() strips the hash fragment, which breaks
 * our hash-based tab routing (#library, #playlists, #settings, #queue).
 */
export function useHashSearchParams() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const setSearchParams = useCallback(
    (
      paramsOrUpdater:
        | URLSearchParams
        | Record<string, string>
        | ((prev: URLSearchParams) => URLSearchParams),
      options?: { replace?: boolean }
    ) => {
      const hash = window.location.hash || '#library';
      let next: URLSearchParams;
      if (typeof paramsOrUpdater === 'function') {
        next = paramsOrUpdater(new URLSearchParams(window.location.search));
      } else if (paramsOrUpdater instanceof URLSearchParams) {
        next = paramsOrUpdater;
      } else {
        next = new URLSearchParams(paramsOrUpdater);
      }
      const paramString = next.toString();
      const url = paramString ? `?${paramString}${hash}` : hash;
      navigate(url, { replace: options?.replace ?? false });
    },
    [navigate]
  );

  return [searchParams, setSearchParams] as const;
}
