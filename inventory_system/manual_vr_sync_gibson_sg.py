#!/usr/bin/env python
"""
Direct V&R Sync Trigger for Gibson SG (RIFF-10000465)
Processes sync_event ID 19235 immediately without needing a background worker
"""

import os
import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.db import connection
from app.services.vr_service import VintageAndRareService
from app.services.vintageandrare.client import VintageAndRareClient
from app.models import SyncEvent, Product

async def manual_sync_gibson_sg():
    """
    Manually trigger V&R sync for Gibson SG (RIFF-10000465, product_id=1112)
    This processes sync_event ID 19235 directly.
    """
    
    print("\n" + "="*70)
    print("MANUAL V&R SYNC TRIGGER — Gibson SG (RIFF-10000465)")
    print("="*70 + "\n")
    
    try:
        # Step 1: Verify the product exists
        print("[1/4] Verifying product exists...")
        product = Product.objects.get(id=1112, sku='RIFF-10000465')
        print(f"✅ Found product: {product.title}")
        print(f"    Description length: {len(product.description) if product.description else 0} chars")
        print(f"    Description preview: {product.description[:100] if product.description else 'EMPTY'}...")
        
        # Step 2: Verify sync event exists
        print("\n[2/4] Verifying sync event exists...")
        sync_event = SyncEvent.objects.get(id=19235, product_id=1112)
        print(f"✅ Found sync_event: ID={sync_event.id}, status={sync_event.status}")
        print(f"    Platform: {sync_event.platform_name}")
        print(f"    Change type: {sync_event.change_type}")
        
        # Step 3: Initialize V&R service
        print("\n[3/4] Initializing V&R service...")
        vr_service = VintageAndRareService()
        vr_client = VintageAndRareClient()
        print("✅ V&R service initialized")
        
        # Step 4: Trigger the sync
        print("\n[4/4] Triggering V&R outbound sync...")
        print("-" * 70)
        
        # Call the VR service to sync this product
        # This should use the HTTP requests path (client.py:846) which directly POSTs item_desc
        result = await vr_service.sync_product_to_vr(
            product_id=1112,
            sku='RIFF-10000465',
            force_update=True
        )
        
        print("-" * 70)
        print(f"✅ Sync completed!")
        print(f"   Result: {result}")
        
        # Step 5: Update sync event status
        print("\n[5/5] Updating sync event status...")
        sync_event.status = 'completed'
        sync_event.processed_at = django.utils.timezone.now()
        sync_event.save()
        print(f"✅ Sync event status updated to: {sync_event.status}")
        
        print("\n" + "="*70)
        print("✅ V&R SYNC COMPLETE!")
        print("="*70)
        print("\nNext steps:")
        print("1. Check Railway logs for: '✅ TinyMCE content flushed to textarea'")
        print("2. Visit Vintage & Rare website")
        print("3. Search for: 'Gibson SG Standard MOD Black 2024'")
        print("4. Open the listing and scroll to Description")
        print("5. Confirm the description is now VISIBLE (not blank)\n")
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        print(f"   Type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    # Run the async function
    asyncio.run(manual_sync_gibson_sg())