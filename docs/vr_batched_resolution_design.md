# V&R Batched ID Resolution - Design Document

## Problem Statement

Currently, after creating each V&R listing via Selenium, the worker:
1. Waits 5 seconds for V&R to process
2. Downloads the full inventory CSV (~3MB, 1500+ rows, ~30s)
3. Parses and searches for the new listing
4. Saves the V&R ID to database

When processing 10 jobs, this means 10 CSV downloads = ~5 minutes of unnecessary overhead.

Additionally, if the worker is killed during CSV download, the job is left stuck in "in_progress" with the listing created on V&R but not recorded locally.

## Proposed Solution

Split the process into two phases:

### Phase 1: Listing Creation (per job, fast)
- Validate brand
- Submit form via Selenium
- Mark job as `completed_pending_id`
- Store matching criteria in job payload

### Phase 2: ID Resolution (batched, triggered periodically)
- Download CSV once
- Resolve all pending jobs in one pass
- Update database entries
- Mark jobs as fully `completed`

## Database Changes

### Option A: New Job Status (Recommended)

Add new status to `vr_jobs.status` enum:
```sql
ALTER TYPE vr_job_status ADD VALUE 'completed_pending_id';
```

Job payload will store matching criteria:
```json
{
  "match_criteria": {
    "brand": "Fender",
    "model": "Stratocaster 1965",
    "sku": "REV-12345",
    "created_at": "2025-12-15T10:30:00Z"
  },
  "listing_created": true
}
```

### Option B: Separate Resolution Queue Table

```sql
CREATE TABLE vr_pending_resolutions (
  id SERIAL PRIMARY KEY,
  job_id INTEGER REFERENCES vr_jobs(id),
  product_id INTEGER REFERENCES products(id),
  brand VARCHAR(255) NOT NULL,
  model VARCHAR(500) NOT NULL,
  sku VARCHAR(100) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

**Recommendation:** Option A is simpler and keeps everything in one table.

## Worker Flow Changes

### Current Flow
```
while True:
    job = fetch_next_queued_job()
    if job:
        create_listing()      # Selenium ~60s
        download_csv()        # ~30s  <-- BOTTLENECK
        find_vr_id()          # ~1s
        save_to_db()          # ~1s
        mark_completed()
    sleep(5)
```

### New Flow
```
while not shutdown_requested:
    job = fetch_next_queued_job()
    if job:
        create_listing()              # Selenium ~60s
        store_match_criteria()        # ~1s
        mark_completed_pending_id()   # ~1s

        # Check if we should resolve now
        pending_count = count_pending_resolutions()
        more_jobs_queued = peek_queue_count() > 0

        if pending_count >= MAX_BATCH_SIZE:
            # Hit max batch - resolve now even if more jobs waiting
            resolve_batch()
        elif not more_jobs_queued:
            # Queue empty - resolve what we have
            resolve_batch()
        # else: more jobs queued, keep creating
    else:
        # No jobs - check for any orphaned pending resolutions
        pending = fetch_pending_resolutions()
        if pending:
            resolve_batch(pending)
        sleep(5)
```

**Key insight:** Only download CSV when:
1. Queue is empty (nothing left to create), OR
2. Pending count hits max (e.g., 10) - don't accumulate too many

## Resolution Triggers

Resolution happens when:

1. **Queue Empty**: No more jobs to create → resolve all pending
2. **Max Batch Reached**: 10 pending → resolve now (don't accumulate too many)
3. **Graceful Shutdown**: Before worker exits
4. **Manual Trigger**: API endpoint to force resolution

```python
# Configuration
MAX_BATCH_SIZE = 10  # Resolve after this many pending, even if more jobs queued

# Decision logic (after each job creation):
pending_count = count_pending_resolutions()
more_jobs_queued = peek_queue_count() > 0

should_resolve = (
    pending_count >= MAX_BATCH_SIZE or  # Hit max batch
    not more_jobs_queued                 # Queue empty
)
```

**Why max batch of 10?**
- Prevents accumulating too many unresolved listings
- If something goes wrong, limits blast radius
- Still gives 51% time savings
- Easy to adjust based on experience

## Matching Algorithm

When resolving, match by:

1. **Exact brand match** (case-insensitive)
2. **Fuzzy model match** (handle minor differences)
3. **Recent items only** (product_id > last known, or created after job timestamp)
4. **Score-based ranking** (existing logic)

```python
def find_vr_id_for_job(job, csv_df):
    criteria = job.payload.get("match_criteria", {})

    # Filter to recent items (created after job was submitted)
    recent = csv_df[csv_df['product_id'] > criteria.get('last_known_vr_id', 0)]

    # Exact brand match
    brand_matches = recent[recent['brand_name'].str.lower() == criteria['brand'].lower()]

    # Fuzzy model match
    for _, row in brand_matches.iterrows():
        score = calculate_match_score(criteria['model'], row['product_model_name'])
        if score >= 8:  # High confidence
            return row['product_id']

    return None  # Will retry next batch
```

## Error Handling

### Resolution Failures
- If a job can't be matched after 3 resolution attempts, mark as `failed` with error
- Log warning for manual review
- Don't block other resolutions

### Partial Failures
- If CSV download fails, retry after delay
- If some jobs resolve but others don't, save successful ones

### Duplicate Prevention
- Before creating listing, check if V&R ID already exists for product
- Skip creation if already listed (idempotency)

## Graceful Shutdown

```python
_shutdown_requested = False
_currently_processing_job = None

def handle_signal(*_):
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown requested - finishing current work...")

async def worker_loop():
    while not _shutdown_requested:
        job = fetch_next_queued_job()
        if job:
            _currently_processing_job = job.id
            await create_listing(job)
            await mark_completed_pending_id(job)
            _currently_processing_job = None
        else:
            await maybe_resolve_batch()
            await asyncio.sleep(POLL_INTERVAL)

    # Shutdown cleanup
    if _currently_processing_job:
        logger.warning(f"Shutdown with job {_currently_processing_job} in progress")

    # Final resolution attempt
    pending = await fetch_pending_resolutions()
    if pending:
        logger.info(f"Resolving {len(pending)} pending IDs before shutdown...")
        await resolve_batch(pending)

    logger.info("Worker shutdown complete")
```

## API Endpoints

### Check Resolution Status
```
GET /api/vr/resolution-status
Response: {
  "pending_count": 5,
  "oldest_pending": "2025-12-15T10:30:00Z",
  "last_resolution": "2025-12-15T10:45:00Z"
}
```

### Force Resolution
```
POST /api/vr/resolve-pending
Response: {
  "resolved": 5,
  "failed": 1,
  "errors": ["Job 123: No match found"]
}
```

## Migration Plan

1. **Add new status value** to vr_jobs enum
2. **Update worker** with new flow
3. **Add resolution logic** (can reuse existing CSV matching code)
4. **Test with small batch** (2-3 items)
5. **Deploy and monitor**

## Performance Comparison

Assuming: Selenium ~45s, CSV download ~60s

| Scenario | Current | Batched | Savings |
|----------|---------|---------|---------|
| 1 job | 105s (45s + 60s) | 105s (same) | 0% |
| 2 jobs | 210s (2 × 105s) | 150s (2×45s + 60s) | 29% |
| 5 jobs | 525s (5 × 105s) | 285s (5×45s + 60s) | 46% |
| 10 jobs | 1050s (17.5 min) | 510s (8.5 min) | 51% |
| 20 jobs | 2100s (35 min) | 960s (16 min) | 54% |

**Savings: 29-54% time reduction, scaling with batch size**

Note: With MAX_BATCH_SIZE=10, a queue of 20 jobs would be:
- Batch 1: 10 creates + 1 CSV = 510s
- Batch 2: 10 creates + 1 CSV = 510s
- Total: 1020s (17 min) vs 2100s (35 min) = 51% savings

## Files to Modify

1. `scripts/vr_worker.py` - Main worker loop changes
2. `app/services/vr_job_queue.py` - Add `completed_pending_id` status handling
3. `app/models/vr_job.py` - Add status enum value (if using SQLAlchemy enum)
4. `app/services/vintageandrare/client.py` - Extract resolution logic to reusable function
5. `app/routes/platforms/vr.py` - Add resolution status/trigger endpoints

## Design Decisions (Confirmed)

1. **Single job = resolve immediately** (queue empty after 1 job → resolve)
   **Multiple jobs = batch** (keep creating until queue empty or max 10)

2. **Only resolve when queue is empty OR max batch reached**
   - Don't resolve if more jobs are waiting to be created
   - This maximizes batching efficiency

3. **Max batch size = 10**
   - Prevents too many pending accumulating
   - Limits blast radius if resolution fails
   - Still achieves 51%+ time savings

## Open Questions

1. What if V&R is slow to index new listings?
   - **Suggestion**: Retry unmatched jobs in next resolution cycle, fail after 3 attempts

2. Should failed resolutions block new job processing?
   - **Suggestion**: No, process new jobs, retry resolutions periodically

3. Should we add a "stale pending" cleanup?
   - If pending items older than 1 hour, mark as needing manual review
