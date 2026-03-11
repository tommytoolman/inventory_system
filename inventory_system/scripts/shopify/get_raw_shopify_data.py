#!/usr/bin/env python3
"""
Get raw Shopify API response for a product to see all available data.

Usage:
    # Get product by SKU and pretty print
    python scripts/shopify/get_raw_shopify_data.py --sku REV-91978727
    
    # Get product by Shopify ID
    python scripts/shopify/get_raw_shopify_data.py --id 12236710936916
"""

import asyncio
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from pprint import pprint

sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.shopify.client import ShopifyGraphQLClient
from app.core.config import get_settings
from app.database import async_session
from sqlalchemy import text

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

def fetch_product_raw(client: ShopifyGraphQLClient, product_id: str):
    """Fetch raw product data from Shopify."""
    
    # Comprehensive GraphQL query
    query = """
    query GetProduct($id: ID!) {
        product(id: $id) {
            id
            title
            handle
            description
            descriptionHtml
            vendor
            productType
            tags
            status
            createdAt
            updatedAt
            publishedAt
            onlineStoreUrl
            onlineStorePreviewUrl
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
            
            productCategory {
                productTaxonomyNode {
                    id
                    name
                    fullName
                }
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
                width
                height
            }
            
            images(first: 10) {
                edges {
                    node {
                        url
                        altText
                        width
                        height
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
                        inventoryItem {
                            id
                            sku
                            tracked
                            requiresShipping
                        }
                    }
                }
            }
            
            metafields(first: 50) {
                edges {
                    node {
                        namespace
                        key
                        value
                        type
                        description
                    }
                }
            }
            
            metafield(namespace: "custom", key: "url") {
                value
                type
            }
            
            collections(first: 10) {
                edges {
                    node {
                        id
                        title
                        handle
                        descriptionHtml
                    }
                }
            }
            
            resourcePublications(first: 10) {
                edges {
                    node {
                        publication {
                            id
                            name
                        }
                        publishDate
                        isPublished
                    }
                }
            }
            
            resourcePublicationsV2(first: 10) {
                edges {
                    node {
                        publication {
                            id
                            name
                        }
                        publishDate
                        isPublished
                    }
                }
            }
            
            media(first: 10) {
                edges {
                    node {
                        alt
                        mediaContentType
                        status
                        ... on MediaImage {
                            id
                            image {
                                url
                                width
                                height
                            }
                        }
                    }
                }
            }
            
            publishedOnCurrentPublication
            
            customProductType
            templateSuffix
            giftCardTemplateSuffix
            
            hasOnlyDefaultVariant
            hasOutOfStockVariants
            isGiftCard
            legacyResourceId
            mediaCount {
                count
                precision
            }
            
            onlineStoreUrl
            onlineStorePreviewUrl
            
            requiresSellingPlan
            sellingPlanGroupCount
            totalVariants
            
            storefrontId
            
            feedback {
                summary
            }
            
            options {
                id
                name
                position
                values
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

async def main(product_id: str = None, sku: str = None):
    """Main function to fetch and display raw Shopify data."""
    
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
    
    # Initialize Shopify client
    client = ShopifyGraphQLClient()
    
    print(f"📦 Fetching raw Shopify data for product {product_id}...\n")
    
    # Fetch product details
    product = fetch_product_raw(client, product_id)
    
    if not product:
        print(f"❌ Product not found or error fetching data")
        return
    
    # Pretty print the entire response
    print("=" * 60)
    print("RAW SHOPIFY API RESPONSE:")
    print("=" * 60)
    print(json.dumps(product, indent=2, default=str))
    
    # Highlight key URLs
    print("\n" + "=" * 60)
    print("KEY URLS AND PUBLISHING INFO:")
    print("=" * 60)
    print(f"Handle: {product.get('handle')}")
    print(f"Online Store URL: {product.get('onlineStoreUrl')}")
    print(f"Online Store Preview URL: {product.get('onlineStorePreviewUrl')}")
    print(f"Published At: {product.get('publishedAt')}")
    
    # Check publication status
    publications = product.get('resourcePublications', {}).get('edges', [])
    if publications:
        print(f"\nPublication Status:")
        for pub in publications:
            pub_data = pub['node']
            publication = pub_data['publication']
            print(f"  - {publication['name']}: {'Published' if pub_data['isPublished'] else 'Not Published'}")
            if pub_data['isPublished']:
                print(f"    Published at: {pub_data.get('publishDate', 'N/A')}")
    
    # Save to file for reference
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    
    filename = f"raw_shopify_{product_id}.json"
    if sku:
        filename = f"raw_{sku}_shopify.json"
    
    output_file = output_dir / filename
    
    with open(output_file, 'w') as f:
        json.dump({
            "fetch_date": datetime.now().isoformat(),
            "product_id": product_id,
            "sku": sku,
            "raw_response": product
        }, f, indent=2, default=str)
    
    print(f"\n💾 Saved to {output_file}")
    
    return product

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get raw Shopify product data")
    parser.add_argument("--id", type=str, help="Shopify product ID")
    parser.add_argument("--sku", type=str, help="Product SKU")
    
    args = parser.parse_args()
    
    asyncio.run(main(
        product_id=args.id,
        sku=args.sku
    ))