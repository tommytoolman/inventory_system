#!/usr/bin/env python3
"""
Simple database query tool using psycopg2.
No venv required — uses system Python.
"""
import sys
import subprocess

# First, try to install psycopg2-binary if not already installed
try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--break-system-packages", "psycopg2-binary"])
    import psycopg2

def connect_and_query():
    db_url = "postgresql://postgres:KrRdFYWqBowSaMDzBLqIdoUxQXkdycJf@gondola.proxy.rlwy.net:19412/railway"
    
    try:
        print("Connecting to database...")
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        print("\n✓ Connected successfully!\n")
        
        # Query 1: Check current product state
        print("=" * 80)
        print("QUERY 1: Current product state")
        print("=" * 80)
        cur.execute("""
            SELECT id, sku, title, condition, last_synced_reverb 
            FROM products 
            WHERE id = 729
        """)
        row = cur.fetchone()
        if row:
            print(f"ID: {row[0]}")
            print(f"SKU: {row[1]}")
            print(f"Title: {row[2]}")
            print(f"Condition: {row[3]}")
            print(f"Last Synced Reverb: {row[4]}")
        else:
            print("Product not found!")
            cur.close()
            conn.close()
            return
        
        # Query 2: Clear the last_synced_reverb timestamp
        print("\n" + "=" * 80)
        print("QUERY 2: Clearing last_synced_reverb to force re-sync")
        print("=" * 80)
        cur.execute("""
            UPDATE products 
            SET last_synced_reverb = NULL 
            WHERE id = 729
        """)
        print(f"✓ Updated {cur.rowcount} row(s)")
        conn.commit()
        
        # Query 3: Verify the update
        print("\n" + "=" * 80)
        print("QUERY 3: Verify the update")
        print("=" * 80)
        cur.execute("""
            SELECT id, sku, title, condition, last_synced_reverb 
            FROM products 
            WHERE id = 729
        """)
        row = cur.fetchone()
        if row:
            print(f"ID: {row[0]}")
            print(f"SKU: {row[1]}")
            print(f"Title: {row[2]}")
            print(f"Condition: {row[3]}")
            print(f"Last Synced Reverb: {row[4]} (now NULL — will trigger re-sync)")
        
        cur.close()
        conn.close()
        
        print("\n" + "=" * 80)
        print("✓ SUCCESS")
        print("=" * 80)
        print("\nThe product's last_synced_reverb timestamp has been cleared.")
        print("Your sync worker should pick it up on the next run and re-push to Reverb")
        print("with the correct NEW condition.\n")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    connect_and_query()