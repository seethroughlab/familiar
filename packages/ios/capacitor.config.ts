import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.familiar.player',
  appName: 'Familiar',
  webDir: 'dist',
  ios: {
    path: 'native',
  },
  server: {
    // Use the default capacitor:// scheme on iOS
    iosScheme: 'capacitor',
    // Allow cleartext HTTP for LAN/Tailscale backend
    cleartext: true,
  },
  plugins: {
    CapacitorHttp: {
      // Route fetch() through native HTTP layer — bypasses CORS in WKWebView
      enabled: true,
    },
  },
  // Local plugins not in npm packages must be explicitly listed
  packageClassList: ['PreferencesPlugin', 'FamiliarAudioPlugin', 'FamiliarAmbientSynthPlugin'],
};

export default config;
