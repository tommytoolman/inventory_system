# app/services/listing_stats_service.py
"""
Listing Stats Service

Handles fetching and storing engagement metrics (views, watches) from
various platforms, with historical tracking for trend analysis.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listing_stats_history import ListingStatsHistory
from app.models.reverb import ReverbListing
from app.models.ebay import EbayListing
from app.models.platform_common import PlatformCommon, ListingStatus
from app.services.reverb.client import ReverbClient

logger = logging.getLogger(__name__)


class ListingStatsService:
    """Service for fetching and storing listing engagement metrics."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def refresh_reverb_stats(
        self,
        api_key: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Fetch current stats from Reverb API and store historical snapshot.

        Args:
            api_key: Reverb API key
            dry_run: If True, don't actually write to database

        Returns:
            Summary of the refresh operation
        """
        logger.info("Starting Reverb stats refresh...")

        client = ReverbClient(api_key=api_key)

        # Fetch all live listings with full details (includes stats)
        try:
            listings = await client.get_all_listings_detailed(state="live", max_concurrent=10)
            logger.info(f"Fetched {len(listings)} live listings from Reverb")
        except Exception as e:
            logger.error(f"Failed to fetch Reverb listings: {e}")
            return {"status": "error", "message": str(e)}

        if not listings:
            logger.info("No live listings found on Reverb")
            return {"status": "success", "listings_processed": 0, "message": "No live listings"}

        # Build a mapping of reverb_listing_id -> product_id for easier lookups
        product_id_map = await self._get_reverb_product_id_map()

        stats_inserted = 0
        listings_updated = 0
        errors = []

        for listing in listings:
            try:
                listing_id = str(listing.get('id', ''))
                if not listing_id:
                    continue

                # Extract stats
                stats = listing.get('stats', {})
                view_count = self._safe_int(stats.get('views'))
                watch_count = self._safe_int(stats.get('watches'))

                # Extract price
                price = self._extract_price(listing)

                # Extract state
                state_data = listing.get('state', {})
                state = state_data.get('slug') if isinstance(state_data, dict) else str(state_data)

                # Get product_id if we have it
                product_id = product_id_map.get(listing_id)

                if not dry_run:
                    # 1. Insert historical snapshot
                    history_entry = ListingStatsHistory(
                        platform="reverb",
                        platform_listing_id=listing_id,
                        product_id=product_id,
                        view_count=view_count,
                        watch_count=watch_count,
                        price=price,
                        state=state,
                        recorded_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    )
                    self.db.add(history_entry)
                    stats_inserted += 1

                    # 2. Update current stats in reverb_listings
                    updated = await self._update_reverb_listing_stats(
                        listing_id, view_count, watch_count
                    )
                    if updated:
                        listings_updated += 1

            except Exception as e:
                error_msg = f"Error processing listing {listing.get('id')}: {e}"
                logger.warning(error_msg)
                errors.append(error_msg)

        if not dry_run:
            await self.db.commit()

        summary = {
            "status": "success",
            "platform": "reverb",
            "listings_fetched": len(listings),
            "stats_snapshots_inserted": stats_inserted,
            "listings_updated": listings_updated,
            "errors": len(errors),
            "dry_run": dry_run,
        }

        if errors and len(errors) <= 5:
            summary["error_samples"] = errors

        logger.info(f"Reverb stats refresh complete: {summary}")
        return summary

    async def refresh_ebay_stats(
        self,
        dry_run: bool = False,
        batch_size: int = 10
    ) -> Dict[str, Any]:
        """
        Fetch current stats from eBay API and store historical snapshot.

        Uses the Trading API GetItem call to fetch HitCount and WatchCount
        for all active eBay listings.

        Args:
            dry_run: If True, don't actually write to database
            batch_size: Number of concurrent API calls

        Returns:
            Summary of the refresh operation
        """
        from app.services.ebay.trading import EbayTradingLegacyAPI
        from app.models.product import Product

        logger.info("Starting eBay stats refresh...")

        # Get all active eBay listings with their product info
        query = (
            select(EbayListing, PlatformCommon, Product)
            .join(PlatformCommon, EbayListing.platform_id == PlatformCommon.id)
            .join(Product, PlatformCommon.product_id == Product.id)
            .where(PlatformCommon.platform_name == 'ebay')
            .where(PlatformCommon.status == ListingStatus.ACTIVE.value)
        )
        result = await self.db.execute(query)
        rows = result.all()

        if not rows:
            logger.info("No active eBay listings found")
            return {"status": "success", "listings_processed": 0, "message": "No active listings"}

        logger.info(f"Found {len(rows)} active eBay listings to refresh stats for")

        stats_inserted = 0
        errors = []
        api = EbayTradingLegacyAPI(sandbox=False)
        semaphore = asyncio.Semaphore(batch_size)

        async def fetch_item_stats(listing: EbayListing, platform_common: PlatformCommon, product: Product):
            """Fetch stats for a single listing."""
            nonlocal stats_inserted
            async with semaphore:
                try:
                    if not listing.ebay_item_id:
                        return

                    # Call GetItem to get current stats (use get_item_details which includes WatchCount)
                    item_data = await api.get_item_details(listing.ebay_item_id)
                    if not item_data:
                        errors.append(f"No data returned for {listing.ebay_item_id}")
                        return

                    # Extract stats - eBay returns these as strings
                    hit_count = self._safe_int(item_data.get('HitCount'))
                    watch_count = self._safe_int(item_data.get('WatchCount'))

                    # Extract current price
                    price = None
                    selling_status = item_data.get('SellingStatus', {})
                    if isinstance(selling_status, dict):
                        current_price = selling_status.get('CurrentPrice', {})
                        if isinstance(current_price, dict):
                            price = self._safe_float(current_price.get('#text'))
                        elif current_price:
                            price = self._safe_float(current_price)

                    # Get listing state
                    state = item_data.get('SellingStatus', {}).get('ListingStatus', 'unknown')
                    if isinstance(state, dict):
                        state = state.get('#text', 'unknown')

                    if not dry_run:
                        # Insert historical snapshot
                        history_entry = ListingStatsHistory(
                            platform="ebay",
                            platform_listing_id=listing.ebay_item_id,
                            product_id=product.id if product else None,
                            view_count=hit_count,
                            watch_count=watch_count,
                            price=price,
                            state=state,
                            recorded_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        )
                        self.db.add(history_entry)
                        stats_inserted += 1

                except Exception as e:
                    error_msg = f"Error fetching stats for {listing.ebay_item_id}: {e}"
                    logger.warning(error_msg)
                    errors.append(error_msg)

        # Process all listings concurrently with rate limiting
        tasks = [
            fetch_item_stats(listing, platform_common, product)
            for listing, platform_common, product in rows
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        if not dry_run and stats_inserted > 0:
            await self.db.commit()

        summary = {
            "status": "success",
            "platform": "ebay",
            "listings_fetched": len(rows),
            "stats_snapshots_inserted": stats_inserted,
            "errors": len(errors),
            "dry_run": dry_run,
        }

        if errors and len(errors) <= 5:
            summary["error_samples"] = errors

        logger.info(f"eBay stats refresh complete: {summary}")
        return summary

    def _safe_float(self, value: Any) -> Optional[float]:
        """Safely convert value to float."""
        if value is None:
            return None
        try:
            return float(str(value).replace(',', ''))
        except (ValueError, TypeError):
            return None

    async def _get_ebay_product_id_map(self) -> Dict[str, int]:
        """
        Build a mapping of ebay_item_id -> product_id.
        """
        query = (
            select(EbayListing.ebay_item_id, PlatformCommon.product_id)
            .join(PlatformCommon, EbayListing.platform_id == PlatformCommon.id)
            .where(EbayListing.ebay_item_id.isnot(None))
        )
        result = await self.db.execute(query)
        rows = result.fetchall()

        return {row[0]: row[1] for row in rows if row[0] and row[1]}

    async def _get_reverb_product_id_map(self) -> Dict[str, int]:
        """
        Build a mapping of reverb_listing_id -> product_id.
        """
        query = (
            select(ReverbListing.reverb_listing_id, PlatformCommon.product_id)
            .join(PlatformCommon, ReverbListing.platform_id == PlatformCommon.id)
            .where(ReverbListing.reverb_listing_id.isnot(None))
        )
        result = await self.db.execute(query)
        rows = result.fetchall()

        return {row[0]: row[1] for row in rows if row[0] and row[1]}

    async def _update_reverb_listing_stats(
        self,
        reverb_listing_id: str,
        view_count: Optional[int],
        watch_count: Optional[int]
    ) -> bool:
        """
        Update the current stats in reverb_listings table.
        """
        query = select(ReverbListing).where(
            ReverbListing.reverb_listing_id == reverb_listing_id
        )
        result = await self.db.execute(query)
        listing = result.scalar_one_or_none()

        if listing:
            if view_count is not None:
                listing.view_count = view_count
            if watch_count is not None:
                listing.watch_count = watch_count
            listing.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
            return True
        return False

    def _safe_int(self, value: Any) -> Optional[int]:
        """Safely convert value to int."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _extract_price(self, listing: Dict) -> Optional[float]:
        """Extract price from listing data."""
        try:
            price_data = listing.get('price', {})
            if isinstance(price_data, dict):
                amount = price_data.get('amount')
                if amount:
                    return float(str(amount).replace(',', ''))
            elif price_data:
                return float(str(price_data).replace(',', ''))
        except (ValueError, TypeError):
            pass
        return None

    async def get_stats_history(
        self,
        platform: str,
        platform_listing_id: str,
        days: int = 30
    ) -> List[ListingStatsHistory]:
        """
        Get historical stats for a specific listing.

        Args:
            platform: Platform name ('reverb', 'ebay', etc.)
            platform_listing_id: The platform's listing ID
            days: Number of days of history to fetch

        Returns:
            List of historical stat entries, ordered by date descending
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        query = (
            select(ListingStatsHistory)
            .where(
                and_(
                    ListingStatsHistory.platform == platform,
                    ListingStatsHistory.platform_listing_id == platform_listing_id,
                    ListingStatsHistory.recorded_at >= cutoff,
                )
            )
            .order_by(ListingStatsHistory.recorded_at.desc())
        )

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_trending_listings(
        self,
        platform: str,
        days: int = 7,
        min_view_increase: int = 10,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get listings with the biggest view count increases over the period.

        This is a placeholder for more sophisticated trending analysis.
        """
        # TODO: Implement trending analysis with window functions
        # For now, return empty - this can be built out later
        return []
