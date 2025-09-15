import asyncio
import csv
from dotenv import load_dotenv

# We assume your client file is at this path
from app.services.shopify.client import ShopifyGraphQLClient

# Load environment variables from .env file
load_dotenv()

async def update_sku_for_product(client: ShopifyGraphQLClient, shopify_product_id: str, new_sku: str):
    """
    Updates the SKU for the first variant of a given Shopify product.
    """
    print(f"\nAttempting to update SKU for Shopify Product ID: {shopify_product_id}")

    # Construct the full GraphQL GID from the numeric ID
    product_gid = f"gid://shopify/Product/{shopify_product_id}"

    # 1. Get the product snapshot to find its variant's GID
    print(f"  -> Step 1: Fetching product details to find the variant ID...")
    product_snapshot = client.get_product_snapshot_by_id(product_gid, num_variants=1)

    if not product_snapshot or not product_snapshot.get("variants", {}).get("edges"):
        print(f"  -> ERROR: Could not find product or variant for Product ID {shopify_product_id}.")
        return

    # Extract the GID of the first variant
    first_variant = product_snapshot["variants"]["edges"][0]["node"]
    variant_gid = first_variant["id"]
    current_sku = first_variant.get("sku", "N/A")
    print(f"  -> Found Variant ID: {variant_gid} (Current SKU: '{current_sku}')")

    # 2. Update the variant's SKU using the reliable REST method
    print(f"  -> Step 2: Sending update request to set SKU to '{new_sku}'...")
    variant_updates = {
        "sku": new_sku
    }
    
    update_result = client.update_variant_rest(variant_gid, variant_updates)

    if update_result and update_result.get("variant"):
        updated_sku = update_result["variant"].get("sku")
        print(f"  -> ✅ SUCCESS! SKU has been updated to '{updated_sku}'.")
    else:
        print(f"  -> ❌ FAILED: The SKU update failed. Check logs for details.")


async def main():
    """
    Main function to read a CSV and run the update process in a batch.
    """
    input_filename = 'scripts/shopify/sku_updates.csv'
    
    print("Initializing Shopify client...")
    shopify_client = ShopifyGraphQLClient()

    print(f"Reading product updates from {input_filename}...")
    try:
        with open(input_filename, mode='r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            updates = list(reader)
    except FileNotFoundError:
        print(f"ERROR: Input file not found at '{input_filename}'. Please create it.")
        return

    print(f"Found {len(updates)} products to update. Starting batch process...")
    
    # Iterate through each row from the CSV
    for row in updates:
        shopify_id = row.get('shopify_id')
        new_sku = row.get('new_sku')

        if not shopify_id or not new_sku:
            print(f"Skipping invalid row: {row}")
            continue

        await update_sku_for_product(shopify_client, shopify_id, new_sku)
        
        # Add a small delay to respect API rate limits
        await asyncio.sleep(1) 

    print("\nBatch process complete.")


if __name__ == "__main__":
    asyncio.run(main())