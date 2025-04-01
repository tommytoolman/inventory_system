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
            # Check eBay mappings
            result = await session.execute(text("""
                SELECT COUNT(*) AS total,
                       COUNT(p.id) AS with_product
                FROM ebay_listings e 
                LEFT JOIN platform_common pc ON e.platform_id = pc.id
                LEFT JOIN products p ON pc.product_id = p.id
            """))
            ebay_stats = result.fetchone()
            
            # Check Reverb mappings
            result = await session.execute(text("""
                SELECT COUNT(*) AS total,
                       COUNT(p.id) AS with_product
                FROM reverb_listings r 
                LEFT JOIN platform_common pc ON r.platform_id = pc.id
                LEFT JOIN products p ON pc.product_id = p.id
            """))
            reverb_stats = result.fetchone()
            
            # Check V&R mappings
            result = await session.execute(text("""
                SELECT COUNT(*) AS total,
                       COUNT(p.id) AS with_product
                FROM vr_listings v 
                LEFT JOIN platform_common pc ON v.platform_id = pc.id
                LEFT JOIN products p ON pc.product_id = p.id
            """))
            vr_stats = result.fetchone()
            
            # Print results
            print("\nMapping Statistics:")
            print(f"eBay: {ebay_stats.with_product}/{ebay_stats.total} listings linked to products ({ebay_stats.with_product/ebay_stats.total*100:.1f}%)")
            print(f"Reverb: {reverb_stats.with_product}/{reverb_stats.total} listings linked to products ({reverb_stats.with_product/reverb_stats.total*100:.1f}%)")
            print(f"V&R: {vr_stats.with_product}/{vr_stats.total} listings linked to products ({vr_stats.with_product/vr_stats.total*100:.1f}%)")
            
    asyncio.run(_check())

if __name__ == "__main__":
    check_mappings()