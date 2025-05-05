#!/usr/bin/env python
# scripts/test_vr_auth_download.py

import asyncio
import argparse
import os
import sys
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.services.vintageandrare.client import VintageAndRareClient

async def test_vr_authentication_and_download(username=None, password=None, save_to=None):
    """
    Test authentication and inventory download from VintageAndRare.
    
    Args:
        username: VintageAndRare username
        password: VintageAndRare password
        save_to: Optional path to save the CSV file
        
    Returns:
        bool: True if both steps were successful
    """
    # Use environment variables if not provided
    if not username:
        username = os.environ.get("VINTAGE_AND_RARE_USERNAME")
    if not password:
        password = os.environ.get("VINTAGE_AND_RARE_PASSWORD")
    
    if not username or not password:
        print("Error: Missing credentials. Provide as arguments or set environment variables.")
        return False
    
    print(f"\n=== VintageAndRare Authentication & Download Test ===")
    print(f"Username: {username[:3]}***")
    
    # Create client
    client = VintageAndRareClient(username=username, password=password)
    
    # Step 1: Test authentication
    print("\n1. Testing authentication...")
    try:
        auth_success = await client.authenticate()
        if auth_success:
            print("✅ Authentication successful!")
        else:
            print("❌ Authentication failed!")
            return False
    except Exception as e:
        print(f"❌ Authentication error: {str(e)}")
        return False
    
    # Step 2: Test inventory download
    print("\n2. Downloading inventory data...")
    try:
        save_file = save_to is not None
        df = await client.download_inventory_dataframe(save_to_file=save_file, output_path=save_to)
        
        if df is not None and len(df) > 0:
            print(f"✅ Successfully downloaded inventory with {len(df)} items")
            print(f"\nInventory preview:")
            print(f"{df.head(3)}")
            
            # Print some statistics
            print(f"\nBasic statistics:")
            print(f"- Number of active items: {len(df[df['product_sold']=='no'])}")
            print(f"- Number of sold items: {len(df[df['product_sold']=='yes'])}")
            print(f"- Number of unique brands: {df['brand_name'].nunique()}")
            
            if save_file:
                print(f"\nFull inventory saved to: {save_to}")
                
            return True
        else:
            print("❌ Download failed or returned empty data")
            return False
    except Exception as e:
        print(f"❌ Download error: {str(e)}")
        return False

def main():
    """Parse arguments and run the test"""
    load_dotenv()  # Load environment variables
    
    parser = argparse.ArgumentParser(description="Test VintageAndRare authentication and inventory download")
    parser.add_argument("--username", help="VintageAndRare username")
    parser.add_argument("--password", help="VintageAndRare password")
    parser.add_argument("--save-to", help="Path to save the CSV file (optional)")
    args = parser.parse_args()
    
    success = asyncio.run(test_vr_authentication_and_download(
        username=args.username,
        password=args.password,
        save_to=args.save_to
    ))
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()