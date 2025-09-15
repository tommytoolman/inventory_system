"""
Sync Statistics Service

Handles updating and querying sync statistics silently during sync operations.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SyncStats

logger = logging.getLogger(__name__)


class SyncStatsService:
    """Service for managing sync statistics."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def update_stats(
        self,
        summary: Dict[str, int],
        sync_run_id: Optional[str] = None,
        platform: Optional[str] = None,
        duration_seconds: Optional[int] = None
    ) -> None:
        """
        Update sync statistics based on the summary from a sync operation.
        
        This method:
        1. Creates a new sync_stats record for this run
        2. Updates the cumulative totals
        
        Args:
            summary: Dictionary with keys like 'processed', 'sales', 'actions_taken', 'errors'
            sync_run_id: Optional ID of the sync run
            platform: Optional platform name if this is platform-specific
            duration_seconds: Optional duration of the sync operation
        """
        try:
            # Get or create cumulative stats record
            cumulative_stmt = select(SyncStats).where(
                SyncStats.sync_run_id.is_(None),
                SyncStats.platform.is_(None)
            )
            result = await self.db.execute(cumulative_stmt)
            cumulative_stats = result.scalar_one_or_none()
            
            if not cumulative_stats:
                # Create the first cumulative record
                cumulative_stats = SyncStats(
                    sync_run_id=None,
                    platform=None
                )
                self.db.add(cumulative_stats)
            
            # Create a new record for this sync run
            run_stats = SyncStats(
                sync_run_id=sync_run_id,
                platform=platform,
                created_at=datetime.now(timezone.utc)
            )
            
            # Map summary fields to stats fields
            mapping = {
                'processed': ('run_events_processed', 'total_events_processed'),
                'sales': ('run_sales', 'total_sales'),
                'created': ('run_listings_created', 'total_listings_created'),
                'updated': ('run_listings_updated', 'total_listings_updated'),
                'removed': ('run_listings_removed', 'total_listings_removed'),
                'errors': ('run_errors', 'total_errors'),
                'price_changes': ('run_price_changes', 'total_price_changes'),
            }
            
            # Update both run and cumulative stats
            for summary_key, (run_field, total_field) in mapping.items():
                value = summary.get(summary_key, 0)
                if value > 0:
                    # Update run stats
                    setattr(run_stats, run_field, value)
                    # Update cumulative stats
                    current_total = getattr(cumulative_stats, total_field, 0) or 0
                    setattr(cumulative_stats, total_field, current_total + value)
            
            # Handle special cases
            if summary.get('errors', 0) > 0:
                cumulative_stats.total_partial_syncs = (cumulative_stats.total_partial_syncs or 0) + 1
            else:
                cumulative_stats.total_successful_syncs = (cumulative_stats.total_successful_syncs or 0) + 1
            
            # Set duration if provided
            if duration_seconds is not None:
                run_stats.run_duration_seconds = duration_seconds
            
            # Add metadata if there are additional fields
            extra_fields = {k: v for k, v in summary.items() 
                          if k not in ['processed', 'sales', 'created', 'updated', 
                                      'removed', 'errors', 'price_changes', 'actions_taken']}
            if extra_fields:
                run_stats.metadata_json = extra_fields
            
            self.db.add(run_stats)
            await self.db.commit()
            
            logger.debug(f"Stats updated - Events: {summary.get('processed', 0)}, "
                        f"Sales: {summary.get('sales', 0)}, "
                        f"Errors: {summary.get('errors', 0)}")
            
        except Exception as e:
            logger.error(f"Failed to update sync stats: {e}", exc_info=True)
            await self.db.rollback()
    
    async def get_current_stats(self, platform: Optional[str] = None) -> Dict:
        """
        Get current cumulative statistics.
        
        Args:
            platform: Optional platform to filter by
            
        Returns:
            Dictionary with current statistics
        """
        try:
            stmt = select(SyncStats).where(
                SyncStats.sync_run_id.is_(None)
            )
            
            if platform:
                stmt = stmt.where(SyncStats.platform == platform)
            else:
                stmt = stmt.where(SyncStats.platform.is_(None))
            
            result = await self.db.execute(stmt)
            stats = result.scalar_one_or_none()
            
            if not stats:
                return {
                    'total_events_processed': 0,
                    'total_sales': 0,
                    'total_listings_created': 0,
                    'total_listings_updated': 0,
                    'total_listings_removed': 0,
                    'total_errors': 0,
                    'total_successful_syncs': 0,
                    'total_partial_syncs': 0
                }
            
            return {
                'total_events_processed': stats.total_events_processed,
                'total_sales': stats.total_sales,
                'total_listings_created': stats.total_listings_created,
                'total_listings_updated': stats.total_listings_updated,
                'total_listings_removed': stats.total_listings_removed,
                'total_errors': stats.total_errors,
                'total_successful_syncs': stats.total_successful_syncs,
                'total_partial_syncs': stats.total_partial_syncs
            }
            
        except Exception as e:
            logger.error(f"Failed to get sync stats: {e}", exc_info=True)
            return {}