"""
scripts/fix_brian_may_condition.py

Standalone script — only requires psycopg2-binary and python-dotenv.
No app framework imports.

Corrects the condition for Brian May Guitar products that were imported from
Reverb as "Brand New" but stored as GOOD due to the missing condition mapping.

Usage:
    DATABASE_URL=postgresql://user:pass@host/db python scripts/fix_brian_may_condition.py --dry-run
    DATABASE_URL=postgresql://user:pass@host/db python scripts/fix_brian_may_condition.py

Or put DATABASE_URL in a .env file in the project root.
"""
import argparse
import os
import re
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not available — rely on env var

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2-binary is required. Install it with: pip install psycopg2-binary")
    sys.exit(1)


def get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set. Paste your Railway PostgreSQL connection string below.")
        print("(Find it in Railway → database → Connect tab)\n")
        url = input("DATABASE_URL: ").strip()
        if not url:
            print("No URL provided. Exiting.")
            sys.exit(1)
    # Convert asyncpg or other driver prefixes to plain psycopg2 URL
    url = re.sub(r"^postgresql\+asyncpg://", "postgresql://", url)
    url = re.sub(r"^postgresql\+psycopg2://", "postgresql://", url)
    url = re.sub(r"^postgres://", "postgresql://", url)
    return url


def fix_condition(dry_run: bool = True) -> None:
    url = get_db_url()

    print(f"Connecting to database...")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find all Brian May Guitar products
    cur.execute("""
        SELECT id, sku, brand, model, title, condition
        FROM products
        WHERE brand ILIKE %s
        ORDER BY id
    """, ("%brian may%",))
    products = cur.fetchall()

    if not products:
        print("No Brian May Guitar products found in the database.")
        cur.close()
        conn.close()
        return

    print(f"\nFound {len(products)} Brian May Guitar product(s):\n")
    print(f"  {'ID':<6} {'SKU':<20} {'Condition':<12} {'Title'}")
    print(f"  {'-'*6} {'-'*20} {'-'*12} {'-'*40}")
    for p in products:
        title = p['title'] or f"{p['brand']} {p['model']}"
        print(f"  {p['id']:<6} {str(p['sku']):<20} {str(p['condition']):<12} {title}")

    to_fix = [p for p in products if p['condition'] != 'NEW']
    already_correct = [p for p in products if p['condition'] == 'NEW']

    print()
    if already_correct:
        print(f"{len(already_correct)} product(s) already have condition=NEW — no change needed.")

    if not to_fix:
        print("All Brian May products already have condition=NEW. Nothing to do.")
        cur.close()
        conn.close()
        return

    print(f"\n{len(to_fix)} product(s) will be updated from their current condition → NEW:")
    for p in to_fix:
        print(f"  ID={p['id']} SKU={p['sku']} condition={p['condition']} → NEW")

    if dry_run:
        print("\n[DRY RUN] No changes written. Run without --dry-run to apply.")
        cur.close()
        conn.close()
        return

    # Apply the fix
    ids_to_fix = [p['id'] for p in to_fix]
    cur.execute("""
        UPDATE products
        SET condition = 'NEW'
        WHERE id = ANY(%s)
    """, (ids_to_fix,))

    updated = cur.rowcount
    conn.commit()

    print(f"\nSuccessfully updated {updated} product(s) to condition=NEW.")
    print("\nNext steps:")
    print("  1. Go to each product's detail page in RIFF")
    print("  2. Click 'Update on Reverb' / trigger a Reverb re-sync")
    print("  3. Verify Reverb shows 'Brand New' condition")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix Brian May Guitar condition: GOOD/EXCELLENT → NEW"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview changes without writing to the database (safe to run first)",
    )
    args = parser.parse_args()
    fix_condition(dry_run=args.dry_run)
