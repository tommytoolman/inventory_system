#!/usr/bin/env python3
"""
Batch apply the sold-product template to all Shopify listings that are
already sold/archived/ended but still showing the default template.

Excludes is_stocked_item=true products (stocked items de-increment, not sell out).

Usage:
    source venv/bin/activate
    python scripts/shopify_batch_apply_sold_template.py --dry-run   # Preview only
    python scripts/shopify_batch_apply_sold_template.py             # Apply changes
    python scripts/shopify_batch_apply_sold_template.py --limit 10  # Apply first 10 only
"""

import os
import sys
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.core.config import Settings
from app.services.shopify.client import ShopifyGraphQLClient


SOLD_TEMPLATE = "sold-product"


def get_db_engine():
    settings = Settings()
    db_url = (str(settings.DATABASE_URL)
              .replace("postgresql+asyncpg", "postgresql+psycopg2")
              .replace("asyncpg", "psycopg2"))
    return create_engine(db_url)


def fetch_candidates(engine, limit=None):
    """Fetch all sold non-stocked Shopify listings from RIFF DB.

    Sold is determined at the product level:
      - p.is_sold = true  (boolean, most reliable)
      - OR UPPER(p.status) IN ('SOLD', 'ARCHIVED')

    Shopify listing status is checked case-insensitively to handle the mixed
    casing found in the DB ('archived', 'ARCHIVED', 'sold', 'ended', etc.).
    We include ACTIVE listings too — some items sold elsewhere haven't had
    their Shopify status updated yet (inventory 0, still showing active).
    """
    query = text("""
        SELECT
            p.id            AS product_id,
            p.sku,
            p.brand,
            p.model,
            p.is_sold,
            p.status        AS product_status,
            pc.status       AS pc_status,
            pc.external_id  AS shopify_legacy_id,
            sl.status       AS shopify_db_status
        FROM products p
        JOIN platform_common pc
            ON pc.product_id = p.id
            AND pc.platform_name = 'shopify'
        JOIN shopify_listings sl
            ON sl.platform_id = pc.id
        WHERE (
            p.is_sold = true
            OR UPPER(p.status::text) IN ('SOLD', 'ARCHIVED')
            OR LOWER(pc.status::text) IN ('sold', 'ended', 'archived')
            OR LOWER(sl.status::text) IN ('sold', 'ended', 'archived')
        )
          AND p.is_stocked_item IS NOT TRUE
          AND pc.external_id IS NOT NULL
        ORDER BY p.id DESC
        LIMIT :lim
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"lim": limit or 99999}).fetchall()
    return rows


def get_current_template(client: ShopifyGraphQLClient, product_gid: str) -> str | None:
    """Fetch the current templateSuffix from Shopify."""
    query = """
    query getProduct($id: ID!) {
      product(id: $id) {
        templateSuffix
      }
    }
    """
    data = client._make_request(query, {"id": product_gid}, estimated_cost=5)
    if data and data.get("product"):
        return data["product"].get("templateSuffix") or ""
    return None


def apply_template(client: ShopifyGraphQLClient, product_gid: str) -> bool:
    """Apply the sold-product template via productUpdate."""
    result = client.update_product({
        "id": product_gid,
        "templateSuffix": SOLD_TEMPLATE,
    })
    return bool(result and result.get("product"))


def main():
    parser = argparse.ArgumentParser(description="Batch apply sold-product Shopify template")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview candidates, no changes made")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N items (useful for staged rollout)")
    parser.add_argument("--skip-check", action="store_true",
                        help="Skip fetching current template (faster, but re-applies even if already set)")
    args = parser.parse_args()

    print(f"\n── Shopify Batch Sold Template ──────────────────────────────")
    print(f"  Mode     : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"  Limit    : {args.limit or 'all'}")
    print(f"  Template : {SOLD_TEMPLATE}")
    print(f"  Started  : {datetime.now().strftime('%d %b %Y %H:%M')}\n")

    engine = fetch_candidates_engine = get_db_engine()
    candidates = fetch_candidates(engine, limit=args.limit)
    print(f"  Candidates from RIFF DB: {len(candidates)}")

    if not candidates:
        print("  Nothing to do.")
        return

    if args.dry_run:
        print(f"\n  [DRY RUN] Would process {len(candidates)} items:\n")
        for row in candidates[:20]:
            print(f"    product {row.product_id:>5} | {row.sku:<20} | is_sold={row.is_sold} | p.status={row.product_status} | pc.status={row.pc_status} | sl.status={row.shopify_db_status} | shopify_id={row.shopify_legacy_id}")
        if len(candidates) > 20:
            print(f"    ... and {len(candidates) - 20} more")
        print(f"\n  [DRY RUN] No changes made.")
        return

    client = ShopifyGraphQLClient()

    applied = 0
    skipped = 0
    failed = 0
    errors = []

    for i, row in enumerate(candidates, 1):
        product_gid = f"gid://shopify/Product/{row.shopify_legacy_id}"
        label = f"product {row.product_id} ({row.sku}) / Shopify {row.shopify_legacy_id}"

        # Optionally check current template to skip already-set items
        if not args.skip_check:
            current = get_current_template(client, product_gid)
            if current is None:
                print(f"  [{i}/{len(candidates)}] SKIP (not found on Shopify): {label}")
                skipped += 1
                continue
            if current == SOLD_TEMPLATE:
                print(f"  [{i}/{len(candidates)}] SKIP (already set): {label}")
                skipped += 1
                continue

        success = apply_template(client, product_gid)
        if success:
            print(f"  [{i}/{len(candidates)}] OK : {label}")
            applied += 1
        else:
            print(f"  [{i}/{len(candidates)}] FAIL: {label}")
            failed += 1
            errors.append(label)

        # Small pause every 50 items to be kind to rate limits
        if i % 50 == 0:
            print(f"  ... pausing briefly ...")
            time.sleep(2)

    print(f"\n{'='*60}")
    print(f"  DONE — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"  Applied : {applied}")
    print(f"  Skipped : {skipped}  (already correct or not found)")
    print(f"  Failed  : {failed}")
    if errors:
        print(f"\n  Failures:")
        for e in errors:
            print(f"    {e}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
