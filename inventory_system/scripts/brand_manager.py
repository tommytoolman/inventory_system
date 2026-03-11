#!/usr/bin/env python3
"""
Brand Manager - Comprehensive Brand Standardization Tool

This script handles all brand standardization tasks:
- Manual brand standardization
- Automated cleanup of common misspellings  
- Brand analysis and reporting
- Configuration management

Usage:
    # Reports
    python scripts/brand_manager.py --summary
    python scripts/brand_manager.py --find "fender"
    python scripts/brand_manager.py --duplicates
    
    # Manual standardization
    python scripts/brand_manager.py --standardize "fender" "Fender"
    python scripts/brand_manager.py --standardize "Fender Custom Shop" "Fender" --partial
    
    # Automated cleanup
    python scripts/brand_manager.py --auto-cleanup --dry-run
    python scripts/brand_manager.py --auto-cleanup --execute
    
    # Configuration
    python scripts/brand_manager.py --config
    python scripts/brand_manager.py --add-mapping "old_brand" "new_brand"
    python scripts/brand_manager.py --save-config
"""

import asyncio
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from sqlalchemy import text

# Add the parent directory to the path so we can import app modules
sys.path.append(str(Path(__file__).parent.parent))

from app.database import async_session

class BrandManager:
    """Comprehensive brand management tool"""
    
    def __init__(self):
        self.config_file = Path(__file__).parent / "brand_mappings.json"
        self.log_dir = Path(__file__).parent.parent / "logs"
        self.log_dir.mkdir(exist_ok=True)
        
        # Default brand mappings
        self.default_mappings = {
            # Case fixes
            "fender": "Fender", "FENDER": "Fender",
            "gibson": "Gibson", "GIBSON": "Gibson", 
            "martin": "Martin", "MARTIN": "Martin",
            "taylor": "Taylor", "TAYLOR": "Taylor",
            "epiphone": "Epiphone", "EPIPHONE": "Epiphone",
            "rickenbacker": "Rickenbacker", "RICKENBACKER": "Rickenbacker",
            "gretsch": "Gretsch", "GRETSCH": "Gretsch",
            "yamaha": "Yamaha", "YAMAHA": "Yamaha",
            
            # Common misspellings
            "Gibosn": "Gibson", "Gibsn": "Gibson", "Gibsoon": "Gibson",
            "Fende": "Fender", "Fendr": "Fender", "Fendor": "Fender",
            "Rickenbackr": "Rickenbacker", "Rickenback": "Rickenbacker",
            "Gretch": "Gretsch", "Gretsh": "Gretsch",
            
            # Sub-brand standardizations
            "Fender Custom Shop": "Fender",
            "Fender Artist Series": "Fender",
            "Gibson Custom Shop": "Gibson",
            "Gibson USA": "Gibson",
            "Gibson Les Paul": "Gibson",
            "Martin & Co": "Martin",
            "Martin Guitar": "Martin",
            "C.F. Martin": "Martin",
            "Taylor Guitars": "Taylor",
            "Epiphone by Gibson": "Epiphone",
            
            # British brands
            "vox": "Vox", "VOX": "Vox",
            "marshall": "Marshall", "MARSHALL": "Marshall",
            "orange": "Orange", "ORANGE": "Orange",
            "burns": "Burns", "BURNS": "Burns",
            
            # Vintage brands  
            "supro": "Supro", "SUPRO": "Supro",
            "silvertone": "Silvertone", "SILVERTONE": "Silvertone",
            "harmony": "Harmony", "HARMONY": "Harmony",
            "kay": "Kay", "KAY": "Kay",
            "danelectro": "Danelectro", "DANELECTRO": "Danelectro",
            
            # Effects/Amp brands
            "boss": "Boss", "BOSS": "Boss",
            "ibanez": "Ibanez", "IBANEZ": "Ibanez",
            "mesa boogie": "Mesa Boogie", "MESA BOOGIE": "Mesa Boogie",
            "mesa/boogie": "Mesa Boogie", "Mesa/Boogie": "Mesa Boogie",
        }
        
        self.mappings = self.default_mappings.copy()
        self.load_custom_mappings()

    def load_custom_mappings(self):
        """Load additional brand mappings from config file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    custom_mappings = json.load(f)
                    self.mappings.update(custom_mappings)
                    print(f"📋 Loaded {len(custom_mappings)} custom mappings")
            except Exception as e:
                print(f"⚠️ Warning: Could not load custom mappings: {e}")

    def save_config(self):
        """Save current mappings to config file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.mappings, f, indent=2, sort_keys=True)
            print(f"💾 Saved {len(self.mappings)} brand mappings to {self.config_file}")
        except Exception as e:
            print(f"❌ Error saving mappings: {e}")

    def add_mapping(self, old_brand: str, new_brand: str):
        """Add a new brand mapping"""
        self.mappings[old_brand] = new_brand
        print(f"✅ Added mapping: '{old_brand}' → '{new_brand}'")

    async def get_brand_summary(self):
        """Get current brand distribution"""
        async with async_session() as db:
            query = text("""
                SELECT 
                    brand,
                    COUNT(*) as product_count
                FROM products 
                WHERE brand IS NOT NULL AND brand != ''
                GROUP BY brand
                ORDER BY product_count DESC, brand
                LIMIT 20
            """)
            
            result = await db.execute(query)
            return result.fetchall()

    async def find_similar_brands(self, brand_name: str, show_details: bool = True):
        """Find brands that might be variations of the given brand"""
        async with async_session() as db:
            # First get the brand summary
            summary_query = text("""
                SELECT DISTINCT brand, COUNT(*) as count
                FROM products 
                WHERE brand IS NOT NULL 
                  AND brand != ''
                  AND (
                      LOWER(brand) LIKE LOWER(:pattern1) OR
                      LOWER(brand) LIKE LOWER(:pattern2) OR
                      LOWER(:brand_name) LIKE LOWER('%' || brand || '%')
                  )
                GROUP BY brand
                ORDER BY count DESC
            """)
            
            pattern1 = f"%{brand_name}%"
            pattern2 = f"{brand_name}%"
            
            result = await db.execute(summary_query, {
                "pattern1": pattern1, 
                "pattern2": pattern2,
                "brand_name": brand_name
            })
            
            brand_summary = result.fetchall()
            
            # If showing details, get sample products for each brand
            if show_details:
                detailed_results = []
                for brand_row in brand_summary:
                    brand = brand_row.brand
                    count = brand_row.count
                    
                    # Get sample products for this brand
                    detail_query = text("""
                        SELECT sku, title, model, year, 
                               CASE 
                                   WHEN LENGTH(description) > 100 THEN LEFT(description, 100) || '...'
                                   ELSE description
                               END as short_description
                        FROM products 
                        WHERE brand = :brand
                        ORDER BY 
                            CASE WHEN title IS NOT NULL AND title != '' THEN 0 ELSE 1 END,
                            sku
                        LIMIT 3
                    """)
                    
                    sample_result = await db.execute(detail_query, {"brand": brand})
                    sample_products = sample_result.fetchall()
                    
                    detailed_results.append({
                        'brand': brand,
                        'count': count,
                        'samples': sample_products
                    })
                
                return detailed_results
            
            return brand_summary
    
    async def find_duplicates(self):
        """Find brands that are likely duplicates (case variations, etc.)"""
        async with async_session() as db:
            query = text("""
                SELECT 
                    LOWER(brand) as normalized_brand,
                    ARRAY_AGG(DISTINCT brand ORDER BY brand) as variations,
                    SUM(count) as total_products
                FROM (
                    SELECT brand, COUNT(*) as count
                    FROM products 
                    WHERE brand IS NOT NULL AND brand != ''
                    GROUP BY brand
                ) brand_counts
                GROUP BY LOWER(brand)
                HAVING COUNT(DISTINCT brand) > 1
                ORDER BY total_products DESC
            """)
            
            result = await db.execute(query)
            return result.fetchall()

    async def search_products_by_brand(self, brand_name: str, limit: int = 20):
        """Search for products by exact brand name"""
        async with async_session() as db:
            query = text("""
                SELECT 
                    sku, 
                    title, 
                    model, 
                    year, 
                    brand,
                    base_price,
                    CASE 
                        WHEN LENGTH(description) > 150 THEN LEFT(description, 150) || '...'
                        ELSE description
                    END as short_description,
                    primary_image,
                    pc.platform_name,
                    COUNT(*) OVER() as total_count
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                WHERE brand = :brand_name
                ORDER BY 
                    CASE WHEN title IS NOT NULL AND title != '' THEN 0 ELSE 1 END,
                    base_price DESC NULLS LAST,
                    sku
                LIMIT :limit
            """)
            
            result = await db.execute(query, {"brand_name": brand_name, "limit": limit})
            return result.fetchall()

    async def preview_standardization(self, old_brand: str, new_brand: str, include_partial: bool = False):
        """Preview what products would be affected by standardization"""
        async with async_session() as db:
            
            if include_partial:
                # Get partial matches (contains the brand name)
                query = text("""
                    SELECT id, sku, brand, title, 
                           COUNT(*) OVER() as total_count
                    FROM products 
                    WHERE LOWER(brand) LIKE LOWER(:pattern) 
                      AND brand != :new_brand
                    ORDER BY sku
                    LIMIT 10
                """)
                pattern = f"%{old_brand}%"
                params = {"pattern": pattern, "new_brand": new_brand}
            else:
                # Get exact matches (case insensitive)
                query = text("""
                    SELECT id, sku, brand, title,
                           COUNT(*) OVER() as total_count
                    FROM products 
                    WHERE LOWER(brand) = LOWER(:old_brand) 
                      AND brand != :new_brand
                    ORDER BY sku
                    LIMIT 10
                """)
                params = {"old_brand": old_brand, "new_brand": new_brand}
            
            result = await db.execute(query, params)
            return result.fetchall()

    async def standardize_brand(self, old_brand: str, new_brand: str, include_partial: bool = False):
        """Update all products with the old brand to use the new brand"""
        async with async_session() as db:
            
            if include_partial:
                query = text("""
                    UPDATE products 
                    SET brand = :new_brand,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE LOWER(brand) LIKE LOWER(:pattern)
                      AND brand != :new_brand
                """)
                pattern = f"%{old_brand}%"
                params = {"new_brand": new_brand, "pattern": pattern}
            else:
                query = text("""
                    UPDATE products 
                    SET brand = :new_brand,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE LOWER(brand) = LOWER(:old_brand)
                      AND brand != :new_brand
                """)
                params = {"new_brand": new_brand, "old_brand": old_brand}
            
            result = await db.execute(query, params)
            await db.commit()
            
            return result.rowcount

    async def find_auto_cleanup_candidates(self):
        """Find all products that match our automated cleanup rules"""
        async with async_session() as db:
            # Create a query that finds all products with brands in our mapping
            placeholders = []
            params = {}
            
            for i, old_brand in enumerate(self.mappings.keys()):
                placeholder = f"brand_{i}"
                placeholders.append(f":{placeholder}")
                params[placeholder] = old_brand
            
            if not placeholders:
                return []
            
            brands_list = ", ".join(placeholders)
            
            query = text(f"""
                SELECT 
                    brand,
                    COUNT(*) as product_count,
                    ARRAY_AGG(sku ORDER BY sku LIMIT 5) as sample_skus
                FROM products 
                WHERE brand IN ({brands_list})
                GROUP BY brand
                ORDER BY product_count DESC
            """)
            
            result = await db.execute(query, params)
            return result.fetchall()

    async def execute_auto_cleanup(self, dry_run: bool = True):
        """Execute automated brand cleanup"""
        candidates = await self.find_auto_cleanup_candidates()
        
        if not candidates:
            print("✅ No automated cleanup needed!")
            return []
        
        changes = []
        total_products = 0
        
        print(f"\n📋 {'Preview of' if dry_run else 'Executing'} automated cleanup:")
        print("-" * 60)
        
        for candidate in candidates:
            old_brand = candidate.brand
            new_brand = self.mappings[old_brand]
            count = candidate.product_count
            sample_skus = candidate.sample_skus[:3]
            
            changes.append({
                'old_brand': old_brand,
                'new_brand': new_brand,
                'count': count,
                'sample_skus': sample_skus
            })
            
            total_products += count
            
            print(f"'{old_brand}' → '{new_brand}' ({count} products)")
            if sample_skus:
                print(f"  Sample SKUs: {', '.join(sample_skus)}")
            print()
        
        if dry_run:
            print(f"📊 Would update {len(changes)} brand variations affecting {total_products} products")
            return changes
        
        # Execute the changes
        total_updated = 0
        async with async_session() as db:
            for change in changes:
                query = text("""
                    UPDATE products 
                    SET brand = :new_brand,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE brand = :old_brand
                """)
                
                result = await db.execute(query, {
                    "old_brand": change['old_brand'],
                    "new_brand": change['new_brand']
                })
                
                updated_count = result.rowcount
                total_updated += updated_count
                
                print(f"✅ '{change['old_brand']}' → '{change['new_brand']}': {updated_count} products")
            
            await db.commit()
        
        # Create log
        await self.create_log("auto_cleanup", changes, total_updated)
        
        return changes

    async def create_log(self, operation: str, changes: list, updated_count: int):
        """Create a log file of the operation"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"brand_{operation}_{timestamp}.json"
        
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "total_updated": updated_count,
            "changes": changes
        }
        
        try:
            with open(log_file, 'w') as f:
                json.dump(log_data, f, indent=2)
            print(f"📝 Log saved to {log_file}")
        except Exception as e:
            print(f"⚠️ Warning: Could not save log: {e}")

    def show_config(self):
        """Show current brand mapping configuration"""
        print("🔧 Brand Manager Configuration")
        print("=" * 50)
        
        # Group by target brand
        by_target = {}
        for old, new in self.mappings.items():
            if new not in by_target:
                by_target[new] = []
            by_target[new].append(old)
        
        for target_brand in sorted(by_target.keys()):
            variants = sorted(by_target[target_brand])
            print(f"\n{target_brand}:")
            for variant in variants:
                if variant != target_brand:
                    print(f"  '{variant}' → '{target_brand}'")
        
        print(f"\n📊 Total mappings: {len(self.mappings)}")
        print(f"📊 Target brands: {len(by_target)}")
        print(f"📋 Config file: {self.config_file}")

async def main():
    """Main function with argument parsing"""
    parser = argparse.ArgumentParser(
        description="Brand Manager - Comprehensive Brand Standardization Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --summary                              # Show brand distribution
  %(prog)s --find "fender"                        # Find fender variations
  %(prog)s --search "D"                           # Show products for brand "D"
  %(prog)s --duplicates                           # Show duplicate brands
  %(prog)s --standardize "fender" "Fender"        # Manual standardization
  %(prog)s --auto-cleanup --dry-run               # Preview auto cleanup
  %(prog)s --auto-cleanup --execute               # Execute auto cleanup
  %(prog)s --config                               # Show configuration
  %(prog)s --add-mapping "old" "new"              # Add custom mapping
        """
    )
    
    # Reporting commands
    parser.add_argument('--summary', action='store_true', help='Show brand distribution')
    parser.add_argument('--find', metavar='BRAND', help='Find variations of a brand')
    parser.add_argument('--search', metavar='BRAND', help='Search products by exact brand name')
    parser.add_argument('--duplicates', action='store_true', help='Show likely duplicate brands')
    
    # Manual standardization
    parser.add_argument('--standardize', nargs=2, metavar=('OLD', 'NEW'), help='Standardize brand manually')
    parser.add_argument('--partial', action='store_true', help='Include partial matches in standardization')
    
    # Automated cleanup
    parser.add_argument('--auto-cleanup', action='store_true', help='Run automated cleanup')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying')
    parser.add_argument('--execute', action='store_true', help='Execute changes')
    
    # Configuration
    parser.add_argument('--config', action='store_true', help='Show current configuration')
    parser.add_argument('--add-mapping', nargs=2, metavar=('OLD', 'NEW'), help='Add custom brand mapping')
    parser.add_argument('--save-config', action='store_true', help='Save configuration to file')
    
    args = parser.parse_args()
    
    # Create brand manager instance
    manager = BrandManager()
    
    print("🎸 Brand Manager")
    print("=" * 30)
    
    try:
        if args.summary:
            brands = await manager.get_brand_summary()
            print("📊 Brand distribution (top 20):")
            for brand in brands:
                print(f"  {brand.brand}: {brand.product_count} products")
        
        elif args.find:
            similar = await manager.find_similar_brands(args.find, show_details=True)
            print(f"🔍 Brands similar to '{args.find}':")
            print("-" * 60)
            
            for brand_info in similar:
                brand = brand_info['brand']
                count = brand_info['count']
                samples = brand_info['samples']
                
                print(f"\n'{brand}' ({count} products):")
                
                if samples:
                    for sample in samples:
                        # Format the product info nicely
                        year_str = f" ({sample.year})" if sample.year else ""
                        model_str = f" - {sample.model}" if sample.model else ""
                        title_str = sample.title if sample.title else "No title"
                        
                        print(f"  📦 {sample.sku}: {title_str}{year_str}{model_str}")
                        
                        if sample.short_description:
                            # Indent and wrap the description
                            desc_lines = sample.short_description.replace('\n', ' ').strip()
                            if desc_lines:
                                print(f"     💬 {desc_lines}")
                        
                        print()  # Empty line between products
                else:
                    print("  (No product details available)")
                
                print("-" * 40)

        elif args.search:
            products = await manager.search_products_by_brand(args.search, limit=20)
            
            if not products:
                print(f"❌ No products found for brand '{args.search}'")
                return
            
            total_count = products[0].total_count if products else 0
            shown_count = len(products)
            
            print(f"🔍 Products for brand '{args.search}' (showing {shown_count} of {total_count}):")
            print("=" * 80)
            
            for i, product in enumerate(products, 1):
                # Format the product info
                year_str = f" ({product.year})" if product.year else ""
                model_str = f" - {product.model}" if product.model else ""
                title_str = product.title if product.title else "No title"
                price_str = f"£{product.base_price:,.2f}" if product.base_price else "No price"
                platform_str = f"[{product.platform_name.upper()}]"
                
                print(f"\n{i:2d}. 📦 {product.sku} {platform_str}")
                print(f"    🏷️  {title_str}{year_str}{model_str}")
                print(f"    💰 {price_str}")
                
                if product.short_description:
                    desc_lines = product.short_description.replace('\n', ' ').strip()
                    if desc_lines:
                        print(f"    💬 {desc_lines}")
                
                if product.primary_image:
                    print(f"    🖼️  Image: {product.primary_image}")
            
            if shown_count < total_count:
                print(f"\n... and {total_count - shown_count} more products")
            
            print(f"\n📊 Total: {total_count} products for brand '{args.search}'")
        
        elif args.duplicates:
            duplicates = await manager.find_duplicates()
            print("🔍 Likely duplicate brands:")
            for dup in duplicates:
                print(f"  {dup.normalized_brand.title()}:")
                for variant in dup.variations:
                    print(f"    {variant}")
                print(f"    Total: {dup.total_products} products\n")
        
        elif args.standardize:
            old_brand, new_brand = args.standardize
            
            # Preview changes
            matches = await manager.preview_standardization(old_brand, new_brand, args.partial)
            
            if not matches:
                print(f"❌ No products found with brand '{old_brand}'")
                return
            
            total_count = matches[0].total_count if matches else 0
            match_type = "partial" if args.partial else "exact"
            
            print(f"📋 {match_type.title()} matches for '{old_brand}' → '{new_brand}' ({total_count} total):")
            for product in matches[:5]:
                print(f"  {product.sku}: {product.brand} - {product.title or 'No title'}")
            if len(matches) > 5:
                print(f"  ... and {total_count - 5} more")
            
            response = input(f"\n❓ Update {total_count} products? (y/N): ")
            if response.lower() == 'y':
                updated = await manager.standardize_brand(old_brand, new_brand, args.partial)
                print(f"✅ Updated {updated} products")
                await manager.create_log("manual_standardization", 
                                       [{"old_brand": old_brand, "new_brand": new_brand, "count": updated}], 
                                       updated)
        
        elif args.auto_cleanup:
            if args.dry_run:
                await manager.execute_auto_cleanup(dry_run=True)
                print("\n💡 To apply these changes, run with --execute")
            elif args.execute:
                changes = await manager.execute_auto_cleanup(dry_run=False)
                if changes:
                    total = sum(c['count'] for c in changes)
                    print(f"\n🎉 Auto cleanup complete! Updated {total} products")
            else:
                print("❌ Use --dry-run to preview or --execute to apply changes")
        
        elif args.config:
            manager.show_config()
        
        elif args.add_mapping:
            old_brand, new_brand = args.add_mapping
            manager.add_mapping(old_brand, new_brand)
        
        elif args.save_config:
            manager.save_config()
        
        else:
            parser.print_help()
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())