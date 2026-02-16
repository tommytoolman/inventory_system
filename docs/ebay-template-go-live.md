# eBay Template Go-Live — CrazyLister Deprecation Plan

*Created: 2026-02-16*
*Difficulty: 4/10 — template already built, mostly wiring and testing*

## Current State

The RIFF eBay listing template (`app/templates/ebay/listing_template.html`) is fully functional in **preview mode** at `/inventory/product/{id}/ebay-template-preview`. It includes:
- CSS-only image gallery with lightbox (checkbox hack — no JS)
- Artist Owned badge (conditional, with `mix-blend-mode: multiply`)
- Description auto-formatting (`_clean_ebay_description_html()`)
- Payment / Shipping / Returns tabs
- Mobile responsive layout
- Schema.org structured data

It is **not yet wired** into `create_listing_from_product()` or used to revise existing listings.

---

## Steps to Go Live

### Step 1: Host Badge Image Publicly

eBay descriptions render on `ebay.com` — they cannot load images from localhost or internal Railway paths. The `artist_badge_url` needs a publicly accessible HTTPS URL.

**Options (pick one):**
| Option | Pros | Cons |
|--------|------|------|
| Upload to existing image host (Reverb CDN, S3, etc.) | Simple, fast CDN delivery | Another asset to manage |
| Base64 data URI inlined in HTML | Zero external dependencies, fully self-contained | Adds ~1-1.5MB to description payload |
| Railway public static URL (`https://your-app.railway.app/static/ebay/...`) | Already there if Railway serves static files | Tied to Railway domain; if domain changes, badge breaks |

**Recommendation:** Base64 data URI is the most robust — no external dependency, survives domain changes, works offline.

### Step 2: Test `mix-blend-mode` on eBay

eBay's HTML sandbox may strip or ignore `mix-blend-mode: multiply`. Test by:
1. Creating a test listing with the badge using `mix-blend-mode`
2. If it renders correctly — done
3. If the checkerboard shows — need a properly transparent PNG (true alpha, no baked-in checkerboard)

### Step 3: Audit eBay Active Content Compliance

eBay bans "active content" (JS, forms, some external resources). The template is mostly compliant but needs checking:

| Element | Status | Action Needed |
|---------|--------|---------------|
| CSS-only gallery (radio/checkbox hack) | Likely OK | Test — eBay has allowed this recently |
| CSS-only tabs (radio hack) | Likely OK | Test alongside gallery |
| Google Fonts `<link>` tag | May be blocked | Move to `@import` inside `<style>`, or accept system font fallback |
| External images (CrazyLister CDN) | Will break eventually | Self-host banner, header logo, footer images |
| `position: fixed` (lightbox) | Will be stripped | Accept lightbox is preview-only; gallery still works without it |
| `<input>` elements | May be stripped | Test — if stripped, gallery falls back to showing first image only |

### Step 4: Wire Template into `create_listing_from_product()`

**File:** `app/services/ebay_service.py` — `create_listing_from_product()` (~line 1624)

Currently this method builds description HTML directly. Change to:
1. Render `ebay/listing_template.html` via Jinja2 with the same context as the preview route
2. Set `preview_mode=False` (strips the preview toolbar)
3. Pass publicly-hosted `artist_badge_url`
4. Run `_clean_ebay_description_html()` on the product description before template rendering
5. Use the full rendered HTML as the `Description` field in `AddFixedPriceItem`

```python
# Pseudocode for the wiring
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("app/templates"))
template = env.get_template("ebay/listing_template.html")

description_html = _clean_ebay_description_html(product.description or "")
rendered = template.render(
    product=product,
    images=image_urls,
    description_html=description_html,
    description_plain=strip_tags(description_html),
    preview_mode=False,
    artist_badge_url="https://...",  # public URL or data URI
)

# Use `rendered` as the eBay Description field
```

### Step 5: Test with a Single New Listing

Before batch migration:
1. Pick a product (ideally one with artist_owned=True for full coverage)
2. Create a new eBay listing via the UI with the template-rendered description
3. Check rendering on:
   - eBay desktop (Chrome, Firefox, Safari)
   - eBay mobile app
   - eBay mobile web
4. Verify: gallery works, tabs work, images load, badge renders, fonts look acceptable

### Step 6: Batch-Revise Existing CrazyLister Listings

Once the template is validated:
1. Use `trading_api.revise_fixed_price_item()` to update the `Description` field on existing listings
2. Target CrazyLister listings first (already flagged via HTML marker detection)
3. Run in batches of 10-20, check results between batches
4. Script pattern:
   ```python
   for listing in crazylister_listings:
       rendered_html = render_template_for(listing.product)
       trading_api.revise_fixed_price_item(
           item_id=listing.ebay_item_id,
           Description=rendered_html,
       )
   ```

### Step 7: Self-Host Remaining External Images

The template currently references CrazyLister CDN for:
- Header logo (`lvg-header-logo img`)
- Banner image (`lvg-banner img`)
- Footer logo (`lvg-footer-logo img`)
- Shop photo (`lvg-shop-section img`)

These are marked with `<!-- TODO: Self-host this image -->` in the template. Download and host locally (or base64 encode) before CrazyLister CDN goes away.

---

## Order of Operations

```
1. Host badge image publicly              [30 min]
2. Test mix-blend-mode on eBay            [30 min]
3. Self-host external images (4 images)   [1 hour]
4. eBay Active Content audit + test       [1-2 hours]
5. Wire template into create_listing      [1-2 hours]
6. Test with single new listing           [30 min]
7. Pilot batch (10 listings)              [1 hour]
8. Full batch migration                   [1-2 hours]
```

**Total estimated effort: ~1-2 sessions**

---

## Rollback

If something goes wrong after batch migration:
- eBay `ReviseFixedPriceItem` can update descriptions again at any time
- Old CrazyLister HTML could be restored from product description history (if logged)
- Individual listings can be manually edited on eBay as a stopgap

## Files Involved

| File | Change |
|------|--------|
| `app/services/ebay_service.py` | Wire template rendering into `create_listing_from_product()` |
| `app/templates/ebay/listing_template.html` | Possibly inline fonts, self-host images |
| `app/routes/inventory.py` | `_clean_ebay_description_html()` may need moving to shared utils |
| New batch script | `scripts/ebay/migrate_crazylister.py` for batch revision |
