#!/usr/bin/env python3
"""
Batch update eBay item specifics (Brand, Model, etc.) from source file.

Usage:
    python scripts/ebay/batch_update_item_specifics.py data/ebay/myfile.xlsx --limit 1 --dry-run
    python scripts/ebay/batch_update_item_specifics.py data/ebay/myfile.xlsx --limit 1
    python scripts/ebay/batch_update_item_specifics.py data/ebay/myfile.xlsx --limit 50
    python scripts/ebay/batch_update_item_specifics.py data/ebay/myfile.xlsx

Required columns in source file:
    - ItemID: eBay item ID
    - brand_needs_update: 'YES' if brand should be updated
    - model_needs_update: 'YES' if model should be updated
    - db_brand: New brand value (used if brand_needs_update='YES')
    - db_model: New model value (used if model_needs_update='YES')
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
from app.database import async_session
from app.services.ebay.trading import EbayTradingLegacyAPI
from app.core.config import get_settings
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def mark_item_processed(source_file: str, item_id: str, status: str = 'success', error_msg: str = None) -> None:
    """Mark an item as processed in the source XLSX file."""
    xlsx_path = Path(source_file)
    df = pd.read_excel(xlsx_path)

    # Add processed column if it doesn't exist
    if 'processed' not in df.columns:
        df['processed'] = ''
    if 'processed_at' not in df.columns:
        df['processed_at'] = ''

    # Find and update the row
    mask = df['ItemID'].astype(str) == str(item_id)
    if mask.any():
        from datetime import datetime
        df.loc[mask, 'processed'] = status
        df.loc[mask, 'processed_at'] = datetime.now().isoformat()
        df.to_excel(xlsx_path, index=False)

    # If failed, append to retries file
    if status == 'failed' and mask.any():
        append_to_retries(source_file, df[mask], error_msg)


def append_to_retries(source_file: str, failed_row: pd.DataFrame, error_msg: str = None) -> None:
    """Append failed item to retries file."""
    # Derive retries filename from source file
    source_path = Path(source_file)
    retries_path = source_path.parent / f"{source_path.stem}_RETRIES.xlsx"

    failed_row = failed_row.copy()
    failed_row['error_reason'] = error_msg or 'Unknown error'
    failed_row['failed_at'] = pd.Timestamp.now().isoformat()

    if retries_path.exists():
        # Append to existing retries file
        existing_df = pd.read_excel(retries_path)
        # Don't add duplicates
        existing_ids = existing_df['ItemID'].astype(str).tolist()
        new_ids = failed_row['ItemID'].astype(str).tolist()
        if not any(nid in existing_ids for nid in new_ids):
            combined_df = pd.concat([existing_df, failed_row], ignore_index=True)
            combined_df.to_excel(retries_path, index=False)
            logger.info(f"Appended failed item to {retries_path}")
    else:
        # Create new retries file
        failed_row.to_excel(retries_path, index=False)
        logger.info(f"Created retries file: {retries_path}")


async def get_items_needing_update(source_file: str, limit: int = None) -> list:
    """Get items where brand/model needs updating from source file."""

    xlsx_path = Path(source_file)

    if not xlsx_path.exists():
        logger.error(f"Source file not found: {xlsx_path}")
        return []

    df = pd.read_excel(xlsx_path)

    # Validate required columns (shipping, color, year columns are optional)
    required_cols = ['ItemID', 'brand_needs_update', 'model_needs_update', 'db_brand', 'db_model']
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        logger.error(f"Missing required columns: {missing}")
        return []

    # Check for optional columns
    has_color = 'color_needs_update' in df.columns and 'db_finish' in df.columns
    has_year = 'year_needs_update' in df.columns and 'db_year' in df.columns
    if has_color:
        logger.info("Color/Finish column found - will update Colour item specific")
    if has_year:
        logger.info("Year column found - will update Year item specific")

    # Check for shipping profile column (may have trailing space)
    shipping_col = None
    for col in df.columns:
        if 'shipment' in col.lower() or 'shipping' in col.lower():
            shipping_col = col
            break

    # Filter to items needing update (brand, model, color, year)
    filter_condition = (
        (df['brand_needs_update'] == 'YES') |
        (df['model_needs_update'] == 'YES')
    )
    if has_color:
        filter_condition = filter_condition | (df['color_needs_update'] == 'YES')
    if has_year:
        filter_condition = filter_condition | (df['year_needs_update'] == 'YES')

    # Exclude already processed items
    if 'processed' in df.columns:
        already_processed = df['processed'].isin(['success', 'failed'])
        filter_condition = filter_condition & ~already_processed
        processed_count = already_processed.sum()
        if processed_count > 0:
            logger.info(f"Skipping {processed_count} already processed items")

    needs_update = df[filter_condition].copy()

    if shipping_col:
        logger.info(f"Found shipping column: '{shipping_col}'")

    logger.info(f"Found {len(needs_update)} items needing updates")

    if limit:
        needs_update = needs_update.head(limit)
        logger.info(f"Limited to {len(needs_update)} items")

    items = []
    for _, row in needs_update.iterrows():
        # Parse shipping profile if column exists
        new_shipping_id = None
        if shipping_col and pd.notna(row.get(shipping_col)):
            shipping_val = row[shipping_col]
            if isinstance(shipping_val, str) and 'ShippingProfileID' in shipping_val:
                import ast
                try:
                    shipping_dict = ast.literal_eval(shipping_val)
                    new_shipping_id = shipping_dict.get('ShippingProfileID')
                except:
                    pass

        # Check color/year updates
        new_color = None
        new_year = None
        if has_color and row.get('color_needs_update') == 'YES':
            new_color = row.get('db_finish')
        if has_year and row.get('year_needs_update') == 'YES':
            db_year = row.get('db_year')
            if pd.notna(db_year):
                new_year = str(int(db_year)) if isinstance(db_year, float) else str(db_year)

        # Get current shipping profile if available - normalize to string without decimals
        current_shipping_id = row.get('current_shipping_profile_id', '')
        if pd.isna(current_shipping_id) or current_shipping_id == '':
            current_shipping_id = None
        else:
            # Convert to string, removing any .0 from float conversion
            current_shipping_id = str(current_shipping_id).replace('.0', '')

        # Normalize new shipping ID the same way
        if new_shipping_id:
            new_shipping_id = str(new_shipping_id).replace('.0', '')

        # Only flag shipping for update if actually different
        if current_shipping_id and new_shipping_id and current_shipping_id == new_shipping_id:
            new_shipping_id = None  # No change needed

        # Get existing Type value to include in update (eBay requires it for some categories)
        existing_type = row.get('type', '')
        if pd.isna(existing_type):
            existing_type = None

        # Get new model - skip if too long (eBay limit is 65 chars)
        new_model_val = row['db_model'] if row['model_needs_update'] == 'YES' else None
        model_skipped = False
        if new_model_val and len(str(new_model_val)) > 65:
            logger.warning(f"Model too long ({len(str(new_model_val))} chars) for item {row['ItemID']} - will skip model update")
            model_skipped = True
            new_model_val = None  # Skip, don't truncate

        # Get existing brand if not being updated (eBay requires it for some categories)
        existing_brand = None
        if row['brand_needs_update'] != 'YES':
            current_brand = row.get('brand', '')
            if pd.notna(current_brand) and str(current_brand).strip() and str(current_brand).lower() != 'unbranded':
                existing_brand = str(current_brand).strip()

        item = {
            'item_id': str(row['ItemID']),
            'title': row['Title'],
            'current_brand': row['brand'],
            'current_model': row['model'],
            'current_color': row.get('color', ''),
            'current_year': row.get('year', ''),
            'current_shipping_profile_id': current_shipping_id or '(unknown)',
            'new_brand': row['db_brand'] if row['brand_needs_update'] == 'YES' else None,
            'new_model': new_model_val,
            'new_color': new_color,
            'new_year': new_year,
            'new_shipping_profile_id': new_shipping_id,
            'existing_type': existing_type,  # Include to satisfy eBay requirements
            'existing_brand': existing_brand,  # Include existing brand if not changing it
            'model_skipped': model_skipped,  # Flag if model was too long
            'original_model': row['db_model'] if model_skipped else None,  # Keep original for retries log
        }
        items.append(item)

    return items


def build_item_specifics_xml(item: dict) -> str:
    """Build the ItemSpecifics XML for the update."""
    specifics_xml = ""

    if item.get('new_brand'):
        brand = xml_escape(str(item['new_brand']))
        specifics_xml += f"""
                <NameValueList>
                    <Name>Brand</Name>
                    <Value>{brand}</Value>
                </NameValueList>"""

    if item.get('new_model'):
        model = xml_escape(str(item['new_model']))
        specifics_xml += f"""
                <NameValueList>
                    <Name>Model</Name>
                    <Value>{model}</Value>
                </NameValueList>"""

    if item.get('new_color'):
        color = xml_escape(str(item['new_color']))
        specifics_xml += f"""
                <NameValueList>
                    <Name>Colour</Name>
                    <Value>{color}</Value>
                </NameValueList>"""

    if item.get('new_year'):
        year = xml_escape(str(item['new_year']))
        specifics_xml += f"""
                <NameValueList>
                    <Name>Year</Name>
                    <Value>{year}</Value>
                </NameValueList>"""

    # Include existing Type if present (eBay requires it for some categories)
    if item.get('existing_type'):
        item_type = xml_escape(str(item['existing_type']))
        specifics_xml += f"""
                <NameValueList>
                    <Name>Type</Name>
                    <Value>{item_type}</Value>
                </NameValueList>"""

    # Include existing Brand if not being updated (eBay requires it for some categories)
    if item.get('existing_brand'):
        existing_brand = xml_escape(str(item['existing_brand']))
        specifics_xml += f"""
                <NameValueList>
                    <Name>Brand</Name>
                    <Value>{existing_brand}</Value>
                </NameValueList>"""

    return specifics_xml


def xml_escape(s: str) -> str:
    """Escape special XML characters."""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')


async def update_item(trading_api: EbayTradingLegacyAPI, item: dict, dry_run: bool = False) -> dict:
    """Update a single eBay item's specifics and/or shipping profile."""

    item_id = item['item_id']
    specifics_xml = build_item_specifics_xml(item)
    shipping_profile_id = item.get('new_shipping_profile_id')

    # Check if there's anything to update
    has_specifics = specifics_xml.strip()
    has_shipping = shipping_profile_id is not None

    if not has_specifics and not has_shipping:
        return {'item_id': item_id, 'status': 'skipped', 'reason': 'No changes needed'}

    # Build change lists separately for metadata and shipping
    metadata_changes = []
    if item.get('new_brand'):
        metadata_changes.append(f"Brand: {item['current_brand']} -> {item['new_brand']}")
    if item.get('new_model'):
        metadata_changes.append(f"Model: {item['current_model']} -> {item['new_model']}")
    if item.get('new_color'):
        current_color = item.get('current_color', '')
        if pd.isna(current_color):
            current_color = '(empty)'
        metadata_changes.append(f"Colour: {current_color} -> {item['new_color']}")
    if item.get('new_year'):
        current_year = item.get('current_year', '')
        if pd.isna(current_year):
            current_year = '(empty)'
        metadata_changes.append(f"Year: {current_year} -> {item['new_year']}")

    shipping_info = ""
    current_shipping = item.get('current_shipping_profile_id', '(unknown)')
    if has_shipping:
        shipping_info = f"{current_shipping} -> {shipping_profile_id}"
    else:
        shipping_info = f"{current_shipping} - No Change"

    # Log with clear sections
    logger.info(f"Item {item_id}:")
    if metadata_changes:
        logger.info(f"  [Metadata] {', '.join(metadata_changes)}")
    logger.info(f"  [Shipping] {shipping_info}")

    changes = metadata_changes + ([f"Shipping: {shipping_info}"] if has_shipping else [])

    if dry_run:
        return {'item_id': item_id, 'status': 'dry_run', 'changes': changes}

    try:
        # Build the ReviseFixedPriceItem XML request
        auth_token = await trading_api._get_auth_token()

        # Build optional sections
        item_specifics_section = ""
        if has_specifics:
            item_specifics_section = f"""<ItemSpecifics>{specifics_xml}
                </ItemSpecifics>"""

        shipping_section = ""
        if has_shipping:
            shipping_section = f"""<SellerProfiles>
                    <SellerShippingProfile>
                        <ShippingProfileID>{shipping_profile_id}</ShippingProfileID>
                    </SellerShippingProfile>
                </SellerProfiles>"""

        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{auth_token}</eBayAuthToken>
            </RequesterCredentials>
            <Item>
                <ItemID>{item_id}</ItemID>
                {item_specifics_section}
                {shipping_section}
            </Item>
        </ReviseFixedPriceItemRequest>"""

        response = await trading_api._make_request('ReviseFixedPriceItem', xml_request)
        result = response.get('ReviseFixedPriceItemResponse', {})
        ack = result.get('Ack', '')

        if ack in ['Success', 'Warning']:
            logger.info(f"Item {item_id}: Updated successfully (Ack={ack})")
            return {'item_id': item_id, 'status': 'success', 'changes': changes, 'ack': ack}
        else:
            errors = result.get('Errors', {})
            error_str = str(errors)
            error_code = errors.get('ErrorCode', '') if isinstance(errors, dict) else ''

            # Check if it's a "Model too long" error (ErrorCode 21919308)
            if '21919308' in error_str and item.get('new_model'):
                logger.warning(f"Item {item_id}: Model too long, retrying without model...")
                # Retry without model
                item_without_model = item.copy()
                item_without_model['new_model'] = None
                retry_result = await update_item(trading_api, item_without_model, dry_run=False)

                if retry_result['status'] == 'success':
                    logger.info(f"Item {item_id}: Partial update succeeded (model skipped)")
                    return {
                        'item_id': item_id,
                        'status': 'partial',
                        'changes': changes,
                        'skipped_fields': ['model'],
                        'note': 'Model too long - needs manual update'
                    }
                else:
                    # Retry also failed
                    logger.error(f"Item {item_id}: Retry without model also failed")
                    return {'item_id': item_id, 'status': 'failed', 'error': error_str, 'ack': ack}

            logger.error(f"Item {item_id}: Failed - {errors}")
            return {'item_id': item_id, 'status': 'failed', 'error': error_str, 'ack': ack}

    except Exception as e:
        logger.error(f"Item {item_id}: Exception - {e}")
        return {'item_id': item_id, 'status': 'error', 'error': str(e)}


async def main():
    parser = argparse.ArgumentParser(description='Batch update eBay item specifics')
    parser.add_argument('source_file', type=str, help='Path to source XLSX file with update data')
    parser.add_argument('--limit', type=int, help='Number of items to process (default: all)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without making changes')
    parser.add_argument('--item-id', type=str, help='Update a specific item ID only')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("eBay Item Specifics Batch Update")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    logger.info(f"Source file: {args.source_file}")

    # Get items to update
    if args.item_id:
        # Single item mode - get from xlsx
        xlsx_path = Path(args.source_file)
        if not xlsx_path.exists():
            logger.error(f"Source file not found: {xlsx_path}")
            return
        df = pd.read_excel(xlsx_path)
        row = df[df['ItemID'].astype(str) == args.item_id]
        if row.empty:
            logger.error(f"Item {args.item_id} not found in master file")
            return
        row = row.iloc[0]
        items = [{
            'item_id': str(row['ItemID']),
            'title': row['Title'],
            'current_brand': row['brand'],
            'current_model': row['model'],
            'new_brand': row['db_brand'] if row['brand_needs_update'] == 'YES' else None,
            'new_model': row['db_model'] if row['model_needs_update'] == 'YES' else None,
        }]
    else:
        items = await get_items_needing_update(args.source_file, limit=args.limit)

    if not items:
        logger.info("No items to update")
        return

    logger.info(f"Processing {len(items)} items...")
    logger.info("-" * 60)

    # Initialize eBay Trading API
    settings = get_settings()
    trading_api = EbayTradingLegacyAPI(sandbox=settings.EBAY_SANDBOX_MODE)

    # Process items
    results = {
        'success': 0,
        'partial': 0,
        'failed': 0,
        'skipped': 0,
        'dry_run': 0,
        'errors': [],
        'partial_items': []
    }

    for item in items:
        result = await update_item(trading_api, item, dry_run=args.dry_run)

        if result['status'] == 'success':
            results['success'] += 1
            # Mark as processed in the XLSX
            mark_item_processed(args.source_file, item['item_id'], 'success')
            # If model was skipped due to length, log to retries for manual fix
            if item.get('model_skipped'):
                results['partial'] += 1
                error_msg = f"PARTIAL: Model too long ({len(str(item['original_model']))} chars) - needs manual update. Model: {item['original_model']}"
                append_to_retries(args.source_file, pd.DataFrame([{'ItemID': item['item_id'], 'Title': item.get('title', '')}]), error_msg)
                logger.info(f"Item {item['item_id']}: Logged to retries (model skipped)")
        elif result['status'] == 'partial':
            results['partial'] += 1
            results['partial_items'].append(result)
            # Mark as processed but log to retries for model-only update
            mark_item_processed(args.source_file, item['item_id'], 'success')
            # Also log to retries with note about model
            error_msg = f"PARTIAL: {result.get('note', 'Some fields skipped')} - skipped: {result.get('skipped_fields', [])}"
            append_to_retries(args.source_file, pd.DataFrame([{'ItemID': item['item_id'], 'Title': item.get('title', '')}]), error_msg)
        elif result['status'] == 'failed':
            results['failed'] += 1
            results['errors'].append(result)
            # Mark as failed and append to retries file
            error_msg = str(result.get('error', 'Unknown error'))[:500]
            mark_item_processed(args.source_file, item['item_id'], 'failed', error_msg)
        elif result['status'] == 'skipped':
            results['skipped'] += 1
        elif result['status'] == 'dry_run':
            results['dry_run'] += 1

    # Summary
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info(f"Would update: {results['dry_run']} items")
    else:
        logger.info(f"Success: {results['success']}")
        logger.info(f"Partial: {results['partial']} (some fields skipped, logged to retries)")
        logger.info(f"Failed: {results['failed']}")
        logger.info(f"Skipped: {results['skipped']}")

    if results['errors']:
        logger.info("\nErrors:")
        for err in results['errors'][:10]:
            logger.info(f"  {err['item_id']}: {err.get('error', 'Unknown')}")


if __name__ == '__main__':
    asyncio.run(main())
