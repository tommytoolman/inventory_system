#!/usr/bin/env python3
"""
Reverb Sync Comparison Tool

This script implements your 4-step sync process:
1. Snapshot Reverb API data
2. Snapshot local Reverb data  
3. Compare the two snapshots
4. Show what changes would be made (without making them)
"""

import asyncio
import sys
import os
from typing import Dict, List, Any, Optional, NamedTuple
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from app.database import get_session
from app.core.config import get_settings
from app.services.reverb.client import ReverbClient

class ReverbSnapshot(NamedTuple):
    """Structure for Reverb snapshot data"""
    timestamp: datetime
    total_listings: int
    listings: Dict[str, Dict]  # external_id -> listing_data
    status_breakdown: Dict[str, int]

class LocalSnapshot(NamedTuple):
    """Structure for local Reverb data"""
    timestamp: datetime
    total_listings: int
    listings: Dict[str, Dict]  # external_id -> local_data
    status_breakdown: Dict[str, int]

class DetectedChange(NamedTuple):
    """Structure for detected changes"""
    external_id: str
    sku: str
    change_type: str  # "status_change", "new_listing", "removed_listing"
    reverb_status: str
    local_status: str
    reverb_mapped: str
    local_mapped: str
    action_needed: str

class ReverbSyncComparison:
    
    def __init__(self):
        self.settings = get_settings()
    
    async def step1_snapshot_reverb_api(self) -> ReverbSnapshot:
        """Step 1: Take snapshot of current Reverb API data"""
        print("📡 Step 1: Fetching current Reverb API data...")
        print("   This may take a few minutes for large inventories...")
        
        try:
            # Initialize Reverb client
            reverb_client = ReverbClient(api_key=self.settings.REVERB_API_KEY)
            
            # Add progress tracking
            print("   🔗 Connecting to Reverb API...")
            
            # Fetch all listings from Reverb with progress updates
            listings = await reverb_client.get_all_listings_detailed(
                max_concurrent=10,
                state="all"  # Get all states: live, sold, ended, draft
            )
            
            print(f"   📦 Processing {len(listings)} listings from API...")
            
            # Convert to lookup dictionary by external_id
            listings_dict = {}
            status_breakdown = {}
            
            # Add progress indicator for processing
            for i, listing in enumerate(listings):
                if i % 100 == 0:  # Update every 100 items
                    print(f"   📊 Processed {i}/{len(listings)} listings...")
                
                # Extract external ID
                external_id = str(listing.get('id'))
                
                # Extract state properly - it's nested in a dict
                state_info = listing.get('state', {})
                if isinstance(state_info, dict):
                    state = state_info.get('slug', 'unknown')  # Extract the actual state string
                else:
                    state = str(state_info) if state_info else 'unknown'
                
                listings_dict[external_id] = {
                    'external_id': external_id,
                    'state': state,
                    'price': listing.get('price', {}).get('amount'),
                    'title': listing.get('title'),
                    'sku': listing.get('sku')
                }
                
                # Count statuses
                status_breakdown[state] = status_breakdown.get(state, 0) + 1
            
            snapshot = ReverbSnapshot(
                timestamp=datetime.now(),
                total_listings=len(listings),
                listings=listings_dict,
                status_breakdown=status_breakdown
            )
            
            print(f"✅ Reverb API snapshot complete: {snapshot.total_listings} listings")
            print(f"   Status breakdown: {snapshot.status_breakdown}")
            
            return snapshot
            
        except Exception as e:
            print(f"❌ Error fetching Reverb data: {e}")
            raise
    
    async def step2_snapshot_local_reverb(self) -> LocalSnapshot:
        """Step 2: Take snapshot of local Reverb data"""
        print("🗃️  Step 2: Fetching local Reverb data...")
        print("   🔍 Querying local database...")
        
        async with get_session() as db:
            # Query local reverb data
            query = text("""
            SELECT 
                pc.external_id,
                rl.reverb_state,
                rl.list_price,
                p.sku,
                p.title,
                psm.central_status as mapped_status
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            LEFT JOIN reverb_listings rl ON pc.external_id = rl.reverb_listing_id
            LEFT JOIN platform_status_mappings psm ON (
                psm.platform_name = 'reverb' 
                AND psm.platform_status = rl.reverb_state
            )
            WHERE pc.platform_name = 'reverb'
            """)
            
            print("   📊 Executing database query...")
            result = await db.execute(query)
            rows = result.fetchall()
            
            print(f"   📦 Processing {len(rows)} local records...")
            
            # Convert to lookup dictionary
            listings_dict = {}
            status_breakdown = {}
            
            for i, row in enumerate(rows):
                if i % 100 == 0:  # Update every 100 items
                    print(f"   📊 Processed {i}/{len(rows)} local records...")
                
                external_id = row.external_id
                state = row.reverb_state or 'unknown'
                
                listings_dict[external_id] = {
                    'external_id': external_id,
                    'state': state,
                    'price': row.list_price,
                    'title': row.title,
                    'sku': row.sku,
                    'mapped_status': row.mapped_status
                }
                
                # Count statuses
                status_breakdown[state] = status_breakdown.get(state, 0) + 1
            
            snapshot = LocalSnapshot(
                timestamp=datetime.now(),
                total_listings=len(listings_dict),
                listings=listings_dict,
                status_breakdown=status_breakdown
            )
            
            print(f"✅ Local snapshot complete: {snapshot.total_listings} listings")
            print(f"   Status breakdown: {snapshot.status_breakdown}")
            
            return snapshot
    
    async def step3_compare_snapshots(self, reverb_snapshot: ReverbSnapshot, local_snapshot: LocalSnapshot) -> List[DetectedChange]:
        """Step 3: Compare snapshots and detect changes"""
        print("🔍 Step 3: Comparing snapshots...")
        print(f"   📊 Comparing {len(reverb_snapshot.listings)} Reverb listings with {len(local_snapshot.listings)} local records...")
        
        changes = []
        
        # Get status mappings for comparison
        print("   🗺️  Loading status mappings...")
        async with get_session() as db:
            mapping_query = text("SELECT platform_status, central_status FROM platform_status_mappings WHERE platform_name = 'reverb'")
            result = await db.execute(mapping_query)
            status_mappings = {row.platform_status: row.central_status for row in result.fetchall()}
        
        print(f"   ✅ Loaded {len(status_mappings)} status mappings")
        
        # Check for status changes in existing listings
        print("   🔄 Checking for status changes...")
        total_to_check = len(reverb_snapshot.listings)
        checked = 0
        
        for external_id in reverb_snapshot.listings:
            checked += 1
            if checked % 500 == 0:  # Update every 500 items
                print(f"   📊 Checked {checked}/{total_to_check} listings for changes...")
            
            reverb_listing = reverb_snapshot.listings[external_id]
            
            if external_id in local_snapshot.listings:
                local_listing = local_snapshot.listings[external_id]
                
                reverb_status = reverb_listing['state']
                local_status = local_listing['state']
                
                # Map to central statuses
                reverb_mapped = status_mappings.get(reverb_status, 'UNKNOWN')
                local_mapped = status_mappings.get(local_status, 'UNKNOWN')
                
                # Check if status changed
                if reverb_status != local_status:
                    action = self._determine_action(reverb_mapped, local_mapped)
                    
                    changes.append(DetectedChange(
                        external_id=external_id,
                        sku=local_listing.get('sku', 'unknown'),
                        change_type="status_change",
                        reverb_status=reverb_status,
                        local_status=local_status,
                        reverb_mapped=reverb_mapped,
                        local_mapped=local_mapped,
                        action_needed=action
                    ))
        
        # Check for new and removed listings with progress
        print("   ➕ Checking for new listings...")
        new_count = 0
        for external_id in reverb_snapshot.listings:
            if external_id not in local_snapshot.listings:
                new_count += 1
                reverb_listing = reverb_snapshot.listings[external_id]
                changes.append(DetectedChange(
                    external_id=external_id,
                    sku=reverb_listing.get('sku', 'unknown'),
                    change_type="new_listing",
                    reverb_status=reverb_listing['state'],
                    local_status="not_found",
                    reverb_mapped=status_mappings.get(reverb_listing['state'], 'UNKNOWN'),
                    local_mapped="NONE",
                    action_needed="CREATE_LOCAL_RECORD"
                ))
        
        print(f"   📊 Found {new_count} new listings")
        
        print("   ➖ Checking for removed listings...")
        removed_count = 0
        for external_id in local_snapshot.listings:
            if external_id not in reverb_snapshot.listings:
                removed_count += 1
                local_listing = local_snapshot.listings[external_id]
                changes.append(DetectedChange(
                    external_id=external_id,
                    sku=local_listing.get('sku', 'unknown'),
                    change_type="removed_listing",
                    reverb_status="not_found",
                    local_status=local_listing['state'],
                    reverb_mapped="NONE",
                    local_mapped=status_mappings.get(local_listing['state'], 'UNKNOWN'),
                    action_needed="MARK_AS_REMOVED"
                ))
        
        print(f"   📊 Found {removed_count} removed listings")
        print(f"✅ Comparison complete: {len(changes)} changes detected")
        return changes
    
    
    def _determine_action(self, reverb_mapped: str, local_mapped: str) -> str:
        """Determine what action is needed based on status change"""
        if reverb_mapped == "SOLD" and local_mapped in ["LIVE", "DRAFT"]:
            return "UPDATE_TO_SOLD_AND_PROPAGATE"
        elif reverb_mapped == "LIVE" and local_mapped == "SOLD":
            return "UPDATE_TO_LIVE_AND_PROPAGATE"  
        elif reverb_mapped != local_mapped:
            return f"UPDATE_STATUS_{local_mapped}_TO_{reverb_mapped}"
        else:
            return "NO_ACTION_NEEDED"
    
    async def step4_show_changes(self, changes: List[DetectedChange]):
        """Step 4: Display what changes would be made (preview mode)"""
        print("\n" + "="*80)
        print("📋 STEP 4: CHANGES THAT WOULD BE MADE")
        print("="*80)
        
        if not changes:
            print("✅ No changes detected - all systems in sync!")
            return
        
        # Group changes by type
        status_changes = [c for c in changes if c.change_type == "status_change"]
        new_listings = [c for c in changes if c.change_type == "new_listing"]
        removed_listings = [c for c in changes if c.change_type == "removed_listing"]
        
        # Show status changes
        if status_changes:
            print(f"\n🔄 STATUS CHANGES ({len(status_changes)}):")
            print("-" * 50)
            for change in status_changes:
                print(f"  SKU: {change.sku}")
                print(f"  Change: {change.local_status} → {change.reverb_status}")
                print(f"  Mapped: {change.local_mapped} → {change.reverb_mapped}")
                print(f"  Action: {change.action_needed}")
                print()
        
        # Show new listings
        if new_listings:
            print(f"\n➕ NEW LISTINGS ({len(new_listings)}):")
            print("-" * 50)
            for change in new_listings:
                print(f"  External ID: {change.external_id}")
                print(f"  Status: {change.reverb_status} ({change.reverb_mapped})")
                print(f"  Action: {change.action_needed}")
                print()
        
        # Show removed listings
        if removed_listings:
            print(f"\n➖ REMOVED LISTINGS ({len(removed_listings)}):")
            print("-" * 50)
            for change in removed_listings:
                print(f"  SKU: {change.sku}")
                print(f"  Last Status: {change.local_status} ({change.local_mapped})")
                print(f"  Action: {change.action_needed}")
                print()
        
        # Summary
        critical_changes = [c for c in status_changes if "SOLD" in c.action_needed]
        print(f"\n📊 SUMMARY:")
        print(f"   Total changes: {len(changes)}")
        print(f"   Critical (sold items): {len(critical_changes)}")
        print(f"   Status changes: {len(status_changes)}")
        print(f"   New listings: {len(new_listings)}")
        print(f"   Removed listings: {len(removed_listings)}")

async def main():
    """Run the complete 4-step Reverb sync comparison"""
    print("🎸 REVERB SYNC COMPARISON TOOL")
    print("=" * 50)
    print("⏱️  This process may take several minutes for large inventories...")
    print()
    
    comparator = ReverbSyncComparison()
    
    try:
        start_time = datetime.now()
        
        # Run all 4 steps with timing
        print(f"⏰ Started at: {start_time.strftime('%H:%M:%S')}")
        
        reverb_snapshot = await comparator.step1_snapshot_reverb_api()
        step1_time = datetime.now()
        print(f"⏱️  Step 1 took: {(step1_time - start_time).total_seconds():.1f} seconds\n")
        
        local_snapshot = await comparator.step2_snapshot_local_reverb()
        step2_time = datetime.now()
        print(f"⏱️  Step 2 took: {(step2_time - step1_time).total_seconds():.1f} seconds\n")
        
        changes = await comparator.step3_compare_snapshots(reverb_snapshot, local_snapshot)
        step3_time = datetime.now()
        print(f"⏱️  Step 3 took: {(step3_time - step2_time).total_seconds():.1f} seconds\n")
        
        await comparator.step4_show_changes(changes)
        
        total_time = datetime.now()
        print(f"\n⏰ Total time: {(total_time - start_time).total_seconds():.1f} seconds")
        
    except Exception as e:
        print(f"❌ Error during sync comparison: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())