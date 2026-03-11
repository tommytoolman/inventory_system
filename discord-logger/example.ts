/**
 * example.ts
 *
 * Usage examples for the Discord Logger in common Node.js scenarios:
 *   - Manual logging (errors, warnings, info)
 *   - Express.js error middleware
 *   - Next.js API route handler
 *   - Cron job / async task runner
 *   - Global unhandled exception capture
 *
 * Run this file to send a test message to Discord:
 *   npx ts-node example.ts
 */

import express, { Request, Response, NextFunction } from 'express';
import { discordLogger, DiscordLogger } from './src/utils/discordLogger';

// ============================================================
// 1. INITIALISATION (call once at application startup)
// ============================================================

discordLogger.initialize({
  webhookUrl:    process.env.DISCORD_WEBHOOK_URL, // or hard-code for testing
  serviceName:   process.env.DISCORD_SERVICE_NAME ?? 'RIFF',
  environment:   process.env.NODE_ENV ?? 'development',
  batchInterval: 5000,  // send every 5 seconds
  queueLimit:    1000,
  logLevels: {
    error: true,
    warn:  true,
    info:  true,  // set false in noisy environments
  },
});

// Start the background batch sender
discordLogger.startBatchProcessor();

// Register global handlers (catches uncaughtException + unhandledRejection)
discordLogger.registerGlobalHandlers();

// Graceful shutdown hook
process.on('SIGTERM', () => {
  discordLogger.stopBatchProcessor();
  process.exit(0);
});

// ============================================================
// 2. MANUAL LOGGING
// ============================================================

async function manualLoggingExamples(): Promise<void> {

  // ---- INFO ----
  discordLogger.info('Server Started', {
    port:    3000,
    version: '1.2.3',
    nodeEnv: process.env.NODE_ENV,
  });

  // ---- WARN ----
  const syncedItems   = 42;
  const expectedItems = 50;
  if (syncedItems < expectedItems) {
    discordLogger.warn('WooCommerce Sync Incomplete', {
      expected:   expectedItems,
      received:   syncedItems,
      difference: expectedItems - syncedItems,
      context:    'hourly_sync_job',
    });
  }

  // ---- ERROR with Error object ----
  try {
    await Promise.reject(new Error('Database connection refused'));
  } catch (error) {
    discordLogger.error('Inventory Sync Failed', {
      error,                            // Error object → stack trace included
      platform:  'woocommerce',
      operation: 'bulkUpdate',
    });
  }

  // ---- ERROR with custom metadata ----
  discordLogger.error('WooCommerce API Timeout', {
    error:        new Error('ETIMEDOUT'),
    endpoint:     '/wp-json/wc/v3/products',
    timeoutMs:    5000,
    itemsAffected: 120,
  });
}

// ============================================================
// 3. EXPRESS.JS INTEGRATION
// ============================================================

function expressExample(): void {
  const app = express();
  app.use(express.json());

  // --- Example route ---
  app.get('/api/sync', async (_req: Request, res: Response, next: NextFunction) => {
    try {
      // Simulate an operation that might fail
      if (Math.random() < 0.5) throw new Error('Simulated sync error');
      res.json({ status: 'ok', synced: 100 });
    } catch (err) {
      next(err); // pass to error middleware below
    }
  });

  // --- Express error middleware (must have 4 parameters) ---
  app.use((err: Error, req: Request, res: Response, _next: NextFunction) => {
    // Log to Discord (non-blocking — won't delay the response)
    discordLogger.error('Express Route Error', {
      error:      err,
      method:     req.method,
      path:       req.path,
      query:      req.query,
      statusCode: (err as { status?: number }).status ?? 500,
    });

    res.status((err as { status?: number }).status ?? 500).json({
      error: 'Internal Server Error',
    });
  });

  app.listen(3000, () => {
    discordLogger.info('Express Server Listening', { port: 3000 });
    console.log('Express server running on port 3000');
  });
}

// ============================================================
// 4. NEXT.JS API ROUTE EXAMPLE
// ============================================================
//
// In pages/api/sync.ts (Pages Router):
//
// import type { NextApiRequest, NextApiResponse } from 'next';
// import { discordLogger } from '@/utils/discordLogger';
//
// export default async function handler(req: NextApiRequest, res: NextApiResponse) {
//   try {
//     // ... your API logic ...
//     res.status(200).json({ ok: true });
//   } catch (error) {
//     discordLogger.error('API Route Error', {
//       error,
//       route:  '/api/sync',
//       method: req.method,
//     });
//     res.status(500).json({ error: 'Internal Server Error' });
//   }
// }
//
// ---
//
// In middleware.ts (App Router):
//
// import { NextRequest, NextResponse } from 'next/server';
// import { discordLogger } from '@/utils/discordLogger';
//
// export function middleware(req: NextRequest) {
//   try {
//     // ... middleware logic ...
//     return NextResponse.next();
//   } catch (error) {
//     discordLogger.error('Middleware Error', {
//       error,
//       pathname: req.nextUrl.pathname,
//       method:   req.method,
//     });
//     return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 });
//   }
// }

// ============================================================
// 5. CRON JOB / ASYNC TASK RUNNER
// ============================================================

async function runSyncJob(): Promise<void> {
  discordLogger.info('Sync Job Started', { jobName: 'woocommerce_hourly_sync' });

  try {
    // Simulate heavy async work
    await new Promise(resolve => setTimeout(resolve, 100));

    const result = { synced: 95, failed: 5, total: 100 };

    if (result.failed > 0) {
      discordLogger.warn('Sync Job Completed with Errors', {
        ...result,
        jobName: 'woocommerce_hourly_sync',
      });
    } else {
      discordLogger.info('Sync Job Completed Successfully', {
        ...result,
        jobName: 'woocommerce_hourly_sync',
      });
    }
  } catch (error) {
    discordLogger.error('Sync Job Crashed', {
      error,
      jobName: 'woocommerce_hourly_sync',
    });
  }
}

// ============================================================
// 6. CUSTOM INSTANCE (for multi-service setups)
// ============================================================
//
// If you have multiple services in the same process you can create
// separate logger instances instead of using the singleton.

const inventoryLogger = new DiscordLogger({
  webhookUrl:  process.env.DISCORD_WEBHOOK_URL,
  serviceName: 'RIFF-Inventory',
  environment: process.env.NODE_ENV ?? 'development',
});

inventoryLogger.initialize({ logLevels: { info: false } }); // errors + warns only
inventoryLogger.startBatchProcessor();

// ============================================================
// ENTRY POINT (for direct execution: npx ts-node example.ts)
// ============================================================

async function main(): Promise<void> {
  console.log('Running Discord Logger examples…');

  await manualLoggingExamples();
  await runSyncJob();

  // Wait long enough for the first batch to flush (5s + buffer)
  console.log('Waiting 6 seconds for Discord batch flush…');
  await new Promise(resolve => setTimeout(resolve, 6000));

  discordLogger.info('Example Script Complete', { timestamp: new Date().toISOString() });

  // Wait one more batch cycle then exit
  await new Promise(resolve => setTimeout(resolve, 6000));
  discordLogger.stopBatchProcessor();
  inventoryLogger.stopBatchProcessor();
  console.log('Done. Check your #system-alerts Discord channel.');
}

// Only run if executed directly (not when imported by tests)
if (require.main === module) {
  main().catch(err => {
    console.error('Example script failed:', err);
    process.exit(1);
  });
}

export { expressExample, runSyncJob };
