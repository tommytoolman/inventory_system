#!/usr/bin/env python3
"""
View current sync statistics.

This script displays the current cumulative sync statistics
and recent sync run details.
"""

import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, desc
from app.database import async_session
from app.models import SyncStats
from app.services.sync_stats_service import SyncStatsService


async def view_stats():
    async with async_session() as session:
        stats_service = SyncStatsService(session)
        
        print("=== CURRENT CUMULATIVE SYNC STATISTICS ===\n")
        
        # Get cumulative stats
        current_stats = await stats_service.get_current_stats()
        
        print("📊 Overall Statistics:")
        print(f"  Total Events Processed: {current_stats['total_events_processed']:,}")
        print(f"  Total Sales Detected: {current_stats['total_sales']:,}")
        print(f"  Total Listings Created: {current_stats['total_listings_created']:,}")
        print(f"  Total Listings Updated: {current_stats['total_listings_updated']:,}")
        print(f"  Total Listings Removed: {current_stats['total_listings_removed']:,}")
        print(f"  Total Errors: {current_stats['total_errors']:,}")
        print(f"  Successful Syncs: {current_stats['total_successful_syncs']:,}")
        print(f"  Partial Syncs: {current_stats['total_partial_syncs']:,}")
        
        # Get recent sync runs
        print("\n\n=== RECENT SYNC RUNS (Last 10) ===\n")
        
        stmt = select(SyncStats).where(
            SyncStats.sync_run_id.isnot(None)
        ).order_by(desc(SyncStats.created_at)).limit(10)
        
        result = await session.execute(stmt)
        recent_runs = result.scalars().all()
        
        if recent_runs:
            for run in recent_runs:
                print(f"📅 {run.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
                if run.sync_run_id:
                    print(f"   Sync Run: {run.sync_run_id}")
                if run.platform:
                    print(f"   Platform: {run.platform}")
                print(f"   Events: {run.run_events_processed}, Sales: {run.run_sales}, "
                      f"Created: {run.run_listings_created}, Errors: {run.run_errors}")
                if run.run_duration_seconds:
                    print(f"   Duration: {run.run_duration_seconds}s")
                print()
        else:
            print("No sync runs recorded yet.")
        
        # Get stats by platform
        print("\n=== STATS BY PLATFORM ===\n")
        
        for platform in ['reverb', 'ebay', 'shopify', 'vr']:
            platform_stats = await stats_service.get_current_stats(platform)
            if any(v > 0 for v in platform_stats.values()):
                print(f"📦 {platform.upper()}:")
                print(f"   Events: {platform_stats['total_events_processed']:,}")
                print(f"   Sales: {platform_stats['total_sales']:,}")
                print(f"   Created: {platform_stats['total_listings_created']:,}")
                print()


if __name__ == "__main__":
    asyncio.run(view_stats())