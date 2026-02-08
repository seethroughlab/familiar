/**
 * Plugin Loader Service
 *
 * Handles loading external plugins (visualizers and library browsers) from
 * pre-built JavaScript bundles. Exposes a global `window.Familiar` API that
 * plugins use to access React, Three.js, hooks, and registration functions.
 */

import React from 'react';
import * as THREE from 'three';
import * as ReactThreeFiber from '@react-three/fiber';
import * as Drei from '@react-three/drei';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createLogger } from '../utils/logger';

const log = createLogger('PluginLoader');

// Visualizer API
import { registerVisualizer } from '../components/Visualizer/types';

// Visualizer hooks
import {
  useAudioAnalyser,
  getAudioData,
} from '../hooks/useAudioAnalyser';
import {
  useArtworkPalette,
} from '../components/Visualizer/hooks/useArtworkPalette';
import {
  useBeatSync,
  getBeatPhase,
  getBeatSine,
} from '../components/Visualizer/hooks/useBeatSync';
import {
  useLyricTiming,
  getUpcomingLyrics,
  getWordTiming,
} from '../components/Visualizer/hooks/useLyricTiming';

// Browser API
import { registerBrowser } from '../components/Library/types';

// API client
import api, { libraryApi, tracksApi } from '../api/client';

/**
 * Current plugin API version.
 * Increment when making breaking changes to the plugin API.
 */
export const PLUGIN_API_VERSION = 1;

/**
 * Type declaration for the global Familiar API exposed to plugins.
 */
export interface FamiliarPluginAPI {
  // Core React
  React: typeof React;

  // Three.js ecosystem (for 3D visualizers)
  THREE: typeof THREE;
  ReactThreeFiber: typeof ReactThreeFiber;
  Drei: typeof Drei;

  // Visualizer registration
  registerVisualizer: typeof registerVisualizer;

  // Browser registration
  registerBrowser: typeof registerBrowser;

  // Visualizer hooks
  hooks: {
    useAudioAnalyser: typeof useAudioAnalyser;
    getAudioData: typeof getAudioData;
    useArtworkPalette: typeof useArtworkPalette;
    useBeatSync: typeof useBeatSync;
    getBeatPhase: typeof getBeatPhase;
    getBeatSine: typeof getBeatSine;
    useLyricTiming: typeof useLyricTiming;
    getUpcomingLyrics: typeof getUpcomingLyrics;
    getWordTiming: typeof getWordTiming;
  };

  // React Query (for browser plugins)
  useQuery: typeof useQuery;
  useQueryClient: typeof useQueryClient;

  // API client (for browser plugins)
  api: {
    library: typeof libraryApi;
    tracks: typeof tracksApi;
  };

  // Version info
  version: string;
  apiVersion: number;
}

// Extend Window type to include Familiar
declare global {
  interface Window {
    Familiar?: FamiliarPluginAPI;
  }
}

/**
 * Plugin info from the backend.
 */
interface PluginInfo {
  id: string;
  plugin_id: string;
  name: string;
  version: string;
  type: 'visualizer' | 'browser';
  enabled: boolean;
  load_error: string | null;
}

/**
 * Plugin loader service.
 */
class PluginLoaderService {
  private loadedPlugins: Set<string> = new Set();
  private loadErrors: Map<string, string> = new Map();
  private initialized = false;

  /**
   * Initialize the global Familiar API.
   * Must be called before loading any plugins.
   */
  initializeGlobalAPI(): void {
    if (this.initialized) {
      return;
    }

    // Get app version from meta tag or default
    const appVersion = document.querySelector('meta[name="app-version"]')?.getAttribute('content') || '1.0.0';

    window.Familiar = {
      // Core React
      React,

      // Three.js ecosystem
      THREE,
      ReactThreeFiber,
      Drei,

      // Registration functions
      registerVisualizer,
      registerBrowser,

      // Hooks
      hooks: {
        useAudioAnalyser,
        getAudioData,
        useArtworkPalette,
        useBeatSync,
        getBeatPhase,
        getBeatSine,
        useLyricTiming,
        getUpcomingLyrics,
        getWordTiming,
      },

      // React Query (for browser plugins)
      useQuery,
      useQueryClient,

      // API client (for browser plugins)
      api: {
        library: libraryApi,
        tracks: tracksApi,
      },

      // Version info
      version: appVersion,
      apiVersion: PLUGIN_API_VERSION,
    };

    this.initialized = true;
    log.info('Global Familiar API initialized');
  }

  /**
   * Load all enabled plugins from the backend.
   */
  async loadAllPlugins(): Promise<void> {
    if (!this.initialized) {
      this.initializeGlobalAPI();
    }

    try {
      const response = await api.get<{ plugins: PluginInfo[]; total: number }>(
        '/plugins',
        { params: { enabled_only: true } }
      );

      const plugins = response.data.plugins;
      log.info(`Loading ${plugins.length} plugin(s)`);

      for (const plugin of plugins) {
        await this.loadPlugin(plugin);
      }
    } catch (error) {
      log.warn('Failed to fetch plugins:', error);
    }
  }

  /**
   * Load a single plugin by fetching and executing its bundle.
   */
  async loadPlugin(plugin: PluginInfo): Promise<boolean> {
    const pluginId = plugin.plugin_id;

    // Skip if already loaded
    if (this.loadedPlugins.has(pluginId)) {
      log.info(`Plugin ${pluginId} already loaded`);
      return true;
    }

    try {
      log.info(`Loading plugin: ${plugin.name} (${pluginId})`);

      // Fetch bundle from backend
      const response = await api.get<string>(
        `/plugins/${pluginId}/bundle`,
        { responseType: 'text' }
      );

      const bundleCode = response.data;

      // Execute the bundle in a try-catch
      try {
        // Use Function constructor for slightly better isolation than eval
        // The bundle is an IIFE that accesses window.Familiar
        const executeBundle = new Function(bundleCode);
        executeBundle();

        this.loadedPlugins.add(pluginId);
        this.loadErrors.delete(pluginId);

        log.info(`Successfully loaded plugin: ${plugin.name}`);
        return true;
      } catch (execError) {
        const errorMessage = execError instanceof Error ? execError.message : String(execError);
        throw new Error(`Plugin execution failed: ${errorMessage}`);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      log.error(`Failed to load plugin ${pluginId}:`, errorMessage);

      this.loadErrors.set(pluginId, errorMessage);

      // Report error to backend
      try {
        await api.post(`/plugins/${pluginId}/report-error`, {
          error: errorMessage,
        });
      } catch {
        // Ignore reporting errors
      }

      return false;
    }
  }

  /**
   * Check if a plugin is loaded.
   */
  isPluginLoaded(pluginId: string): boolean {
    return this.loadedPlugins.has(pluginId);
  }

  /**
   * Get all load errors.
   */
  getLoadErrors(): Map<string, string> {
    return new Map(this.loadErrors);
  }

  /**
   * Get error for a specific plugin.
   */
  getLoadError(pluginId: string): string | undefined {
    return this.loadErrors.get(pluginId);
  }

  /**
   * Clear loaded plugins (for testing or refresh).
   */
  reset(): void {
    this.loadedPlugins.clear();
    this.loadErrors.clear();
    // Note: We don't reset the global API or unregister plugins
    // because the registries don't support removal
  }
}

/**
 * Singleton plugin loader instance.
 */
export const pluginLoader = new PluginLoaderService();
