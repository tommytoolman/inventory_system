# app/cli/check_mappings.py
import asyncio
import click
from sqlalchemy import text
from app.database import async_session

@click.command()
def check_mappings():
    """Check product-to-platform mappings in the database"""
    
    async def _check():
        async with async_session() as session:
            # Check basic table counts first
            query = """
            SELECT 
                (SELECT COUNT(*) FROM products) AS products_count,
                (SELECT COUNT(*) FROM platform_common) AS platform_common_count,
                (SELECT COUNT(*) FROM ebay_listings) AS ebay_count,
                (SELECT COUNT(*) FROM reverb_listings) AS reverb_count,
                (SELECT COUNT(*) FROM vr_listings) AS vr_count
            """
            result = await session.execute(text(query))
            counts = result.fetchone()
            
            print("\nDatabase Counts:")
            print(f"Products: {counts.products_count}")
            print(f"Platform Common: {counts.platform_common_count}")
            print(f"eBay Listings: {counts.ebay_count}")
            print(f"Reverb Listings: {counts.reverb_count}")
            print(f"V&R Listings: {counts.vr_count}")
            
            # Now check eBay structure - note that ebay_listings doesn't have platform_id in your schema
            try:
                # Get column names from ebay_listings table
                cols_query = """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'ebay_listings'
                """
                result = await session.execute(text(cols_query))
                ebay_columns = [row[0] for row in result.fetchall()]
                print(f"\neBay Listings Columns: {', '.join(ebay_columns)}")
                
                # Check if platform_id exists
                if 'platform_id' in ebay_columns:
                    # Check eBay mappings to platform_common
                    result = await session.execute(text("""
                        SELECT COUNT(*) AS total,
                               COUNT(pc.id) AS with_platform
                        FROM ebay_listings e 
                        LEFT JOIN platform_common pc ON e.platform_id = pc.id
                    """))
                    ebay_stats = result.fetchone()
                    print(f"eBay listings with platform_common: {ebay_stats.with_platform}/{ebay_stats.total}")
                else:
                    print("WARNING: ebay_listings table doesn't have a platform_id column")
            except Exception as e:
                print(f"Error checking eBay structure: {str(e)}")
            
            # Check Reverb mappings - these should work based on your previous imports
            try:
                result = await session.execute(text("""
                    SELECT COUNT(*) AS total,
                           COUNT(pc.id) AS with_platform
                    FROM reverb_listings r 
                    LEFT JOIN platform_common pc ON r.platform_id = pc.id
                """))
                reverb_stats = result.fetchone()
                print(f"Reverb listings with platform_common: {reverb_stats.with_platform}/{reverb_stats.total}")
                
                # Check products as well
                result = await session.execute(text("""
                    SELECT COUNT(*) AS with_product
                    FROM reverb_listings r 
                    LEFT JOIN platform_common pc ON r.platform_id = pc.id
                    LEFT JOIN products p ON pc.product_id = p.id
                    WHERE p.id IS NOT NULL
                """))
                reverb_product_stats = result.fetchone()
                print(f"Reverb listings with products: {reverb_product_stats.with_product}/{reverb_stats.total}")
            except Exception as e:
                print(f"Error checking Reverb structure: {str(e)}")
            
            # Check V&R mappings
            try:
                result = await session.execute(text("""
                    SELECT COUNT(*) AS total,
                           COUNT(pc.id) AS with_platform
                    FROM vr_listings v 
                    LEFT JOIN platform_common pc ON v.platform_id = pc.id
                """))
                vr_stats = result.fetchone()
                print(f"V&R listings with platform_common: {vr_stats.with_platform}/{vr_stats.total}")
                
                # Check products as well
                result = await session.execute(text("""
                    SELECT COUNT(*) AS with_product
                    FROM vr_listings v 
                    LEFT JOIN platform_common pc ON v.platform_id = pc.id
                    LEFT JOIN products p ON pc.product_id = p.id
                    WHERE p.id IS NOT NULL
                """))
                vr_product_stats = result.fetchone()
                print(f"V&R listings with products: {vr_product_stats.with_product}/{vr_stats.total}")
            except Exception as e:
                print(f"Error checking V&R structure: {str(e)}")
                
    asyncio.run(_check())

if __name__ == "__main__":
    check_mappings()