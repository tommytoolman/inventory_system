import asyncio
import os
import csv
from dotenv import load_dotenv

# We assume your client file is at this path
from app.services.shopify.client import ShopifyGraphQLClient

# Load environment variables from .env file
load_dotenv()

async def fetch_shopify_inventory_and_create_mapping():
    """
    This function initializes the Shopify client, fetches all products,
    and creates a 3-column reverb_to_shopify.csv mapping file for review.
    """
    print("Initializing Shopify client...")
    client = ShopifyGraphQLClient()

    print("\nFetching all products from Shopify...")
    all_products = client.get_all_products_summary()

    if not all_products:
        print("No products found or an error occurred.")
        return

    print(f"\nFound {len(all_products)} total products. Processing all of them for the CSV...")
    
    # List to hold our 3-column mapping data
    mapping_data = []
    
    # --- Modified Logic: Process ALL products ---
    for product in all_products:
        shopify_id = product.get('legacyResourceId')
        title = product.get('title', 'No Title Found') # Get the title for the description column
        
        sku = ""
        variants = product.get('variants', {}).get('nodes', [])
        if variants:
            sku = variants[0].get('sku', '')

        reverb_id = '' # Default to blank
        
        # Check if the SKU is a Reverb-linked SKU and extract the ID
        if sku and sku.startswith('rev-'):
            reverb_id = sku.replace('rev-', '', 1)

        # Add a row for every product, with reverb_id being blank if not found
        mapping_data.append([reverb_id, shopify_id, title])

    # Write the collected data to a CSV file
    output_filename = 'reverb_to_shopify_for_review.csv'
    print(f"\nWriting {len(mapping_data)} products to {output_filename}...")

    with open(output_filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        # Write the new 3-column header
        writer.writerow(['reverb_id', 'shopify_id', 'description'])
        # Write all the data rows
        writer.writerows(mapping_data)

    print(f"✅ Success! {output_filename} has been created with all products.")


if __name__ == "__main__":
    asyncio.run(fetch_shopify_inventory_and_create_mapping())