import asyncio
import json
import argparse  # Import the argparse library
from dotenv import load_dotenv

# We assume your client file is at this path
from app.services.shopify.client import ShopifyGraphQLClient

# Load environment variables from .env file
load_dotenv()

async def fetch_single_product_details(shopify_product_id: str):
    """
    Fetches and prints all available details for a single Shopify product.
    """
    print("Initializing Shopify client...")
    client = ShopifyGraphQLClient()

    # Construct the full GraphQL GID from the numeric ID
    product_gid = f"gid://shopify/Product/{shopify_product_id}"
    print(f"\nFetching full snapshot for Product GID: {product_gid}...")

    # Call the method to get the product's complete data snapshot
    product_data = client.get_product_snapshot_by_id(product_gid)

    if product_data:
        print("\n✅ Success! Full product data retrieved:")
        # Pretty-print the entire JSON response so you can see all available fields
        print(json.dumps(product_data, indent=4))
    else:
        print(f"\n❌ ERROR: Could not retrieve data for product ID {shopify_product_id}.")


if __name__ == "__main__":
    # --- New: Use argparse to get the ID from the command line ---
    parser = argparse.ArgumentParser(
        description="Fetch all details for a single Shopify product by its numeric ID."
    )
    # Add one required positional argument for the ID
    parser.add_argument("shopify_id", help="The numeric ID of the Shopify product to fetch.")
    
    args = parser.parse_args()

    # Run the async function with the ID provided by the user
    asyncio.run(fetch_single_product_details(args.shopify_id))