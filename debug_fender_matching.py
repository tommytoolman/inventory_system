# Create debug_fender_matching.py in your root directory
import asyncio
from app.database import async_session
from scripts.product_matcher import ProductMatcher

async def debug_fender_matching():
    async with async_session() as session:
        matcher = ProductMatcher(session)
        
        # Get Fender products
        products_by_platform = await matcher._get_products_by_platform("ACTIVE", "fender")
        
        reverb_fenders = products_by_platform.get('reverb', [])
        shopify_fenders = products_by_platform.get('shopify', [])
        
        print(f"Found {len(reverb_fenders)} Reverb Fenders")
        print(f"Found {len(shopify_fenders)} Shopify Fenders")
        
        # Show sample data
        print(f"\nSample Reverb Fenders:")
        for i, p in enumerate(reverb_fenders[:3]):
            print(f"  {i+1}. ID:{p['id']}, SKU:{p['sku']}, Brand:'{p['brand']}', Title:'{p['title']}', Price:£{p['price']}")
            print(f"      Normalized brand: '{matcher.normalize_brand(p['brand'])}'")
        
        print(f"\nSample Shopify Fenders:")
        for i, p in enumerate(shopify_fenders[:3]):
            print(f"  {i+1}. ID:{p['id']}, SKU:{p['sku']}, Brand:'{p['brand']}', Title:'{p['title']}', Price:£{p['price']}")
            print(f"      Normalized brand: '{matcher.normalize_brand(p['brand'])}'")
        
        # Test manual confidence calculation
        if reverb_fenders and shopify_fenders:
            print(f"\nTesting confidence calculations:")
            for i in range(min(3, len(reverb_fenders))):
                for j in range(min(3, len(shopify_fenders))):
                    rev_product = reverb_fenders[i]
                    shop_product = shopify_fenders[j]
                    
                    confidence = matcher._calculate_match_confidence(rev_product, shop_product)
                    
                    print(f"  Reverb {rev_product['sku']} vs Shopify {shop_product['sku']}: {confidence:.1f}%")
                    print(f"    Rev: '{rev_product['title']}' £{rev_product['price']}")
                    print(f"    Shop: '{shop_product['title']}' £{shop_product['price']}")
                    
                    if confidence >= 80:
                        print(f"    ✅ This should be a match!")
                    else:
                        print(f"    ❌ Below threshold")
                    print()

if __name__ == "__main__":
    asyncio.run(debug_fender_matching())