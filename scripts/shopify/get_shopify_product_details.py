#!/usr/bin/env python3
"""
Get detailed Shopify product information to understand what data is available.

Usage:
    # Get product by Shopify ID
    python scripts/shopify/get_shopify_product_details.py --id 12236710936916
    
    # Get product by SKU
    python scripts/shopify/get_shopify_product_details.py --sku REV-91978727
    
    # Save to JSON
    python scripts/shopify/get_shopify_product_details.py --sku REV-91978727 --save
"""

import asyncio
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.shopify.client import ShopifyGraphQLClient
from app.core.config import get_settings
from app.database import async_session
from sqlalchemy import text

def fetch_product_details(client: ShopifyGraphQLClient, product_id: str):
    """Fetch detailed product information from Shopify."""
    
    # GraphQL query to get comprehensive product data
    query = """
    query GetProduct($id: ID!) {
        product(id: $id) {
            id
            title
            handle
            description
            vendor
            productType
            tags
            status
            createdAt
            updatedAt
            publishedAt
            onlineStoreUrl
            totalInventory
            tracksInventory
            
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
                maxVariantPrice {
                    amount
                    currencyCode
                }
            }
            
            featuredImage {
                url
                altText
            }
            
            images(first: 10) {
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
                        title
                        sku
                        price
                        compareAtPrice
                        availableForSale
                        inventoryQuantity
                        barcode
                    }
                }
            }
            
            metafields(first: 20) {
                edges {
                    node {
                        namespace
                        key
                        value
                        type
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
        }
    }
    """
    
    variables = {"id": f"gid://shopify/Product/{product_id}"}
    
    try:
        data = client._make_request(query, variables)
        return data.get('product') if data else None
    except Exception as e:
        print(f"Error fetching product: {e}")
        return None

async def get_shopify_id_from_sku(sku: str):
    """Get Shopify product ID from SKU."""
    async with async_session() as session:
        query = text("""
            SELECT pc.external_id
            FROM platform_common pc
            JOIN products p ON pc.product_id = p.id
            WHERE p.sku = :sku
              AND pc.platform_name = 'shopify'
        """)
        result = await session.execute(query, {"sku": sku})
        row = result.fetchone()
        return row[0] if row else None

async def main(product_id: str = None, sku: str = None, save_to_file: bool = False):
    """Main function to fetch and display Shopify product details."""
    
    settings = get_settings()
    
    # Get Shopify ID if SKU provided
    if sku and not product_id:
        product_id = await get_shopify_id_from_sku(sku)
        if not product_id:
            print(f"❌ No Shopify product found for SKU: {sku}")
            return
        print(f"Found Shopify ID: {product_id} for SKU: {sku}\n")
    
    if not product_id:
        print("❌ Please provide either --id or --sku")
        return
    
    # Initialize Shopify client - it loads settings internally
    client = ShopifyGraphQLClient()
    
    print(f"📦 Fetching Shopify product {product_id}...\n")
    
    # Fetch product details
    product = fetch_product_details(client, product_id)
    
    if not product:
        print(f"❌ Product not found or error fetching data")
        return
    
    # Display key information
    print("=" * 60)
    print(f"PRODUCT DETAILS:")
    print("=" * 60)
    print(f"Title: {product.get('title')}")
    print(f"Handle: {product.get('handle')}")
    print(f"Status: {product.get('status')}")
    print(f"Vendor: {product.get('vendor')}")
    print(f"Product Type: {product.get('productType')}")
    print(f"Tags: {', '.join(product.get('tags', []))}")
    
    # URLs
    print(f"\n📌 URLs:")
    print(f"Online Store URL: {product.get('onlineStoreUrl')}")
    
    # SEO
    seo = product.get('seo', {})
    print(f"\n🔍 SEO:")
    print(f"SEO Title: {seo.get('title', 'Not set')}")
    print(f"SEO Description: {seo.get('description', 'Not set')}")
    
    # Category
    category = product.get('category', {})
    if category:
        print(f"\n📂 Category:")
        print(f"Name: {category.get('name')}")
        print(f"Full Name: {category.get('fullName')}")
    
    # Pricing
    price_range = product.get('priceRange', {})
    if price_range:
        min_price = price_range.get('minVariantPrice', {})
        print(f"\n💰 Price:")
        print(f"Amount: {min_price.get('amount')} {min_price.get('currencyCode')}")
    
    # Inventory
    print(f"\n📦 Inventory:")
    print(f"Total: {product.get('totalInventory')}")
    print(f"Tracks Inventory: {product.get('tracksInventory')}")
    
    # Variants
    variants = product.get('variants', {}).get('edges', [])
    if variants:
        print(f"\n🔀 Variants ({len(variants)}):")
        for v in variants:
            variant = v['node']
            print(f"  - SKU: {variant.get('sku')}, Price: {variant.get('price')}, Qty: {variant.get('inventoryQuantity')}")
    
    # Collections
    collections = product.get('collections', {}).get('edges', [])
    if collections:
        print(f"\n📚 Collections:")
        for c in collections:
            coll = c['node']
            print(f"  - {coll.get('title')} (handle: {coll.get('handle')})")
    
    # Metafields
    metafields = product.get('metafields', {}).get('edges', [])
    if metafields:
        print(f"\n🏷️ Metafields ({len(metafields)}):")
        for m in metafields:
            meta = m['node']
            print(f"  - {meta.get('namespace')}.{meta.get('key')}: {meta.get('value')[:50]}...")
    
    # Save to file if requested
    if save_to_file:
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        
        filename = f"shopify_product_{product_id}.json"
        if sku:
            filename = f"{sku}_shopify.json"
        
        output_file = output_dir / filename
        
        with open(output_file, 'w') as f:
            json.dump({
                "fetch_date": datetime.now().isoformat(),
                "product_id": product_id,
                "sku": sku,
                "product": product
            }, f, indent=2, default=str)
        
        print(f"\n💾 Saved to {output_file}")
    
    # Show what should be in extended_attributes
    print("\n" + "=" * 60)
    print("SUGGESTED extended_attributes:")
    print("=" * 60)
    
    extended_attrs = {
        "handle": product.get('handle'),
        "online_store_url": product.get('onlineStoreUrl'),
        "vendor": product.get('vendor'),
        "product_type": product.get('productType'),
        "tags": product.get('tags', []),
        "status": product.get('status'),
        "total_inventory": product.get('totalInventory'),
        "collections": [c['node']['handle'] for c in collections],
        "featured_image": product.get('featuredImage', {}).get('url') if product.get('featuredImage') else None,
        "shopify_created_at": product.get('createdAt'),
        "shopify_updated_at": product.get('updatedAt')
    }
    
    print(json.dumps(extended_attrs, indent=2))
    
    return product

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get Shopify product details")
    parser.add_argument("--id", type=str, help="Shopify product ID")
    parser.add_argument("--sku", type=str, help="Product SKU")
    parser.add_argument("--save", action="store_true", help="Save to JSON file")
    
    args = parser.parse_args()
    
    asyncio.run(main(
        product_id=args.id,
        sku=args.sku,
        save_to_file=args.save
    ))