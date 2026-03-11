#!/usr/bin/env python3
"""
Product Status Reconciliation Script

This script updates products.status based on actual platform statuses
using the platform_status_mappings table.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from app.database import get_session

class StatusReconciler:
    
    async def preview_changes(self):
        """Preview what changes would be made without applying them"""
        preview_sql = """
        SELECT 
            current_status,
            new_status,
            COUNT(*) as affected_products
        FROM (
            SELECT 
                p.id,
                p.status as current_status,
                CASE 
                    WHEN platform_status = 'SOLD' THEN 'SOLD'
                    WHEN platform_status = 'LIVE' THEN 'ACTIVE'  
                    WHEN platform_status = 'DRAFT' THEN 'DRAFT'
                    ELSE p.status
                END as new_status
            FROM products p
            JOIN (
                SELECT DISTINCT 
                    p.id,
                    CASE 
                        -- Any SOLD status wins (priority-based)
                        WHEN bool_or(psm.central_status = 'SOLD') THEN 'SOLD'
                        -- If no SOLD, check for LIVE
                        WHEN bool_or(psm.central_status = 'LIVE') THEN 'LIVE'
                        -- Otherwise DRAFT
                        ELSE 'DRAFT'
                    END as platform_status
                    
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                LEFT JOIN reverb_listings rl ON (pc.platform_name = 'reverb' AND CONCAT('REV-', pc.external_id) = rl.reverb_listing_id)
                LEFT JOIN ebay_listings el ON (pc.platform_name = 'ebay' AND pc.external_id = el.ebay_item_id)
                LEFT JOIN shopify_listings sl ON (pc.platform_name = 'shopify' AND pc.id = sl.platform_id)
                LEFT JOIN vr_listings vl ON (pc.platform_name = 'vr' AND pc.external_id = vl.vr_listing_id)
                LEFT JOIN platform_status_mappings psm ON (
                    (pc.platform_name = 'reverb' AND psm.platform_name = 'reverb' AND psm.platform_status = rl.reverb_state) OR
                    (pc.platform_name = 'ebay' AND psm.platform_name = 'ebay' AND psm.platform_status = el.listing_status) OR
                    (pc.platform_name = 'shopify' AND psm.platform_name = 'shopify' AND psm.platform_status = sl.status) OR
                    (pc.platform_name = 'vr' AND psm.platform_name = 'vr' AND psm.platform_status = vl.vr_state)
                )
                WHERE psm.central_status IS NOT NULL
                GROUP BY p.id
            ) AS status_logic ON p.id = status_logic.id
        ) changes
        WHERE current_status != new_status
        GROUP BY current_status, new_status
        ORDER BY current_status, new_status;
        """
        
        async with get_session() as db:
            result = await db.execute(text(preview_sql))
            changes = result.fetchall()
            
            if not changes:
                print("✅ No status changes needed - all products are already in sync!")
                return False
            
            print("\n" + "="*60)
            print("PREVIEW: STATUS CHANGES TO BE MADE")
            print("="*60)
            print(f"{'Current Status':<15} {'New Status':<15} {'Affected Products'}")
            print("-" * 50)
            
            total_changes = 0
            for change in changes:
                print(f"{change.current_status:<15} {change.new_status:<15} {change.affected_products}")
                total_changes += change.affected_products
            
            print("-" * 50)
            print(f"{'TOTAL':<30} {total_changes}")
            print("="*60)
            
            return True
    
    async def reconcile_statuses(self, dry_run=True):
        """Reconcile product statuses with platform data"""
        
        if dry_run:
            print("🔍 DRY RUN MODE - No changes will be made")
            has_changes = await self.preview_changes()
            if not has_changes:
                return
            
            confirm = input("\nProceed with actual update? (y/N): ").strip().lower()
            if confirm != 'y':
                print("❌ Update cancelled")
                return
        
        # The actual update query
        update_sql = """
        UPDATE products 
        SET status = CASE 
            WHEN platform_status = 'SOLD' THEN 'SOLD'
            WHEN platform_status = 'LIVE' THEN 'ACTIVE'  
            WHEN platform_status = 'DRAFT' THEN 'DRAFT'
            ELSE products.status
        END
        FROM (
            SELECT DISTINCT 
                p.id,
                CASE 
                    -- Any SOLD status wins (priority-based)
                    WHEN bool_or(psm.central_status = 'SOLD') THEN 'SOLD'
                    -- If no SOLD, check for LIVE
                    WHEN bool_or(psm.central_status = 'LIVE') THEN 'LIVE'
                    -- Otherwise DRAFT
                    ELSE 'DRAFT'
                END as platform_status
                
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id
            LEFT JOIN reverb_listings rl ON (pc.platform_name = 'reverb' AND CONCAT('REV-', pc.external_id) = rl.reverb_listing_id)
            LEFT JOIN ebay_listings el ON (pc.platform_name = 'ebay' AND pc.external_id = el.ebay_item_id)
            LEFT JOIN shopify_listings sl ON (pc.platform_name = 'shopify' AND pc.id = sl.platform_id)
            LEFT JOIN vr_listings vl ON (pc.platform_name = 'vr' AND pc.external_id = vl.vr_listing_id)
            LEFT JOIN platform_status_mappings psm ON (
                (pc.platform_name = 'reverb' AND psm.platform_name = 'reverb' AND psm.platform_status = rl.reverb_state) OR
                (pc.platform_name = 'ebay' AND psm.platform_name = 'ebay' AND psm.platform_status = el.listing_status) OR
                (pc.platform_name = 'shopify' AND psm.platform_name = 'shopify' AND psm.platform_status = sl.status) OR
                (pc.platform_name = 'vr' AND psm.platform_name = 'vr' AND psm.platform_status = vl.vr_state)
            )
            WHERE psm.central_status IS NOT NULL
            GROUP BY p.id
        ) AS status_logic
        WHERE products.id = status_logic.id
        AND products.status != CASE 
            WHEN platform_status = 'SOLD' THEN 'SOLD'
            WHEN platform_status = 'LIVE' THEN 'ACTIVE'  
            WHEN platform_status = 'DRAFT' THEN 'DRAFT'
            ELSE products.status
        END;
        """
        
        async with get_session() as db:
            result = await db.execute(text(update_sql))
            await db.commit()
            
            updated_count = result.rowcount
            print(f"✅ Successfully updated {updated_count} product statuses!")
            
            # Show final status counts
            await self.show_current_status_counts()
    
    async def show_current_status_counts(self):
        """Show current product status distribution"""
        count_sql = "SELECT status, COUNT(*) as count FROM products GROUP BY status ORDER BY count DESC"
        
        async with get_session() as db:
            result = await db.execute(text(count_sql))
            counts = result.fetchall()
            
            print("\n📊 CURRENT PRODUCT STATUS DISTRIBUTION:")
            print("-" * 40)
            for row in counts:
                print(f"{row.status}: {row.count}")

async def main():
    reconciler = StatusReconciler()
    
    print("🔧 PRODUCT STATUS RECONCILIATION TOOL")
    print("This will sync products.status with actual platform statuses")
    
    choice = input("\n1. Preview changes\n2. Run reconciliation\n\nChoice (1-2): ").strip()
    
    if choice == "1":
        await reconciler.preview_changes()
    elif choice == "2":
        await reconciler.reconcile_statuses(dry_run=True)
    else:
        print("Invalid choice")

if __name__ == "__main__":
    asyncio.run(main())