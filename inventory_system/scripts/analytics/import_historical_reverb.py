#!/usr/bin/env python3
"""
Import Historical Reverb Data for Analytics

This script imports historical Reverb listings into the reverb_historical_listings
table for velocity analysis and pricing benchmarks.

Data Sources (in priority order for date accuracy):
1. reverb_orders table - exact paid_at timestamps for sold items
2. sync_events table - detected_at timestamps for recent status changes
3. Snapshot comparisons - triangulate transitions between dated snapshots
4. CSV snapshot data - use snapshot date as upper bound for ended items

Usage:
    python scripts/analytics/import_historical_reverb.py --dry-run
    python scripts/analytics/import_historical_reverb.py --import
    python scripts/analytics/import_historical_reverb.py --import --skip-live
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime, date, timezone
from pathlib import Path
import pandas as pd
import json
from typing import Optional, Dict, List, Tuple, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import async_session
from app.models.reverb_historical import ReverbHistoricalListing
from sqlalchemy import text, select
from sqlalchemy.dialects.postgresql import insert


# Data source paths
BROKEN_REPO = Path("/Users/wommy/Documents/GitHub/PROJECTS/HANKS/inventory_system_broken_1763825305")
DATA_DIR = BROKEN_REPO / "data" / "reverb"

# Snapshot files with dates
SNAPSHOTS = [
    (DATA_DIR / "reverb_listings_all_detailed_20251110_081256.csv", date(2025, 11, 10)),
    (DATA_DIR / "reverb_listings_all_20250926_121649.csv", date(2025, 9, 26)),
    (DATA_DIR / "reverb_listings_live_20250812_160709.csv", date(2025, 8, 12)),
]


def parse_state(state_str: str) -> Optional[str]:
    """Extract state slug from Reverb state dict string."""
    try:
        if pd.isna(state_str):
            return None
        d = eval(state_str)
        return d.get('slug')
    except:
        return str(state_str) if state_str else None


def parse_stats(stats_str: str) -> Tuple[int, int]:
    """Extract views and watches from stats dict string."""
    try:
        if pd.isna(stats_str):
            return 0, 0
        d = eval(stats_str)
        return d.get('views', 0), d.get('watches', 0)
    except:
        return 0, 0


def parse_categories(cat_str: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract full and root category from categories list string."""
    try:
        if pd.isna(cat_str):
            return None, None
        cats = eval(cat_str)
        if cats and len(cats) > 0:
            full_name = cats[0].get('full_name', '')
            root = full_name.split(' / ')[0] if full_name else None
            return full_name, root
    except:
        pass
    return None, None


def parse_condition(cond_str: str) -> Optional[str]:
    """Extract condition display name from condition dict string."""
    try:
        if pd.isna(cond_str):
            return None
        d = eval(cond_str)
        return d.get('display_name')
    except:
        return str(cond_str) if cond_str else None


def parse_price(price_val) -> Optional[float]:
    """Parse price from various formats."""
    try:
        if pd.isna(price_val):
            return None
        if isinstance(price_val, (int, float)):
            return float(price_val)
        if isinstance(price_val, str):
            # Try to parse as dict
            if price_val.startswith('{'):
                d = eval(price_val)
                return float(d.get('amount', 0))
            # Try direct parse
            return float(price_val.replace(',', '').replace('£', '').replace('$', ''))
    except:
        pass
    return None


def parse_datetime(dt_str: str) -> Optional[datetime]:
    """Parse datetime from ISO format string. Returns naive datetime."""
    try:
        if pd.isna(dt_str):
            return None
        # Handle various ISO formats - strip timezone info for consistency
        dt_str = str(dt_str)
        # Remove timezone suffixes
        for tz in ['+00:00', '+01:00', '+02:00', 'Z']:
            dt_str = dt_str.replace(tz, '')
        if 'T' in dt_str:
            return datetime.fromisoformat(dt_str)
        return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    except:
        return None


def make_naive(dt) -> Optional[datetime]:
    """Convert datetime to naive (no timezone) for consistent comparisons."""
    if dt is None:
        return None
    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def clean_string(val) -> Optional[str]:
    """Clean a value for string fields - handle NaN and convert to string."""
    if val is None:
        return None
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s.lower() in ('nan', 'none', 'null', ''):
        return None
    return s


async def get_order_dates(db) -> Dict[str, datetime]:
    """Get paid_at dates from reverb_orders table."""
    result = await db.execute(text('''
        SELECT reverb_listing_id::text, paid_at
        FROM reverb_orders
        WHERE reverb_listing_id IS NOT NULL AND paid_at IS NOT NULL
    '''))
    return {str(row[0]): make_naive(row[1]) for row in result.fetchall()}


async def get_sync_event_dates(db) -> Tuple[Dict[str, datetime], Dict[str, datetime]]:
    """Get detected_at dates from sync_events for status changes."""
    # Sold events
    result = await db.execute(text('''
        SELECT external_id, detected_at
        FROM sync_events
        WHERE platform_name = 'reverb'
        AND change_type = 'status_change'
        AND change_data::text LIKE '%sold%'
        AND external_id IS NOT NULL
    '''))
    sold_dates = {str(row[0]): make_naive(row[1]) for row in result.fetchall()}

    # Ended events
    result = await db.execute(text('''
        SELECT external_id, detected_at
        FROM sync_events
        WHERE platform_name = 'reverb'
        AND change_type = 'status_change'
        AND change_data::text LIKE '%ended%'
        AND external_id IS NOT NULL
    '''))
    ended_dates = {str(row[0]): make_naive(row[1]) for row in result.fetchall()}

    return sold_dates, ended_dates


def load_snapshot(path: Path) -> pd.DataFrame:
    """Load a Reverb snapshot CSV."""
    if not path.exists():
        print(f"  Warning: Snapshot not found: {path}")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df['id'] = df['id'].astype(str)
    df['state_slug'] = df['state'].apply(parse_state)
    return df


def find_transitions(older: pd.DataFrame, newer: pd.DataFrame,
                    older_date: date, newer_date: date) -> Dict[str, Dict]:
    """Find state transitions between two snapshots."""
    transitions = {}

    if older.empty or newer.empty:
        return transitions

    # Merge on ID
    merged = newer.merge(
        older[['id', 'state_slug']],
        on='id',
        how='left',
        suffixes=('_new', '_old')
    )

    for _, row in merged.iterrows():
        old_state = row.get('state_slug_old')
        new_state = row.get('state_slug_new')

        if pd.isna(old_state):
            # New item
            continue

        if old_state != new_state:
            listing_id = str(row['id'])
            # Use midpoint between snapshots as estimated transition date
            midpoint = older_date + (newer_date - older_date) / 2

            transitions[listing_id] = {
                'from_state': old_state,
                'to_state': new_state,
                'estimated_date': midpoint,
                'date_range': (older_date, newer_date)
            }

    return transitions


async def get_existing_ids(db) -> set:
    """Get IDs already in the historical table."""
    result = await db.execute(text(
        "SELECT reverb_listing_id FROM reverb_historical_listings"
    ))
    return {str(row[0]) for row in result.fetchall()}


async def get_active_listing_ids(db) -> set:
    """Get Reverb listing IDs from active inventory."""
    result = await db.execute(text('''
        SELECT rl.reverb_listing_id
        FROM reverb_listings rl
        JOIN platform_common pc ON rl.platform_id = pc.id
        WHERE pc.status = 'active'
    '''))
    return {str(row[0]) for row in result.fetchall()}


def prepare_record(row: pd.Series,
                  order_dates: Dict[str, datetime],
                  sold_event_dates: Dict[str, datetime],
                  ended_event_dates: Dict[str, datetime],
                  transitions: Dict[str, Dict],
                  snapshot_date: date) -> Dict[str, Any]:
    """Prepare a historical listing record from a CSV row."""
    listing_id = str(row['id'])
    state = parse_state(row.get('state'))
    views, watches = parse_stats(row.get('stats', '{}'))
    category_full, category_root = parse_categories(row.get('categories'))
    created_at = make_naive(parse_datetime(row.get('created_at')))

    # Determine outcome
    outcome = state  # 'sold', 'ended', 'live', 'draft'

    # Determine sold_at and ended_at
    sold_at = None
    ended_at = None

    if state == 'sold':
        # Priority 1: Check order dates
        if listing_id in order_dates:
            sold_at = order_dates[listing_id]
        # Priority 2: Check sync event dates
        elif listing_id in sold_event_dates:
            sold_at = sold_event_dates[listing_id]
        # Priority 3: Check transitions
        elif listing_id in transitions:
            trans = transitions[listing_id]
            if trans['to_state'] == 'sold':
                sold_at = datetime.combine(trans['estimated_date'], datetime.min.time())
        # Priority 4: Use snapshot date as upper bound
        else:
            # We know it was sold by snapshot_date, but don't know exactly when
            pass

        ended_at = sold_at  # For sold items, ended_at = sold_at

    elif state == 'ended':
        # Priority 1: Check sync event dates
        if listing_id in ended_event_dates:
            ended_at = ended_event_dates[listing_id]
        # Priority 2: Check transitions
        elif listing_id in transitions:
            trans = transitions[listing_id]
            if trans['to_state'] == 'ended':
                ended_at = datetime.combine(trans['estimated_date'], datetime.min.time())
        # Priority 3: Use snapshot date as upper bound
        else:
            # We know it was ended by snapshot_date
            ended_at = datetime.combine(snapshot_date, datetime.min.time())

    # Calculate days_listed and days_to_sell
    days_listed = None
    days_to_sell = None

    if created_at:
        if ended_at:
            days_listed = (ended_at - created_at).days
        elif state in ('sold', 'ended'):
            # Use snapshot date as upper bound
            days_listed = (datetime.combine(snapshot_date, datetime.min.time()) - created_at).days

        if sold_at:
            days_to_sell = (sold_at - created_at).days

    # Parse prices
    final_price = parse_price(row.get('price'))
    original_price = parse_price(row.get('original_price'))

    # Calculate price reduction
    price_drops = 0
    total_price_reduction = None
    price_reduction_pct = None

    if original_price and final_price and original_price > final_price:
        price_drops = 1  # We know at least one price drop occurred
        total_price_reduction = original_price - final_price
        price_reduction_pct = (total_price_reduction / original_price) * 100

    # Get primary image
    primary_image = None
    image_count = 0
    photos = row.get('photos')
    if not pd.isna(photos):
        try:
            photo_list = eval(photos) if isinstance(photos, str) else photos
            if photo_list:
                image_count = len(photo_list)
                if isinstance(photo_list[0], dict):
                    primary_image = photo_list[0].get('_links', {}).get('large_crop', {}).get('href')
                else:
                    primary_image = str(photo_list[0])
        except:
            pass

    return {
        'reverb_listing_id': listing_id,
        'title': clean_string(row.get('title')),
        'sku': clean_string(row.get('sku')),
        'brand': clean_string(row.get('make')),
        'model': clean_string(row.get('model')),
        'category_full': clean_string(category_full),
        'category_root': clean_string(category_root),
        'condition': clean_string(parse_condition(row.get('condition'))),
        'year': clean_string(row.get('year')),
        'finish': clean_string(row.get('finish')),
        'original_price': original_price if original_price and not pd.isna(original_price) else None,
        'final_price': final_price if final_price and not pd.isna(final_price) else None,
        'currency': clean_string(row.get('listing_currency')) or 'GBP',
        'created_at': created_at,
        'sold_at': sold_at,
        'ended_at': ended_at,
        'outcome': clean_string(outcome),
        'days_listed': int(days_listed) if days_listed is not None and not pd.isna(days_listed) else None,
        'days_to_sell': int(days_to_sell) if days_to_sell is not None and not pd.isna(days_to_sell) else None,
        'view_count': int(views) if views and not pd.isna(views) else 0,
        'watch_count': int(watches) if watches and not pd.isna(watches) else 0,
        'offer_count': int(row.get('offer_count', 0)) if not pd.isna(row.get('offer_count', 0)) else 0,
        'price_drops': int(price_drops) if price_drops is not None else 0,
        'total_price_reduction': total_price_reduction if total_price_reduction and not pd.isna(total_price_reduction) else None,
        'price_reduction_pct': price_reduction_pct if price_reduction_pct and not pd.isna(price_reduction_pct) else None,
        'primary_image': clean_string(primary_image),
        'image_count': int(image_count) if image_count and not pd.isna(image_count) else 0,
        'shop_id': clean_string(row.get('shop_id')),
        'shop_name': clean_string(row.get('shop_name')),
        'raw_data': None,  # Optionally store full row as JSON
        'imported_at': datetime.now(timezone.utc).replace(tzinfo=None),
        'updated_at': datetime.now(timezone.utc).replace(tzinfo=None),
    }


async def import_historical_data(dry_run: bool = True, skip_live: bool = True):
    """Main import function."""
    print("=" * 60)
    print("Historical Reverb Data Import")
    print("=" * 60)

    if dry_run:
        print("\n*** DRY RUN MODE - No data will be written ***\n")

    # Load primary snapshot (most detailed)
    primary_path, primary_date = SNAPSHOTS[0]
    print(f"\n1. Loading primary snapshot: {primary_path.name}")
    primary_df = load_snapshot(primary_path)
    print(f"   Loaded {len(primary_df)} listings")

    # Load secondary snapshots for triangulation
    print("\n2. Loading secondary snapshots for triangulation...")
    secondary_dfs = []
    for path, snap_date in SNAPSHOTS[1:]:
        df = load_snapshot(path)
        if not df.empty:
            print(f"   {snap_date}: {len(df)} listings")
            secondary_dfs.append((df, snap_date))

    # Find transitions between snapshots
    print("\n3. Analyzing state transitions between snapshots...")
    all_transitions = {}

    # Compare primary with each secondary
    for sec_df, sec_date in secondary_dfs:
        transitions = find_transitions(sec_df, primary_df, sec_date, primary_date)
        print(f"   {sec_date} → {primary_date}: {len(transitions)} transitions")
        all_transitions.update(transitions)

    # Get database date sources
    print("\n4. Loading precise dates from database...")
    async with async_session() as db:
        order_dates = await get_order_dates(db)
        print(f"   Reverb orders with paid_at: {len(order_dates)}")

        sold_event_dates, ended_event_dates = await get_sync_event_dates(db)
        print(f"   Sync events (sold): {len(sold_event_dates)}")
        print(f"   Sync events (ended): {len(ended_event_dates)}")

        existing_ids = await get_existing_ids(db)
        print(f"   Already in historical table: {len(existing_ids)}")

        active_ids = await get_active_listing_ids(db) if skip_live else set()
        print(f"   Active listings (will skip): {len(active_ids)}")

    # Filter and prepare records
    print("\n5. Preparing records for import...")

    state_counts = primary_df['state_slug'].value_counts().to_dict()
    print(f"   States in snapshot: {state_counts}")

    records_to_import = []
    skipped = {'existing': 0, 'active': 0, 'live': 0, 'draft': 0, 'error': 0}
    date_accuracy = {'order': 0, 'sync_sold': 0, 'sync_ended': 0, 'transition': 0, 'snapshot': 0}

    for _, row in primary_df.iterrows():
        listing_id = str(row['id'])
        state = parse_state(row.get('state'))

        # Skip if already imported
        if listing_id in existing_ids:
            skipped['existing'] += 1
            continue

        # Skip active inventory
        if listing_id in active_ids:
            skipped['active'] += 1
            continue

        # Skip live and draft items (they're current inventory)
        if skip_live and state in ('live', 'draft'):
            skipped[state] += 1
            continue

        try:
            record = prepare_record(
                row, order_dates, sold_event_dates, ended_event_dates,
                all_transitions, primary_date
            )
            records_to_import.append(record)

            # Track date accuracy
            if listing_id in order_dates:
                date_accuracy['order'] += 1
            elif listing_id in sold_event_dates:
                date_accuracy['sync_sold'] += 1
            elif listing_id in ended_event_dates:
                date_accuracy['sync_ended'] += 1
            elif listing_id in all_transitions:
                date_accuracy['transition'] += 1
            else:
                date_accuracy['snapshot'] += 1

        except Exception as e:
            skipped['error'] += 1
            print(f"   Error processing {listing_id}: {e}")

    print(f"\n   Records to import: {len(records_to_import)}")
    print(f"   Skipped: {skipped}")
    print(f"\n   Date accuracy breakdown:")
    print(f"     From orders (exact): {date_accuracy['order']}")
    print(f"     From sync events (sold): {date_accuracy['sync_sold']}")
    print(f"     From sync events (ended): {date_accuracy['sync_ended']}")
    print(f"     From transitions (estimated): {date_accuracy['transition']}")
    print(f"     From snapshot (upper bound): {date_accuracy['snapshot']}")

    # Show sample records
    print("\n6. Sample records:")
    for i, rec in enumerate(records_to_import[:3]):
        print(f"\n   [{i+1}] {rec['title'][:50]}...")
        print(f"       ID: {rec['reverb_listing_id']}")
        print(f"       Outcome: {rec['outcome']}")
        print(f"       Category: {rec['category_root']}")
        print(f"       Price: £{rec['final_price']:,.0f}" if rec['final_price'] else "       Price: N/A")
        print(f"       Created: {rec['created_at']}")
        print(f"       Sold: {rec['sold_at']}")
        print(f"       Days to sell: {rec['days_to_sell']}")
        print(f"       Views/Watches: {rec['view_count']}/{rec['watch_count']}")

    if dry_run:
        print("\n*** DRY RUN COMPLETE - No data written ***")
        print(f"\nWould import {len(records_to_import)} records")
        return

    # Actually import the data
    print("\n7. Importing to database...")
    async with async_session() as db:
        batch_size = 100
        imported = 0

        for i in range(0, len(records_to_import), batch_size):
            batch = records_to_import[i:i+batch_size]

            # Use upsert to handle any duplicates
            stmt = insert(ReverbHistoricalListing).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=['reverb_listing_id'],
                set_={
                    'view_count': stmt.excluded.view_count,
                    'watch_count': stmt.excluded.watch_count,
                    'offer_count': stmt.excluded.offer_count,
                    'updated_at': stmt.excluded.updated_at,
                }
            )

            await db.execute(stmt)
            await db.commit()

            imported += len(batch)
            print(f"   Imported {imported}/{len(records_to_import)} records...")

    print(f"\n✓ Successfully imported {imported} historical listings!")

    # Summary by category
    print("\n8. Import summary by category:")
    df_imported = pd.DataFrame(records_to_import)
    if not df_imported.empty:
        cat_summary = df_imported.groupby('category_root').agg({
            'reverb_listing_id': 'count',
            'outcome': lambda x: (x == 'sold').sum(),
            'days_to_sell': 'mean'
        }).rename(columns={
            'reverb_listing_id': 'total',
            'outcome': 'sold',
            'days_to_sell': 'avg_days_to_sell'
        })
        cat_summary['sell_through'] = (cat_summary['sold'] / cat_summary['total'] * 100).round(1)
        cat_summary = cat_summary.sort_values('total', ascending=False)
        print(cat_summary.head(10).to_string())


async def main():
    parser = argparse.ArgumentParser(description='Import historical Reverb data')
    parser.add_argument('--dry-run', action='store_true',
                       help='Analyze data without importing')
    parser.add_argument('--import', dest='do_import', action='store_true',
                       help='Actually import the data')
    parser.add_argument('--skip-live', action='store_true', default=True,
                       help='Skip live/draft listings (default: True)')
    parser.add_argument('--include-live', action='store_true',
                       help='Include live listings (for testing)')

    args = parser.parse_args()

    dry_run = not args.do_import
    skip_live = not args.include_live

    await import_historical_data(dry_run=dry_run, skip_live=skip_live)


if __name__ == '__main__':
    asyncio.run(main())
