# scripts/drop_recreate_product.py
import asyncio
from sqlalchemy import text
from app.database import engine, get_session

async def recreate_products_table():
    """
    Drop and recreate the products table with correct column order and constraints.
    This matches the Product model exactly but puts description last for pgAdmin readability.
    """
    
    print("Starting products table recreation...")
    
    async with engine.begin() as conn:
        try:
            # Check if table exists first (using async approach)
            print("Checking if products table exists...")
            result = await conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'products'
                );
            """))
            table_exists = result.scalar()
            
            if table_exists:
                print("Dropping existing products table...")
                await conn.execute(text("DROP TABLE IF EXISTS products CASCADE;"))
                print("✅ Table dropped successfully")
            else:
                print("No existing products table found")
            
            # Create table with optimized column order
            create_table_sql = """
            CREATE TABLE products (
                -- Primary Key & Timestamps (NOT NULL as per model)
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
                
                -- Core Identifiers (logical early positions)
                sku VARCHAR UNIQUE,
                brand VARCHAR,
                model VARCHAR,
                year INTEGER,
                decade INTEGER,
                finish VARCHAR,
                category VARCHAR,
                condition productcondition NOT NULL,
                
                -- Pricing Fields  
                base_price DOUBLE PRECISION,
                cost_price DOUBLE PRECISION,
                price DOUBLE PRECISION,
                price_notax DOUBLE PRECISION,
                collective_discount DOUBLE PRECISION,
                offer_discount DOUBLE PRECISION,
                
                -- Status and Business Flags
                status productstatus DEFAULT 'DRAFT',
                is_sold BOOLEAN DEFAULT false,
                in_collective BOOLEAN DEFAULT false,
                in_inventory BOOLEAN DEFAULT true,
                in_reseller BOOLEAN DEFAULT false,
                free_shipping BOOLEAN DEFAULT false,
                buy_now BOOLEAN DEFAULT true,
                show_vat BOOLEAN DEFAULT true,
                local_pickup BOOLEAN DEFAULT false,
                available_for_shipment BOOLEAN DEFAULT true,
                
                -- Media and Links
                primary_image VARCHAR,
                additional_images JSONB DEFAULT '[]'::jsonb,
                video_url VARCHAR,
                external_link VARCHAR,
                
                -- Logistics
                processing_time INTEGER,
                shipping_profile_id INTEGER,
                package_type VARCHAR(50),
                package_weight DOUBLE PRECISION,
                package_dimensions JSONB,
                
                -- Description LAST (for pgAdmin readability)
                description TEXT
            );
            """
            
            print("Creating products table with optimized structure...")
            await conn.execute(text(create_table_sql))
            print("✅ Table created successfully")
            
            # Create essential indexes
            print("Creating indexes...")
            
            await conn.execute(text("CREATE INDEX idx_products_status ON products(status);"))
            print("✅ Status index created")
            
            await conn.execute(text("CREATE UNIQUE INDEX idx_products_sku ON products(sku);"))
            print("✅ SKU unique index created")
            
            # Add foreign key constraint for shipping_profile_id if shipping_profiles table exists
            try:
                # Check if shipping_profiles table exists first
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'shipping_profiles'
                    );
                """))
                shipping_table_exists = result.scalar()
                
                if shipping_table_exists:
                    await conn.execute(text("""
                        ALTER TABLE products 
                        ADD CONSTRAINT fk_products_shipping_profile 
                        FOREIGN KEY (shipping_profile_id) 
                        REFERENCES shipping_profiles(id);
                    """))
                    print("✅ Shipping profile foreign key constraint added")
                else:
                    print("⚠️  Shipping profiles table not found - FK constraint skipped")
                    
            except Exception as e:
                print(f"⚠️  Shipping profile FK constraint skipped: {e}")
            
            print("✅ All changes committed successfully")
            
        except Exception as e:
            print(f"❌ Error during table recreation: {e}")
            raise
    
    # Verify the new structure
    print("\nVerifying new table structure...")
    async with get_session() as session:
        try:
            result = await session.execute(text("""
                SELECT 
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    ordinal_position
                FROM information_schema.columns 
                WHERE table_name = 'products' 
                    AND table_schema = 'public'
                ORDER BY ordinal_position
                LIMIT 10;
            """))
            
            print("First 10 columns in new structure:")
            rows = result.fetchall()
            for row in rows:
                nullable = "NULL" if row[2] == "YES" else "NOT NULL"
                default = row[3] if row[3] else "No default"
                print(f"  {row[4]:2}. {row[0]:20} {row[1]:25} {nullable:8}")
                
        except Exception as e:
            print(f"⚠️  Could not verify structure: {e}")

if __name__ == "__main__":
    asyncio.run(recreate_products_table())