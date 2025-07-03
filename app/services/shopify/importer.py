# app/services/shopify/importer.py
"""
Shopify Importer Service - handles bulk import of Shopify listings into database.
Follows the same pattern as ReverbImporter.
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

# Import your proven Shopify client
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

# Database models
from app.core.enums import ProductCondition, SyncStatus
from app.models.shopify import ShopifyListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.services.shopify.client import ShopifyGraphQLClient


logger = logging.getLogger(__name__)

class ShopifyImporter:
    """
    Shopify importer service that handles bulk import of Shopify listings.
    Populates: shopify_listings, platform_common, and products tables.
    """
    
    def __init__(self, db_session: AsyncSession):
        """Initialize with database session."""
        self.session = db_session
        self.client = ShopifyGraphQLClient()
        
    async def import_all_listings(self, status_filter: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, int]:
        """
        Import all Shopify listings from API to database.
        
        Args:
            include_drafts: Whether to import DRAFT status products
            include_archived: Whether to import ARCHIVED status products
            
        Returns:
            Statistics dictionary with counts
        """
        logger.info("Starting Shopify listings import")
        start_time = datetime.now()
        
        stats = {
            "total": 0,
            "created": 0,
            "updated": 0,
            "sku_matched": 0,  # ✅ Add this
            "errors": 0,
            "skipped": 0,
            "active": 0,
            "draft": 0,
            "archived": 0
        }
        
        try:
            # Get all products from Shopify API
            logger.info("Fetching all products from Shopify API...")
            shopify_products = self.client.get_all_products_summary(page_size=250)

            # Apply limit if specified
            if limit:
                shopify_products = shopify_products[:limit]
                logger.info(f"Limited to first {limit} products")

            # Apply limit if specified
            if limit:
                shopify_products = shopify_products[:limit]
            
            logger.info(f"Retrieved {len(shopify_products)} products from Shopify API")
            stats["total"] = len(shopify_products)
            
            # Process each product
            for i, product_data in enumerate(shopify_products, 1):
                try:
                    # Log progress every 50 products
                    if i % 50 == 0:
                        logger.info(f"Processing product {i}/{len(shopify_products)}")
                    
                    # Apply limit if specified
                    if limit and i > limit:
                        break

                    # Filter by status if needed
                    product_status = product_data.get("status", "").upper()

                    if status_filter and product_status != status_filter:
                        stats["skipped"] += 1
                        continue
                    
                    # Count by status
                    if product_status == "ACTIVE":
                        stats["active"] += 1
                    elif product_status == "DRAFT":
                        stats["draft"] += 1
                    elif product_status == "ARCHIVED":
                        stats["archived"] += 1
                    
                    # Process this product
                    result = await self._process_single_product(product_data)
                    
                    if result == "created":
                        stats["created"] += 1
                    elif result == "updated":
                        stats["updated"] += 1
                    elif result == "sku_matched":
                        stats["sku_matched"] += 1
                    
                except Exception as e:
                    logger.error(f"Error processing product {product_data.get('id', 'unknown')}: {str(e)}")
                    stats["errors"] += 1
                    continue
            
            # Commit all changes
            await self.session.commit()
            
            duration = datetime.now() - start_time
            logger.info(f"Shopify import completed in {duration}")
            logger.info(f"Stats: {stats}")
            
            return stats
            
        except Exception as e:
            logger.exception("Error during Shopify import")
            await self.session.rollback()
            raise
    
    async def _process_single_product(self, product_data: Dict[str, Any]) -> str:
        """
        Process a single product from Shopify API data.
        Creates entries in shopify_listings, platform_common, and products tables.
        
        Returns:
            "created" or "updated" or "sku_matched"
        """
        
        shopify_gid = product_data.get("id")
        shopify_id = shopify_gid.split("/")[-1] if shopify_gid else None
        
        if not shopify_id:
            raise ValueError("Product missing Shopify ID")
    
        # Extract data first
        product_data_processed = self._extract_product_data(product_data)
        listing_data = self._extract_listing_data(product_data)
        platform_common_data = self._extract_platform_common_data(product_data)
        
        current_sku = str(product_data_processed.get("sku", "") or "").strip()
        
        # Check if shopify_listing already exists (for updates)
        existing_listing = await self.session.execute(
            select(ShopifyListing).where(ShopifyListing.shopify_legacy_id == shopify_id)
        )
        existing_listing = existing_listing.scalar_one_or_none()
        
        if existing_listing:
            # Update existing Shopify listing
            await self._update_existing_product(
                existing_listing, 
                product_data_processed, 
                listing_data, 
                platform_common_data
            )
            return "updated"
        
        # Check if Product with same SKU already exists
        existing_product = await self.session.execute(
            select(Product).where(Product.sku == current_sku)
        )
        existing_product = existing_product.scalar_one_or_none()
        
        if existing_product:
            # SKU already exists - log the match and use existing product
            logger.info(f"SKU MATCH FOUND:")
            logger.info(f"  Shopify Product: {product_data.get('title', 'N/A')}")
            logger.info(f"  Shopify ID: {shopify_id}")
            logger.info(f"  SKU: {current_sku}")
            logger.info(f"  Existing Product ID: {existing_product.id}")
            logger.info(f"  Existing Product Title: {existing_product.title or existing_product.display_title}")
            logger.info(f"  Existing Product Brand: {existing_product.brand}")
            logger.info(f"  → Reusing existing product, creating Shopify listing")
            
            # Create shopify_listing and platform_common for existing product
            await self._create_platform_records_for_existing_product(
                existing_product.id,
                listing_data,
                platform_common_data
            )
            return "sku_matched"
        else:
            # Create completely new product
            await self._create_new_product(
                product_data_processed, 
                listing_data, 
                platform_common_data
            )
            return "created"
    
    def _extract_product_data(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract data for the products table."""
        
        # DEBUG: Let's see what we actually have
        variants_raw = product_data.get("variants")
        # logger.info(f"DEBUG variants_raw: {variants_raw}")
        # logger.info(f"DEBUG variants_raw type: {type(variants_raw)}")
        
        # Get primary variant data - with proper null checking
        if variants_raw is None:
            # logger.info("DEBUG: variants is None")
            primary_variant = {}
        elif isinstance(variants_raw, dict):
            # logger.info(f"DEBUG: variants is dict with keys: {variants_raw.keys()}")
            variants_nodes = variants_raw.get("nodes", [])
            primary_variant = variants_nodes[0] if variants_nodes else {}
        elif isinstance(variants_raw, list):
            # logger.info(f"DEBUG: variants is list with length: {len(variants_raw)}")
            primary_variant = variants_raw[0] if variants_raw else {}
        else:
            # logger.info(f"DEBUG: variants is unexpected type: {type(variants_raw)}")
            primary_variant = {}
        
        # logger.info(f"DEBUG primary_variant: {primary_variant}")
        
        # Force SKU to be string and remove .0 suffix
        raw_sku = str(primary_variant.get("sku", "") or "").strip()
        if raw_sku.endswith('.0'):
            raw_sku = raw_sku[:-2]  # Remove .0 suffix
            
        # logger.info(f"DEBUG final SKU: {raw_sku}")
        
        # Get category data
        category = product_data.get("category", {})
        category_full_name = category.get("fullName") if category else None
        
        return {
            "sku": raw_sku,
            "title": product_data.get("title", "").strip() if product_data.get("title") else None,
            "description": product_data.get("description", ""),
            "brand": product_data.get("vendor", "").strip(),
            "category": category_full_name,
            "condition": ProductCondition.GOOD,
            "created_at": self._parse_shopify_date(product_data.get("createdAt")),
            "updated_at": self._parse_shopify_date(product_data.get("updatedAt")),
        }
    
    def _extract_listing_data(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract data for the shopify_listings table."""
        
        shopify_gid = product_data.get("id")
        shopify_id = shopify_gid.split("/")[-1] if shopify_gid else None
        
        # Get primary variant data
        variants = product_data.get("variants", {}).get("nodes", [])
        primary_variant = variants[0] if variants else {}
        
        # Get category data with null safety
        category = product_data.get("category", {})
        if category is None:
            category = {}
        
        # Get media data (first image)
        media_edges = product_data.get("media", {}).get("edges", [])
        featured_image_url = None
        if media_edges:
            first_image = media_edges[0].get("node", {}).get("preview", {}).get("image", {})
            featured_image_url = first_image.get("url")
        
        return {
            "shopify_legacy_id": shopify_id,
            "shopify_product_id": shopify_gid,
            "handle": product_data.get("handle", "").strip(),
            "title": product_data.get("title", "").strip(),
            # "description": product_data.get("description", ""),
            # "description_html": product_data.get("descriptionHtml", ""),
            "vendor": product_data.get("vendor", "").strip(),
            # "product_type": product_data.get("productType", "").strip(),
            "status": product_data.get("status", "").upper(),
            # "tags": product_data.get("tags", []),
            
            # Variant data (primary variant)
            # "variant_id": primary_variant.get("id", "").split("/")[-1] if primary_variant.get("id") else None,
            # "variant_sku": str(primary_variant.get("sku", "")).strip(),
            "price": float(primary_variant.get("price", 0)) if primary_variant.get("price") else None,
            # "compare_at_price": float(primary_variant.get("compareAtPrice", 0)) if primary_variant.get("compareAtPrice") else None,
            # "inventory_quantity": primary_variant.get("inventoryQuantity", 0),
            # "available_for_sale": primary_variant.get("availableForSale", False),

            # Category data
            "category_gid": category.get("id"),
            "category_name": category.get("name"),
            "category_full_name": category.get("fullName"),
            
            # SEO data
            "seo_title": product_data.get("seo", {}).get("title"),
            "seo_description": product_data.get("seo", {}).get("description"),

            # Media
            # "featured_image_url": featured_image_url,
            # "media_count": product_data.get("mediaCount", {}).get("count", 0),
            
            # Timestamps
            # "published_at": self._parse_shopify_date(product_data.get("publishedAt")),
            # "created_at": self._parse_shopify_date(product_data.get("createdAt")),
            # "updated_at": self._parse_shopify_date(product_data.get("updatedAt")),
            
            # Store URLs
            # "online_store_url": product_data.get("onlineStoreUrl"),
            # "online_store_preview_url": product_data.get("onlineStorePreviewUrl"),
            
            "extended_attributes": product_data,  # Store full Shopify JSON
        }
    
    def _extract_platform_common_data(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract data for the platform_common table."""
        
        # Get primary variant data - use the same safe logic as product extraction
        variants_raw = product_data.get("variants")
        if variants_raw is None:
            primary_variant = {}
        elif isinstance(variants_raw, dict):
            variants_nodes = variants_raw.get("nodes", [])
            primary_variant = variants_nodes[0] if variants_nodes else {}
        elif isinstance(variants_raw, list):
            primary_variant = variants_raw[0] if variants_raw else {}
        else:
            primary_variant = {}
        
        shopify_status = product_data.get("status", "").upper()
        platform_status = self._map_shopify_status_to_platform_status(shopify_status)
        
        # Build listing URL from handle
        handle = product_data.get("handle", "")
        listing_url = f"https://londonvintageguitars.myshopify.com/products/{handle}" if handle else None
            
        # Store price and other data in platform_specific_data
        platform_specific_data = {
            "price": primary_variant.get("price"),
            "currency": "GBP",
            "inventory_quantity": primary_variant.get("inventoryQuantity"),
            "available_for_sale": primary_variant.get("availableForSale"),
        }
        
        return {
            "platform_name": "shopify",
            "external_id": product_data.get("id", "").split("/")[-1] if product_data.get("id") else None,
            "status": platform_status,
             "listing_url": listing_url,  # ✅ Fixed: Build from handle
            "last_sync": datetime.now(timezone.utc).replace(tzinfo=None),  # ✅ Fixed: Current timestamp (naive)
            "sync_status": SyncStatus.SYNCED,  # ✅ Fixed: Set to SYNCED since we just synced
            "platform_specific_data": platform_specific_data,
            "created_at": self._parse_shopify_date(product_data.get("createdAt")),
            "updated_at": self._parse_shopify_date(product_data.get("updatedAt")),
        }
    
    def _map_shopify_status_to_platform_status(self, shopify_status: str) -> str:
        """Map Shopify status to platform_common status."""
        status_mapping = {
            "ACTIVE": "active",
            "DRAFT": "draft", 
            "ARCHIVED": "archived"
        }
        return status_mapping.get(shopify_status, "unknown")
    
    async def _create_platform_records_for_existing_product(
        self,
        product_id: int,
        listing_data: Dict[str, Any],
        platform_common_data: Dict[str, Any]
    ):
        """Create shopify_listing and platform_common for existing product."""
        
        # Create platform_common record FIRST
        platform_common_data["product_id"] = product_id
        platform_listing = PlatformCommon(**platform_common_data)
        self.session.add(platform_listing)
        await self.session.flush()  # Get the platform_listing.id
        
        # Create shopify_listing record with platform_id link
        listing_data["platform_id"] = platform_listing.id  # ✅ Add this link!
        listing = ShopifyListing(**listing_data)
        self.session.add(listing)
    
    async def _create_new_product(
        self, 
        product_data: Dict[str, Any], 
        listing_data: Dict[str, Any], 
        platform_common_data: Dict[str, Any]
    ):
        """Create new product, listing, and platform_common records."""
        
        # Create product record
        product = Product(**product_data)
        self.session.add(product)
        await self.session.flush()  # Get the product.id
        
        # Create platform_common record
        platform_common_data["product_id"] = product.id
        platform_listing = PlatformCommon(**platform_common_data)
        self.session.add(platform_listing)
        await self.session.flush()  # Get the platform_listing.id
        
        # Create shopify_listing record with platform_id link
        listing_data["platform_id"] = platform_listing.id  # ✅ This is the key line!
        listing = ShopifyListing(**listing_data)
        self.session.add(listing)
    
    async def _update_existing_product(
        self, 
        existing_listing: ShopifyListing,
        product_data: Dict[str, Any], 
        listing_data: Dict[str, Any], 
        platform_common_data: Dict[str, Any]
    ):
        """Update existing product, listing, and platform_common records."""
        
        # Get the product_id from the related platform_common record
        platform_listing = await self.session.execute(
            select(PlatformCommon).where(PlatformCommon.id == existing_listing.platform_id)
        )
        platform_listing = platform_listing.scalar_one_or_none()
        
        if not platform_listing:
            logger.warning(f"No platform_common found for ShopifyListing {existing_listing.id}")
            return
        
        product_id = platform_listing.product_id
        
        # Update product record
        product = await self.session.get(Product, product_id)
        if product:
            for key, value in product_data.items():
                if key not in ['created_at', 'updated_at']:  # Don't overwrite timestamps
                    setattr(product, key, value)
        
        # Update shopify_listing record
        for key, value in listing_data.items():
            setattr(existing_listing, key, value)
        
        # Update platform_common record
        if platform_listing:
            for key, value in platform_common_data.items():
                if key != "product_id":
                    setattr(platform_listing, key, value)
    
    def _parse_shopify_date(self, date_string: Optional[str]) -> Optional[datetime]:
        """Parse Shopify ISO date string to naive datetime object."""
        if not date_string:
            return None
        
        try:
            # Shopify uses ISO format: "2025-06-02T13:03:46Z"
            if date_string.endswith('Z'):
                date_string = date_string[:-1] + '+00:00'
            
            # Parse as timezone-aware then convert to naive UTC
            aware_dt = datetime.fromisoformat(date_string)
            
            # Convert to naive datetime (remove timezone info)
            if aware_dt.tzinfo is not None:
                naive_dt = aware_dt.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                naive_dt = aware_dt
                
            return naive_dt
            
        except (ValueError, TypeError):
            logger.warning(f"Could not parse date: {date_string}")
            return None
        
        