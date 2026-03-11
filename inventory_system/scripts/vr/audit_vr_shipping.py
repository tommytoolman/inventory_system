#!/usr/bin/env python3
"""
VR Shipping Rate Audit Script

Scrapes ALL active VR listings to extract actual shipping rates from the edit page,
compares them against expected rates from the product's shipping profile,
and outputs a CSV report of discrepancies.

Usage:
    # Full audit of all active listings
    python scripts/vr/audit_vr_shipping.py

    # Audit specific listings by VR ID
    python scripts/vr/audit_vr_shipping.py --ids 12345 67890

    # Dry run - just show what would be audited
    python scripts/vr/audit_vr_shipping.py --dry-run

    # Resume from a specific offset (if previous run was interrupted)
    python scripts/vr/audit_vr_shipping.py --offset 100

    # Limit number of listings to audit
    python scripts/vr/audit_vr_shipping.py --limit 50

Notes:
    - Runs via Selenium (slow, ~50-100 listings/hour)
    - Checks for pending user VR jobs and yields priority to them
    - Saves progress to allow resumption
    - Outputs: scripts/vr/output/vr_shipping_audit_{timestamp}.csv
"""

import asyncio
import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, text
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from app.database import async_session
from app.models.vr import VRListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.models.shipping import ShippingProfile
from app.models.vr_job import VRJob, VRJobStatus
from app.services.vintageandrare.client import VintageAndRareClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class VRShippingAuditor:
    """Audits VR listings for shipping rate discrepancies."""

    # Shipping regions in VR form order
    REGIONS = ['uk', 'europe', 'usa', 'world']

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.client: Optional[VintageAndRareClient] = None
        self.driver = None
        self.results: List[Dict] = []
        self.errors: List[Dict] = []
        self.processed_count = 0
        self.output_dir = Path("scripts/vr/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> bool:
        """Initialize the VR client and authenticate."""
        logger.info("Initializing VR client...")
        self.client = VintageAndRareClient(self.username, self.password)

        if not await self.client.authenticate():
            logger.error("Failed to authenticate with V&R")
            return False

        logger.info("Successfully authenticated with V&R")
        return True

    async def check_for_pending_user_jobs(self) -> bool:
        """Check if there are pending user-submitted VR jobs that should take priority."""
        async with async_session() as session:
            result = await session.execute(
                select(VRJob).where(VRJob.status == VRJobStatus.QUEUED.value).limit(1)
            )
            pending_job = result.scalar_one_or_none()
            return pending_job is not None

    async def get_active_vr_listings(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict]:
        """Get all active VR listings with their product and shipping profile info."""
        logger.info(f"Fetching active VR listings (offset={offset}, limit={limit})...")

        async with async_session() as session:
            query = text("""
                SELECT
                    vl.id as vr_listing_id,
                    vl.vr_listing_id as vr_id,
                    vl.vr_state,
                    p.id as product_id,
                    p.sku,
                    p.brand,
                    p.model,
                    p.shipping_profile_id,
                    sp.name as profile_name,
                    sp.rates as profile_rates
                FROM vr_listings vl
                JOIN platform_common pc ON vl.platform_id = pc.id
                JOIN products p ON pc.product_id = p.id
                LEFT JOIN shipping_profiles sp ON p.shipping_profile_id = sp.id
                WHERE vl.vr_state = 'active'
                ORDER BY vl.id
                OFFSET :offset
            """)

            if limit:
                query = text(str(query) + " LIMIT :limit")
                result = await session.execute(query, {"offset": offset, "limit": limit})
            else:
                result = await session.execute(query, {"offset": offset})

            rows = result.fetchall()

            listings = []
            for row in rows:
                listings.append({
                    'vr_listing_id': row.vr_listing_id,
                    'vr_id': row.vr_id,
                    'vr_state': row.vr_state,
                    'product_id': row.product_id,
                    'sku': row.sku,
                    'brand': row.brand,
                    'model': row.model,
                    'shipping_profile_id': row.shipping_profile_id,
                    'profile_name': row.profile_name,
                    'profile_rates': row.profile_rates
                })

            logger.info(f"Found {len(listings)} active VR listings")
            return listings

    def _get_expected_rates(self, listing: Dict) -> Dict[str, Optional[float]]:
        """Get expected shipping rates from the product's shipping profile."""
        profile_rates = listing.get('profile_rates')

        if not profile_rates:
            # No profile - return None to indicate unknown expected rates
            return {region: None for region in self.REGIONS}

        return {
            'uk': profile_rates.get('uk'),
            'europe': profile_rates.get('europe'),
            'usa': profile_rates.get('usa'),
            'world': profile_rates.get('row') or profile_rates.get('world')
        }

    def _scrape_shipping_rates(self, vr_id: str) -> Dict[str, Any]:
        """
        Navigate to VR edit page and scrape shipping rates.

        Returns dict with:
            - success: bool
            - rates: {uk, europe, usa, world} or None
            - error: error message if failed
        """
        if not self.client or not self.client.session:
            return {'success': False, 'rates': None, 'error': 'Client not initialized'}

        edit_url = f"https://www.vintageandrare.com/instruments/add_edit_item/{vr_id}"

        try:
            # Use requests first to check if page is accessible
            response = self.client.session.get(edit_url, timeout=30)

            if response.status_code != 200:
                return {
                    'success': False,
                    'rates': None,
                    'error': f'HTTP {response.status_code}'
                }

            html = response.text

            # Parse shipping fees from the HTML
            # Use the hidden shipping_fees_destination[] field for reliable region names
            import re

            # Pattern to match fee value followed by destination hidden field
            # Structure: <input name="shipping_fees_fee[]" value="XX"> <input name="shipping_fees_destination[]" value="REGION">
            pair_pattern = r'name="shipping_fees_fee\[\]"[^>]*value="([^"]*)"[^<]*<input[^>]*name="shipping_fees_destination\[\]"[^>]*value="([^"]*)"'
            matches = re.findall(pair_pattern, html)

            if matches:
                rates = {}
                # Map region labels to our standard keys
                region_map = {
                    'uk': 'uk',
                    'united kingdom': 'uk',
                    'europe': 'europe',
                    'eu': 'europe',
                    'eurozone': 'europe',
                    'usa': 'usa',
                    'us': 'usa',
                    'united states': 'usa',
                    'world': 'world',
                    'rest of world': 'world',
                    'row': 'world',
                    'worldwide': 'world',
                }

                for fee_value, region_label in matches:
                    region_label_clean = region_label.strip().lower()
                    # Find matching standard region key
                    for label_variant, standard_key in region_map.items():
                        if label_variant in region_label_clean:
                            try:
                                rates[standard_key] = float(fee_value) if fee_value else 0
                            except ValueError:
                                rates[standard_key] = 0
                            break

                if rates:
                    return {'success': True, 'rates': rates, 'error': None}
                else:
                    return {
                        'success': False,
                        'rates': None,
                        'error': f'Found {len(matches)} shipping rows but could not map regions'
                    }
            else:
                # Fallback: check if shipping fields exist at all
                fee_pattern = r'name="shipping_fees_fee\[\]"[^>]*value="([^"]*)"'
                fees = re.findall(fee_pattern, html)

                if 'shipping_fees_fee' in html:
                    return {
                        'success': False,
                        'rates': None,
                        'error': f'Found shipping fields but could not parse destination pairs (found {len(fees)} fees)'
                    }
                else:
                    return {
                        'success': False,
                        'rates': None,
                        'error': 'No shipping fields found in page'
                    }

        except Exception as e:
            return {'success': False, 'rates': None, 'error': str(e)}

    def _compare_rates(self, actual: Dict, expected: Dict) -> Dict[str, Any]:
        """
        Compare actual vs expected rates.

        Returns:
            - match: bool - True if all rates match
            - discrepancies: list of {region, actual, expected, diff}
        """
        discrepancies = []

        for region in self.REGIONS:
            actual_rate = actual.get(region)
            expected_rate = expected.get(region)

            # Skip comparison if no expected rate (no profile assigned)
            if expected_rate is None:
                continue

            # Compare with tolerance (£1)
            if actual_rate is not None and expected_rate is not None:
                diff = abs(float(actual_rate) - float(expected_rate))
                if diff > 1:  # More than £1 difference
                    discrepancies.append({
                        'region': region,
                        'actual': actual_rate,
                        'expected': expected_rate,
                        'diff': diff
                    })

        return {
            'match': len(discrepancies) == 0,
            'discrepancies': discrepancies
        }

    async def audit_listing(self, listing: Dict) -> Dict:
        """Audit a single VR listing."""
        vr_id = listing['vr_id']
        sku = listing['sku']

        logger.info(f"Auditing {sku} (VR ID: {vr_id})...")

        # Get expected rates from shipping profile
        expected_rates = self._get_expected_rates(listing)

        # Scrape actual rates from VR
        scrape_result = self._scrape_shipping_rates(vr_id)

        if not scrape_result['success']:
            return {
                'vr_id': vr_id,
                'sku': sku,
                'brand': listing['brand'],
                'model': listing['model'],
                'profile_name': listing['profile_name'],
                'status': 'error',
                'error': scrape_result['error'],
                'actual_uk': None,
                'actual_europe': None,
                'actual_usa': None,
                'actual_world': None,
                'expected_uk': expected_rates.get('uk'),
                'expected_europe': expected_rates.get('europe'),
                'expected_usa': expected_rates.get('usa'),
                'expected_world': expected_rates.get('world'),
                'has_discrepancy': None
            }

        actual_rates = scrape_result['rates']
        comparison = self._compare_rates(actual_rates, expected_rates)

        result = {
            'vr_id': vr_id,
            'sku': sku,
            'brand': listing['brand'],
            'model': listing['model'],
            'profile_name': listing['profile_name'] or 'NO PROFILE',
            'status': 'ok' if comparison['match'] else 'discrepancy',
            'error': None,
            'actual_uk': actual_rates.get('uk'),
            'actual_europe': actual_rates.get('europe'),
            'actual_usa': actual_rates.get('usa'),
            'actual_world': actual_rates.get('world'),
            'expected_uk': expected_rates.get('uk'),
            'expected_europe': expected_rates.get('europe'),
            'expected_usa': expected_rates.get('usa'),
            'expected_world': expected_rates.get('world'),
            'has_discrepancy': not comparison['match']
        }

        if comparison['discrepancies']:
            logger.warning(f"  Discrepancies found: {comparison['discrepancies']}")
        else:
            logger.info(f"  OK - rates match")

        return result

    async def run_audit(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
        specific_ids: Optional[List[str]] = None,
        dry_run: bool = False,
        check_priority: bool = True,
        delay_between_requests: float = 1.0
    ) -> Dict[str, Any]:
        """
        Run the full audit.

        Args:
            limit: Max number of listings to audit
            offset: Start from this offset (for resumption)
            specific_ids: Only audit these VR IDs
            dry_run: Just show what would be audited
            check_priority: Pause if user jobs are pending
            delay_between_requests: Seconds to wait between requests
        """
        stats = {
            'total': 0,
            'processed': 0,
            'ok': 0,
            'discrepancy': 0,
            'error': 0,
            'paused_for_priority': 0
        }

        # Get listings to audit
        if specific_ids:
            # TODO: Filter by specific IDs
            listings = await self.get_active_vr_listings()
            listings = [l for l in listings if l['vr_id'] in specific_ids]
        else:
            listings = await self.get_active_vr_listings(limit=limit, offset=offset)

        stats['total'] = len(listings)

        if dry_run:
            logger.info(f"DRY RUN - Would audit {len(listings)} listings:")
            for listing in listings[:10]:
                logger.info(f"  - {listing['sku']} (VR: {listing['vr_id']}) - Profile: {listing['profile_name'] or 'NONE'}")
            if len(listings) > 10:
                logger.info(f"  ... and {len(listings) - 10} more")
            return stats

        # Initialize client
        if not await self.initialize():
            return {'error': 'Failed to initialize VR client'}

        # Process each listing
        for i, listing in enumerate(listings):
            # Check for priority jobs
            if check_priority and i > 0 and i % 10 == 0:
                if await self.check_for_pending_user_jobs():
                    logger.warning("Pausing - user VR job detected in queue")
                    stats['paused_for_priority'] += 1
                    # Wait for user job to complete
                    while await self.check_for_pending_user_jobs():
                        await asyncio.sleep(30)
                    logger.info("Resuming audit - user job queue cleared")

            try:
                result = await self.audit_listing(listing)
                self.results.append(result)

                if result['status'] == 'ok':
                    stats['ok'] += 1
                elif result['status'] == 'discrepancy':
                    stats['discrepancy'] += 1
                else:
                    stats['error'] += 1

                stats['processed'] += 1
                self.processed_count += 1

                # Progress update every 10 listings
                if stats['processed'] % 10 == 0:
                    logger.info(f"Progress: {stats['processed']}/{stats['total']} "
                               f"(OK: {stats['ok']}, Discrepancy: {stats['discrepancy']}, Error: {stats['error']})")
                    # Save intermediate results
                    self._save_results(intermediate=True)

            except Exception as e:
                logger.error(f"Error auditing {listing['sku']}: {e}")
                self.errors.append({
                    'vr_id': listing['vr_id'],
                    'sku': listing['sku'],
                    'error': str(e)
                })
                stats['error'] += 1

            # Rate limiting
            if delay_between_requests > 0:
                await asyncio.sleep(delay_between_requests)

        # Save final results
        self._save_results(intermediate=False)

        return stats

    def _save_results(self, intermediate: bool = False):
        """Save audit results to CSV."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "_partial" if intermediate else ""

        # Single output file with clear column naming
        results_file = self.output_dir / f"vr_shipping_audit_{timestamp}{suffix}.csv"

        if self.results:
            fieldnames = [
                'vr_id', 'sku', 'brand', 'model', 'profile_name', 'status', 'error',
                'has_discrepancy',
                'current_uk', 'current_europe', 'current_usa', 'current_world',
                'expected_uk', 'expected_europe', 'expected_usa', 'expected_world'
            ]

            # Rename actual -> current for clarity
            rows_to_write = []
            for r in self.results:
                row = r.copy()
                row['current_uk'] = row.pop('actual_uk', None)
                row['current_europe'] = row.pop('actual_europe', None)
                row['current_usa'] = row.pop('actual_usa', None)
                row['current_world'] = row.pop('actual_world', None)
                rows_to_write.append(row)

            with open(results_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows_to_write)

            discrepancy_count = len([r for r in self.results if r.get('has_discrepancy')])
            logger.info(f"Saved {len(self.results)} results to {results_file} ({discrepancy_count} with discrepancies)")

            # Clean up partial files when saving final results
            if not intermediate:
                self._cleanup_partial_files()

    def _cleanup_partial_files(self):
        """Delete all partial audit files."""
        import glob
        partial_pattern = str(self.output_dir / "vr_shipping_audit_*_partial.csv")
        partial_files = glob.glob(partial_pattern)
        for f in partial_files:
            try:
                os.remove(f)
            except OSError:
                pass
        if partial_files:
            logger.info(f"Cleaned up {len(partial_files)} partial files")

    def cleanup(self):
        """Clean up resources."""
        if self.client:
            self.client.cleanup_temp_files()


async def main():
    parser = argparse.ArgumentParser(description="Audit VR listings for shipping rate discrepancies")

    parser.add_argument("--ids", nargs="+", help="Specific VR IDs to audit")
    parser.add_argument("--limit", type=int, help="Max number of listings to audit")
    parser.add_argument("--offset", type=int, default=0, help="Start from this offset (for resumption)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be audited without doing it")
    parser.add_argument("--no-priority-check", action="store_true", help="Don't pause for user jobs")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Get credentials
    username = os.environ.get("VINTAGE_AND_RARE_USERNAME")
    password = os.environ.get("VR_PASSWORD") or os.environ.get("VINTAGE_AND_RARE_PASSWORD")

    if not username or not password:
        logger.error("V&R credentials required. Set VINTAGE_AND_RARE_USERNAME and VR_PASSWORD env vars.")
        sys.exit(1)

    auditor = VRShippingAuditor(username, password)

    try:
        stats = await auditor.run_audit(
            limit=args.limit,
            offset=args.offset,
            specific_ids=args.ids,
            dry_run=args.dry_run,
            check_priority=not args.no_priority_check,
            delay_between_requests=args.delay
        )

        print("\n" + "=" * 60)
        print("VR SHIPPING AUDIT COMPLETE")
        print("=" * 60)
        print(f"Total listings:     {stats.get('total', 0)}")
        print(f"Processed:          {stats.get('processed', 0)}")
        print(f"OK (rates match):   {stats.get('ok', 0)}")
        print(f"Discrepancies:      {stats.get('discrepancy', 0)}")
        print(f"Errors:             {stats.get('error', 0)}")
        print(f"Priority pauses:    {stats.get('paused_for_priority', 0)}")

        if args.dry_run:
            print("\nDRY RUN - No changes made")
        else:
            print(f"\nResults saved to: scripts/vr/output/")

    except KeyboardInterrupt:
        logger.info("\nAudit interrupted by user")
        auditor._save_results(intermediate=True)
    except Exception as e:
        logger.error(f"Audit failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        auditor.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
