# V&R Cookie Refresh Process

V&R (Vintage & Rare) uses Cloudflare's bot protection which requires special handling. This document explains how to refresh cookies when V&R operations start failing.

## Background

Cloudflare validates requests using:
1. **cf_clearance cookie** - A long-lived token (valid ~1 year) that proves you passed a Cloudflare challenge
2. **TLS fingerprint** - Cloudflare checks if your HTTP client looks like a real browser

We use `curl_cffi` library which impersonates Chrome's TLS fingerprint, combined with a valid `cf_clearance` cookie harvested from a real browser.

## When to Refresh

Refresh cookies when you see:
- 403 errors from V&R
- `cf-mitigated: challenge` header in responses
- Authentication failures despite correct credentials

The cf_clearance cookie typically lasts **~1 year**, so refreshes should be rare.

## Refresh Process

### Step 1: Harvest Fresh Cookies (Local)

Run this on your local machine (requires Chrome):

```bash
cd /path/to/inventory_system
source venv/bin/activate
python scripts/vr/harvest_and_test_curl_cffi.py
```

This will:
1. Open a visible Chrome browser
2. Navigate to V&R and auto-solve Cloudflare challenge
3. Auto-login (or wait for manual login)
4. Save cookies to `scripts/vr/output/vr_cookies.json`
5. Test if curl_cffi can use the cookies

### Step 2: Export for Railway

```bash
python scripts/vr/export_cookies_for_railway.py
```

This creates:
- `scripts/vr/output/vr_cookies_base64.txt` - Minimal cookies (recommended)
- `scripts/vr/output/vr_cookies_full_base64.txt` - All cookies

### Step 3: Update Railway

1. Copy contents of `vr_cookies_base64.txt`
2. Go to Railway Dashboard → Your Service → Variables
3. Update `VR_COOKIES_BASE64` with the new value
4. Redeploy

## Environment Variables

| Variable | Description | Where |
|----------|-------------|-------|
| `VR_COOKIES_BASE64` | Base64-encoded cookies | Railway |
| `VINTAGE_AND_RARE_COOKIES_FILE` | Path to JSON file | Local dev only |
| `VINTAGE_AND_RARE_USERNAME` | V&R login username | Both |
| `VINTAGE_AND_RARE_PASSWORD` | V&R login password | Both |

## How It Works

1. **Cookie Loading**: On startup, the client loads cookies from `VR_COOKIES_BASE64` (Railway) or `VINTAGE_AND_RARE_COOKIES_FILE` (local)

2. **Cloudflare Bypass**: The `cf_clearance` cookie, combined with curl_cffi's Chrome TLS fingerprint, bypasses Cloudflare

3. **Fresh Login**: We always perform a fresh login to get a new session (PHPSESSID), so the harvested cookies don't need to include an active session

## Troubleshooting

### "Still getting 403 after refresh"

The cf_clearance may be tied to your IP range. Try:
1. Re-harvest cookies from the same network as Railway (unlikely to help)
2. Check if V&R changed their Cloudflare settings
3. Verify curl_cffi is installed: `pip install curl_cffi`

### "Browser closes too fast during harvest"

The harvest script waits for Cloudflare automatically. If login fails:
1. The script waits 45 seconds for manual login
2. Make sure you complete login before the timeout

### "curl_cffi not working"

Ensure it's installed:
```bash
pip install curl_cffi>=0.5.0
```

Check it's in requirements.txt and deployed to Railway.

## Files Reference

| File | Purpose |
|------|---------|
| `app/services/vintageandrare/client.py` | Main V&R client with curl_cffi support |
| `scripts/vr/harvest_and_test_curl_cffi.py` | Cookie harvesting script |
| `scripts/vr/export_cookies_for_railway.py` | Export cookies as base64 |
| `scripts/vr/check_cookie_expiry.py` | Check when cookies expire |
| `scripts/vr/output/vr_cookies.json` | Harvested cookies (JSON) |
| `scripts/vr/output/vr_cookies_base64.txt` | Cookies for Railway (base64) |
