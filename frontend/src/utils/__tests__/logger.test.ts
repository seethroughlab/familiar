import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('logger', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  describe('createLogger', () => {
    it('should return an object with debug, info, warn, and error methods', async () => {
      const { createLogger } = await import('../logger');
      const log = createLogger('Methods');

      expect(typeof log.debug).toBe('function');
      expect(typeof log.info).toBe('function');
      expect(typeof log.warn).toBe('function');
      expect(typeof log.error).toBe('function');
    });

    it('should prefix messages with namespace tag', async () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { createLogger } = await import('../logger');
      const log = createLogger('TestNS');

      log.error('something broke');

      expect(spy).toHaveBeenCalledWith('[TestNS]', 'something broke');
    });

    it('should always log errors regardless of environment', async () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { createLogger } = await import('../logger');
      const log = createLogger('Err');

      log.error('critical', { code: 500 });

      expect(spy).toHaveBeenCalledWith('[Err]', 'critical', { code: 500 });
    });

    it('should pass multiple args through to console', async () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { createLogger } = await import('../logger');
      const log = createLogger('Multi');

      log.error('a', 'b', 'c', 123);

      expect(spy).toHaveBeenCalledWith('[Multi]', 'a', 'b', 'c', 123);
    });
  });

  describe('dev mode logging', () => {
    it('should call console.debug for debug in dev mode', async () => {
      const spy = vi.spyOn(console, 'debug').mockImplementation(() => {});
      const { createLogger } = await import('../logger');
      const log = createLogger('Dev');

      log.debug('debug msg');

      // In test environment, import.meta.env.DEV is true
      expect(spy).toHaveBeenCalledWith('[Dev]', 'debug msg');
    });

    it('should call console.log for info in dev mode', async () => {
      const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
      const { createLogger } = await import('../logger');
      const log = createLogger('Info');

      log.info('info msg');

      expect(spy).toHaveBeenCalledWith('[Info]', 'info msg');
    });

    it('should call console.warn for warn in dev mode', async () => {
      const spy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const { createLogger } = await import('../logger');
      const log = createLogger('Warn');

      log.warn('warning msg');

      expect(spy).toHaveBeenCalledWith('[Warn]', 'warning msg');
    });
  });

  describe('backwards-compatible exports', () => {
    it('should export logger as default and named export', async () => {
      const mod = await import('../logger');

      expect(mod.logger).toBeDefined();
      expect(mod.default).toBe(mod.logger);
    });

    it('should have error method on default logger', async () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const { logger } = await import('../logger');

      logger.error('test');

      expect(spy).toHaveBeenCalledWith('[app]', 'test');
    });
  });

  describe('prod mode gating', () => {
    it('should suppress debug/info/warn but keep error in prod mode', async () => {
      vi.stubEnv('DEV', false);

      const { createLogger } = await import('../logger');
      const log = createLogger('Prod');

      const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});
      const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      log.debug('hidden');
      log.info('hidden');
      log.warn('hidden');
      log.error('visible');

      expect(debugSpy).not.toHaveBeenCalled();
      expect(logSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
      expect(errorSpy).toHaveBeenCalledWith('[Prod]', 'visible');

      vi.unstubAllEnvs();
    });
  });

  describe('runtime debug toggle', () => {
    function stubLocalStorageDebug(value: string) {
      // The test setup replaces localStorage with a mock object;
      // override its getItem to return the desired debug flag.
      (localStorage.getItem as ReturnType<typeof vi.fn>).mockReturnValue(value);
    }

    it('should enable verbose logging in prod when namespace matches localStorage.debug', async () => {
      vi.stubEnv('DEV', false);
      stubLocalStorageDebug('AudioEngine');

      const { createLogger } = await import('../logger');
      const log = createLogger('AudioEngine');

      const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});
      log.debug('should appear');
      expect(debugSpy).toHaveBeenCalledWith('[AudioEngine]', 'should appear');

      vi.unstubAllEnvs();
    });

    it('should enable all namespaces with wildcard *', async () => {
      vi.stubEnv('DEV', false);
      stubLocalStorageDebug('*');

      const { createLogger } = await import('../logger');
      const log = createLogger('AnyNamespace');

      const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});
      log.debug('wildcard msg');
      expect(debugSpy).toHaveBeenCalledWith('[AnyNamespace]', 'wildcard msg');

      vi.unstubAllEnvs();
    });

    it('should stay suppressed when namespace does not match', async () => {
      vi.stubEnv('DEV', false);
      stubLocalStorageDebug('AudioEngine');

      const { createLogger } = await import('../logger');
      const log = createLogger('OtherModule');

      const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});
      log.debug('should not appear');
      expect(debugSpy).not.toHaveBeenCalled();

      vi.unstubAllEnvs();
    });

    it('should support comma-separated namespace list', async () => {
      vi.stubEnv('DEV', false);
      stubLocalStorageDebug('AudioEngine,app,PlayerStore');

      const { createLogger } = await import('../logger');
      const logAudio = createLogger('AudioEngine');
      const logApp = createLogger('app');
      const logOther = createLogger('SomethingElse');

      const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});

      logAudio.debug('audio msg');
      logApp.debug('app msg');
      logOther.debug('other msg');

      expect(debugSpy).toHaveBeenCalledWith('[AudioEngine]', 'audio msg');
      expect(debugSpy).toHaveBeenCalledWith('[app]', 'app msg');
      expect(debugSpy).not.toHaveBeenCalledWith('[SomethingElse]', 'other msg');

      vi.unstubAllEnvs();
    });
  });
});
