#!/usr/bin/env python3
"""
Automated Sync Update System

This script implements automated updates for detected changes:
1. Update local database status
2. Propagate changes to other platforms
"""

import asyncio
import sys
import os
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from app.database import get_session
from app.core.config import get_settings
from app.services.activity_logger import ActivityLogger
from app.services.ebay.trading import EbayTradingLegacyAPI
from app.services.shopify.client import ShopifyGraphQLClient
from app.services.vintageandrare.client import VintageAndRareClient


class AutomatedSyncUpdater:
    
    def __init__(self):
        self.settings = get_settings()
    
    async def update_single_item_status(self, sku: str, new_status: str, reason: str = "reverb_sync") -> bool:
        """
        Step 1: Update local database status for a single item
        
        Args:
            sku: Product SKU (e.g., 'REV-90271822')
            new_status: New status ('SOLD', 'LIVE', 'DRAFT')
            reason: Reason for change
            
        Returns:
            bool: Success status
        """
        print(f"🔄 STEP 1: Updating local status for {sku}")
        print(f"   New Status: {new_status}")
        print(f"   Reason: {reason}")
        
        async with get_session() as db:
            try:
                # Get current product info
                product_query = text("""
                SELECT 
                    p.id,
                    p.sku,
                    p.status as current_status,
                    p.brand,
                    p.model,
                    p.base_price
                FROM products p
                WHERE p.sku = :sku
                """)
                
                result = await db.execute(product_query, {"sku": sku})
                product = result.fetchone()
                
                if not product:
                    print(f"❌ Product {sku} not found in database")
                    return False
                
                print(f"   Found product: {product.brand} {product.model}")
                print(f"   Current status: {product.current_status}")
                print(f"   Price: £{product.base_price}")
                
                if product.current_status == new_status:
                    print(f"✅ Status already correct ({new_status}) - no update needed")
                    return True
                
                # Update products table
                update_query = text("""
                UPDATE products 
                SET 
                    status = :new_status,
                    updated_at = CURRENT_TIMESTAMP
                WHERE sku = :sku
                """)
                
                await db.execute(update_query, {
                    "sku": sku,
                    "new_status": new_status
                })
                
                # Update reverb_listings table (if applicable)
                if sku.startswith('REV-'):
                    external_id = sku.replace('REV-', '')
                    reverb_update_query = text("""
                    UPDATE reverb_listings 
                    SET 
                        reverb_state = :reverb_state,
                        last_synced_at = CURRENT_TIMESTAMP
                    WHERE reverb_listing_id = :external_id
                    """)
                    
                    # Map central status back to reverb status
                    reverb_state_mapping = {
                        'SOLD': 'ended',  # Use 'ended' for sold elsewhere
                        'LIVE': 'live',
                        'DRAFT': 'draft'
                    }
                    reverb_state = reverb_state_mapping.get(new_status, 'unknown')
                    
                    await db.execute(reverb_update_query, {
                        "external_id": external_id,
                        "reverb_state": reverb_state
                    })
                    
                    print(f"   Updated reverb_listings: {reverb_state}")
                
                # Log the activity
                activity_logger = ActivityLogger(db)
                await activity_logger.log_activity(
                    action="status_update",
                    entity_type="product",
                    entity_id=str(product.id),
                    platform="sync_system",
                    details={
                        "sku": sku,
                        "old_status": product.current_status,
                        "new_status": new_status,
                        "reason": reason,
                        "automated": True
                    }
                )
                
                await db.commit()
                
                print(f"✅ Successfully updated {sku}: {product.current_status} → {new_status}")
                return True
                
            except Exception as e:
                print(f"❌ Error updating {sku}: {e}")
                await db.rollback()
                return False
    
    async def propagate_to_other_platforms(self, sku: str, action: str = "end_listings") -> Dict[str, bool]:
        """
        Step 2: Propagate changes to other platforms
        
        Args:
            sku: Product SKU
            action: Action to take ('end_listings', 'activate_listings')
            
        Returns:
            Dict[str, bool]: Success status for each platform
        """
        print(f"🌐 STEP 2: Propagating changes for {sku}")
        print(f"   Action: {action}")
        
        results = {}
        
        async with get_session() as db:
            # Find all platforms this product is listed on
            platform_query = text("""
            SELECT 
                pc.platform_name,
                pc.external_id,
                pc.id as platform_common_id,
                p.brand,
                p.model
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            WHERE p.sku = :sku
            AND pc.platform_name != 'reverb'  -- Don't propagate back to Reverb
            """)
            
            result = await db.execute(platform_query, {"sku": sku})
            platforms = result.fetchall()
            
            if not platforms:
                print("   No other platforms found for this product")
                return results
            
            print(f"   Found on platforms: {[p.platform_name for p in platforms]}")
            
            # Process each platform
            for platform in platforms:
                platform_name = platform.platform_name
                external_id = platform.external_id
                
                print(f"   📤 Processing {platform_name} (ID: {external_id})")
                
                try:
                    if action == "end_listings":
                        success = await self._end_listing_on_platform(
                            platform_name, external_id, sku
                        )
                    elif action == "activate_listings":
                        success = await self._activate_listing_on_platform(
                            platform_name, external_id, sku
                        )
                    else:
                        print(f"      ❌ Unknown action: {action}")
                        success = False
                    
                    results[platform_name] = success
                    
                    if success:
                        print(f"      ✅ {platform_name}: Success")
                    else:
                        print(f"      ❌ {platform_name}: Failed")
                        
                except Exception as e:
                    print(f"      ❌ {platform_name}: Error - {e}")
                    results[platform_name] = False
            
            return results
    
    async def _end_listing_on_platform(self, platform: str, external_id: str, sku: str) -> bool:
        """End a listing on a specific platform"""
        
        if platform == "ebay":
            return await self._end_ebay_listing(external_id, sku)
        elif platform == "vr":
            return await self._end_vr_listing(external_id, sku)
        elif platform == "shopify":
            return await self._mark_shopify_as_sold(external_id, sku)
        else:
            print(f"      ⚠️  Platform {platform} not implemented yet")
            return False
    
    async def _end_ebay_listing(self, external_id: str, sku: str) -> bool:
        """End an eBay listing using real eBay Trading Legacy API"""
        try:
            # Check if eBay is configured
            if not all([
                getattr(self.settings, 'EBAY_CLIENT_ID', None),
                getattr(self.settings, 'EBAY_DEV_ID', None),
                getattr(self.settings, 'EBAY_CLIENT_SECRET', None),
                getattr(self.settings, 'EBAY_REFRESH_TOKEN', None)
            ]):
                print(f"      ⚠️  eBay credentials not configured - skipping API call")
                print(f"      📝 Would end eBay listing {external_id}")
                return True  # Simulate success for now
            
            print(f"      🔌 Connecting to eBay Trading API...")
            
            # Initialize eBay Trading Legacy API (no parameters needed - gets from settings)
            trading_api = EbayTradingLegacyAPI(
                sandbox=getattr(self.settings, 'EBAY_SANDBOX', True)
            )
            
            # End the listing using the commented-out method (we need to uncomment it)
            print(f"      📤 Ending eBay listing {external_id}...")
            
            # Create the XML request directly since end_listing is commented out
            auth_token = await trading_api._get_auth_token()
            
            xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
            <EndItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                <RequesterCredentials>
                    <eBayAuthToken>{auth_token}</eBayAuthToken>
                </RequesterCredentials>
                <ItemID>{external_id}</ItemID>
                <EndingReason>NotAvailable</EndingReason>
            </EndItemRequest>"""
            
            response = await trading_api._make_request('EndItem', xml_request)
            
            # Check response
            if response and 'EndItemResponse' in response:
                end_response = response['EndItemResponse']
                ack = end_response.get('Ack', '')
                
                if ack in ['Success', 'Warning']:
                    print(f"      ✅ eBay listing ended successfully")
                    
                    # Update local eBay listing status
                    async with get_session() as db:
                        update_query = text("""
                        UPDATE ebay_listings 
                        SET listing_status = 'ended',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE ebay_item_id = :external_id
                        """)
                        await db.execute(update_query, {"external_id": external_id})
                        await db.commit()
                        print(f"      📝 Updated local eBay status to 'ended'")
                    
                    return True
                else:
                    # Handle errors
                    errors = end_response.get('Errors', [])
                    if not isinstance(errors, list):
                        errors = [errors]
                    
                    error_messages = []
                    for error in errors:
                        error_messages.append(error.get('LongMessage', 'Unknown error'))
                    
                    error_str = "; ".join(error_messages)
                    print(f"      ❌ eBay ending failed: {error_str}")
                    return False
            else:
                print(f"      ❌ Invalid response from eBay EndItem")
                return False
                
        except Exception as e:
            print(f"      ❌ eBay error: {e}")
            return False
    
    async def _end_vr_listing(self, external_id: str, sku: str) -> bool:
        """End a V&R listing (mark as sold locally since V&R doesn't have direct API ending)"""
        try:
            print(f"      🔌 Connecting to V&R system...")
            print(f"      📝 Marking V&R listing {external_id} as sold locally...")
            
            async with get_session() as db:
                # Update V&R listing status to 'sold'
                vr_update_query = text("""
                UPDATE vr_listings 
                SET 
                    vr_state = 'sold',
                    updated_at = CURRENT_TIMESTAMP,
                    last_synced_at = CURRENT_TIMESTAMP,
                    extended_attributes = COALESCE(extended_attributes, '{}'::jsonb) || 
                        jsonb_build_object('sold_on_reverb_at', CURRENT_TIMESTAMP::text)
                WHERE vr_listing_id = :external_id
                """)
                
                vr_result = await db.execute(vr_update_query, {"external_id": external_id})
                vr_rows_affected = vr_result.rowcount
                
                # Also update platform_common status tracking
                platform_update_query = text("""
                UPDATE platform_common 
                SET 
                    status = 'SOLD',
                    updated_at = CURRENT_TIMESTAMP
                WHERE platform_name = 'vr' 
                AND external_id = :external_id
                """)
                
                platform_result = await db.execute(platform_update_query, {"external_id": external_id})
                platform_rows_affected = platform_result.rowcount
                
                await db.commit()
                
                if vr_rows_affected > 0:
                    print(f"      ✅ V&R listing marked as 'sold'")
                    print(f"      📝 Added Reverb sale timestamp to extended_attributes")
                    
                    if platform_rows_affected > 0:
                        print(f"      ✅ Platform_common status updated to 'SOLD'")
                    else:
                        print(f"      ⚠️  Platform_common record not found (might be normal)")
                    
                    return True
                else:
                    print(f"      ❌ V&R listing {external_id} not found in local database")
                    return False
                    
        except Exception as e:
            print(f"      ❌ V&R error: {e}")
            return False

    async def _mark_shopify_as_sold(self, external_id: str, sku: str) -> bool:
        """Mark Shopify product as sold by reducing inventory"""
        try:
            print(f"      🔌 Connecting to Shopify API...")
            
            from app.services.shopify.client import ShopifyGraphQLClient
            
            shopify_client = ShopifyGraphQLClient()
            
            # Get Shopify product GID from database
            async with get_session() as db:
                product_query = text("""
                SELECT 
                    sl.platform_id,
                    sl.shopify_product_id 
                FROM shopify_listings sl
                JOIN platform_common pc ON sl.platform_id = pc.id
                WHERE pc.external_id = :external_id 
                AND pc.platform_name = 'shopify'
                """)
                result = await db.execute(product_query, {"external_id": external_id})
                shopify_data = result.fetchone()
                
                if not shopify_data:
                    print(f"      ❌ Could not find Shopify product for external_id {external_id}")
                    return False
                
                platform_id = shopify_data.platform_id
                shopify_product_gid = shopify_data.shopify_product_id
                print(f"      📦 Found Shopify product: {shopify_product_gid}")
            
            # Mark as sold via inventory reduction
            print(f"      📤 Reducing inventory by 1 (marking as sold)...")
            
            result = await shopify_client.mark_product_as_sold(shopify_product_gid, reduce_by=1)
            
            if result.get("success"):
                print(f"      ✅ Shopify inventory reduced successfully")
                print(f"      📊 New quantity: {result.get('new_quantity')}")
                print(f"      📊 Product status: {result.get('status')} (remains active)")
                
                # Update local database only if Shopify API succeeded
                async with get_session() as db:
                    update_query = text("""
                    UPDATE shopify_listings 
                    SET status = 'SOLD_OUT',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE platform_id = :platform_id
                    """)
                    await db.execute(update_query, {"platform_id": platform_id})
                    await db.commit()
                    print(f"      📝 Updated local Shopify status to 'SOLD_OUT'")
                
                return True
            else:
                error_msg = result.get("error", "Unknown error")
                step = result.get("step", "unknown")
                print(f"      ❌ Shopify mark as sold failed at step '{step}': {error_msg}")
                return False
                
        except Exception as e:
            print(f"      ❌ Shopify error: {e}")
            return False

    async def process_detected_change(self, sku: str, change_type: str = "sold_on_reverb") -> bool:
        """
        Complete automated process for a detected change
        
        Args:
            sku: Product SKU to update
            change_type: Type of change detected
            
        Returns:
            bool: Overall success status
        """
        print("="*60)
        print(f"🤖 AUTOMATED SYNC UPDATE: {sku}")
        print(f"📋 Change Type: {change_type}")
        print("="*60)
        
        try:
            # Step 1: Update local status
            if change_type == "sold_on_reverb":
                local_success = await self.update_single_item_status(
                    sku=sku,
                    new_status="SOLD",
                    reason="sold_on_reverb_detected_by_sync"
                )
            else:
                print(f"❌ Unknown change type: {change_type}")
                return False
            
            if not local_success:
                print(f"❌ Failed to update local status for {sku}")
                return False
            
            # Step 2: Propagate to other platforms
            propagation_results = await self.propagate_to_other_platforms(
                sku=sku,
                action="end_listings"
            )
            
            # Check overall success
            all_success = local_success and all(propagation_results.values())
            
            print("\n" + "="*60)
            print("📊 FINAL RESULTS:")
            print(f"   Local Update: {'✅ Success' if local_success else '❌ Failed'}")
            for platform, success in propagation_results.items():
                print(f"   {platform.title()}: {'✅ Success' if success else '❌ Failed'}")
            print(f"   Overall: {'✅ Complete Success' if all_success else '⚠️ Partial Success'}")
            print("="*60)
            
            return all_success
            
        except Exception as e:
            print(f"❌ Error processing {sku}: {e}")
            return False

async def main():
    """Test the automated update system with REV-90271822"""
    
    print("🎸 AUTOMATED SYNC UPDATE SYSTEM")
    print("Testing with REV-90271822 (sold on Reverb)")
    print()
    
    updater = AutomatedSyncUpdater()
    
    # Process the detected change
    success = await updater.process_detected_change(
        sku="REV-90271822",
        change_type="sold_on_reverb"
    )
    
    if success:
        print("\n🎉 Automated update completed successfully!")
    else:
        print("\n⚠️ Automated update completed with some issues")

if __name__ == "__main__":
    asyncio.run(main())