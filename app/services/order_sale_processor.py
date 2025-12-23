"""
Order Sale Processor Service

Processes orders to manage inventory changes:
- For INVENTORIED items (is_stocked_item=True): Orders trigger quantity decrement
- For NON-INVENTORIED items: Platform sync handles status changes, orders just get acknowledged

The sale_processed flag prevents double-counting when orders are re-synced.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductStatus
from app.models.platform_common import PlatformCommon, ListingStatus
from app.models.reverb_order import ReverbOrder
from app.models.ebay_order import EbayOrder
from app.models.shopify_order import ShopifyOrder

logger = logging.getLogger(__name__)


# Platform-specific status mappings to determine if an order indicates a confirmed sale
SALE_STATUSES = {
    "reverb": {
        # Reverb order statuses that indicate a confirmed sale
        "statuses": {"shipped", "received", "payment_pending"},  # payment_pending = buyer paid
        "status_field": "status",
    },
    "ebay": {
        # eBay order statuses that indicate a confirmed sale
        "statuses": {"Completed", "Shipped"},
        "status_field": "order_status",
    },
    "shopify": {
        # Shopify financial statuses that indicate payment received
        "statuses": {"PAID", "PARTIALLY_PAID", "PARTIALLY_REFUNDED"},
        "status_field": "financial_status",
    },
}


class OrderSaleProcessor:
    """
    Processes orders to update inventory based on sales.

    For stocked/inventoried items: Decrements quantity when order indicates a sale.
    For non-stocked items: Just acknowledges the order (platform sync handles status).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    def _is_sale_order(self, platform: str, order) -> bool:
        """
        Determine if an order indicates a confirmed sale based on platform-specific status.
        """
        config = SALE_STATUSES.get(platform)
        if not config:
            return False

        status_field = config["status_field"]
        valid_statuses = config["statuses"]

        order_status = getattr(order, status_field, None)
        if not order_status:
            return False

        # Case-insensitive comparison
        return order_status.lower() in {s.lower() for s in valid_statuses}

    async def _get_product_for_order(self, order) -> Optional[Product]:
        """Get the linked product for an order."""
        if not order.product_id:
            return None
        return await self.db.get(Product, order.product_id)

    async def _propagate_quantity_to_platforms(
        self,
        product: Product,
        source_platform: str,
        dry_run: bool = False,
    ) -> List[str]:
        """
        Propagate quantity changes to other platforms.

        For stocked items, we sync the new quantity.
        If quantity reaches 0, we also need to end listings.

        Returns list of actions taken.
        """
        actions = []

        # Get all platform listings for this product
        result = await self.db.execute(
            select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name != source_platform,
                PlatformCommon.status == ListingStatus.ACTIVE.value,
            )
        )
        other_listings = result.scalars().all()

        if product.quantity == 0:
            # Need to end listings on other platforms
            for listing in other_listings:
                action = f"End listing on {listing.platform_name} (qty=0)"
                actions.append(action)
                if not dry_run:
                    listing.status = ListingStatus.ENDED.value
                    self.db.add(listing)
                    logger.info(
                        "Ended listing for product %s on %s due to zero quantity",
                        product.id,
                        listing.platform_name,
                    )
        else:
            # Just log that quantity changed - actual API sync happens via scheduled jobs
            for listing in other_listings:
                action = f"Queue quantity sync to {listing.platform_name} (qty={product.quantity})"
                actions.append(action)
                logger.info(
                    "Product %s quantity changed to %s, will sync to %s",
                    product.id,
                    product.quantity,
                    listing.platform_name,
                )

        return actions

    async def process_order(
        self,
        order: Union[ReverbOrder, EbayOrder, ShopifyOrder],
        platform: str,
        dry_run: bool = False,
    ) -> Dict:
        """
        Process a single order for inventory management.

        Returns a dict with processing results.
        """
        result = {
            "order_id": None,
            "platform": platform,
            "processed": False,
            "was_already_processed": False,
            "is_sale": False,
            "is_stocked_item": False,
            "quantity_decremented": False,
            "new_quantity": None,
            "actions": [],
            "notes": "",
        }

        # Get order identifier for logging
        if platform == "reverb":
            result["order_id"] = order.order_uuid
        elif platform == "ebay":
            result["order_id"] = order.order_id
        elif platform == "shopify":
            result["order_id"] = order.shopify_order_id

        # Check if already processed
        if order.sale_processed:
            result["was_already_processed"] = True
            result["notes"] = "Order already processed for inventory"
            return result

        # Check if this is a sale order
        if not self._is_sale_order(platform, order):
            result["notes"] = f"Order status does not indicate confirmed sale"
            return result

        result["is_sale"] = True

        # Get linked product
        product = await self._get_product_for_order(order)
        if not product:
            # No linked product - just mark as processed
            result["notes"] = "No linked product, marking order as processed"
            if not dry_run:
                order.sale_processed = True
                order.sale_processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                self.db.add(order)
            result["processed"] = True
            return result

        result["is_stocked_item"] = product.is_stocked_item

        if product.is_stocked_item:
            # INVENTORIED ITEM: Decrement quantity
            quantity_to_decrement = 1

            # For multi-quantity orders, get the quantity from the order
            if platform == "reverb" and order.quantity:
                quantity_to_decrement = order.quantity
            elif platform == "ebay" and order.quantity_purchased:
                quantity_to_decrement = order.quantity_purchased
            elif platform == "shopify" and order.primary_quantity:
                quantity_to_decrement = order.primary_quantity

            if product.quantity >= quantity_to_decrement:
                if not dry_run:
                    product.quantity -= quantity_to_decrement
                    self.db.add(product)

                result["quantity_decremented"] = True
                result["new_quantity"] = product.quantity - (quantity_to_decrement if dry_run else 0)
                result["actions"].append(
                    f"Decremented quantity by {quantity_to_decrement} -> {result['new_quantity']}"
                )

                logger.info(
                    "Sale from %s order %s: Decremented product %s quantity by %d -> %d",
                    platform,
                    result["order_id"],
                    product.id,
                    quantity_to_decrement,
                    result["new_quantity"],
                )

                # Check if product is now sold out
                if (product.quantity if dry_run else result["new_quantity"]) == 0:
                    if not dry_run:
                        product.status = ProductStatus.SOLD
                        self.db.add(product)
                    result["actions"].append("Product marked as SOLD (quantity=0)")
                    logger.info("Product %s marked as SOLD", product.id)

                # Propagate to other platforms
                propagate_actions = await self._propagate_quantity_to_platforms(
                    product, platform, dry_run
                )
                result["actions"].extend(propagate_actions)
            else:
                result["notes"] = (
                    f"Insufficient quantity: have {product.quantity}, "
                    f"order wants {quantity_to_decrement}"
                )
                logger.warning(
                    "Order %s from %s: Insufficient quantity for product %s",
                    result["order_id"],
                    platform,
                    product.id,
                )
        else:
            # NON-INVENTORIED ITEM: Platform sync handles status changes
            # We just acknowledge the order was processed
            result["notes"] = "Non-stocked item: platform sync handles status changes"
            result["actions"].append("Acknowledged sale (platform sync handles listing status)")

        # Mark order as processed
        if not dry_run:
            order.sale_processed = True
            order.sale_processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            self.db.add(order)

        result["processed"] = True
        return result

    async def process_unprocessed_orders(
        self,
        platform: str,
        dry_run: bool = False,
        limit: Optional[int] = None,
    ) -> Dict:
        """
        Process all unprocessed orders for a platform.

        Returns summary of processing results.
        """
        # Select the right model
        if platform == "reverb":
            model = ReverbOrder
        elif platform == "ebay":
            model = EbayOrder
        elif platform == "shopify":
            model = ShopifyOrder
        else:
            raise ValueError(f"Unknown platform: {platform}")

        # Fetch unprocessed orders that indicate sales
        stmt = select(model).where(model.sale_processed == False)

        if limit:
            stmt = stmt.limit(limit)

        result = await self.db.execute(stmt)
        orders = result.scalars().all()

        summary = {
            "platform": platform,
            "dry_run": dry_run,
            "total_unprocessed": len(orders),
            "sales_detected": 0,
            "stocked_items_processed": 0,
            "non_stocked_items_processed": 0,
            "quantity_decrements": 0,
            "already_processed": 0,
            "no_linked_product": 0,
            "errors": 0,
            "details": [],
        }

        for order in orders:
            try:
                result = await self.process_order(order, platform, dry_run)
                summary["details"].append(result)

                if result["was_already_processed"]:
                    summary["already_processed"] += 1
                elif result["is_sale"]:
                    summary["sales_detected"] += 1
                    if result["is_stocked_item"]:
                        summary["stocked_items_processed"] += 1
                        if result["quantity_decremented"]:
                            summary["quantity_decrements"] += 1
                    elif result["processed"]:
                        summary["non_stocked_items_processed"] += 1
                    if not result.get("product_id"):
                        summary["no_linked_product"] += 1

            except Exception as e:
                logger.error(
                    "Error processing %s order: %s",
                    platform,
                    e,
                    exc_info=True,
                )
                summary["errors"] += 1

        if not dry_run:
            await self.db.commit()

        return summary


async def process_platform_orders(
    db: AsyncSession,
    platform: str,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> Dict:
    """
    Convenience function to process orders for a platform.
    """
    processor = OrderSaleProcessor(db)
    return await processor.process_unprocessed_orders(platform, dry_run, limit)
