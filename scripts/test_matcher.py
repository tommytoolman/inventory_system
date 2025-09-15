# Update your test_matcher.py to focus on the known match
import asyncio
from app.database import async_session
from scripts.product_matcher import ProductMatcher
from sqlalchemy import text

async def debug_specific_burns_match():
    async with async_session() as session:
        matcher = ProductMatcher(session)
        
        # Get the specific products we know should match
        products_by_platform = await matcher._get_products_by_platform("ACTIVE")
        
        reverb_products = products_by_platform.get('reverb', [])
        shopify_products = products_by_platform.get('shopify', [])
        
        # Find our specific Burns products
        target_reverb = None
        target_shopify = None
        
        for product in reverb_products:
            if product['id'] == 4163:  # Our known Reverb Burns
                target_reverb = product
                break
                
        for product in shopify_products:
            if product['id'] == 7854:  # Our known Shopify Burns  
                target_shopify = product
                break
        
        if target_reverb and target_shopify:
            print("Found our target products:")
            print(f"Reverb: ID={target_reverb['id']}, SKU={target_reverb['sku']}")
            print(f"  Brand: '{target_reverb['brand']}'")
            print(f"  Title: '{target_reverb['title']}'") 
            print(f"  Price: {target_reverb['price']}")
            
            print(f"Shopify: ID={target_shopify['id']}, SKU={target_shopify['sku']}")
            print(f"  Brand: '{target_shopify['brand']}'")
            print(f"  Title: '{target_shopify['title']}'")
            print(f"  Price: {target_shopify['price']}")
            
            # Test each step of the matching process
            print("\\n--- Matching Debug ---")
            
            # 1. Brand normalization
            brand1 = matcher.normalize_brand(target_reverb['brand'])
            brand2 = matcher.normalize_brand(target_shopify['brand'])
            print(f"1. Brand normalization:")
            print(f"   Reverb: '{target_reverb['brand']}' → '{brand1}'")
            print(f"   Shopify: '{target_shopify['brand']}' → '{brand2}'")
            print(f"   Brands match: {brand1 == brand2}")
            
            # 2. Year extraction
            year1 = matcher._extract_year_from_title(target_reverb['title'])
            year2 = matcher._extract_year_from_title(target_shopify['title'])
            print(f"\\n2. Year extraction:")
            print(f"   Reverb title: '{target_reverb['title']}' → Year: {year1}")
            print(f"   Shopify title: '{target_shopify['title']}' → Year: {year2}")
            print(f"   Years match: {year1 == year2}")
            
            # 3. Price comparison
            price1 = target_reverb['price']
            price2 = target_shopify['price']
            if price1 and price2:
                price_diff = abs(price1 - price2)
                price_diff_pct = (price_diff / max(price1, price2)) * 100
                print(f"\\n3. Price comparison:")
                print(f"   Reverb: £{price1}")
                print(f"   Shopify: £{price2}")
                print(f"   Difference: £{price_diff} ({price_diff_pct:.1f}%)")
            
            # 4. Full confidence calculation
            confidence = matcher._calculate_match_confidence(target_reverb, target_shopify)
            print(f"\\n4. Final confidence: {confidence:.1f}%")
            
            # 5. Check if they would be in the same brand group for filtering
            reverb_brand_key = target_reverb.get('brand', '').lower()
            shopify_brand_key = target_shopify.get('brand', '').lower()
            print(f"\\n5. Brand filtering check:")
            print(f"   Reverb brand key: '{reverb_brand_key}'")
            print(f"   Shopify brand key: '{shopify_brand_key}'")
            print(f"   Would be grouped together: {reverb_brand_key == shopify_brand_key}")
            
        else:
            print("Could not find target products!")
            print(f"Target Reverb found: {target_reverb is not None}")
            print(f"Target Shopify found: {target_shopify is not None}")

# Add this to test_matcher.py
async def check_actual_titles():
    async with async_session() as session:
        # Get the actual product titles from the database
        query = text('''
            SELECT p.id, p.sku, p.brand, p.model, p.title, p.year
            FROM products p
            WHERE p.id IN (4163, 7854)
            ORDER BY p.id
        ''')
        
        result = await session.execute(query)
        rows = result.fetchall()
        
        print("Actual product data:")
        for row in rows:
            print(f'  ID: {row.id}, SKU: {row.sku}')
            print(f'    Brand: "{row.brand}", Model: "{row.model}"')
            print(f'    Title: "{row.title}"')
            print(f'    Year: {row.year}')
            print()

if __name__ == "__main__":
    asyncio.run(check_actual_titles())

#     asyncio.run(debug_specific_burns_match())