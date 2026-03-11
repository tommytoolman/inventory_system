#!/usr/bin/env python3
"""
Populate extended_attributes for Shopify listings with comprehensive data.

This script fetches fresh data from Shopify API and populates the extended_attributes
field in shopify_listings with URL, images, and other metadata.

Usage:
    # Dry run - see what would be updated
    python scripts/shopify/populate_shopify_extended_attributes.py --dry-run
    
    # Update all Shopify listings
    python scripts/shopify/populate_shopify_extended_attributes.py
    
    # Update specific SKU
    python scripts/shopify/populate_shopify_extended_attributes.py --sku REV-91978727
    
    # Update in batches
    python scripts/shopify/populate_shopify_extended_attributes.py --batch-size 5
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.shopify.client import ShopifyGraphQLClient
from app.core.config import get_settings
from app.database import async_session
from sqlalchemy import text, update
from app.models.shopify import ShopifyListing

def fetch_product_details(client: ShopifyGraphQLClient, product_id: str) -> Optional[Dict]:
    """Fetch comprehensive product data from Shopify."""
    
    query = """
    query GetProduct($id: ID!) {
        product(id: $id) {
            id
            title
            handle
            vendor
            productType
            tags
            status
            onlineStoreUrl
            onlineStorePreviewUrl
            publishedAt
            totalInventory
            
            seo {
                title
                description
            }
            
            category {
                id
                name
                fullName
            }
            
            priceRange {
                minVariantPrice {
                    amount
                    currencyCode
                }
            }
            
            featuredImage {
                url
                altText
            }
            
            images(first: 20) {
                edges {
                    node {
                        url
                        altText
                    }
                }
            }
            
            variants(first: 10) {
                edges {
                    node {
                        id
                        sku
                        price
                        inventoryQuantity
                    }
                }
            }
            
            collections(first: 10) {
                edges {
                    node {
                        id
                        title
                        handle
                    }
                }
            }
            
            resourcePublications(first: 5) {
                edges {
                    node {
                        publication {
                            name
                        }
                        publishDate
                        isPublished
                    }
                }
            }
        }
    }
    """
    
    variables = {"id": f"gid://shopify/Product/{product_id}"}
    
    try:
        data = client._make_request(query, variables)
        return data.get('product') if data else None
    except Exception as e:
        print(f"  ❌ Error fetching product {product_id}: {e}")
        return None

async def get_shopify_listings_to_update(session, sku: Optional[str] = None):
    """Get Shopify listings that need extended_attributes populated."""
    
    if sku:
        query = text("""
            SELECT 
                sl.id as listing_id,
                pc.external_id as shopify_id,
                p.sku,
                sl.extended_attributes,
                sl.category_full_name,
                sl.seo_title
            FROM shopify_listings sl
            JOIN platform_common pc ON sl.platform_id = pc.id
            JOIN products p ON pc.product_id = p.id
            WHERE p.sku = :sku
        """)
        result = await session.execute(query, {"sku": sku})
    else:
        query = text("""
            SELECT 
                sl.id as listing_id,
                pc.external_id as shopify_id,
                p.sku,
                sl.extended_attributes,
                sl.category_full_name,
                sl.seo_title
            FROM shopify_listings sl
            JOIN platform_common pc ON sl.platform_id = pc.id
            JOIN products p ON pc.product_id = p.id
            WHERE (sl.extended_attributes IS NULL OR sl.extended_attributes::text = '{}')
               OR sl.category_full_name IS NULL
               OR sl.seo_title IS NULL
            ORDER BY pc.created_at DESC
            LIMIT 100
        """)
        result = await session.execute(query)
    
    listings = []
    for row in result:
        listings.append({
            'listing_id': row[0],
            'shopify_id': row[1],
            'sku': row[2],
            'current_extended': row[3] or {},
            'current_category': row[4],
            'current_seo_title': row[5]
        })
    
    return listings

async def update_listing_attributes(session, listing: Dict, product_data: Dict, dry_run: bool = False):
    """Update a single listing with extended attributes."""
    
    # Build extended_attributes
    extended_attrs = {
        "handle": product_data.get('handle'),
        "url": product_data.get('onlineStorePreviewUrl'),  # Using the preview URL as main URL
        "online_store_url": product_data.get('onlineStoreUrl'),  # May be null
        "vendor": product_data.get('vendor'),
        "product_type": product_data.get('productType'),
        "tags": product_data.get('tags', []),
        "status": product_data.get('status'),
        "published_at": product_data.get('publishedAt'),
        "total_inventory": product_data.get('totalInventory'),
    }
    
    # Add featured image
    if product_data.get('featuredImage'):
        extended_attrs['featured_image'] = product_data['featuredImage'].get('url')
    
    # Add all images
    images = []
    for edge in product_data.get('images', {}).get('edges', []):
        images.append(edge['node']['url'])
    if images:
        extended_attrs['images'] = images
    
    # Add collections
    collections = []
    for edge in product_data.get('collections', {}).get('edges', []):
        collections.append({
            'title': edge['node']['title'],
            'handle': edge['node']['handle']
        })
    if collections:
        extended_attrs['collections'] = collections
    
    # Add publication status
    publications = []
    for edge in product_data.get('resourcePublications', {}).get('edges', []):
        pub = edge['node']
        publications.append({
            'name': pub['publication']['name'],
            'published': pub['isPublished'],
            'date': pub.get('publishDate')
        })
    if publications:
        extended_attrs['publications'] = publications
    
    # Extract SEO data
    seo = product_data.get('seo', {})
    seo_title = seo.get('title') or product_data.get('title')
    seo_description = seo.get('description', '')
    
    # Extract category
    category = product_data.get('category') or {}
    category_full_name = category.get('fullName', '') if category else ''
    
    if dry_run:
        print(f"\n  Would update {listing['sku']}:")
        print(f"    - URL: {extended_attrs.get('url')}")
        print(f"    - Category: {category_full_name}")
        print(f"    - SEO Title: {seo_title}")
        print(f"    - Images: {len(images)} images")
        return True
    
    # Update the database
    try:
        stmt = (
            update(ShopifyListing)
            .where(ShopifyListing.id == listing['listing_id'])
            .values(
                extended_attributes=extended_attrs,
                category_full_name=category_full_name if category_full_name else None,
                seo_title=seo_title,
                seo_description=seo_description if seo_description else None,
                updated_at=datetime.utcnow()
            )
        )
        await session.execute(stmt)
        
        # Also update the URL in platform_common if we have it
        if extended_attrs.get('url'):
            pc_stmt = text("""
                UPDATE platform_common 
                SET listing_url = :url,
                    updated_at = :updated_at
                WHERE external_id = :shopify_id 
                  AND platform_name = 'shopify'
            """)
            await session.execute(pc_stmt, {
                'url': extended_attrs['url'],
                'updated_at': datetime.utcnow(),
                'shopify_id': listing['shopify_id']
            })
        
        print(f"  ✅ Updated {listing['sku']}: URL={extended_attrs.get('url', 'N/A')[:50]}...")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed to update {listing['sku']}: {e}")
        return False

async def main(dry_run: bool = False, batch_size: int = 10, sku: Optional[str] = None):
    """Main function to populate Shopify extended attributes."""
    
    settings = get_settings()
    client = ShopifyGraphQLClient()
    
    async with async_session() as session:
        # Get listings to update
        print("🔍 Fetching Shopify listings to update...")
        listings = await get_shopify_listings_to_update(session, sku)
        
        if not listings:
            print("✅ No listings need updating!")
            return
        
        print(f"📦 Found {len(listings)} listings to update\n")
        
        if dry_run:
            print("🔄 DRY RUN MODE - No changes will be made\n")
        
        # Process in batches
        successful = 0
        failed = 0
        
        for i in range(0, len(listings), batch_size):
            batch = listings[i:i+batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(listings) + batch_size - 1) // batch_size
            
            print(f"📦 Processing batch {batch_num}/{total_batches}...")
            
            for listing in batch:
                # Fetch fresh data from Shopify
                product_data = fetch_product_details(client, listing['shopify_id'])
                
                if not product_data:
                    print(f"  ⚠️  No data for {listing['sku']}")
                    failed += 1
                    continue
                
                # Update the listing
                success = await update_listing_attributes(session, listing, product_data, dry_run)
                if success:
                    successful += 1
                else:
                    failed += 1
                
                # Small delay to respect rate limits
                await asyncio.sleep(0.5)
            
            # Commit batch
            if not dry_run:
                await session.commit()
                print(f"  💾 Committed batch {batch_num}")
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 SUMMARY:")
        print(f"   Total processed: {len(listings)}")
        print(f"   Successful: {successful}")
        if failed > 0:
            print(f"   Failed: {failed}")
        
        if not dry_run:
            # Check final state
            check_query = text("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN extended_attributes IS NOT NULL 
                               AND extended_attributes::text != '{}' THEN 1 END) as with_attrs,
                    COUNT(CASE WHEN category_full_name IS NOT NULL THEN 1 END) as with_category,
                    COUNT(CASE WHEN seo_title IS NOT NULL THEN 1 END) as with_seo
                FROM shopify_listings
            """)
            result = await session.execute(check_query)
            row = result.fetchone()
            
            print(f"\n   Final State:")
            print(f"   - Total Shopify listings: {row[0]}")
            print(f"   - With extended_attributes: {row[1]} ({row[1]*100//row[0] if row[0] > 0 else 0}%)")
            print(f"   - With category: {row[2]} ({row[2]*100//row[0] if row[0] > 0 else 0}%)")
            print(f"   - With SEO title: {row[3]} ({row[3]*100//row[0] if row[0] > 0 else 0}%)")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Populate Shopify extended attributes")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of listings per batch")
    parser.add_argument("--sku", type=str, help="Update specific SKU only")
    
    args = parser.parse_args()
    
    asyncio.run(main(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        sku=args.sku
    ))