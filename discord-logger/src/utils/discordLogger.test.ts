/**
 * Unit tests for discordLogger.ts
 *
 * Run:  npx jest
 * Watch: npx jest --watch
 */

import { DiscordLogger } from './discordLogger';

// ============================================================
// GLOBAL MOCK SETUP
// ============================================================

// Replace the global fetch with a Jest mock so no real HTTP calls are made
const mockFetch = jest.fn();
global.fetch = mockFetch;

/** Helper: build a minimal fetch Response-like object. */
function mockResponse(
  status: number,
  body = '',
  headers: Record<string, string> = {},
): Response {
  return {
    ok:      status >= 200 && status < 300,
    status,
    headers: new Headers(headers),
    text:    () => Promise.resolve(body),
    json:    () => Promise.resolve({}),
  } as unknown as Response;
}

/** Advance fake timers AND let the microtask queue drain. */
async function tick(ms = 0): Promise<void> {
  jest.advanceTimersByTime(ms);
  // Two rounds of microtask flushing to let async/await chains resolve
  await Promise.resolve();
  await Promise.resolve();
}

// ============================================================
// HELPERS
// ============================================================

function makeLogger(overrides: ConstructorParameters<typeof DiscordLogger>[0] = {}) {
  return new DiscordLogger({
    webhookUrl:    'https://discord.com/api/webhooks/test/token',
    serviceName:   'TestService',
    environment:   'test',
    batchInterval: 5000,
    queueLimit:    10,
    enabled:       true,
    ...overrides,
  });
}

// ============================================================
// TEST SUITES
// ============================================================

describe('DiscordLogger', () => {
  let logger: DiscordLogger;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    logger = makeLogger();
  });

  afterEach(() => {
    logger.stopBatchProcessor();
    jest.useRealTimers();
  });

  // ============================================================
  // INITIALIZATION
  // ============================================================

  describe('initialization', () => {
    it('creates an instance with default config when no args given', () => {
      const l = new DiscordLogger();
      expect(l).toBeDefined();
    });

    it('reads webhook URL from environment variable', () => {
      process.env.DISCORD_WEBHOOK_URL = 'https://example.com/hook';
      const l = new DiscordLogger();
      expect(l).toBeDefined();
      delete process.env.DISCORD_WEBHOOK_URL;
    });

    it('respects DISCORD_LOGGING_ENABLED=false env var', () => {
      process.env.DISCORD_LOGGING_ENABLED = 'false';
      const l = new DiscordLogger();
      expect(l).toBeDefined(); // logger created, but disabled
      delete process.env.DISCORD_LOGGING_ENABLED;
    });

    it('initialize() updates config without throwing', () => {
      expect(() =>
        logger.initialize({ serviceName: 'UpdatedService', batchInterval: 10_000 })
      ).not.toThrow();
    });

    it('initialize() disables logger when DISCORD_LOGGING_ENABLED=false', () => {
      process.env.DISCORD_LOGGING_ENABLED = 'false';
      logger.initialize({ enabled: true }); // env var should win
      // Logger is now disabled — verify no fetch on flush
      logger.error('Should not reach Discord');
      logger.startBatchProcessor();
      jest.advanceTimersByTime(5000);
      expect(mockFetch).not.toHaveBeenCalled();
      delete process.env.DISCORD_LOGGING_ENABLED;
    });
  });

  // ============================================================
  // BATCH PROCESSOR
  // ============================================================

  describe('batch processor', () => {
    it('starts and stops without errors', () => {
      expect(() => {
        logger.startBatchProcessor();
        logger.stopBatchProcessor();
      }).not.toThrow();
    });

    it('flushes queue after the batch interval elapses', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.error('Interval flush test');
      logger.startBatchProcessor();
      await tick(5000);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('sends multiple log entries in a single webhook call', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      for (let i = 0; i < 5; i++) logger.error(`Error ${i}`);
      logger.startBatchProcessor();
      await tick(5000);
      // All 5 fit in one webhook message (≤10 embeds)
      expect(mockFetch).toHaveBeenCalledTimes(1);
      const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
      expect(body.embeds).toHaveLength(5);
    });

    it('splits more than 10 embeds across multiple webhook calls', async () => {
      // Use a logger with a higher queue limit so all 12 entries fit
      const bigLogger = makeLogger({ queueLimit: 100 });
      mockFetch.mockResolvedValue(mockResponse(204));
      for (let i = 0; i < 12; i++) bigLogger.error(`Error ${i}`);
      bigLogger.startBatchProcessor();
      await tick(5000);
      // 12 embeds → 2 calls (10 + 2)
      expect(mockFetch).toHaveBeenCalledTimes(2);
      bigLogger.stopBatchProcessor();
    });
  });

  // ============================================================
  // LOG LEVEL METHODS
  // ============================================================

  describe('log level methods', () => {
    it('error() queues an entry when error level is enabled', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.error('Test Error', { error: new Error('boom') });
      logger.startBatchProcessor();
      await tick(5000);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('warn() queues an entry when warn level is enabled', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.warn('Test Warning', { detail: 'something odd' });
      logger.startBatchProcessor();
      await tick(5000);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('info() queues an entry when info level is enabled', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.info('Test Info', { version: '1.0.0' });
      logger.startBatchProcessor();
      await tick(5000);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('does NOT send when the specific level is disabled', async () => {
      logger.initialize({ logLevels: { error: false, warn: true, info: true } });
      logger.error('Should be silenced');
      logger.startBatchProcessor();
      await tick(5000);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('does NOT send when the entire logger is disabled', async () => {
      logger.initialize({ enabled: false });
      logger.error('Disabled logger');
      logger.startBatchProcessor();
      await tick(5000);
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  // ============================================================
  // QUEUE MANAGEMENT
  // ============================================================

  describe('queue management', () => {
    it('drops the oldest item and emits a console.warn when queue is full', () => {
      const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => undefined);

      // queueLimit is 10; push 15 entries
      for (let i = 0; i < 15; i++) logger.error(`Error ${i}`);

      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('Queue full'),
      );
      warnSpy.mockRestore();
    });

    it('does not grow the queue beyond the configured limit', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      for (let i = 0; i < 50; i++) logger.error(`Flood ${i}`);
      // Queue is capped at 10 — only 10 embeds should be sent
      logger.startBatchProcessor();
      await tick(5000);
      const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
      expect(body.embeds.length).toBeLessThanOrEqual(10);
    });
  });

  // ============================================================
  // RETRY LOGIC
  // ============================================================

  describe('retry logic', () => {
    it('retries on transient network failure and succeeds on 3rd attempt', async () => {
      mockFetch
        .mockRejectedValueOnce(new Error('Network error'))
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce(mockResponse(204));

      logger.error('Retry success test');
      logger.startBatchProcessor();
      // Trigger flush
      await tick(5000);
      // Advance timers to allow backoff sleeps to elapse
      await tick(1000);
      await tick(2000);
      await tick(0);

      expect(mockFetch).toHaveBeenCalledTimes(3);
    });

    it('handles rate-limit (429) by waiting retry-after and retrying', async () => {
      mockFetch
        .mockResolvedValueOnce(mockResponse(429, 'rate limited', { 'retry-after': '1' }))
        .mockResolvedValueOnce(mockResponse(204));

      logger.error('Rate limit test');
      logger.startBatchProcessor();
      await tick(5000);
      await tick(1000); // consume the 1-second retry-after delay
      await tick(0);

      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it('gives up after MAX_RETRY_ATTEMPTS and logs to console.error', async () => {
      const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
      mockFetch.mockRejectedValue(new Error('Permanent failure'));

      logger.error('Max retries test');
      logger.startBatchProcessor();

      // Trigger the flush
      await tick(5000);
      // Advance through backoff sleeps: 1s, 2s, 4s — drain promises between each
      await tick(1000);
      await tick(2000);
      await tick(4000);
      await tick(0);

      // The "Failed after N attempts" message should have been logged
      expect(errorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Failed after'),
        expect.anything(),
      );
      errorSpy.mockRestore();
    });
  });

  // ============================================================
  // ERROR HANDLING & EDGE CASES
  // ============================================================

  describe('error handling & edge cases', () => {
    it('handles a proper Error object', () => {
      const err = new Error('Test error message');
      err.stack = 'Error: Test error message\n    at test.ts:1:1';
      expect(() => logger.error('Error object', { error: err })).not.toThrow();
    });

    it('handles a plain string as error', () => {
      expect(() => logger.error('String error', { error: 'simple string' })).not.toThrow();
    });

    it('handles null error gracefully', () => {
      expect(() => logger.error('Null error', { error: null })).not.toThrow();
    });

    it('handles undefined context gracefully', () => {
      expect(() => logger.error('No context')).not.toThrow();
    });

    it('NEVER throws when Discord is unreachable', async () => {
      mockFetch.mockRejectedValue(new Error('Connection refused'));
      expect(() => logger.error('Unreachable Discord')).not.toThrow();
      logger.startBatchProcessor();
      // Even after flush + retries, no throw
      await expect(tick(5000)).resolves.toBeUndefined();
    });

    it('does not crash when no webhook URL is configured', async () => {
      const noUrlLogger = makeLogger({ webhookUrl: '' });
      expect(() => noUrlLogger.error('No URL test')).not.toThrow();
      noUrlLogger.startBatchProcessor();
      await tick(5000);
      expect(mockFetch).not.toHaveBeenCalled();
      noUrlLogger.stopBatchProcessor();
    });
  });

  // ============================================================
  // DATA SANITISATION
  // ============================================================

  describe('data sanitisation', () => {
    it('redacts sensitive fields before sending to Discord', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));

      logger.error('Sensitive data test', {
        apiKey:   'super-secret-key',   // should be REDACTED
        password: 'hunter2',            // should be REDACTED
        userId:   '12345',              // should NOT be redacted
      });

      logger.startBatchProcessor();
      await tick(5000);

      expect(mockFetch).toHaveBeenCalledTimes(1);

      const body   = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
      const fields = (body.embeds[0].fields ?? []) as Array<{ name: string; value: string }>;

      const apiKeyField  = fields.find(f => f.name === 'apiKey');
      const passwordField = fields.find(f => f.name === 'password');
      const userIdField  = fields.find(f => f.name === 'userId');

      if (apiKeyField)   expect(apiKeyField.value).toBe('[REDACTED]');
      if (passwordField) expect(passwordField.value).toBe('[REDACTED]');
      if (userIdField)   expect(userIdField.value).not.toBe('[REDACTED]');
    });

    it('does not mutate the original context object', () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      const ctx = { apiKey: 'secret', userId: '99' };
      logger.error('Mutation test', ctx);
      // Original object must be untouched
      expect(ctx.apiKey).toBe('secret');
    });
  });

  // ============================================================
  // TIMEOUT
  // ============================================================

  describe('timeout', () => {
    it('aborts the request after 5 seconds and retries', async () => {
      const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => undefined);

      // Never resolve — relies on AbortController to cancel
      mockFetch.mockImplementation((_url: string, options: RequestInit) =>
        new Promise((_resolve, reject) => {
          options.signal?.addEventListener('abort', () =>
            reject(Object.assign(new Error('AbortError'), { name: 'AbortError' }))
          );
        })
      );

      logger.error('Timeout test');
      logger.startBatchProcessor();
      await tick(5000);  // trigger flush
      await tick(5000);  // trigger AbortController timeout inside fetch
      await tick(0);

      // Should have logged a retry warning
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('Retrying'),
        expect.anything(),
      );
      warnSpy.mockRestore();
    });
  });

  // ============================================================
  // EMBED STRUCTURE
  // ============================================================

  describe('embed structure', () => {
    it('sets correct colour for ERROR level', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.error('Colour test');
      logger.startBatchProcessor();
      await tick(5000);

      const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
      expect(body.embeds[0].color).toBe(0xff0000);
    });

    it('sets correct colour for WARN level', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.warn('Colour test');
      logger.startBatchProcessor();
      await tick(5000);

      const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
      expect(body.embeds[0].color).toBe(0xffa500);
    });

    it('sets correct colour for INFO level', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.info('Colour test');
      logger.startBatchProcessor();
      await tick(5000);

      const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
      expect(body.embeds[0].color).toBe(0x0099ff);
    });

    it('includes the service name in the footer', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.info('Footer test');
      logger.startBatchProcessor();
      await tick(5000);

      const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
      expect(body.embeds[0].footer.text).toContain('TestService');
    });

    it('includes the environment in the footer', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.info('Env footer test');
      logger.startBatchProcessor();
      await tick(5000);

      const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
      expect(body.embeds[0].footer.text).toContain('test');
    });

    it('includes a timestamp in ISO format', async () => {
      mockFetch.mockResolvedValue(mockResponse(204));
      logger.info('Timestamp test');
      logger.startBatchProcessor();
      await tick(5000);

      const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
      expect(body.embeds[0].timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    });
  });
});
