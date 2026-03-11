import os, sys, time, json
import pandas as pd
import argparse  # Import the argparse library

from datetime import datetime

os.chdir('/Users/wommy/Documents/GitHub/PROJECTS/HANKS/inventory_system')
from app.core.config import get_settings
from app.services.shopify.client import ShopifyGraphQLClient, ShopifyGraphQLError

# --- Argument Parser Setup ---
parser = argparse.ArgumentParser(description="Delete a specified number of products from Shopify.")
parser.add_argument("--num_products", type=int, default=10, help="The number of products to delete (default: 10)")
args = parser.parse_args()


# --- Load Settings/Credentials (Adapt to your setup) ---

settings = get_settings()

client = ShopifyGraphQLClient()

product_list = client.get_all_products_summary()
print(f"Total products found: {len(product_list)}")

# Use the parsed argument to determine how many products to delete
products_to_delete = product_list[0:args.num_products]

print(f"Preparing to delete {len(products_to_delete)} products...")

for prod in products_to_delete:
    client.delete_product(prod['id'])
    print(f"Deleted {prod['title']}")