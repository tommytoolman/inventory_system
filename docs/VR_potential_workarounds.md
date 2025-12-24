# V&R (Vintage & Rare) Cloudflare Workarounds

## The Problem

V&R uses Cloudflare protection which blocks automated requests from our server. This affects:
- Brand validation API calls
- Listing creation/updates
- Mark as sold operations
- Item deletion

## Workaround Options

### Option 1: Browser Console (Quick & Manual)

If you're logged into V&R in your browser, you can execute AJAX commands directly from the DevTools console. The browser session already has valid Cloudflare cookies.

#### End/Mark Item as Sold
```javascript
fetch('https://www.vintageandrare.com/ajax/mark_as_sold/' + Math.random(), {
    method: 'POST',
    headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    },
    body: 'product_id=REPLACE_WITH_ITEM_ID'
}).then(r => r.text()).then(result => console.log('Result:', result));
```

#### Delete Item
```javascript
fetch('https://www.vintageandrare.com/ajax/delete_item', {
    method: 'POST',
    headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    },
    body: 'product_id=REPLACE_WITH_ITEM_ID'
}).then(r => r.text()).then(result => console.log('Result:', result));
```

#### Check Brand Exists
```javascript
fetch('https://www.vintageandrare.com/ajax/check_brand_exists', {
    method: 'POST',
    headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    },
    body: 'brand_name=Fender'
}).then(r => r.text()).then(result => console.log('Brand ID:', result));
```

**Responses:**
- `true` = success (for mark_as_sold/delete)
- `false` = failed
- Brand check returns brand ID (integer) or `0` if not found

---

### Option 2: Export Browser Cookies for Local Use

Export cookies from your authenticated browser session and use them in local Python scripts.

#### Step 1: Export Cookies

Run this in browser console while on vintageandrare.com:

```javascript
copy(JSON.stringify(document.cookie.split('; ').map(c => {
    const [name, ...v] = c.split('=');
    return {name, value: v.join('='), domain: '.vintageandrare.com'};
})));
```

Save the clipboard contents to `vr_cookies.json`.

Alternatively, use a browser extension like "Cookie-Editor" to export as JSON.

#### Step 2: Local Python Script

```python
import requests
import json
import random

# Load cookies from exported file
with open('vr_cookies.json', 'r') as f:
    cookies = json.load(f)

session = requests.Session()
for c in cookies:
    session.cookies.set(c['name'], c['value'], domain=c.get('domain', '.vintageandrare.com'))

def end_item(item_id):
    """Mark item as sold/ended on V&R"""
    response = session.post(
        f'https://www.vintageandrare.com/ajax/mark_as_sold/{random.random()}',
        data=f'product_id={item_id}',
        headers={
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Referer': 'https://www.vintageandrare.com/account/items'
        }
    )
    return response.text.strip()

def delete_item(item_id):
    """Permanently delete item from V&R"""
    response = session.post(
        'https://www.vintageandrare.com/ajax/delete_item',
        data=f'product_id={item_id}',
        headers={
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Referer': 'https://www.vintageandrare.com/account/items'
        }
    )
    return response.text.strip()

# Process items
items_to_end = ['12345', '67890']  # Your V&R item IDs

for item_id in items_to_end:
    result = end_item(item_id)
    print(f"Item {item_id}: {result}")
```

---

### Option 3: Query Database for Items Needing Action

Get a list of V&R items that need ending/updating from local database:

```python
from sqlalchemy import create_engine, text

engine = create_engine('postgresql://user:pass@host/db')

with engine.connect() as conn:
    # Items sold locally but not ended on V&R
    result = conn.execute(text("""
        SELECT vl.vr_listing_id, p.brand, p.model
        FROM vr_listings vl
        JOIN platform_common pc ON vl.platform_id = pc.id
        JOIN products p ON pc.product_id = p.id
        WHERE pc.status = 'sold'
        AND vl.vr_state != 'ended'
    """))

    for row in result:
        print(f"Need to end: {row.vr_listing_id} - {row.brand} {row.model}")
```

---

## V&R AJAX Endpoints Reference

| Endpoint | Method | Data | Response |
|----------|--------|------|----------|
| `/ajax/mark_as_sold/{random}` | POST | `product_id={id}` | `true`/`false` |
| `/ajax/delete_item` | POST | `product_id={id}` | `true`/`false` |
| `/ajax/check_brand_exists` | POST | `brand_name={name}` | Brand ID or `0` |
| `/instruments/add_edit_item` | POST | Form data (see below) | Redirect/HTML |

### Add/Edit Item Form Fields

```
recipient_name     = Brand name
model_name         = Model name
year               = Year (e.g., "1965")
finish_color       = Finish/color
price              = Price (numeric)
external_id        = Your SKU/reference
item_desc          = Description (HTML allowed)
category_id        = V&R category ID
condition_id       = V&R condition ID
```

---

## Temporary Fix: Local Brand Validation

Currently deployed (see `app/services/vintageandrare/brand_validator.py`):

```python
# TEMPORARY: Set to True to bypass V&R API and use local DB check instead
# TODO: Set back to False when V&R Cloudflare issues are resolved
USE_LOCAL_DB_CHECK = True
```

This checks the local `products` table for brand existence instead of calling V&R API.

---

## Cookie Expiry

Cloudflare cookies (`cf_clearance`) typically expire after:
- 15-30 minutes of inactivity
- Or when the browser session ends

For sustained automation, consider:
1. Selenium Grid cookie harvesting (already implemented in `harvest_cookies_from_grid`)
2. Regular manual cookie refresh
3. Using the `/api/vr/cookies/harvest` endpoint on Railway

---

## Related Files

- `app/services/vintageandrare/client.py` - Main V&R client with all methods
- `app/services/vintageandrare/brand_validator.py` - Brand validation (with temp local DB fix)
- `app/routes/platforms/vr.py` - API endpoints for V&R operations
- `scripts/vr/vr_cf_cookie_harvest.py` - Standalone cookie harvester
