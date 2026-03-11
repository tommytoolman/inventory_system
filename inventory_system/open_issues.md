⏺ Summary of Open Issues

  1. eBay Shipping Mismatch (Critical)

  - Problem: The sync service and inventory route use completely different approaches for eBay listings
  - Inventory Route (List Item button): Uses use_shipping_profile=True with hardcoded Business Policy IDs - WORKS
  - Sync Service (process_sync_event.py): Uses use_shipping_profile=False trying to map Reverb shipping inline -
  FAILS
  - Solution needed: Either:
    - Update sync service to use Business Policies like the inventory route
    - Fix the inline shipping mapping to meet eBay's requirements
    - Make policy IDs configurable in settings rather than hardcoded

  2. STATS Updates During Sync

  - Problem: Platform stats (views, watches, offers) aren't being updated during regular syncs
  - Available data:
    - Reverb: view_count, watch_count
    - eBay: WatchCount
    - VR: stats: {views: 257, watches: 26}
    - Shopify: Likely available via GraphQL
  - Solution needed: Implement "silent" sync that updates stats without creating sync events

  3. VR Reconciliation Failure

  - Problem: VR listings are created successfully but reconciliation can't find the VR ID
  - From your test: "Created successfully but reconciliation failed to find the VR ID"
  - Solution needed: Fix the VR service to properly capture and store the listing ID after creation
  - I THINK WE NEED A RETRY AS SOMETIMES VR IS FUCKED

  4. Product Update Sync

  - Problem: Editing product details doesn't sync changes to platforms
  - Current state: Edit UI works but platform sync is disabled due to errors
  - Solution needed: Implement proper update sync that pushes changes to all platforms

  5. eBay ItemSpecifics for Niche Categories

  - Problem: Special categories require specific fields that aren't being handled
  - Example: Musical instruments need specific attributes
  - Solution needed: Category-specific ItemSpecifics mapping

  6. Configuration Management

  - Problem: Business Policy IDs are hardcoded in the inventory route
  - Current: shipping_profile_id: '252277357017' etc.
  - Solution needed: Move these to configuration settings

  The most critical issue is #1 - the eBay shipping mismatch that's preventing listings from being created via the
  sync process.

⏺ Low Priority Backlog

  - Status badge consolidation
    - Problem: `inventory/list.html` and `inventory/detail.html` both define their own Tailwind class stacks for
      status “bubbles,” which makes future palette/size tweaks repetitive.
    - Idea: Extract a shared Jinja macro or shared CSS utility classes so badges inherit the same base style with a
      single change point.
