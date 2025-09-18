# Railway Scheduler Setup

This guide explains how to set up scheduled syncs on Railway.

## Option 1: Built-in APScheduler (Recommended)

The application includes a built-in scheduler that runs within your FastAPI app.

### Configuration

Set these environment variables in Railway:

```bash
# Enable the scheduler
SYNC_SCHEDULE_ENABLED=true

# Set the schedule (cron expression)
# Default: every 4 hours
SYNC_SCHEDULE=0 */4 * * *

# Examples:
# Every 2 hours: 0 */2 * * *
# Daily at 8am: 0 8 * * *
# Every 30 minutes: */30 * * * *
# Twice daily (8am and 8pm): 0 8,20 * * *

# Authentication (required)
AUTH_USER=your_username
AUTH_PASS=your_password
```

### Monitoring

Check scheduler status:
```bash
curl https://your-app.railway.app/api/scheduler/status \
  -H "Authorization: Basic [base64_encoded_credentials]"
```

Manually trigger sync:
```bash
curl -X POST https://your-app.railway.app/api/scheduler/trigger-sync \
  -H "Authorization: Basic [base64_encoded_credentials]"
```

### Advantages
- No additional services needed
- Runs in your existing Railway app
- Easy to monitor and control
- Survives deployments

### Disadvantages
- Uses resources from your main app
- If app crashes, scheduler stops
- Limited to simple schedules

## Option 2: Railway Cron Jobs (Alternative)

Railway supports cron jobs as separate services.

### Setup

1. Create a new service in Railway
2. Use the same repo but different start command
3. Set the service type to "Cron"

### Create `railway.cron.json`:
```json
{
  "jobs": [
    {
      "name": "sync-all-platforms",
      "schedule": "0 */4 * * *",
      "command": "python scripts/railway_sync.py"
    }
  ]
}
```

### Create `scripts/railway_sync.py`:
```python
#!/usr/bin/env python
import os
import asyncio
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def trigger_sync():
    """Trigger sync via internal Railway network"""

    # Use Railway's internal networking
    base_url = os.getenv("RAILWAY_PRIVATE_DOMAIN", "localhost:8080")
    if not base_url.startswith("http"):
        base_url = f"http://{base_url}"

    auth_user = os.getenv("AUTH_USER")
    auth_pass = os.getenv("AUTH_PASS")

    if not auth_user or not auth_pass:
        logger.error("AUTH_USER and AUTH_PASS must be set")
        return

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{base_url}/api/sync/all",
                auth=(auth_user, auth_pass)
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Sync completed: {result}")
            else:
                logger.error(f"Sync failed: {response.status_code} - {response.text}")

    except Exception as e:
        logger.exception(f"Error triggering sync: {str(e)}")

if __name__ == "__main__":
    asyncio.run(trigger_sync())
```

### Advantages
- Isolated from main app
- Can have different resource limits
- Won't affect app performance

### Disadvantages
- Additional service cost
- More complex setup
- Need to maintain separate service

## Option 3: External Triggers

Use external services to trigger syncs:

### GitHub Actions
Create `.github/workflows/sync.yml`:
```yaml
name: Sync Platforms

on:
  schedule:
    - cron: '0 */4 * * *'  # Every 4 hours
  workflow_dispatch:  # Manual trigger

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger sync
        run: |
          curl -X POST https://your-app.railway.app/api/sync/all \
            -H "Authorization: Basic ${{ secrets.SYNC_AUTH }}" \
            -f
```

### Uptime Monitoring Services
Many uptime services (UptimeRobot, Pingdom) can make POST requests on a schedule.

## Logs and Monitoring

### View Logs in Railway

All scheduler activities are logged. View them in Railway's log viewer or use:

```bash
railway logs -n 1000 | grep -i scheduler
```

### Database Activity Log

The scheduler logs all sync activities to the database:

```sql
SELECT * FROM activity_log
WHERE action = 'scheduled_sync'
ORDER BY created_at DESC
LIMIT 10;
```

## Troubleshooting

### Scheduler Not Starting

1. Check `SYNC_SCHEDULE_ENABLED=true` is set
2. Verify logs for startup errors
3. Check `/api/scheduler/status` endpoint

### Syncs Not Running

1. Verify cron expression is valid
2. Check authentication is configured
3. Look for errors in logs
4. Manually trigger to test: `/api/scheduler/trigger-sync`

### Time Zone Issues

Railway uses UTC. Adjust your cron schedules accordingly:
- 8 AM EST = 13:00 UTC (or 12:00 during DST)
- 8 AM PST = 16:00 UTC (or 15:00 during DST)

## Best Practices

1. **Start Conservative**: Begin with less frequent syncs (e.g., every 6 hours)
2. **Monitor Performance**: Watch CPU and memory usage
3. **Use Alerts**: Set up Railway alerts for failed deploys
4. **Test Manually**: Always test with manual trigger first
5. **Log Retention**: Consider log volume with frequent syncs

## Example Production Setup

```bash
# Railway Environment Variables
SYNC_SCHEDULE_ENABLED=true
SYNC_SCHEDULE=35 11,15,19,23,3,7 * * *  # Starting at 11:35 UTC (12:35 BST), then every 4 hours
# Note: BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD should already be set in your Railway environment
LOG_LEVEL=INFO
```