import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { getSelectedProfileId } from '../../services/profileService';
import { useHomeStore } from '../../stores/homeStore';
import { classifyRecentDestination } from './homeRouteRecents';

export function HomeRouteTracker() {
  const location = useLocation();
  const addRecentDestination = useHomeStore((state) => state.addRecentDestination);

  useEffect(() => {
    const destination = classifyRecentDestination(location.pathname);
    if (!destination) {
      return;
    }

    let cancelled = false;
    getSelectedProfileId()
      .then((profileId) => {
        if (!cancelled) {
          addRecentDestination(profileId, destination);
        }
      })
      .catch(() => {
        if (!cancelled) {
          addRecentDestination(null, destination);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [addRecentDestination, location.pathname]);

  return null;
}
