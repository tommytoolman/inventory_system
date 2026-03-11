# Relist Automation Plan — Phase 2

*Created: 2026-02-16*
*Difficulty: 5/10*
*Prerequisite: Phase 1 (relist detection + activity log) completed 2026-02-16*

## Context

When a product is relisted on one platform (e.g. order cancelled on Reverb, user relists it), the system currently:
- Detects the status change (`sold → live`) via sync
- Logs a `relist_detected` activity event (Phase 1)
- Does **nothing** to reactivate listings on other platforms

The user must manually relist on eBay, Shopify, and VR. This plan describes how to automate that.

## Current State After Phase 1

| What | Status |
|------|--------|
| Detect relist on Reverb sync | Done — `_handle_status_change()` |
| Activity log event | Done — `relist_detected` action |
| Dashboard rendering | Done — shows "Relisted {title} on {PLATFORM}" |
| Shopify reactivation | **Manual** |
| eBay reactivation | **Manual** |
| VR reactivation | **Manual** |

## Phase 2: Automatic Cross-Platform Relisting

### What Needs to Happen

When `_handle_status_change()` detects a relist (sold/ended → live/active):

1. **Update the master product** — set `status=ACTIVE`, `is_sold=False`
2. **Reactivate on each platform** where the product has an ended/archived listing:
   - **Shopify**: Call `shopify_service.relist_listing(external_id)` (already exists, tested)
   - **eBay**: Need to implement — likely `trading_api.relist_item()` or create a new listing
   - **VR**: Need to implement — may require `vr_client.relist_item()` or new creation
3. **Update local DB** — flip `platform_common.status` and platform-specific listing status back to active
4. **Log a consolidated activity event** — `relist_item` at product level with platforms relisted

### Existing Methods That Can Be Used

| Platform | Method | Location | Notes |
|----------|--------|----------|-------|
| Shopify | `relist_listing(external_id, days_since_sold)` | `shopify_service.py:1431` | Sets status to ACTIVE, inventory to 1. Ready to use. |
| eBay | None | — | eBay API supports `RelistFixedPriceItem`. Needs implementing in `trading.py`. |
| VR | None | — | V&R may need a new listing creation rather than reactivation. Check API. |
| Reverb | Not needed | — | Reverb is the source platform in this flow — already relisted by user. |

### Implementation Plan

#### 1. Add `_propagate_relist()` to `sync_services.py`

Mirror of `_propagate_end_listing()` but in reverse:

```python
async def _propagate_relist(
    self,
    product: Product,
    source_platform: str,
    dry_run: bool,
) -> Tuple[List[str], List[str], int]:
    """Reactivate listings on other platforms after a relist is detected."""

    all_links = await self._get_platform_links(product.id)

    for link in all_links:
        if link.platform_name == source_platform:
            continue  # Already relisted
        if link.status == ListingStatus.ACTIVE.value:
            continue  # Already active

        service = self.platform_services.get(link.platform_name)
        if service and hasattr(service, 'relist_listing'):
            await service.relist_listing(link.external_id)
```

#### 2. Add `relist_listing()` to eBay service

```python
async def relist_listing(self, external_id: str) -> bool:
    """Relist an ended eBay item."""
    response = await self.trading_api.relist_fixed_price_item(item_id=external_id)
    # Update local DB
    return True
```

#### 3. Add `relist_listing()` to VR service

Investigate whether V&R supports reactivation or if a new listing must be created.

#### 4. Wire into `_handle_status_change()`

Replace the current "no action" path with:

```python
if raw_old_status in ('sold', 'ended') and new_status == ListingStatus.ACTIVE.value:
    # Update master product
    product.status = ProductStatus.ACTIVE.value
    product.is_sold = False

    # Propagate relist to other platforms
    if not dry_run:
        await self._propagate_relist(product, event.platform_name, dry_run)

    # Log consolidated activity event
    await activity_logger.log_activity(
        action="relist_item",
        entity_type="product",
        entity_id=str(product.id),
        details={...platforms_relisted...}
    )
```

#### 5. Also fix the `shopify_listings.status` sync gap

When `platform_common.status` is updated during sync reconciliation, `shopify_listings.status` (and other platform-specific tables) must also be updated. This is what caused the count mismatch on product 1053.

### Files to Modify

| File | Change |
|------|--------|
| `app/services/sync_services.py` | Add `_propagate_relist()`, wire into `_handle_status_change()` |
| `app/services/ebay_service.py` | Add `relist_listing()` method |
| `app/services/ebay/trading.py` | Add `relist_fixed_price_item()` API call |
| `app/services/vintageandrare/client.py` | Investigate relist capability |
| `app/services/shopify_service.py` | Already has `relist_listing()` — no changes needed |
| `app/routes/dashboard.py` | Add rendering for `relist_item` action |

### Safety Considerations

- Relisting should only trigger from explicit `sold/ended → live` transitions, not other status changes
- Consider adding a configurable flag to enable/disable automatic cross-platform relisting
- eBay has relist limits — check if item is eligible before calling API
- VR relisting may have different semantics than eBay/Shopify — investigate
- Should this update pricing? The product price may have changed since it was originally listed

### Testing

1. End a test product across all platforms
2. Relist it on Reverb
3. Wait for sync to detect the change
4. Verify all other platforms reactivate
5. Verify dashboard shows consolidated relist event
6. Verify all platform counts are correct
