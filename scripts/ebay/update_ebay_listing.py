#!/usr/bin/env python3
"""
Script to update eBay listing on Railway

Usage:
    python scripts/update_ebay_listing.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

async def update_ebay_listing():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        return

    # Convert to async URL
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    # Show which database we're connecting to (masked)
    host_part = db_url.split('@')[1].split('/')[0] if '@' in db_url else 'unknown'
    print(f"Connecting to database at: {host_part}")

    engine = create_async_engine(db_url)

    async with engine.connect() as conn:
        # First check current values
        result = await conn.execute(
            text("""
                SELECT ebay_item_id, price, listing_status, title
                FROM ebay_listings
                WHERE ebay_item_id = :item_id
            """),
            {"item_id": "257054645278"}
        )

        row = result.first()
        if not row:
            print("ERROR: eBay listing with ID 257054645278 not found")
            await engine.dispose()
            return

        print("\nCurrent values:")
        print(f"  eBay Item ID: {row[0]}")
        print(f"  Title: {row[3]}")
        print(f"  Price: £{row[1]:,.0f}")
        print(f"  Status: {row[2]}")

        print("\nNew values:")
        print(f"  Price: £75,999 (was £{row[1]:,.0f})")
        print(f"  Status: ended (was {row[2]})")

        confirm = input("\nUpdate this listing? (y/N): ")
        if confirm.lower() != 'y':
            print("Update cancelled")
            await engine.dispose()
            return

        # Update the listing
        await conn.execute(
            text("""
                UPDATE ebay_listings
                SET price = :new_price,
                    listing_status = :new_status,
                    updated_at = timezone('utc', now())
                WHERE ebay_item_id = :item_id
            """),
            {
                "new_price": 75999,
                "new_status": "ended",
                "item_id": "257054645278"
            }
        )

        await conn.commit()
        print("\n✓ Updated eBay listing successfully!")

        # Verify the update
        verify_result = await conn.execute(
            text("""
                SELECT price, listing_status
                FROM ebay_listings
                WHERE ebay_item_id = :item_id
            """),
            {"item_id": "257054645278"}
        )

        verify_row = verify_result.first()
        print(f"\nVerified new values:")
        print(f"  Price: £{verify_row[0]:,.0f}")
        print(f"  Status: {verify_row[1]}")

    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(update_ebay_listing())