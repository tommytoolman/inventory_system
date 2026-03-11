"""
## How to Use It

Here are some examples of how to run the script from your command line.

Example 1: Dry run to see what would happen if you pushed a new price of £1999 to just V&R and eBay.
    $ python scripts/update_product_price.py --sku "REV-85380995" --price 1999.0 --platform vr ebay --dry-run

Example 2: A live run to enforce the current master price across ALL platforms.
    This is useful if you know the master price is correct and just want to fix inconsistencies.
    $ python scripts/update_product_price.py --sku "REV-85380995" --platform all --live

Example 3: A live run to update the master price to £2500 and push it only to Shopify.
    $ python scripts/update_product_price.py --sku "REV-85380995" --price 2500.0 --platform shopify --live

This script gives you the full manual control you wanted for your outbound pricing strategy.

"""

# scripts/update_product_price.py
import sys
import os
import asyncio
import argparse
import logging
from typing import List, Optional

# Add project root to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import async_session
from app.models.product import Product
from app.services.sync_services import SyncService
from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main(args):
    """Updates a product's master price and propagates it to specified platforms."""
    async with async_session() as db:
        try:
            # Step 1: Find the product by SKU
            stmt = select(Product).where(Product.sku.ilike(args.sku))
            product = (await db.execute(stmt)).scalar_one_or_none()

            if not product:
                logging.error(f"Product with SKU '{args.sku}' not found.")
                return

            # Step 2: Determine the new price
            old_price = product.base_price
            new_price = args.price if args.price is not None else old_price

            if new_price == old_price and args.price is not None:
                logging.warning(f"New price £{new_price} is the same as the current master price. No update needed.")
                # Still proceed to propagate if requested, to enforce consistency
            elif args.price is not None:
                logging.info(f"Found Product #{product.id}. Current base_price: £{old_price}. New base_price: £{new_price}.")
                product.base_price = new_price
            else:
                logging.info(f"Using current base_price of £{old_price} to enforce consistency across platforms.")


            # Step 3: Update the master price in the database if in a live run and price is changing
            if not args.dry_run and args.price is not None:
                await db.commit()
                await db.refresh(product)
                logging.info(f"Successfully updated master price for SKU '{args.sku}' in the database.")

            # Step 4: Propagate the change using the SyncService
            service = SyncService(db)
            platforms_to_update = args.platform

            if 'all' in platforms_to_update:
                logging.info(f"Propagating price £{new_price} to ALL platforms...")
            else:
                logging.info(f"Propagating price £{new_price} to specified platforms: {', '.join(platforms_to_update)}")

            successful_platforms, action_log, failed_count = await service.propagate_price_update_from_master(
                product=product,
                new_price=new_price,
                platforms_to_update=platforms_to_update,
                dry_run=args.dry_run
            )

            logging.info("--- Propagation Report ---")
            for log in action_log:
                logging.info(log)
            logging.info("--------------------------")
            logging.info(f"Propagation complete. Success: {len(successful_platforms)}, Failed: {failed_count}.")

        except Exception as e:
            logging.error(f"An error occurred: {e}", exc_info=True)
            if not args.dry_run:
                await db.rollback()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update a product's master price and propagate to platforms.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('--sku', required=True, help="The SKU of the product to update.")
    parser.add_argument(
        '--price',
        type=float,
        help="Optional: The new master price to set. If not provided, the current master price will be used to enforce consistency."
    )
    parser.add_argument(
        '--platform',
        nargs='+',  # This allows for one or more platform names
        required=True,
        help="Specify platform(s) to update (e.g., vr ebay shopify reverb). Use 'all' for all platforms."
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--dry-run', action='store_true', help="Simulate the run without making changes.")
    mode_group.add_argument('--live', action='store_false', dest='dry_run', help="Execute the run with live DB and API calls.")

    args = parser.parse_args()
    asyncio.run(main(args))