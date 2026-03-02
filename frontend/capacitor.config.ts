import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.familiar.player',
  appName: 'Familiar',
  webDir: 'dist',
  server: {
    // Use the default capacitor:// scheme on iOS
    iosScheme: 'capacitor',
    // Allow cleartext HTTP for LAN/Tailscale backend
    cleartext: true,
  },
};

export default config;
