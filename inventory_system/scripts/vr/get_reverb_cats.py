import pandas as pd
import json
import ast
import csv
from collections import Counter

# Read the Reverb CSV file
csv_file = "/Users/wommy/Documents/GitHub/PROJECTS/HANKS/inventory_system/scripts/reverb/output/reverb_listings_all_20250806_114936.csv"
df = pd.read_csv(csv_file)

print(f"📊 Loaded {len(df)} rows from {csv_file}")
print(f"Columns: {df.columns.tolist()}")

# Check if categories column exists
if 'categories' not in df.columns:
    print("❌ No 'categories' column found!")
    print(f"Available columns: {df.columns.tolist()}")
else:
    print(f"\n🔍 Analyzing 'categories' column...")
    
    # Get all category values (including NaN)
    category_values = df['categories'].value_counts(dropna=False)
    print(f"\n📈 Raw category value counts:")
    print(category_values.head(5))
    
    # Parse JSON categories and extract full category objects
    category_objects = []
    
    for idx, row in df.iterrows():
        categories_raw = row.get('categories', '')
        
        if pd.isna(categories_raw) or not categories_raw:
            continue
            
        try:
            # The issue is that pandas reads it as a string with single quotes
            # We need to use ast.literal_eval instead of json.loads
            if isinstance(categories_raw, str) and categories_raw.startswith('['):
                # Use ast.literal_eval which can handle single quotes
                categories_list = ast.literal_eval(categories_raw)
                
                for category in categories_list:
                    if isinstance(category, dict):
                        # Store the full category object as a string for counting
                        category_str = json.dumps(category, sort_keys=True)
                        category_objects.append(category_str)
                            
        except (ValueError, SyntaxError, TypeError) as e:
            print(f"❌ Error parsing categories in row {idx}: {categories_raw[:100]}...")
    
    # Count unique category objects
    category_counts = Counter(category_objects)
    
    print(f"\n🎯 **UNIQUE CATEGORY OBJECTS** ({len(category_counts)} unique)")
    print("=" * 60)
    
    # Prepare data for CSV output
    csv_data = []
    
    for category_str, count in category_counts.most_common():
        try:
            # Parse back to dict for display and CSV
            category_dict = json.loads(category_str)
            uuid = category_dict.get('uuid', '')
            full_name = category_dict.get('full_name', '')
            
            print(f"{full_name} ({uuid}): {count} listings")
            
            # Add to CSV data
            csv_data.append({
                'uuid': uuid,
                'full_name': full_name,
                'count': count,
                'full_json': category_str
            })
            
        except json.JSONDecodeError:
            print(f"Error parsing: {category_str[:100]}...")
    
    # Save to CSV
    output_csv = "scripts/vr/reverb_cats_counts.csv"
    
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['uuid', 'full_name', 'count', 'full_json']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        writer.writerows(csv_data)
    
    print(f"\n💾 **SAVED TO CSV**")
    print(f"File: {output_csv}")
    print(f"Rows: {len(csv_data)}")
    
    # Summary statistics
    print(f"\n📊 **SUMMARY**")
    print("=" * 20)
    print(f"Total rows: {len(df)}")
    print(f"Rows with categories: {len([x for x in df['categories'] if pd.notna(x) and x])}")
    print(f"Unique category objects: {len(category_counts)}")
    print(f"Total category instances: {sum(category_counts.values())}")
    
    # Show top 10 for quick reference
    print(f"\n🔝 **TOP 10 CATEGORIES**")
    print("=" * 40)
    for i, (category_str, count) in enumerate(category_counts.most_common(10), 1):
        try:
            category_dict = json.loads(category_str)
            full_name = category_dict.get('full_name', 'Unknown')
            print(f"{i:2d}. {full_name}: {count} listings")
        except:
            print(f"{i:2d}. Parse error: {count} listings")