import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { lastfmApi } from '../api';
import { queryKeys } from '../api/queryKeys';
import { showSuccess, showError } from '../stores/toastStore';

/**
 * Handles Last.fm OAuth callback token from URL params.
 * After Last.fm auth, the user is redirected back with ?token=XXX.
 * This hook detects the token, exchanges it for a session, and cleans up the URL.
 * Must be mounted at AppShell level (always rendered), not inside the Settings modal.
 */
export function useLastfmCallback() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const handledRef = useRef(false);

  useEffect(() => {
    const token = searchParams.get('token');
    if (!token || handledRef.current) return;
    handledRef.current = true;

    lastfmApi.callback(token)
      .then((result) => {
        queryClient.invalidateQueries({ queryKey: queryKeys.lastfmStatus.all });
        showSuccess(`Connected to Last.fm as ${result.username}`);
      })
      .catch(() => {
        showError('Failed to connect Last.fm. Please try again.');
      })
      .finally(() => {
        searchParams.delete('token');
        setSearchParams(searchParams, { replace: true });
      });
  }, [searchParams, setSearchParams, queryClient]);
}
