#!/usr/bin/env python3
"""
Enrich a product with data fetched from platform APIs.
Fetches full listing data from Reverb, eBay, and V&R to populate missing fields.

Usage:
    python scripts/enrich_product_from_apis.py --product-id 545
"""

import asyncio
import argparse
from typing import Optional, Dict, Any
from sqlalchemy import select, update
from app.database import async_session
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.services.reverb_client import ReverbClient
from app.services.ebay_client import EbayClient
from app.services.vintage_and_rare_client import VintageAndRareClient
from app.core.config import Settings
from datetime import datetime

async def fetch_reverb_data(reverb_id: str, settings: Settings) -> Dict[str, Any]:
    """Fetch full listing data from Reverb API"""
    async with async_session() as session:
        reverb_client = ReverbClient(
            api_key=settings.REVERB_API_KEY,
            db_session=session
        )
        
        try:
            listing = await reverb_client.get_listing(reverb_id)
            if not listing:
                print(f"❌ Could not fetch Reverb listing {reverb_id}")
                return {}
                
            return {
                "title": listing.get("title"),
                "description": listing.get("description"),
                "category": listing.get("categories", [{}])[0].get("full_name") if listing.get("categories") else None,
                "additional_images": [img.get("_links", {}).get("large", {}).get("href", "") 
                                    for img in listing.get("photos", [])],
                "year": listing.get("year"),
                "finish": listing.get("finish"),
                "condition": listing.get("condition", {}).get("display_name"),
                "shipping_profile_id": listing.get("shipping", {}).get("profile", {}).get("id")
            }
        except Exception as e:
            print(f"❌ Error fetching Reverb data: {e}")
            return {}

async def fetch_ebay_data(ebay_id: str, settings: Settings) -> Dict[str, Any]:
    """Fetch full listing data from eBay API"""
    async with async_session() as session:
        ebay_client = EbayClient(
            client_id=settings.EBAY_CLIENT_ID,
            client_secret=settings.EBAY_CLIENT_SECRET,
            refresh_token=settings.EBAY_REFRESH_TOKEN,
            db_session=session
        )
        
        try:
            listing = await ebay_client.get_listing(ebay_id)
            if not listing:
                print(f"❌ Could not fetch eBay listing {ebay_id}")
                return {}
                
            # Extract images from PictureDetails
            images = []
            if "PictureDetails" in listing and "PictureURL" in listing["PictureDetails"]:
                pic_urls = listing["PictureDetails"]["PictureURL"]
                if isinstance(pic_urls, str):
                    images = [pic_urls]
                else:
                    images = pic_urls
                    
            return {
                "title": listing.get("Title"),
                "description": listing.get("Description"),
                "category": listing.get("PrimaryCategory", {}).get("CategoryName"),
                "additional_images": images,
                "condition": listing.get("ConditionDisplayName")
            }
        except Exception as e:
            print(f"❌ Error fetching eBay data: {e}")
            return {}

async def fetch_vr_data(vr_id: str, settings: Settings) -> Dict[str, Any]:
    """Fetch full listing data from V&R"""
    async with async_session() as session:
        vr_client = VintageAndRareClient(
            username=settings.VINTAGE_AND_RARE_USERNAME,
            password=settings.VINTAGE_AND_RARE_PASSWORD,
            db_session=session
        )
        
        try:
            # V&R doesn't have a get listing API, so we'd need to parse from CSV
            # For now, return empty - would need to implement CSV parsing
            print(f"⚠️  V&R API fetch not implemented - would need CSV parsing")
            return {}
        except Exception as e:
            print(f"❌ Error fetching V&R data: {e}")
            return {}

async def enrich_product(product_id: int, dry_run: bool = False):
    """Enrich a product with data from platform APIs"""
    
    async with async_session() as session:
        # Get product and platform links
        result = await session.execute(
            select(Product).where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        
        if not product:
            print(f"❌ Product {product_id} not found")
            return
            
        print(f"\nEnriching product {product_id}: {product.sku}")
        print(f"Current state:")
        print(f"  Title: {product.title or 'None'}")
        print(f"  Category: {product.category or 'None'}")
        print(f"  Description: {'Yes' if product.description else 'No'}")
        print(f"  Additional Images: {len(product.additional_images) if product.additional_images else 0}")
        
        # Get platform links
        result = await session.execute(
            select(PlatformCommon).where(PlatformCommon.product_id == product_id)
        )
        platform_links = result.scalars().all()
        
        settings = Settings()
        enrichment_data = {}
        
        # Fetch data from each platform
        for link in platform_links:
            print(f"\nFetching from {link.platform_name}...")
            
            if link.platform_name == 'reverb':
                data = await fetch_reverb_data(link.external_id, settings)
                if data:
                    enrichment_data.update(data)
                    
            elif link.platform_name == 'ebay':
                data = await fetch_ebay_data(link.external_id, settings)
                if data:
                    # eBay data is supplementary
                    for key, value in data.items():
                        if key not in enrichment_data or not enrichment_data[key]:
                            enrichment_data[key] = value
                            
            elif link.platform_name == 'vr':
                data = await fetch_vr_data(link.external_id, settings)
                if data:
                    enrichment_data.update(data)
        
        # Show what would be updated
        print("\nEnrichment data collected:")
        updates_needed = {}
        
        if enrichment_data.get("title") and not product.title:
            updates_needed["title"] = enrichment_data["title"]
            print(f"  Title: {enrichment_data['title']}")
            
        if enrichment_data.get("category") and not product.category:
            updates_needed["category"] = enrichment_data["category"]
            print(f"  Category: {enrichment_data['category']}")
            
        if enrichment_data.get("description") and not product.description:
            updates_needed["description"] = enrichment_data["description"]
            print(f"  Description: {len(enrichment_data['description'])} chars")
            
        if enrichment_data.get("additional_images") and len(enrichment_data["additional_images"]) > len(product.additional_images or []):
            updates_needed["additional_images"] = enrichment_data["additional_images"]
            print(f"  Additional Images: {len(enrichment_data['additional_images'])} images")
            
        if enrichment_data.get("year") and not product.year:
            updates_needed["year"] = int(enrichment_data["year"])
            print(f"  Year: {enrichment_data['year']}")
            
        if enrichment_data.get("finish") and not product.finish:
            updates_needed["finish"] = enrichment_data["finish"]
            print(f"  Finish: {enrichment_data['finish']}")
            
        if not updates_needed:
            print("\n✅ No updates needed - product already has complete data")
            return
            
        if dry_run:
            print("\n[DRY RUN] Would update product with above data")
            return
            
        # Apply updates
        for field, value in updates_needed.items():
            setattr(product, field, value)
            
        # Calculate decade if year is set
        if product.year and not product.decade:
            product.decade = (product.year // 10) * 10
            
        await session.commit()
        
        print(f"\n✅ Updated product {product_id} with enriched data")

async def main():
    parser = argparse.ArgumentParser(description='Enrich product data from platform APIs')
    parser.add_argument('--product-id', type=int, required=True,
                       help='Product ID to enrich')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would happen without making changes')
    
    args = parser.parse_args()
    
    await enrich_product(args.product_id, args.dry_run)

if __name__ == "__main__":
    asyncio.run(main())
