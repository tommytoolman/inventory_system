/**
 * Discord Application Logger
 *
 * Production-grade logger that sends application logs to a Discord channel
 * via webhook. Designed to NEVER crash your application, even if Discord
 * is completely unreachable.
 *
 * Features:
 *  - Batching (sends every 5 seconds to avoid Discord rate limits)
 *  - In-memory queue with overflow protection (configurable max, default 1000)
 *  - Exponential backoff retry logic (3 attempts: 1s, 2s, 4s)
 *  - 5-second timeout per request
 *  - Sensitive data sanitisation (passwords, tokens, API keys, etc.)
 *  - Graceful degradation: console fallback if Discord is unavailable
 *  - Global unhandled exception / promise rejection handlers
 */

'use strict';

// ============================================================
// TYPES & INTERFACES
// ============================================================

export type LogLevel = 'ERROR' | 'WARN' | 'INFO';

export interface LoggerConfig {
  /** Discord webhook URL. Falls back to DISCORD_WEBHOOK_URL env var. */
  webhookUrl?: string;
  /** Identifies which service sent the log (e.g. "RIFF"). */
  serviceName?: string;
  /** e.g. "production" | "development". Falls back to NODE_ENV. */
  environment?: string;
  /** How often (ms) to flush the queue to Discord. Default: 5000. */
  batchInterval?: number;
  /** Max items held in queue before oldest are dropped. Default: 1000. */
  queueLimit?: number;
  /** Set false (or DISCORD_LOGGING_ENABLED=false) to disable Discord sending. */
  enabled?: boolean;
  /** Granular per-level control. */
  logLevels?: {
    error?: boolean;
    warn?: boolean;
    info?: boolean;
  };
}

export interface LogEntry {
  level: LogLevel;
  title: string;
  error?: unknown;
  metadata?: Record<string, unknown>;
  timestamp: string;
}

interface DiscordEmbed {
  title: string;
  description: string;
  color: number;
  timestamp: string;
  footer: { text: string };
  fields?: Array<{ name: string; value: string; inline?: boolean }>;
}

interface DiscordWebhookPayload {
  username: string;
  embeds: DiscordEmbed[];
}

// ============================================================
// CONSTANTS
// ============================================================

/** Discord embed border colours per log level. */
const LOG_COLORS: Record<LogLevel, number> = {
  ERROR: 0xff0000, // Red
  WARN:  0xffa500, // Orange / Yellow
  INFO:  0x0099ff, // Blue
};

/** Visual prefix for each level. */
const LOG_EMOJIS: Record<LogLevel, string> = {
  ERROR: '🔴',
  WARN:  '🟡',
  INFO:  '🔵',
};

const DEFAULT_CONFIG: Required<LoggerConfig> = {
  webhookUrl:    '',
  serviceName:   'RIFF',
  environment:   process.env.NODE_ENV || 'development',
  batchInterval: 5000,
  queueLimit:    1000,
  enabled:       true,
  logLevels:     { error: true, warn: true, info: true },
};

/**
 * Regex patterns that identify sensitive field keys.
 * Matching values are replaced with '[REDACTED]' before being sent to Discord.
 */
const SENSITIVE_PATTERNS = [
  /password/i,
  /secret/i,
  /token/i,
  /api[_-]?key/i,
  /auth/i,
  /credential/i,
  /private/i,
  /webhook/i,
];

// Discord API limits
const DISCORD_MAX_EMBED_DESCRIPTION = 4096;
const DISCORD_MAX_FIELD_VALUE       = 1024;
const DISCORD_MAX_EMBEDS_PER_BATCH  = 10;  // Discord allows max 10 embeds per message
const DISCORD_REQUEST_TIMEOUT_MS    = 5000;
const MAX_RETRY_ATTEMPTS            = 3;

// ============================================================
// UTILITY FUNCTIONS (private, not exported)
// ============================================================

/**
 * Recursively redact values whose key matches a sensitive pattern.
 * Never throws — returns { '[sanitise_error]': '...' } on failure.
 */
function sanitiseData(data: Record<string, unknown>): Record<string, unknown> {
  try {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(data)) {
      if (SENSITIVE_PATTERNS.some(p => p.test(key))) {
        result[key] = '[REDACTED]';
      } else if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
        result[key] = sanitiseData(value as Record<string, unknown>);
      } else {
        result[key] = value;
      }
    }
    return result;
  } catch {
    return { '[sanitise_error]': 'Failed to sanitise data' };
  }
}

/** Truncate a string to maxLength, appending a notice when clipped. */
function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.substring(0, maxLength - 30) + '\n... [truncated]';
}

/** Extract a safe message/stack/code from any thrown value. */
function extractErrorInfo(error: unknown): {
  message: string;
  stack?: string;
  code?: string;
} {
  try {
    if (error instanceof Error) {
      return {
        message: error.message || 'Unknown error',
        stack:   error.stack,
        code:    (error as NodeJS.ErrnoException).code,
      };
    }
    if (typeof error === 'string') return { message: error };
    if (error !== null && typeof error === 'object') {
      const obj = error as Record<string, unknown>;
      return {
        message: String(obj.message ?? obj.error ?? JSON.stringify(error)),
        stack:   typeof obj.stack  === 'string' ? obj.stack  : undefined,
        code:    typeof obj.code   === 'string' ? obj.code   : undefined,
      };
    }
    return { message: String(error) };
  } catch {
    return { message: 'Failed to extract error information' };
  }
}

/** Collect lightweight Node.js process metadata for context. */
function getProcessMetadata(): Record<string, string> {
  try {
    return {
      nodeVersion:   process.version,
      platform:      process.platform,
      arch:          process.arch,
      pid:           String(process.pid),
      uptime:        `${Math.round(process.uptime())}s`,
      memoryUsageMB: `${Math.round(process.memoryUsage().heapUsed / 1024 / 1024)}MB`,
    };
  } catch {
    return {};
  }
}

/** Simple promise-based sleep. */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ============================================================
// DISCORD LOGGER CLASS
// ============================================================

class DiscordLogger {
  private config: Required<LoggerConfig>;
  private queue: LogEntry[]                           = [];
  private batchTimer: ReturnType<typeof setInterval> | null = null;
  private isFlushing                                  = false;

  constructor(config: LoggerConfig = {}) {
    // Merge defaults, then override with environment variables
    this.config = {
      ...DEFAULT_CONFIG,
      ...config,
      logLevels: { ...DEFAULT_CONFIG.logLevels, ...config.logLevels },
    };

    // Environment variable overrides (env always wins over constructor default,
    // but an explicit constructor value wins over env — mirrored below).
    if (!config.webhookUrl) {
      this.config.webhookUrl = process.env.DISCORD_WEBHOOK_URL || '';
    }
    if (!config.serviceName) {
      this.config.serviceName = process.env.DISCORD_SERVICE_NAME || DEFAULT_CONFIG.serviceName;
    }
    if (config.enabled === undefined) {
      this.config.enabled = process.env.DISCORD_LOGGING_ENABLED !== 'false';
    }
    if (config.batchInterval === undefined) {
      const v = parseInt(process.env.DISCORD_BATCH_INTERVAL || '');
      if (!isNaN(v)) this.config.batchInterval = v;
    }
    if (config.queueLimit === undefined) {
      const v = parseInt(process.env.DISCORD_QUEUE_LIMIT || '');
      if (!isNaN(v)) this.config.queueLimit = v;
    }
  }

  // ============================================================
  // PUBLIC API
  // ============================================================

  /**
   * Re-configure the logger after construction.
   * Safe to call multiple times (e.g. after loading env vars from a config file).
   */
  initialize(config: LoggerConfig): void {
    try {
      this.config = {
        ...this.config,
        ...config,
        logLevels: { ...this.config.logLevels, ...config.logLevels },
      };
      // Always respect the kill-switch env var
      if (process.env.DISCORD_LOGGING_ENABLED === 'false') {
        this.config.enabled = false;
      }
    } catch (err) {
      console.error('[Discord Logger] Failed to initialize:', err);
    }
  }

  /**
   * Start the background batch processor.
   * Call once at application startup — typically right after initialize().
   *
   * @example
   *   discordLogger.startBatchProcessor();
   */
  startBatchProcessor(): void {
    try {
      if (this.batchTimer) this.stopBatchProcessor();

      this.batchTimer = setInterval(() => {
        void this.flushQueue();
      }, this.config.batchInterval);

      // unref() prevents this timer from keeping the process alive on exit
      if (typeof this.batchTimer.unref === 'function') {
        this.batchTimer.unref();
      }

      console.log(`[Discord Logger] Batch processor started (every ${this.config.batchInterval}ms)`);
    } catch (err) {
      console.error('[Discord Logger] Failed to start batch processor:', err);
    }
  }

  /**
   * Stop the batch processor and attempt a final flush of remaining logs.
   * Call during graceful shutdown (SIGTERM, SIGINT).
   */
  stopBatchProcessor(): void {
    try {
      if (this.batchTimer) {
        clearInterval(this.batchTimer);
        this.batchTimer = null;
      }
      if (this.queue.length > 0) {
        console.warn(`[Discord Logger] Stopping with ${this.queue.length} logs in queue — flushing now`);
        void this.flushQueue();
      }
    } catch (err) {
      console.error('[Discord Logger] Failed to stop batch processor:', err);
    }
  }

  /**
   * Register Node.js global handlers for uncaught exceptions and unhandled
   * promise rejections. Call once at the very top of your entry point.
   */
  registerGlobalHandlers(): void {
    try {
      process.on('uncaughtException', (error: Error) => {
        console.error('[Discord Logger] Uncaught Exception:', error);
        this.addToQueue('ERROR', 'Uncaught Exception', {
          error,
          fatal:       true,
          processInfo: getProcessMetadata(),
        });
        void this.flushQueue(); // best-effort immediate send
      });

      process.on('unhandledRejection', (reason: unknown) => {
        console.error('[Discord Logger] Unhandled Promise Rejection:', reason);
        this.addToQueue('ERROR', 'Unhandled Promise Rejection', {
          error:       reason,
          processInfo: getProcessMetadata(),
        });
        void this.flushQueue();
      });

      console.log('[Discord Logger] Global error handlers registered');
    } catch (err) {
      console.error('[Discord Logger] Failed to register global handlers:', err);
    }
  }

  // ----------------------------------------------------------
  // Log level methods
  // ----------------------------------------------------------

  /**
   * Log a critical error (red embed).
   *
   * @param title   Short description of what failed.
   * @param context Optional object. Include `error` key for Error/exception.
   *
   * @example
   *   discordLogger.error('WooCommerce Sync Failed', { error, orderId: 123 });
   */
  error(title: string, context?: { error?: unknown; [key: string]: unknown }): void {
    if (!this.config.logLevels.error) return;
    this.addToQueue('ERROR', title, context);
  }

  /**
   * Log a warning (yellow/orange embed).
   *
   * @example
   *   discordLogger.warn('Low stock detected', { sku: 'REV-456', qty: 1 });
   */
  warn(title: string, context?: { error?: unknown; [key: string]: unknown }): void {
    if (!this.config.logLevels.warn) return;
    this.addToQueue('WARN', title, context);
  }

  /**
   * Log informational data (blue embed).
   *
   * @example
   *   discordLogger.info('Deployment complete', { version: '2.1.0' });
   */
  info(title: string, context?: { error?: unknown; [key: string]: unknown }): void {
    if (!this.config.logLevels.info) return;
    this.addToQueue('INFO', title, context);
  }

  // ============================================================
  // PRIVATE METHODS
  // ============================================================

  /**
   * Add an entry to the in-memory queue.
   * Drops the oldest entry (with a warning) when the queue is full.
   * Always writes to console as a fallback — even when Discord is disabled.
   */
  private addToQueue(
    level: LogLevel,
    title: string,
    context?: { error?: unknown; [key: string]: unknown },
  ): void {
    try {
      // Console fallback regardless of Discord status
      const logFn = level === 'ERROR'
        ? console.error
        : level === 'WARN'
        ? console.warn
        : console.info;
      logFn(`[${level}] ${title}`, context ?? '');

      if (!this.config.enabled) return;
      if (!this.config.webhookUrl) {
        console.warn(`[Discord Logger] No webhook URL configured — skipping Discord send for: [${level}] ${title}`);
        return;
      }

      // Separate the error from general metadata
      const { error, ...metadata } = context ?? {};

      // Drop oldest when at capacity
      if (this.queue.length >= this.config.queueLimit) {
        const dropped = this.queue.shift();
        console.warn(
          `[Discord Logger] Queue full (${this.config.queueLimit}). Dropped: [${dropped?.level}] ${dropped?.title}`
        );
      }

      this.queue.push({
        level,
        title,
        error,
        metadata: Object.keys(metadata).length > 0
          ? (metadata as Record<string, unknown>)
          : undefined,
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      // Absolute last resort — never propagate
      console.error('[Discord Logger] addToQueue failed:', err, `| Original: [${level}] ${title}`);
    }
  }

  /**
   * Drain the queue and send all pending entries to Discord.
   * Called automatically by the batch timer, and manually on shutdown/errors.
   */
  private async flushQueue(): Promise<void> {
    if (this.isFlushing || this.queue.length === 0) return;
    this.isFlushing = true;

    try {
      // Drain the entire queue atomically (new entries added while we're
      // sending will be picked up on the next flush cycle).
      const batch = this.queue.splice(0, this.queue.length);

      // Build Discord embeds — skip any that fail to build
      const embeds: DiscordEmbed[] = [];
      for (const entry of batch) {
        try {
          embeds.push(this.buildEmbed(entry));
        } catch (err) {
          console.error('[Discord Logger] Failed to build embed for entry:', entry.title, err);
        }
      }

      // Discord allows max 10 embeds per webhook call — chunk if needed
      for (let i = 0; i < embeds.length; i += DISCORD_MAX_EMBEDS_PER_BATCH) {
        const chunk = embeds.slice(i, i + DISCORD_MAX_EMBEDS_PER_BATCH);
        await this.sendToDiscord({
          username: `${this.config.serviceName} Logger`,
          embeds:   chunk,
        });
      }
    } catch (err) {
      console.error('[Discord Logger] flushQueue failed:', err);
    } finally {
      this.isFlushing = false;
    }
  }

  /**
   * Convert a LogEntry into a Discord embed object.
   */
  private buildEmbed(entry: LogEntry): DiscordEmbed {
    const errorInfo = entry.error ? extractErrorInfo(entry.error) : null;
    const fields: NonNullable<DiscordEmbed['fields']> = [];

    // --- Error details ---
    if (errorInfo) {
      if (errorInfo.code) {
        fields.push({
          name:   'Error Code',
          value:  truncate(errorInfo.code, DISCORD_MAX_FIELD_VALUE),
          inline: true,
        });
      }
      if (errorInfo.stack) {
        fields.push({
          name:   'Stack Trace',
          value:  `\`\`\`\n${truncate(errorInfo.stack, DISCORD_MAX_FIELD_VALUE - 10)}\n\`\`\``,
          inline: false,
        });
      }
    }

    // --- Sanitised metadata fields ---
    if (entry.metadata) {
      const safe = sanitiseData(entry.metadata);

      for (const [key, value] of Object.entries(safe)) {
        // processInfo gets its own dedicated field below
        if (key === 'processInfo') continue;

        const str = typeof value === 'object'
          ? JSON.stringify(value, null, 2)
          : String(value ?? '');

        fields.push({
          name:   key,
          value:  truncate(str, DISCORD_MAX_FIELD_VALUE),
          inline: typeof value !== 'object',
        });
      }

      // Condense processInfo into a single neat field
      if (safe.processInfo && typeof safe.processInfo === 'object') {
        const info = safe.processInfo as Record<string, string>;
        fields.push({
          name:   'Process Info',
          value:  truncate(
            Object.entries(info).map(([k, v]) => `**${k}:** ${v}`).join('\n'),
            DISCORD_MAX_FIELD_VALUE
          ),
          inline: false,
        });
      }
    }

    // --- Embed description ---
    let description = '';
    if (errorInfo?.message) {
      description = `**${truncate(errorInfo.message, 512)}**`;
    }

    return {
      title:       `${LOG_EMOJIS[entry.level]} ${entry.level} — ${truncate(entry.title, 200)}`,
      description: truncate(description, DISCORD_MAX_EMBED_DESCRIPTION),
      color:       LOG_COLORS[entry.level],
      timestamp:   entry.timestamp,
      footer:      { text: `${this.config.serviceName} | ${this.config.environment}` },
      fields:      fields.slice(0, 25), // Discord hard limit: 25 fields per embed
    };
  }

  /**
   * POST a webhook payload to Discord with:
   *  - 5-second request timeout
   *  - Rate-limit (429) awareness
   *  - Exponential backoff: 1s → 2s → 4s
   */
  private async sendToDiscord(payload: DiscordWebhookPayload): Promise<void> {
    if (!this.config.webhookUrl) return;

    for (let attempt = 1; attempt <= MAX_RETRY_ATTEMPTS; attempt++) {
      try {
        const controller = new AbortController();
        const timeoutId  = setTimeout(() => controller.abort(), DISCORD_REQUEST_TIMEOUT_MS);

        const response = await fetch(this.config.webhookUrl, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify(payload),
          signal:  controller.signal,
        });

        clearTimeout(timeoutId);

        // Handle rate limiting
        if (response.status === 429) {
          const retryAfterSec = parseInt(response.headers.get('retry-after') ?? '5', 10);
          const delayMs       = retryAfterSec * 1000;
          console.warn(`[Discord Logger] Rate limited — waiting ${delayMs}ms before retry`);
          await sleep(delayMs);
          continue; // retry without decrementing attempt counter would be more correct,
                    // but to keep things simple we count this as an attempt
        }

        if (!response.ok) {
          const body = await response.text().catch(() => '<unreadable>');
          throw new Error(`Discord webhook HTTP ${response.status}: ${body}`);
        }

        console.log(`[Discord Logger] Batch sent: ${payload.embeds.length} embed(s)`);
        return; // success

      } catch (err) {
        if (attempt === MAX_RETRY_ATTEMPTS) {
          console.error(
            `[Discord Logger] Failed after ${MAX_RETRY_ATTEMPTS} attempts. Dropping batch.`,
            err
          );
          return;
        }

        // Exponential backoff: 1 000ms, 2 000ms, 4 000ms
        const backoffMs = Math.pow(2, attempt - 1) * 1000;
        console.warn(
          `[Discord Logger] Send failed (attempt ${attempt}/${MAX_RETRY_ATTEMPTS}). Retrying in ${backoffMs}ms…`,
          err
        );
        await sleep(backoffMs);
      }
    }
  }
}

// ============================================================
// SINGLETON EXPORT
// ============================================================

/**
 * Pre-configured singleton instance.
 *
 * Reads DISCORD_WEBHOOK_URL, DISCORD_SERVICE_NAME, DISCORD_LOGGING_ENABLED,
 * DISCORD_BATCH_INTERVAL, and DISCORD_QUEUE_LIMIT from environment variables
 * automatically.
 *
 * @example
 *   import { discordLogger } from './utils/discordLogger';
 *
 *   discordLogger.initialize({ serviceName: 'RIFF', environment: 'production' });
 *   discordLogger.startBatchProcessor();
 *   discordLogger.error('Sync failed', { error, orderId: 42 });
 */
export const discordLogger = new DiscordLogger();

export { DiscordLogger };
export default discordLogger;
