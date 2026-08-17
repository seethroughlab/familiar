/**
 * Platform detection utilities.
 */

// Navigator with userAgentData (not in all TS types yet)
interface NavigatorWithUAData extends Navigator {
  userAgentData?: {
    platform?: string;
  };
}

/**
 * Check if the app is running on iOS (iPhone, iPad, iPod).
 */
export function isIOS(): boolean {
  if (typeof navigator === 'undefined') return false;

  const nav = navigator as NavigatorWithUAData;

  // Modern detection
  if (nav.userAgentData?.platform) {
    return nav.userAgentData.platform === 'iOS';
  }

  // Fallback to userAgent
  const ua = navigator.userAgent;
  return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

/**
 * Check if the app is running on mobile (iOS or Android).
 */
export function isMobile(): boolean {
  if (typeof navigator === 'undefined') return false;

  const ua = navigator.userAgent;
  return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua);
}

/**
 * Check if background downloads are supported.
 * Returns true for desktop browsers, false for iOS.
 */
export function supportsBackgroundDownloads(): boolean {
  // iOS Safari suspends a backgrounded tab's transfers. This was written about PWAs; it is just
  // as true of a plain tab, which is all there is since ADR-0059.
  return !isIOS();
}
