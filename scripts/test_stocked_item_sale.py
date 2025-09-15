#!/usr/bin/env python3
"""Test stocked item sale handling"""

import os
import sys
import asyncio
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import async_session
from app.models.product import Product, ProductStatus
from app.models.sync_event import SyncEvent, SyncEventType
from app.services.sync_services import SyncService
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_stocked_item_sale():
    """Test that stocked items have quantity decremented instead of being marked as sold"""
    
    async with async_session() as db:
        # Find a stocked item with quantity > 1
        result = await db.execute(
            select(Product)
            .where(
                Product.is_stocked_item == True,
                Product.quantity > 1,
                Product.status == ProductStatus.ACTIVE
            )
            .limit(1)
        )
        product = result.scalar_one_or_none()
        
        if not product:
            logger.error("No active stocked items with quantity > 1 found")
            # Create a test stocked item
            product = Product(
                sku="TEST-STOCKED-001",
                title="Test Stocked Item",
                brand="Test Brand",
                model="Test Model",
                base_price=100.0,
                is_stocked_item=True,
                quantity=5,
                status=ProductStatus.ACTIVE
            )
            db.add(product)
            await db.commit()
            await db.refresh(product)
            logger.info(f"Created test stocked product: {product.sku} with quantity {product.quantity}")
        else:
            logger.info(f"Found stocked product: {product.sku} with quantity {product.quantity}")
        
        # Create a mock sale event
        sale_event = SyncEvent(
            platform_name='reverb',
            external_id='TEST-123',
            event_type=SyncEventType.STATUS_CHANGE,
            product_id=product.id,
            change_data={'old': 'live', 'new': 'sold'},
            created_at=datetime.utcnow()
        )
        db.add(sale_event)
        await db.commit()
        
        # Test the sync service
        sync_service = SyncService(db)
        
        # Process the sale event (dry run first)
        logger.info("\n=== DRY RUN TEST ===")
        initial_quantity = product.quantity
        initial_status = product.status
        
        report = await sync_service.process_pending_events(dry_run=True)
        logger.info(f"Dry run report: {report}")
        
        # Refresh to check nothing changed in dry run
        await db.refresh(product)
        assert product.quantity == initial_quantity, "Quantity should not change in dry run"
        assert product.status == initial_status, "Status should not change in dry run"
        
        # Now do actual processing
        logger.info("\n=== ACTUAL PROCESSING ===")
        report = await sync_service.process_pending_events(dry_run=False)
        logger.info(f"Processing report: {report}")
        
        # Refresh and check the results
        await db.refresh(product)
        logger.info(f"\nAfter processing:")
        logger.info(f"  Initial quantity: {initial_quantity}")
        logger.info(f"  New quantity: {product.quantity}")
        logger.info(f"  Status: {product.status}")
        
        # Verify behavior
        if initial_quantity > 1:
            assert product.quantity == initial_quantity - 1, f"Quantity should decrement by 1, but went from {initial_quantity} to {product.quantity}"
            assert product.status == ProductStatus.ACTIVE, f"Status should remain ACTIVE when quantity > 0, but is {product.status}"
            logger.info("✅ SUCCESS: Stocked item quantity decremented correctly!")
        
        # Test multiple sales until quantity reaches 0
        logger.info("\n=== TESTING MULTIPLE SALES ===")
        while product.quantity > 0:
            # Create another sale event
            sale_event = SyncEvent(
                platform_name='reverb',
                external_id=f'TEST-{product.quantity}',
                event_type=SyncEventType.STATUS_CHANGE,
                product_id=product.id,
                change_data={'old': 'live', 'new': 'sold'},
                created_at=datetime.utcnow()
            )
            db.add(sale_event)
            await db.commit()
            
            # Process
            await sync_service.process_pending_events(dry_run=False)
            await db.refresh(product)
            logger.info(f"After sale: Quantity = {product.quantity}, Status = {product.status}")
        
        # Final check - should be SOLD when quantity reaches 0
        assert product.quantity == 0, "Quantity should be 0"
        assert product.status == ProductStatus.SOLD, f"Status should be SOLD when quantity reaches 0, but is {product.status}"
        logger.info("✅ SUCCESS: Product marked as SOLD when quantity reached 0!")

async def main():
    await test_stocked_item_sale()

if __name__ == "__main__":
    asyncio.run(main())