# Discord Logger — RIFF Integration Guide

A production-grade TypeScript/Node.js module that sends application logs to Discord `#system-alerts` via webhook. Designed to **never crash your application**, even when Discord is completely unreachable.

---

## Features

| Feature | Detail |
|---|---|
| Log levels | ERROR (red), WARN (yellow), INFO (blue) |
| Batching | Collects logs, flushes every 5 s (configurable) |
| Queue | In-memory, capped at 1 000 items; drops oldest on overflow |
| Retry | 3 attempts with exponential backoff (1 s → 2 s → 4 s) |
| Rate limits | Respects Discord 429 `retry-after` header |
| Timeout | 5-second hard timeout per request via `AbortController` |
| Sanitisation | Redacts passwords, tokens, API keys, etc. from metadata |
| Fallback | Always writes to `console` — Discord is supplementary |
| Global handlers | Catches `uncaughtException` and `unhandledRejection` |

---

## Quick Start

### 1. Install dependencies

```bash
cd discord-logger
npm install
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and set DISCORD_WEBHOOK_URL
```

### 3. Add to your application entry point

```typescript
import { discordLogger } from './src/utils/discordLogger';

discordLogger.initialize({
  serviceName: 'RIFF',
  environment: process.env.NODE_ENV ?? 'production',
});
discordLogger.startBatchProcessor();
discordLogger.registerGlobalHandlers(); // optional but recommended
```

### 4. Log something

```typescript
// Error (red embed)
discordLogger.error('WooCommerce Sync Failed', {
  error,
  orderId: 123,
  platform: 'woocommerce',
});

// Warning (yellow embed)
discordLogger.warn('Low Stock', { sku: 'REV-456', qty: 1 });

// Info (blue embed)
discordLogger.info('Deployment Complete', { version: '2.1.0' });
```

---

## Configuration

All options can be set via constructor/`initialize()` **or** environment variables.

| Env var | Constructor key | Default | Description |
|---|---|---|---|
| `DISCORD_WEBHOOK_URL` | `webhookUrl` | — | **Required.** Discord channel webhook URL |
| `DISCORD_SERVICE_NAME` | `serviceName` | `RIFF` | Shown in embed footer |
| `NODE_ENV` | `environment` | `development` | Shown in embed footer |
| `DISCORD_LOGGING_ENABLED` | `enabled` | `true` | Set `false` to disable Discord sends |
| `DISCORD_BATCH_INTERVAL` | `batchInterval` | `5000` | Flush interval in milliseconds |
| `DISCORD_QUEUE_LIMIT` | `queueLimit` | `1000` | Max items in memory queue |

---

## Integration Examples

### Express.js

```typescript
import express from 'express';
import { discordLogger } from './src/utils/discordLogger';

const app = express();

// Error middleware must have 4 parameters
app.use((err: Error, req, res, _next) => {
  discordLogger.error('Express Error', {
    error:      err,
    method:     req.method,
    path:       req.path,
    statusCode: (err as any).status ?? 500,
  });
  res.status(500).json({ error: 'Internal Server Error' });
});
```

### Next.js API Route (Pages Router)

```typescript
import type { NextApiRequest, NextApiResponse } from 'next';
import { discordLogger } from '@/utils/discordLogger';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  try {
    // ... your logic ...
    res.status(200).json({ ok: true });
  } catch (error) {
    discordLogger.error('API Error', { error, route: req.url });
    res.status(500).json({ error: 'Internal Server Error' });
  }
}
```

### Next.js Middleware (App Router)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { discordLogger } from '@/utils/discordLogger';

export function middleware(req: NextRequest) {
  try {
    return NextResponse.next();
  } catch (error) {
    discordLogger.error('Middleware Error', {
      error,
      pathname: req.nextUrl.pathname,
    });
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 });
  }
}
```

### Cron Job / Async Task

```typescript
import { discordLogger } from './src/utils/discordLogger';

async function runHourlySync(): Promise<void> {
  discordLogger.info('Sync started');
  try {
    await doSync();
    discordLogger.info('Sync complete', { itemsSynced: 500 });
  } catch (error) {
    discordLogger.error('Sync failed', { error });
  }
}
```

### Graceful Shutdown

```typescript
process.on('SIGTERM', () => {
  discordLogger.stopBatchProcessor(); // flushes remaining queue
  server.close(() => process.exit(0));
});
```

---

## What You'll See in Discord

```
🔴 ERROR — WooCommerce Sync Failed
Error: Connection timeout
Code: ETIMEDOUT

Stack Trace:
  at syncProducts (src/sync.ts:45)
  at runHourlySync (src/cron.ts:12)

platform:  woocommerce
operation: bulkUpdate
orderId:   123

─────────────────────────────────────
RIFF | production               14:23 UTC
```

---

## Development

```bash
# Run tests
npm test

# Run tests in watch mode
npm run test:watch

# Run with coverage
npm run test:cover

# Type check only
npm run typecheck

# Run the example script (sends real Discord messages)
npm run example

# Build to dist/
npm run build
```

---

## Railway Deployment

### Set environment variables via Railway dashboard

1. Open your Railway project → select the service
2. Click **Variables** tab
3. Add:
   ```
   DISCORD_WEBHOOK_URL=https://discordapp.com/api/webhooks/...
   DISCORD_SERVICE_NAME=RIFF
   DISCORD_LOGGING_ENABLED=true
   NODE_ENV=production
   ```
4. Railway will redeploy automatically.

### Set via Railway CLI

```bash
railway variables set DISCORD_WEBHOOK_URL="https://discordapp.com/api/webhooks/..."
railway variables set DISCORD_SERVICE_NAME="RIFF"
railway variables set DISCORD_LOGGING_ENABLED="true"
railway up
```

---

## Troubleshooting

### Logs not appearing in Discord

1. **Check webhook URL** — go to Discord channel → Edit → Integrations → Webhooks → copy URL
2. **Check `DISCORD_LOGGING_ENABLED`** — must not be `"false"`
3. **Check Railway logs** for lines like `[Discord Logger] Batch sent: N embed(s)` or error messages
4. **Verify initialization** — `startBatchProcessor()` must be called

### Rate limiting

Increase the batch interval if you generate very high log volume:

```typescript
discordLogger.initialize({ batchInterval: 30_000 }); // every 30 seconds
```

### Logs are batched — I need immediate sends

Call `stopBatchProcessor()` and instead trigger flushes manually by wrapping your critical operation:

```typescript
discordLogger.error('Critical failure', { error });
// The next batch flush (≤5 s) will deliver it.
// For immediate delivery in shutdown scenarios, stopBatchProcessor() triggers a flush.
```

---

## Security

- Sensitive field keys (`password`, `token`, `apiKey`, `secret`, `auth`, `credential`, `webhook`, `private`) are automatically replaced with `[REDACTED]` before being sent to Discord.
- The webhook URL itself is **never** logged to Discord or console.
- Never commit your `.env` file — it is listed in `.gitignore`.
