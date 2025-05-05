# ebay_data_analysis.py
import asyncio
import json
import os, sys
import inspect
from datetime import datetime, timezone
from sqlalchemy import text, inspect as sa_inspect
from sqlalchemy.ext.asyncio import create_async_engine
from tabulate import tabulate
from dotenv import load_dotenv

sys.path.append(os.path.abspath("/Users/wommy/Documents/GitHub/PROJECTS/HANKS/inventory_system"))

from app.services.ebay.trading import EbayTradingAPI
from app.models.ebay import EbayListing

# Load environment variables
load_dotenv()

async def analyze_ebay_data():
    """Analyze and compare eBay data structures"""
    print("== eBay Data Structure Analysis ==\n")
    
    # Initialize trading API and database connection
    trading_api = EbayTradingAPI(sandbox=False)
    db_url = os.environ.get('DATABASE_URL')
    engine = create_async_engine(db_url)
    
    # Step 1: Get eBay listings from API
    print("Fetching eBay listings from API...")
    listings = await trading_api.get_all_active_listings()
    print(f"Retrieved {len(listings)} listings from eBay API\n")
    
    # Select 2 sample listings for detailed analysis
    sample_listings = listings[:2] if len(listings) >= 2 else listings
    
    # Step 2: Display eBay API data structure
    print("=== eBay API Data Structure ===")
    for i, listing in enumerate(sample_listings):
        print(f"\nSample Listing {i+1} ({listing.get('ItemID')}):")
        formatted_json = json.dumps(listing, indent=2, default=str)
        print(formatted_json)
    
    # Step 3: Analyze model fields
    print("\n\n=== EbayListing Model Structure ===")
    model_columns = inspect.getmembers(EbayListing, lambda a: not(inspect.isroutine(a)))
    model_columns = [m for m in model_columns if not m[0].startswith('_')]
    
    # Extract SQLAlchemy column attributes
    print("SQLAlchemy model attributes:")
    for name, attr in model_columns:
        print(f"- {name}: {attr}")
    
    # Attempt to get table columns directly
    print("\nColumns from __table__ attribute:")
    if hasattr(EbayListing, '__table__') and hasattr(EbayListing.__table__, 'columns'):
        for column in EbayListing.__table__.columns:
            print(f"- {column.name}: {column.type} (nullable: {column.nullable})")
    
    # Step 4: Get database table structure
    print("\n\n=== Database Table Structure ===")
    try:
        # Using run_sync to inspect the database structure
        async with engine.connect() as conn:
            # This function will be executed in a sync context
            def inspect_table(sync_conn):
                inspector = sa_inspect(sync_conn)
                columns = inspector.get_columns('ebay_listings')
                return columns
            
            # Run the inspection in a sync context
            columns = await conn.run_sync(inspect_table)
            
            # Display table structure
            table_data = []
            for column in columns:
                table_data.append([
                    column.get('name'),
                    str(column.get('type')),
                    column.get('nullable', ''),
                    column.get('default', '')
                ])
            
            print(tabulate(
                table_data,
                headers=['Column', 'Type', 'Nullable', 'Default'],
                tablefmt='grid'
            ))
            
            # Count records
            result = await conn.execute(text("SELECT COUNT(*) FROM ebay_listings"))
            count = result.scalar()
            print(f"\nTotal records in ebay_listings table: {count}")
            
            # Get sample record from database if any exist
            if count > 0:
                result = await conn.execute(text("SELECT * FROM ebay_listings LIMIT 1"))
                row = result.fetchone()
                if row:
                    print("\nSample record from database:")
                    print(dict(row))
    
    except Exception as e:
        print(f"Error inspecting database: {str(e)}")
    
    # Step 5: Mapping analysis
    print("\n\n=== API to Database Mapping Analysis ===")
    
    # Get a list of API fields from the first listing
    if sample_listings:
        api_fields = set(sample_listings[0].keys())
        
        # Get model fields
        model_fields = set()
        if hasattr(EbayListing, '__table__') and hasattr(EbayListing.__table__, 'columns'):
            model_fields = {col.name for col in EbayListing.__table__.columns}
        
        # Compare and suggest mappings
        print(f"API fields count: {len(api_fields)}")
        print(f"Database fields count: {len(model_fields)}")
        
        # Fields in API but not in model
        print("\nAPI fields not mapped to database:")
        unmapped_fields = api_fields - model_fields
        for field in sorted(unmapped_fields):
            # Get a sample value
            sample_value = sample_listings[0].get(field)
            print(f"- {field}: {type(sample_value).__name__} (example: {sample_value})")
        
        # Fields in model not found in API
        print("\nDatabase fields not present in API:")
        for field in sorted(model_fields - {'id', 'created_at', 'updated_at'}):
            if field not in api_fields:
                print(f"- {field}")
    
    # Step 6: Mapping suggestions
    print("\n\n=== Suggested Mapping Implementation ===")
    print("Based on the API data, here's a suggested mapping implementation:")
    
    print("""
    def _map_ebay_api_to_db(listing: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Map eBay API data to database fields\"\"\"
        
        # Extract item ID
        item_id = listing.get('ItemID')
        
        # Extract price
        selling_status = listing.get('SellingStatus', {})
        price_data = selling_status.get('CurrentPrice', {})
        price = float(price_data.get('#text', '0.0'))
        
        # Extract quantity
        quantity = int(listing.get('QuantityAvailable', '1'))
        
        # Extract listing format
        listing_type = listing.get('ListingType', '')
        format_value = 'BUY_IT_NOW'
        if listing_type == 'Chinese':
            format_value = 'AUCTION'
        
        # Extract category information
        primary_category = listing.get('PrimaryCategory', {})
        secondary_category = listing.get('SecondaryCategory', {})
        ebay_category_id = primary_category.get('CategoryID') if primary_category else None
        ebay_second_category_id = secondary_category.get('CategoryID') if secondary_category else None
        
        # Extract listing duration
        listing_duration = listing.get('ListingDuration', '')
        
        # Extract condition ID
        condition_id = listing.get('ConditionID')
        
        # Map item specifics to JSON field
        item_specifics = {}
        api_specifics = listing.get('ItemSpecifics', {})
        if api_specifics and 'NameValueList' in api_specifics:
            name_value_list = api_specifics['NameValueList']
            if isinstance(name_value_list, list):
                for nv in name_value_list:
                    name = nv.get('Name')
                    value = nv.get('Value')
                    if name and value:
                        item_specifics[name] = value
            elif isinstance(name_value_list, dict):
                name = name_value_list.get('Name')
                value = name_value_list.get('Value')
                if name and value:
                    item_specifics[name] = value
        
        # Result mapping
        return {
            'ebay_item_id': item_id,
            'ebay_category_id': ebay_category_id,
            'ebay_second_category_id': ebay_second_category_id,
            'format': format_value,
            'price': price,
            'quantity': quantity,
            'listing_duration': listing_duration,
            'listing_status': 'ACTIVE',
            'item_specifics': item_specifics,
            'ebay_condition_id': condition_id
        }
    """)

asyncio.run(analyze_ebay_data())