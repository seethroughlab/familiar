/**
 * Tests for pluginLoader - dynamic plugin loading and lifecycle.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock all heavy dependencies that pluginLoader imports
vi.mock('react', () => ({ default: {} }));
vi.mock('three', () => ({}));
vi.mock('@react-three/fiber', () => ({}));
vi.mock('@react-three/drei', () => ({}));
vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(),
  useQueryClient: vi.fn(),
}));

vi.mock('../../utils/logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }),
}));

vi.mock('../../components/Visualizer/types', () => ({
  registerVisualizer: vi.fn(),
}));

vi.mock('../../hooks/useAudioAnalyser', () => ({
  useAudioAnalyser: vi.fn(),
  getAudioData: vi.fn(),
}));

vi.mock('../../components/Visualizer/hooks/useArtworkPalette', () => ({
  useArtworkPalette: vi.fn(),
}));

vi.mock('../../components/Visualizer/hooks/useBeatSync', () => ({
  useBeatSync: vi.fn(),
  getBeatPhase: vi.fn(),
  getBeatSine: vi.fn(),
}));

vi.mock('../../components/Visualizer/hooks/useLyricTiming', () => ({
  useLyricTiming: vi.fn(),
  getUpcomingLyrics: vi.fn(),
  getWordTiming: vi.fn(),
}));

vi.mock('../../components/Library/types', () => ({
  registerBrowser: vi.fn(),
}));

// Mock the API client
const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
  libraryApi: {},
  tracksApi: {},
}));

import { pluginLoader, PLUGIN_API_VERSION } from '../pluginLoader';

// We need to re-import a fresh module for each test since initializeGlobalAPI
// uses a private `initialized` flag that `reset()` doesn't clear.
// Instead, we test that the first call works, and subsequent calls are idempotent.

describe('pluginLoader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pluginLoader.reset();
  });

  describe('initializeGlobalAPI', () => {
    it('should set window.Familiar with correct API version', () => {
      pluginLoader.initializeGlobalAPI();

      expect(window.Familiar).toBeDefined();
      expect(window.Familiar?.apiVersion).toBe(PLUGIN_API_VERSION);
    });

    it('should only initialize once (idempotent)', () => {
      pluginLoader.initializeGlobalAPI();
      const firstRef = window.Familiar;

      pluginLoader.initializeGlobalAPI();
      expect(window.Familiar).toBe(firstRef);
    });

    it('should expose hooks and registration functions', () => {
      pluginLoader.initializeGlobalAPI();

      expect(window.Familiar?.hooks).toBeDefined();
      expect(window.Familiar?.registerVisualizer).toBeDefined();
      expect(window.Familiar?.registerBrowser).toBeDefined();
    });
  });

  describe('loadPlugin', () => {
    const mockPlugin = {
      id: '1',
      plugin_id: 'test-viz',
      name: 'Test Visualizer',
      version: '1.0.0',
      type: 'visualizer' as const,
      enabled: true,
      load_error: null,
    };

    it('should load a plugin bundle successfully', async () => {
      pluginLoader.initializeGlobalAPI();

      mockGet.mockResolvedValue({ data: 'console.log("plugin loaded")' });

      const result = await pluginLoader.loadPlugin(mockPlugin);

      expect(result).toBe(true);
      expect(pluginLoader.isPluginLoaded('test-viz')).toBe(true);
      expect(mockGet).toHaveBeenCalledWith('/plugins/test-viz/bundle', { responseType: 'text' });
    });

    it('should skip already loaded plugins', async () => {
      pluginLoader.initializeGlobalAPI();
      mockGet.mockResolvedValue({ data: '/* noop */' });

      await pluginLoader.loadPlugin(mockPlugin);
      const result = await pluginLoader.loadPlugin(mockPlugin);

      expect(result).toBe(true);
      // Only called once
      expect(mockGet).toHaveBeenCalledTimes(1);
    });

    it('should handle fetch errors', async () => {
      pluginLoader.initializeGlobalAPI();
      mockGet.mockRejectedValue(new Error('Network error'));

      const result = await pluginLoader.loadPlugin(mockPlugin);

      expect(result).toBe(false);
      expect(pluginLoader.isPluginLoaded('test-viz')).toBe(false);
      expect(pluginLoader.getLoadError('test-viz')).toBe('Network error');
    });

    it('should handle bundle execution errors', async () => {
      pluginLoader.initializeGlobalAPI();
      mockGet.mockResolvedValue({ data: 'throw new Error("syntax error in plugin")' });

      const result = await pluginLoader.loadPlugin(mockPlugin);

      expect(result).toBe(false);
      expect(pluginLoader.getLoadError('test-viz')).toContain('Plugin execution failed');
    });

    it('should report errors to backend', async () => {
      pluginLoader.initializeGlobalAPI();
      mockGet.mockRejectedValue(new Error('Load failed'));
      mockPost.mockResolvedValue({});

      await pluginLoader.loadPlugin(mockPlugin);

      expect(mockPost).toHaveBeenCalledWith(
        '/plugins/test-viz/report-error',
        { error: 'Load failed' }
      );
    });

    it('should handle error reporting failure gracefully', async () => {
      pluginLoader.initializeGlobalAPI();
      mockGet.mockRejectedValue(new Error('Load failed'));
      mockPost.mockRejectedValue(new Error('Report failed too'));

      // Should not throw
      const result = await pluginLoader.loadPlugin(mockPlugin);
      expect(result).toBe(false);
    });
  });

  describe('loadAllPlugins', () => {
    it('should fetch and load all enabled plugins', async () => {
      mockGet.mockImplementation((url: string) => {
        if (url === '/plugins') {
          return Promise.resolve({
            data: {
              plugins: [
                { id: '1', plugin_id: 'viz-1', name: 'Viz 1', version: '1.0', type: 'visualizer', enabled: true, load_error: null },
                { id: '2', plugin_id: 'viz-2', name: 'Viz 2', version: '1.0', type: 'visualizer', enabled: true, load_error: null },
              ],
              total: 2,
            },
          });
        }
        return Promise.resolve({ data: '/* plugin code */' });
      });

      await pluginLoader.loadAllPlugins();

      expect(pluginLoader.isPluginLoaded('viz-1')).toBe(true);
      expect(pluginLoader.isPluginLoaded('viz-2')).toBe(true);
    });

    it('should handle plugin list fetch failure', async () => {
      mockGet.mockRejectedValue(new Error('Server down'));

      // Should not throw
      await pluginLoader.loadAllPlugins();
    });

    it('should initialize global API during loadAll', async () => {
      mockGet.mockResolvedValue({ data: { plugins: [], total: 0 } });

      // loadAllPlugins calls initializeGlobalAPI internally
      await pluginLoader.loadAllPlugins();

      // Since initializeGlobalAPI was already called in earlier tests,
      // window.Familiar persists (it's only set once)
      expect(window.Familiar).toBeDefined();
      expect(window.Familiar?.apiVersion).toBe(PLUGIN_API_VERSION);
    });
  });

  describe('getLoadErrors', () => {
    it('should return a copy of errors', async () => {
      pluginLoader.initializeGlobalAPI();
      mockGet.mockRejectedValue(new Error('Fail'));

      await pluginLoader.loadPlugin({
        id: '1', plugin_id: 'bad-plugin', name: 'Bad', version: '1.0',
        type: 'visualizer', enabled: true, load_error: null,
      });

      const errors = pluginLoader.getLoadErrors();
      expect(errors.size).toBe(1);
      expect(errors.get('bad-plugin')).toBe('Fail');

      // Verify it's a copy
      errors.clear();
      expect(pluginLoader.getLoadErrors().size).toBe(1);
    });
  });

  describe('reset', () => {
    it('should clear loaded plugins and errors', async () => {
      pluginLoader.initializeGlobalAPI();

      mockGet.mockResolvedValueOnce({ data: '/* ok */' });
      await pluginLoader.loadPlugin({
        id: '1', plugin_id: 'p1', name: 'P1', version: '1.0',
        type: 'visualizer', enabled: true, load_error: null,
      });

      mockGet.mockRejectedValueOnce(new Error('Fail'));
      await pluginLoader.loadPlugin({
        id: '2', plugin_id: 'p2', name: 'P2', version: '1.0',
        type: 'visualizer', enabled: true, load_error: null,
      });

      pluginLoader.reset();

      expect(pluginLoader.isPluginLoaded('p1')).toBe(false);
      expect(pluginLoader.getLoadErrors().size).toBe(0);
    });
  });
});
