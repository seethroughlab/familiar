import { useState, useEffect } from 'react';
import { Download, X, Share, CheckCircle, Monitor, Smartphone } from 'lucide-react';

import { createLogger } from '../../utils/logger';
import { isNativeApp } from '../../utils/platform';

const log = createLogger('InstallPrompt');

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

type InstallState =
  | 'checking'
  | 'installed'
  | 'can-install'       // Chrome/Edge with beforeinstallprompt
  | 'ios-safari'        // iOS Safari - needs Add to Home Screen
  | 'macos-safari'      // macOS Safari - needs Add to Dock
  | 'needs-https'       // Chrome/Edge but not HTTPS
  | 'waiting'           // Chrome/Edge on HTTPS, waiting for beforeinstallprompt
  | 'unsupported';      // Firefox or other browsers

function detectInstallState(hasPromptEvent: boolean): InstallState {
  // Native Capacitor app is always "installed"
  if (isNativeApp()) {
    return 'installed';
  }

  // Check if already installed as PWA
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || (navigator as { standalone?: boolean }).standalone === true;

  if (isStandalone) {
    return 'installed';
  }

  // If we have the beforeinstallprompt event, we can install natively
  if (hasPromptEvent) {
    return 'can-install';
  }

  const ua = navigator.userAgent.toLowerCase();
  const isIOS = /iphone|ipad|ipod/.test(ua);
  const isMacOS = /macintosh/.test(ua) && navigator.maxTouchPoints === 0;
  const isSafari = /safari/.test(ua) && !/chrome|chromium|edg/.test(ua);
  const isChrome = /chrome|chromium/.test(ua) && !/edg/.test(ua);
  const isEdge = /edg/.test(ua);
  const isHTTPS = window.location.protocol === 'https:';
  const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';

  if (isIOS && isSafari) {
    return 'ios-safari';
  }

  if (isMacOS && isSafari) {
    return 'macos-safari';
  }

  // Chrome/Edge need HTTPS (except localhost) to show install prompt
  if ((isChrome || isEdge) && !isHTTPS && !isLocalhost) {
    return 'needs-https';
  }

  // Chrome/Edge on HTTPS - waiting for beforeinstallprompt event
  if ((isChrome || isEdge) && (isHTTPS || isLocalhost)) {
    return 'waiting';
  }

  // Firefox or other browsers that don't support PWA install
  return 'unsupported';
}

export function InstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installState, setInstallState] = useState<InstallState>('checking');
  const [showPrompt, setShowPrompt] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [installing, setInstalling] = useState(false);

  useEffect(() => {
    // Check if already dismissed this session
    const wasDismissed = sessionStorage.getItem('pwa-prompt-dismissed');
    if (wasDismissed) {
      setDismissed(true);
    }

    // Check initial state without prompt event
    setInstallState(detectInstallState(false));

    const handleBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
      setInstallState('can-install');
    };

    // Listen for app installed event
    const handleAppInstalled = () => {
      setInstallState('installed');
      setShowPrompt(false);
    };

    window.addEventListener('beforeinstallprompt', handleBeforeInstall);
    window.addEventListener('appinstalled', handleAppInstalled);

    // Show prompt after delay (unless already installed)
    const timer = setTimeout(() => {
      setShowPrompt(true);
    }, 3000);

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstall);
      window.removeEventListener('appinstalled', handleAppInstalled);
      clearTimeout(timer);
    };
  }, []);

  const handleInstall = async () => {
    if (!deferredPrompt) return;

    setInstalling(true);
    try {
      await deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;

      if (outcome === 'accepted') {
        setInstallState('installed');
        setShowPrompt(false);
      }
    } catch (err) {
      log.error('Install error:', err);
    } finally {
      setInstalling(false);
      setDeferredPrompt(null);
    }
  };

  const handleDismiss = () => {
    setShowPrompt(false);
    setDismissed(true);
    sessionStorage.setItem('pwa-prompt-dismissed', 'true');
  };

  // Don't show if checking, dismissed, already installed, or waiting for Chrome prompt
  if (!showPrompt || dismissed || installState === 'checking' || installState === 'installed' || installState === 'waiting') {
    return null;
  }

  return (
    <div className="fixed bottom-24 left-4 right-4 md:left-auto md:right-4 md:w-96 z-50 animate-slide-up mb-safe">
      <div className="bg-zinc-800 border border-zinc-700 rounded-xl shadow-xl p-4">
        <div className="flex items-start gap-3">
          <div className={`p-2 rounded-lg shrink-0 ${
            installState === 'can-install'
              ? 'bg-green-500/20'
              : 'bg-blue-500/20'
          }`}>
            {installState === 'can-install' ? (
              <Download className="w-5 h-5 text-green-500" />
            ) : installState === 'ios-safari' ? (
              <Smartphone className="w-5 h-5 text-blue-400" />
            ) : (
              <Monitor className="w-5 h-5 text-blue-400" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-medium text-white text-sm">Install Familiar</h3>
            <InstallInstructions state={installState} />
          </div>
          <button
            onClick={handleDismiss}
            className="p-1 hover:bg-zinc-700 rounded-md transition-colors"
          >
            <X className="w-4 h-4 text-zinc-400" />
          </button>
        </div>

        <div className="flex gap-2 mt-3">
          {installState === 'can-install' ? (
            <>
              <button
                onClick={handleInstall}
                disabled={installing}
                className="flex-1 py-2 px-3 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {installing ? 'Installing...' : 'Install'}
              </button>
              <button
                onClick={handleDismiss}
                className="py-2 px-3 bg-zinc-700 hover:bg-zinc-600 text-white text-sm rounded-lg transition-colors"
              >
                Not now
              </button>
            </>
          ) : (
            <button
              onClick={handleDismiss}
              className="flex-1 py-2 px-3 bg-zinc-700 hover:bg-zinc-600 text-white text-sm rounded-lg transition-colors"
            >
              Got it
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function InstallInstructions({ state }: { state: InstallState }) {
  switch (state) {
    case 'can-install':
      return (
        <p className="text-xs text-zinc-400 mt-1">
          Add to your home screen for the best experience
        </p>
      );

    case 'ios-safari':
      return (
        <div className="text-xs text-zinc-400 mt-1 space-y-1">
          <p>To install on your device:</p>
          <ol className="list-decimal list-inside space-y-0.5 text-zinc-300">
            <li>Tap the <Share className="w-3 h-3 inline mx-0.5" /> Share button</li>
            <li>Scroll and tap <span className="text-white">"Add to Home Screen"</span></li>
          </ol>
        </div>
      );

    case 'macos-safari':
      return (
        <div className="text-xs text-zinc-400 mt-1 space-y-1">
          <p>To install on your Mac:</p>
          <ol className="list-decimal list-inside space-y-0.5 text-zinc-300">
            <li>Click <span className="text-white">File</span> in the menu bar</li>
            <li>Click <span className="text-white">"Add to Dock"</span></li>
          </ol>
        </div>
      );

    case 'needs-https':
      return (
        <div className="text-xs text-zinc-400 mt-1">
          <p>PWA installation requires HTTPS.</p>
          <p className="mt-1">Access via HTTPS or set up a reverse proxy with SSL.</p>
        </div>
      );

    case 'unsupported':
      return (
        <div className="text-xs text-zinc-400 mt-1">
          <p>Your browser doesn't support app installation.</p>
          <p className="mt-1">Try using Chrome, Edge, or Safari for the best experience.</p>
        </div>
      );

    default:
      return null;
  }
}

// Separate component for Settings page to show install status
export function InstallStatus() {
  const [installState, setInstallState] = useState<InstallState>('checking');
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installing, setInstalling] = useState(false);

  useEffect(() => {
    setInstallState(detectInstallState(false));

    const handleBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
      setInstallState('can-install');
    };

    const handleAppInstalled = () => {
      setInstallState('installed');
    };

    window.addEventListener('beforeinstallprompt', handleBeforeInstall);
    window.addEventListener('appinstalled', handleAppInstalled);

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstall);
      window.removeEventListener('appinstalled', handleAppInstalled);
    };
  }, []);

  const handleInstall = async () => {
    if (!deferredPrompt) return;

    setInstalling(true);
    try {
      await deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      if (outcome === 'accepted') {
        setInstallState('installed');
      }
    } catch (err) {
      log.error('Install error:', err);
    } finally {
      setInstalling(false);
      setDeferredPrompt(null);
    }
  };

  if (installState === 'checking') {
    return null;
  }

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <Download className="w-5 h-5 text-blue-400" />
        <h4 className="font-medium text-white">App Installation</h4>
      </div>

      {installState === 'installed' ? (
        <div className="flex items-center gap-2 text-green-400">
          <CheckCircle className="w-4 h-4" />
          <span className="text-sm">Familiar is installed</span>
        </div>
      ) : installState === 'can-install' ? (
        <div className="space-y-3">
          <p className="text-sm text-zinc-400">
            Install Familiar as an app for quick access and offline use.
          </p>
          <button
            onClick={handleInstall}
            disabled={installing}
            className="w-full py-2 px-3 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {installing ? 'Installing...' : 'Install App'}
          </button>
        </div>
      ) : installState === 'ios-safari' ? (
        <div className="space-y-2">
          <p className="text-sm text-zinc-400">To install on your device:</p>
          <ol className="list-decimal list-inside space-y-1 text-sm text-zinc-300">
            <li>Tap the <Share className="w-3 h-3 inline mx-0.5" /> Share button in Safari</li>
            <li>Scroll down and tap <span className="text-white">"Add to Home Screen"</span></li>
            <li>Tap <span className="text-white">"Add"</span> to confirm</li>
          </ol>
        </div>
      ) : installState === 'macos-safari' ? (
        <div className="space-y-2">
          <p className="text-sm text-zinc-400">To install on your Mac:</p>
          <ol className="list-decimal list-inside space-y-1 text-sm text-zinc-300">
            <li>Click <span className="text-white">File</span> in the menu bar</li>
            <li>Click <span className="text-white">"Add to Dock"</span></li>
          </ol>
        </div>
      ) : installState === 'needs-https' ? (
        <div className="space-y-2">
          <p className="text-sm text-zinc-400">
            PWA installation requires HTTPS.
          </p>
          <p className="text-sm text-zinc-500">
            To install as an app, access Familiar via HTTPS. You can set up a reverse proxy
            (like Caddy or nginx) with SSL, or use a service like Tailscale for automatic HTTPS.
          </p>
        </div>
      ) : installState === 'waiting' ? (
        <div className="space-y-2">
          <p className="text-sm text-zinc-400">
            Ready to install. Look for the install icon in your browser's address bar,
            or use the browser menu to install Familiar as an app.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-sm text-zinc-400">
            Your browser doesn't support app installation.
          </p>
          <p className="text-sm text-zinc-500">
            Try using Chrome, Edge, or Safari for the full PWA experience.
          </p>
        </div>
      )}
    </div>
  );
}
