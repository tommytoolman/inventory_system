# Vintage & Rare (V&R) Integration - Complete Summary

*Last updated: 2025-12-09*

## Non-Technical Overview

**The Problem:** V&R doesn't have a standard API like Reverb or eBay. We can't just send data and get responses - we have to interact with their website like a human would.

**The Solution:** A multi-layered system that:
1. **Downloads inventory** via CSV export (like clicking "Export" on their website)
2. **Creates listings** by filling out their web forms (either via code or automated browser)
3. **Validates brands** by calling their internal AJAX endpoints (the same calls their website makes)
4. **Handles security** by managing cookies and bypassing Cloudflare bot protection

**Key Limitation:** Cookies need periodic refresh (every few months) by manually logging in via a real browser and exporting the session.

---

## Technical Summary

### Communication Methods

| Method | Use Case | Speed | Reliability |
|--------|----------|-------|-------------|
| **curl_cffi** | Primary HTTP/AJAX client | Fast | Good (Chrome TLS fingerprint) |
| **requests** | Fallback HTTP/AJAX | Fast | Lower (blocked more often) |
| **Selenium** | Form filling, cookie harvest | Slow | High (real browser) |

---

## V&R Endpoints We Interact With

### AJAX Endpoints (JSON/Text responses)

These are internal V&R endpoints normally called by their website's JavaScript. We mimic these calls with special headers.

| Endpoint | Method | Request | Response | Purpose |
|----------|--------|---------|----------|---------|
| `/ajax/check_brand_exists` | POST | `{brand_name: "Fender"}` | `"383"` (brand_id) or `"0"` | Brand validation |
| `/ajax/get_suggested_brands_name` | POST | `{term: "Fen"}` | JSON array of suggestions | Brand autocomplete |

**Required Headers for AJAX:**
```python
{
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://www.vintageandrare.com",
    "Referer": "https://www.vintageandrare.com/"
}
```

### Standard HTTP Endpoints (HTML/CSV responses)

| Endpoint | Method | Purpose | Response |
|----------|--------|---------|----------|
| `/do_login` | POST | Authentication | Redirect + session cookie |
| `/instruments/export_inventory/export_inventory` | GET | CSV inventory download | CSV file stream |
| `/instruments/add_edit_item` | GET | Load blank create form | HTML form |
| `/instruments/add_edit_item` | POST | Submit new/edit listing | HTML + redirect |
| `/instruments/add_edit_item/{id}` | GET | Load edit form for item | HTML page |
| `/instruments/show` | GET | View listing (scrape ID) | HTML page |

### Form Submission (Multipart)

For creating/updating listings with images:
```python
# Multipart form data
{
    "recipient_name": "Fender",        # Brand
    "model_name": "Stratocaster",      # Model
    "year": "1965",
    "finish_color": "Sunburst",
    "item_desc": "Description...",
    "price": "5000",
    "external_id": "RIFF-123",         # Our SKU
    "processing_time": "3",            # Days
    "categ_level_0": "51",             # Category IDs
    "categ_level_1": "83",
    "image_1": <file>,                 # Up to 20 images
    "image_2": <file>,
    ...
}
```

---

## File Structure

```
app/services/vintageandrare/
├── client.py           # Main client (auth, download, create, update)
├── brand_validator.py  # Brand checking via AJAX with fallbacks
├── inspect_form.py     # Selenium form automation
├── export.py           # CSV export formatting
├── media_handler.py    # Image download/upload
├── category_map.json   # V&R category hierarchy
└── constants.py        # Shared constants (DEFAULT_VR_BRAND = "Justin")

app/routes/platforms/vr.py    # Our API endpoints
app/services/vr_service.py    # Orchestration layer
app/services/vr_job_queue.py  # Async job queue
app/models/vr.py              # VRListing, VRAcceptedBrand models
app/models/vr_job.py          # VRJob model for queue

scripts/vr_worker.py          # Background worker
scripts/vr/                   # Cookie harvest & utility scripts
├── vr_cf_cookie_harvest.py   # SeleniumBase cookie harvesting
├── export_cookies_for_railway.py  # Base64 encode for Railway
├── check_cookie_expiry.py    # Check cookie expiration
└── ...
```

---

## Our API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/vr/validate-brand` | GET | Check if brand accepted (calls V&R AJAX) |
| `/api/sync/vr` | POST | Trigger inventory download & sync |
| `/api/vr/listings/{id}/end` | POST | Mark listing as sold |
| `/api/vr/listings/{id}/delete` | POST | Delete listing |
| `/api/vr/harvest-cookies` | POST | Trigger cookie refresh via Selenium Grid |
| `/api/vr/harvest-status` | GET | Check harvest progress |
| `/api/vr/cookies-status` | GET | Get current cookies status |

---

## Data Flows

### 1. Download/Sync Flow
```
POST /api/sync/vr
    ↓
Background task starts
    ↓
VintageAndRareClient.authenticate()
    → POST /do_login (with credentials)
    → Handle Cloudflare if needed
    ↓
VintageAndRareClient.download_inventory_dataframe()
    → GET /instruments/export_inventory/export_inventory
    → Stream CSV (180s timeout)
    → Parse to DataFrame
    ↓
VRService.sync_vr_inventory()
    → Compare CSV with database
    → Create/Update/Remove products
    → Log sync_events
```

### 2. Create Listing Flow
```
Enqueue VR job (product_id, payload)
    ↓
vr_worker.py polls queue (every 5s)
    ↓
Validate brand:
    → POST /ajax/check_brand_exists
    → Fallback to local DB if AJAX fails
    → Fallback to known_brands.json
    ↓
Map category:
    → Lookup in category_mappings table
    → Get V&R category IDs (level 0-3)
    ↓
Create listing (choose method):

    HTTP Method (faster):
    → GET /instruments/add_edit_item (extract hidden fields)
    → Download images to temp files
    → POST /instruments/add_edit_item (multipart form)

    Selenium Method (more robust):
    → Launch browser via Selenium Grid
    → Navigate to add form
    → Fill dropdowns, fields, upload images
    → Submit form
    ↓
Extract V&R listing ID from response
    ↓
Save to database (platform_common + vr_listings)
```

### 3. Brand Validation Flow
```
GET /api/vr/validate-brand?brand=Fender
    ↓
Check in-memory cache (TTL: 5 min)
    ↓ (cache miss)
Try V&R AJAX (3s timeout):
    → POST /ajax/check_brand_exists
    → Response: "383" = valid, "0" = not found
    ↓ (if AJAX fails/timeout)
Check local products DB:
    → SELECT COUNT(*) WHERE brand = ?
    ↓ (if not in DB)
Check known_brands.json file
    ↓ (if not found anywhere)
Return {valid: null, error_code: "api_unavailable"}
```

### 4. Update Listing Flow
```
Load edit form:
    → GET /instruments/add_edit_item/{id}
    → Extract all current field values
    ↓
Modify specific fields (price, description, etc.)
    ↓
Submit update:
    → POST /instruments/add_edit_item/{id}
    → Update database records
```

---

## Cloudflare Handling

V&R uses Cloudflare bot protection. We use a three-layer bypass:

| Layer | Method | When Used |
|-------|--------|-----------|
| 1 | Pre-harvested `cf_clearance` cookie | Always (first attempt) |
| 2 | curl_cffi Chrome TLS fingerprint | Combined with layer 1 |
| 3 | Selenium browser automation | Fallback when blocked |

**Detection & Response:**
```python
response = cf_session.get(url)

if response.status_code == 403:
    # Blocked by Cloudflare
    → Try Selenium bootstrap
    → Harvest fresh cookies
    → Retry request

if "cf-mitigated" in response.headers:
    # Challenge required
    → Use Selenium to solve
```

---

## Cookie Management

### Storage Locations

| Environment | Storage | Format |
|-------------|---------|--------|
| **Railway** | `VR_COOKIES_BASE64` env var | Base64 encoded JSON |
| **Local** | `VINTAGE_AND_RARE_COOKIES_FILE` | JSON file path |

### Cookie Structure
```json
[
  {
    "name": "cf_clearance",
    "value": "long_encrypted_token",
    "domain": ".vintageandrare.com",
    "expiry": 1735689600
  },
  {
    "name": "PHPSESSID",
    "value": "session_id",
    "domain": "www.vintageandrare.com"
  }
]
```

### Refresh Process
```bash
# 1. Harvest cookies locally (opens browser)
python scripts/vr/vr_cf_cookie_harvest.py

# 2. Export for Railway
python scripts/vr/export_cookies_for_railway.py

# 3. Update Railway env var with base64 string

# 4. Redeploy application
```

---

## Job Queue System

**Table:** `vr_jobs`

| Field | Type | Purpose |
|-------|------|---------|
| `id` | int | Primary key |
| `product_id` | FK | Link to product |
| `payload` | JSONB | Job data (enriched_data, options, etc.) |
| `status` | enum | queued / in_progress / completed / failed |
| `attempts` | int | Retry counter |
| `error_message` | text | Last error if failed |

**Worker Loop:**
```python
while True:
    job = fetch_next_queued_job()  # SELECT ... FOR UPDATE SKIP LOCKED
    if job:
        mark_job_in_progress(job)
        try:
            process_job(job)
            mark_job_completed(job)
        except Exception as e:
            mark_job_failed(job, str(e))
    sleep(5)  # Poll interval
```

---

## Environment Variables

```bash
# Credentials
VINTAGE_AND_RARE_USERNAME=your_username
VINTAGE_AND_RARE_PASSWORD=your_password

# Cookies
VR_COOKIES_BASE64=eyJm...              # Railway (base64)
VINTAGE_AND_RARE_COOKIES_FILE=/path/to/cookies.json  # Local

# Selenium
SELENIUM_GRID_URL=http://localhost:4444
VR_USE_UDC=1                           # Use undetected-chromedriver
VR_HEADLESS=true                       # Run headless

# Brand Validation
VR_BRAND_TIMEOUT=3.0                   # AJAX timeout (seconds)
VR_BRAND_CACHE_TTL=300                 # Cache TTL (seconds)
VR_BRAND_CACHE_MAX=200                 # Max cached brands
VR_KNOWN_BRANDS_FILE=/tmp/vr_known_brands.json

# Worker
VR_WORKER_POLL_INTERVAL=5              # Seconds between polls
VR_WORKER_LOG_LEVEL=INFO

# User Agent (for all requests)
VR_USER_AGENT=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36...
```

---

## Summary Table

| Component | Technology | V&R Interaction |
|-----------|------------|-----------------|
| **Brand Validation** | AJAX POST | `/ajax/check_brand_exists` |
| **Brand Suggestions** | AJAX POST | `/ajax/get_suggested_brands_name` |
| **Authentication** | HTTP POST | `/do_login` |
| **Inventory Download** | HTTP GET (stream) | `/instruments/export_inventory/...` |
| **Create Listing** | HTTP POST (multipart) | `/instruments/add_edit_item` |
| **Create Listing** | Selenium | Form automation |
| **Update Listing** | HTTP POST | `/instruments/add_edit_item/{id}` |
| **Cloudflare Bypass** | curl_cffi + cookies | TLS fingerprint impersonation |
| **Cookie Harvest** | Selenium | Browser automation |
