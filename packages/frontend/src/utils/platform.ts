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
 * Check if the app is running as a PWA (installed to home screen).
 */
export function isPWA(): boolean {
  if (typeof window === 'undefined') return false;

  // iOS PWA detection
  if ('standalone' in navigator && (navigator as Navigator & { standalone: boolean }).standalone) {
    return true;
  }

  // Android/Desktop PWA detection
  if (window.matchMedia('(display-mode: standalone)').matches) {
    return true;
  }

  return false;
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
 * Check if the app is running as a Capacitor native app.
 */
export function isNativeApp(): boolean {
  if (typeof window === 'undefined') return false;

  return !!(window as unknown as Record<string, unknown>).Capacitor &&
    (window as unknown as { Capacitor: { isNativePlatform?: () => boolean } })
      .Capacitor.isNativePlatform?.() === true;
}

/**
 * Check if background downloads are supported.
 * Returns true for desktop browsers, false for iOS.
 */
export function supportsBackgroundDownloads(): boolean {
  // iOS doesn't support background downloads in PWAs
  return !isIOS();
}
