#!/usr/bin/env python3
"""
Platform Status Mapping Management Script

This script allows you to:
1. Create the platform_status_mappings table
2. Add new status mappings
3. View existing mappings
4. Update mappings
5. Populate with initial data
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text, create_engine
from sqlalchemy.exc import IntegrityError
from app.core.config import get_settings
from app.database import get_session

class StatusMappingManager:
    def __init__(self):
        self.settings = get_settings()
    
    async def create_table(self):
        """Create the platform_status_mappings table"""
        create_sql = """
        CREATE TABLE IF NOT EXISTS platform_status_mappings (
            id SERIAL PRIMARY KEY,
            platform_name VARCHAR(50) NOT NULL,
            platform_status VARCHAR(100) NOT NULL,
            central_status VARCHAR(20) NOT NULL CHECK (central_status IN ('LIVE', 'SOLD', 'DRAFT')),
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(platform_name, platform_status)
        );
        """
        
        async with get_session() as db:
            await db.execute(text(create_sql))
            await db.commit()
            print("✅ Table 'platform_status_mappings' created successfully!")
    
    async def add_mapping(self, platform_name, platform_status, central_status, description=""):
        """Add a new status mapping"""
        insert_sql = """
        INSERT INTO platform_status_mappings (platform_name, platform_status, central_status, description)
        VALUES (:platform_name, :platform_status, :central_status, :description)
        """
        
        try:
            async with get_session() as db:
                await db.execute(text(insert_sql), {
                    'platform_name': platform_name,
                    'platform_status': platform_status,
                    'central_status': central_status,
                    'description': description
                })
                await db.commit()
                print(f"✅ Added mapping: {platform_name}.{platform_status} → {central_status}")
        except IntegrityError as e:
            if "unique constraint" in str(e).lower():
                print(f"❌ Mapping {platform_name}.{platform_status} already exists!")
            else:
                print(f"❌ Error: {e}")
    
    async def view_mappings(self, platform_name=None):
        """View existing mappings"""
        if platform_name:
            sql = "SELECT * FROM platform_status_mappings WHERE platform_name = :platform_name ORDER BY platform_name, central_status"
            params = {'platform_name': platform_name}
        else:
            sql = "SELECT * FROM platform_status_mappings ORDER BY platform_name, central_status"
            params = {}
        
        async with get_session() as db:
            result = await db.execute(text(sql), params)
            mappings = result.fetchall()
            
            if not mappings:
                print("No mappings found.")
                return
            
            print(f"\n{'Platform':<15} {'Platform Status':<20} {'Central Status':<15} {'Description'}")
            print("-" * 80)
            
            for mapping in mappings:
                print(f"{mapping.platform_name:<15} {mapping.platform_status:<20} {mapping.central_status:<15} {mapping.description or ''}")
    
    async def populate_initial_data(self):
        """Populate with initial status mappings"""
        initial_mappings = [
            # Reverb mappings
            ('reverb', 'live', 'LIVE', 'Active listing on Reverb'),
            ('reverb', 'sold', 'SOLD', 'Sold on Reverb'),
            ('reverb', 'ended', 'SOLD', 'Listing ended (sold elsewhere)'),
            ('reverb', 'draft', 'DRAFT', 'Draft listing'),
            
            # eBay mappings
            ('ebay', 'active', 'LIVE', 'Active eBay listing'),
            ('ebay', 'unsold', 'SOLD', 'Listing ended without sale (sold elsewhere)'),
            ('ebay', 'sold', 'SOLD', 'Sold on eBay'),
            ('ebay', 'completed', 'SOLD', 'eBay completed transaction'),
            
            # Shopify mappings
            ('shopify', 'ACTIVE', 'LIVE', 'Active Shopify product'),
            ('shopify', 'ARCHIVED', 'SOLD', 'Archived Shopify product'),
            ('shopify', 'DRAFT', 'DRAFT', 'Draft Shopify product'),
            
            # V&R mappings
            ('vr', 'active', 'LIVE', 'Active V&R listing'),
            ('vr', 'sold', 'SOLD', 'Sold on V&R'),
        ]
        
        print("Populating initial status mappings...")
        for platform_name, platform_status, central_status, description in initial_mappings:
            await self.add_mapping(platform_name, platform_status, central_status, description)
        
        print("\n✅ Initial data population complete!")
    
    async def update_mapping(self, platform_name, platform_status, new_central_status, new_description=None):
        """Update an existing mapping"""
        update_sql = """
        UPDATE platform_status_mappings 
        SET central_status = :central_status, 
            description = COALESCE(:description, description),
            updated_at = CURRENT_TIMESTAMP
        WHERE platform_name = :platform_name AND platform_status = :platform_status
        """
        
        async with get_session() as db:
            result = await db.execute(text(update_sql), {
                'platform_name': platform_name,
                'platform_status': platform_status,
                'central_status': new_central_status,
                'description': new_description
            })
            await db.commit()
            
            if result.rowcount > 0:
                print(f"✅ Updated mapping: {platform_name}.{platform_status} → {new_central_status}")
            else:
                print(f"❌ No mapping found for {platform_name}.{platform_status}")

def get_user_input(prompt, options=None, required=True):
    """Get user input with validation"""
    while True:
        value = input(prompt).strip()
        
        if not value and required:
            print("This field is required. Please enter a value.")
            continue
        
        if options and value.upper() not in [opt.upper() for opt in options]:
            print(f"Invalid option. Please choose from: {', '.join(options)}")
            continue
        
        return value

async def main():
    manager = StatusMappingManager()
    
    while True:
        print("\n" + "="*60)
        print("PLATFORM STATUS MAPPING MANAGER")
        print("="*60)
        print("1. Create table")
        print("2. Add new mapping")
        print("3. View mappings")
        print("4. Update mapping")
        print("5. Populate initial data")
        print("6. Exit")
        
        choice = input("\nEnter your choice (1-6): ").strip()
        
        try:
            if choice == "1":
                await manager.create_table()
            
            elif choice == "2":
                print("\n--- ADD NEW MAPPING ---")
                platform_name = get_user_input("Platform name (e.g., reverb, ebay, shopify, vr): ")
                platform_status = get_user_input("Platform status (e.g., active, sold, ended): ")
                central_status = get_user_input("Central status: ", options=['LIVE', 'SOLD', 'DRAFT'])
                description = get_user_input("Description (optional): ", required=False)
                
                await manager.add_mapping(platform_name, platform_status, central_status.upper(), description)
            
            elif choice == "3":
                print("\n--- VIEW MAPPINGS ---")
                platform_filter = get_user_input("Filter by platform (optional, press Enter for all): ", required=False)
                await manager.view_mappings(platform_filter if platform_filter else None)
            
            elif choice == "4":
                print("\n--- UPDATE MAPPING ---")
                platform_name = get_user_input("Platform name: ")
                platform_status = get_user_input("Platform status: ")
                new_central_status = get_user_input("New central status: ", options=['LIVE', 'SOLD', 'DRAFT'])
                new_description = get_user_input("New description (optional, press Enter to keep current): ", required=False)
                
                await manager.update_mapping(
                    platform_name, 
                    platform_status, 
                    new_central_status.upper(),
                    new_description if new_description else None
                )
            
            elif choice == "5":
                confirm = input("This will add initial mappings. Continue? (y/N): ").strip().lower()
                if confirm == 'y':
                    await manager.populate_initial_data()
            
            elif choice == "6":
                print("Goodbye!")
                break
            
            else:
                print("Invalid choice. Please enter 1-6.")
        
        except KeyboardInterrupt:
            print("\n\nOperation cancelled.")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())