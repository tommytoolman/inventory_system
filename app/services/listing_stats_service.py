# app/services/listing_stats_service.py
"""
Listing Stats Service

Handles fetching and storing engagement metrics (views, watches) from
various platforms, with historical tracking for trend analysis.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listing_stats_history import ListingStatsHistory
from app.models.reverb import ReverbListing
from app.models.platform_common import PlatformCommon
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
