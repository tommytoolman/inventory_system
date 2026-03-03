# app/services/woocommerce/importer.py
"""
WooCommerce Importer Service - handles bulk import of WooCommerce products into database.
Follows the same pattern as ShopifyImporter.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.enums import SyncStatus, ListingStatus
from app.models.woocommerce import WooCommerceListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.services.woocommerce.client import WooCommerceClient

logger = logging.getLogger(__name__)


class WooCommerceImporter:
    """
    WooCommerce importer service that handles bulk import of WooCommerce products.
    Populates: woocommerce_listings, platform_common, and products tables.
    """

    def __init__(self, db_session: AsyncSession):
        """Initialize with database session."""
        self.session = db_session
        self.client = WooCommerceClient()

    async def import_all_listings(self, status_filter: Optional[str] = None,
                                  limit: Optional[int] = None) -> Dict[str, int]:
        """
        Import all WooCommerce products from API to database.

        Args:
            status_filter: Only import products with this status (publish, draft, etc.)
            limit: Max number of products to import

        Returns:
            Statistics dictionary with counts
        """
        logger.info("Starting WooCommerce product import")
        start_time = datetime.now()

        stats = {
            "total": 0,
            "created": 0,
            "updated": 0,
            "sku_matched": 0,
            "errors": 0,
            "skipped": 0,
        }

        try:
            # Fetch all products from WooCommerce
            logger.info("Fetching all products from WooCommerce API...")
            wc_products = await self.client.get_all_products()

            if limit:
                wc_products = wc_products[:limit]

            logger.info(f"Retrieved {len(wc_products)} products from WooCommerce API")
            stats["total"] = len(wc_products)

            for i, product_data in enumerate(wc_products, 1):
                try:
                    if i % 50 == 0:
                        logger.info(f"Processing product {i}/{len(wc_products)}")

                    # Apply status filter
                    product_status = product_data.get("status", "")
                    if status_filter and product_status != status_filter:
                        stats["skipped"] += 1
                        continue

                    result = await self._process_single_product(product_data)
                    stats[result] += 1

                except Exception as e:
                    logger.error(f"Error processing WooCommerce product {product_data.get('id')}: {e}")
                    stats["errors"] += 1

            await self.session.commit()

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"WooCommerce import completed in {elapsed:.1f}s - "
                f"Total: {stats['total']}, Created: {stats['created']}, "
                f"Updated: {stats['updated']}, SKU matched: {stats['sku_matched']}, "
                f"Errors: {stats['errors']}"
            )

        except Exception as e:
            logger.error(f"WooCommerce import failed: {e}", exc_info=True)
            await self.session.rollback()
            raise

        return stats

    async def _process_single_product(self, wc_data: Dict[str, Any]) -> str:
        """
        Process a single WooCommerce product into the database.

        Returns one of: 'created', 'updated', 'sku_matched'
        """
        wc_product_id = str(wc_data["id"])
        wc_sku = wc_data.get("sku", "")

        # Extract data for our tables
        product_info = self._extract_product_data(wc_data)
        listing_info = self._extract_listing_data(wc_data)
        platform_info = self._extract_platform_common_data(wc_data)

        # Check if WooCommerceListing already exists for this WC product
        existing_listing = await self._find_existing_listing(wc_product_id)

        if existing_listing:
            # UPDATE existing listing
            await self._update_existing(existing_listing, listing_info, platform_info, wc_data)
            return "updated"

        # Check if a Product with matching SKU already exists (cross-platform link)
        if wc_sku:
            existing_product = await self._find_product_by_sku(wc_sku)
            if existing_product:
                await self._create_listing_for_existing_product(
                    existing_product, listing_info, platform_info, wc_data
                )
                logger.info(f"SKU MATCH: WC product {wc_product_id} → existing product SKU {wc_sku}")
                return "sku_matched"

        # CREATE new Product + PlatformCommon + WooCommerceListing
        await self._create_new(product_info, listing_info, platform_info, wc_data)
        return "created"

    # ------------------------------------------------------------------
    # Data extraction helpers
    # ------------------------------------------------------------------

    def _extract_product_data(self, wc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract RIFF Product fields from WooCommerce data."""
        images = wc_data.get("images", [])
        primary_image = images[0]["src"] if images else None
        additional_images = [img["src"] for img in images[1:]] if len(images) > 1 else []

        # Extract brand from attributes or meta
        brand = ""
        model_name = ""
        for attr in wc_data.get("attributes", []):
            name_lower = attr.get("name", "").lower()
            if name_lower == "brand":
                options = attr.get("options", [])
                brand = options[0] if options else ""
            elif name_lower == "model":
                options = attr.get("options", [])
                model_name = options[0] if options else ""

        price_str = wc_data.get("regular_price") or wc_data.get("price") or "0"
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            price = 0.0

        return {
            "sku": wc_data.get("sku") or f"WC-{wc_data['id']}",
            "title": wc_data.get("name", ""),
            "brand": brand,
            "model": model_name,
            "description": wc_data.get("description", ""),
            "base_price": price,
            "quantity": wc_data.get("stock_quantity") or 1,
            "primary_image": primary_image,
            "additional_images": additional_images,
            "category": self._extract_category_name(wc_data),
        }

    def _extract_listing_data(self, wc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract WooCommerceListing-specific fields."""
        price_str = wc_data.get("price") or wc_data.get("regular_price") or "0"
        regular_str = wc_data.get("regular_price") or "0"
        sale_str = wc_data.get("sale_price") or None

        try:
            price = float(price_str)
        except (ValueError, TypeError):
            price = 0.0
        try:
            regular_price = float(regular_str)
        except (ValueError, TypeError):
            regular_price = 0.0
        try:
            sale_price = float(sale_str) if sale_str else None
        except (ValueError, TypeError):
            sale_price = None

        # Parse WC timestamps
        wc_created = self._parse_wc_datetime(wc_data.get("date_created"))
        wc_modified = self._parse_wc_datetime(wc_data.get("date_modified"))

        categories = wc_data.get("categories", [])
        cat_id = str(categories[0]["id"]) if categories else None
        cat_name = categories[0].get("name") if categories else None

        return {
            "wc_product_id": str(wc_data["id"]),
            "slug": wc_data.get("slug"),
            "permalink": wc_data.get("permalink"),
            "title": wc_data.get("name"),
            "status": wc_data.get("status"),
            "product_type": wc_data.get("type"),
            "sku": wc_data.get("sku"),
            "price": price,
            "regular_price": regular_price,
            "sale_price": sale_price,
            "manage_stock": wc_data.get("manage_stock", False),
            "stock_quantity": wc_data.get("stock_quantity"),
            "stock_status": wc_data.get("stock_status"),
            "category_id": cat_id,
            "category_name": cat_name,
            "weight": wc_data.get("weight"),
            "shipping_class": wc_data.get("shipping_class"),
            "total_sales": wc_data.get("total_sales", 0),
            "wc_created_at": wc_created,
            "wc_modified_at": wc_modified,
        }

    def _extract_platform_common_data(self, wc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract PlatformCommon fields."""
        status_map = {
            "publish": ListingStatus.ACTIVE.value,
            "draft": ListingStatus.DRAFT.value,
            "pending": ListingStatus.DRAFT.value,
            "private": ListingStatus.ACTIVE.value,
            "trash": ListingStatus.DELETED.value,
        }
        wc_status = wc_data.get("status", "draft")
        internal_status = status_map.get(wc_status, ListingStatus.DRAFT.value)

        return {
            "platform_name": "woocommerce",
            "external_id": str(wc_data["id"]),
            "status": internal_status,
            "sync_status": SyncStatus.SYNCED.value,
            "listing_url": wc_data.get("permalink"),
            "platform_specific_data": {
                "price": wc_data.get("price"),
                "currency": "GBP",
                "stock_quantity": wc_data.get("stock_quantity"),
                "stock_status": wc_data.get("stock_status"),
            },
        }

    def _extract_category_name(self, wc_data: Dict[str, Any]) -> str:
        """Extract primary category name."""
        categories = wc_data.get("categories", [])
        if categories:
            return categories[0].get("name", "Uncategorised")
        return "Uncategorised"

    def _parse_wc_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse WooCommerce datetime string to naive UTC datetime."""
        if not dt_str:
            return None
        try:
            # WC returns ISO 8601: "2024-01-15T10:30:00"
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _find_existing_listing(self, wc_product_id: str) -> Optional[WooCommerceListing]:
        """Find existing WooCommerceListing by WC product ID."""
        result = await self.session.execute(
            select(WooCommerceListing).where(
                WooCommerceListing.wc_product_id == wc_product_id
            )
        )
        return result.scalar_one_or_none()

    async def _find_product_by_sku(self, sku: str) -> Optional[Product]:
        """Find existing Product by SKU."""
        result = await self.session.execute(
            select(Product).where(Product.sku == sku)
        )
        return result.scalar_one_or_none()

    async def _update_existing(self, existing_listing: WooCommerceListing,
                               listing_info: Dict, platform_info: Dict,
                               wc_data: Dict) -> None:
        """Update an existing WooCommerceListing and its PlatformCommon."""
        # Update listing fields
        for key, value in listing_info.items():
            if hasattr(existing_listing, key) and value is not None:
                setattr(existing_listing, key, value)

        existing_listing.extended_attributes = wc_data
        existing_listing.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Update PlatformCommon
        if existing_listing.platform_id:
            pc_result = await self.session.execute(
                select(PlatformCommon).where(PlatformCommon.id == existing_listing.platform_id)
            )
            platform_common = pc_result.scalar_one_or_none()
            if platform_common:
                platform_common.status = platform_info["status"]
                platform_common.sync_status = SyncStatus.SYNCED.value
                platform_common.listing_url = platform_info.get("listing_url")
                platform_common.platform_specific_data = platform_info.get("platform_specific_data", {})
                platform_common.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)

    async def _create_listing_for_existing_product(self, product: Product,
                                                   listing_info: Dict,
                                                   platform_info: Dict,
                                                   wc_data: Dict) -> None:
        """Create WooCommerceListing + PlatformCommon for an existing Product (SKU match)."""
        # Create PlatformCommon
        platform_common = PlatformCommon(
            product_id=product.id,
            last_sync=datetime.now(timezone.utc).replace(tzinfo=None),
            **platform_info,
        )
        self.session.add(platform_common)
        await self.session.flush()

        # Create WooCommerceListing
        wc_listing = WooCommerceListing(
            platform_id=platform_common.id,
            extended_attributes=wc_data,
            last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            **listing_info,
        )
        self.session.add(wc_listing)

    async def _create_new(self, product_info: Dict, listing_info: Dict,
                          platform_info: Dict, wc_data: Dict) -> None:
        """Create a new Product + PlatformCommon + WooCommerceListing."""
        # Create Product
        product = Product(
            sku=product_info["sku"],
            title=product_info.get("title"),
            brand=product_info.get("brand"),
            model=product_info.get("model"),
            description=product_info.get("description"),
            base_price=product_info.get("base_price"),
            quantity=product_info.get("quantity", 1),
            primary_image=product_info.get("primary_image"),
            additional_images=product_info.get("additional_images", []),
            category=product_info.get("category"),
        )
        self.session.add(product)
        await self.session.flush()

        # Create PlatformCommon
        platform_common = PlatformCommon(
            product_id=product.id,
            last_sync=datetime.now(timezone.utc).replace(tzinfo=None),
            **platform_info,
        )
        self.session.add(platform_common)
        await self.session.flush()

        # Create WooCommerceListing
        wc_listing = WooCommerceListing(
            platform_id=platform_common.id,
            extended_attributes=wc_data,
            last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            **listing_info,
        )
        self.session.add(wc_listing)
