import pandas as pd
import json
import csv
from collections import Counter, defaultdict

def load_category_map(json_file="scripts/vr/category_map.json"):
    """Load the V&R category mapping JSON"""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def build_category_paths(category_data, path_so_far="", id_path_so_far=""):
    """Recursively build full category paths from the JSON structure"""
    paths = {}
    
    # Handle case where category_data might not be a dict
    if not isinstance(category_data, dict):
        return paths
    
    for cat_id, cat_info in category_data.items():
        # Skip if cat_info is not a dictionary
        if not isinstance(cat_info, dict):
            continue
            
        cat_name = cat_info.get('name', '')
        if not cat_name:  # Skip if no name
            continue
            
        current_path = f"{path_so_far}>{cat_name}" if path_so_far else cat_name
        current_id_path = f"{id_path_so_far}-{cat_id}" if id_path_so_far else str(cat_id)
        
        # ✅ FIXED: Store full path as key instead of just category name
        paths[current_path.lower()] = {
            'full_path': current_path,
            'id': cat_id,
            'full_id_path': current_id_path,
            'level': len(current_path.split('>'))
        }
        
        # Process subcategories recursively
        subcategories = cat_info.get('subcategories', {})
        
        if isinstance(subcategories, dict) and subcategories:
            sub_paths = build_category_paths(subcategories, current_path, current_id_path)
            paths.update(sub_paths)
        elif isinstance(subcategories, list) and subcategories:
            for sub_item in subcategories:
                if isinstance(sub_item, dict) and 'id' in sub_item and 'name' in sub_item:
                    sub_id = sub_item['id']
                    sub_name = sub_item['name']
                    sub_path = f"{current_path}>{sub_name}"
                    sub_id_path = f"{current_id_path}-{sub_id}"
                    
                    # ✅ FIXED: Store full path as key
                    paths[sub_path.lower()] = {
                        'full_path': sub_path,
                        'id': sub_id,
                        'full_id_path': sub_id_path,
                        'level': len(sub_path.split('>'))
                    }
    
    return paths

def find_best_category_match(vr_category, category_paths):
    """Find the best matching category path for a V&R category name"""
    vr_lower = vr_category.lower().strip()
    
    # ✅ DEBUG: Show what we're looking for exactly
    if "pickups" in vr_lower and "other" in vr_lower:
        print(f"🔍 EXACT SEARCH: Looking for key '{vr_lower}'")
        print(f"   Character breakdown: {[c for c in vr_lower]}")
        
        # Show all pickups-related keys in the lookup
        pickups_keys = [key for key in category_paths.keys() if "pickups" in key]
        print(f"   Available pickups keys: {pickups_keys}")
        
        # Check exact match manually
        if vr_lower in category_paths:
            print(f"   ✅ EXACT MATCH FOUND!")
        else:
            print(f"   ❌ NO EXACT MATCH")
            # Find closest match
            for key in pickups_keys:
                if "other" in key:
                    print(f"   Close match: '{key}' vs '{vr_lower}'")
                    print(f"   Character comparison: {[c for c in key]} vs {[c for c in vr_lower]}")
    
    # Direct exact match on full path
    if vr_lower in category_paths:
        print(f"🎯 EXACT MATCH for '{vr_category}' -> {category_paths[vr_lower]['full_path']}")
        return category_paths[vr_lower]
    
    # Split the V&R category path to analyze components
    vr_parts = [part.strip().lower() for part in vr_category.split('>')]
    target_level = len(vr_parts)
    
    # Find matches where the first part (main category) matches
    main_category_matches = []
    full_matches_count = 0
    partial_matches_count = 0
    
    for cat_name, cat_info in category_paths.items():
        path_parts = [part.strip().lower() for part in cat_info['full_path'].split('>')]
        
        # Check if the first part matches (e.g., "Guitars" should match "Guitars")
        if len(vr_parts) > 0 and len(path_parts) > 0:
            if vr_parts[0] == path_parts[0]:  # Main category must match
                # Calculate how many parts match in sequence
                matching_parts = 0
                for i in range(min(len(vr_parts), len(path_parts))):
                    if vr_parts[i] == path_parts[i]:
                        matching_parts += 1
                    else:
                        break
                
                level_diff = abs(len(path_parts) - target_level)
                is_exact_level = (len(path_parts) == target_level)
                is_full_match = (matching_parts == len(vr_parts))
                
                # Count full vs partial matches
                if is_full_match:
                    full_matches_count += 1
                else:
                    partial_matches_count += 1
                
                main_category_matches.append((
                    cat_info, 
                    matching_parts, 
                    len(path_parts),
                    is_exact_level,
                    is_full_match,
                    level_diff
                ))
    
    # ✅ DETAILED DEBUG for problematic categories
    if "pickups>other" in vr_lower or "baritone" in vr_lower:
        print(f"🔍 DEBUG for '{vr_category}': found {full_matches_count} full matches, {partial_matches_count} partial matches")
        
        # Show ALL full matches if any exist
        if full_matches_count > 0:
            print(f"   📋 ALL FULL MATCHES:")
            full_match_candidates = [x for x in main_category_matches if x[4] == True]  # x[4] is is_full_match
            for i, match in enumerate(full_match_candidates):
                print(f"     {i+1}. {match[0]['full_path']} (ID: {match[0]['full_id_path']})")
        
        # Show top 3 candidates regardless
        if main_category_matches:
            sorted_matches = sorted(main_category_matches, key=lambda x: (
                -x[3],  # Exact level match first
                -x[4],  # Full path match second
                -x[1],  # More matching parts third
                x[5]    # Smaller level difference fourth
            ))
            
            print(f"   🏆 Top 3 candidates:")
            for i, match in enumerate(sorted_matches[:3]):
                full_indicator = "🎯 FULL" if match[4] else "⚡ PARTIAL"
                print(f"     {i+1}. {full_indicator} - {match[0]['full_path']} (parts={match[1]}, level={match[3]}, full={match[4]})")
    
    if main_category_matches:
        # Sort by exact level match first, then full match, then matching parts
        main_category_matches.sort(key=lambda x: (
            -x[3],  # Exact level match first
            -x[4],  # Full path match second
            -x[1],  # More matching parts third
            x[5]    # Smaller level difference fourth
        ))
        
        best_match = main_category_matches[0]
        match_type = "FULL" if best_match[4] else "PARTIAL"
        print(f"🔍 Best match for '{vr_category}': {match_type} - {best_match[0]['full_path']} (matching_parts={best_match[1]}, level_match={best_match[3]}, full_match={best_match[4]})")
        return best_match[0]
    
    # If no main category match, try partial matches as fallback
    partial_matches = []
    for cat_name, cat_info in category_paths.items():
        if any(part in cat_info['full_path'].lower() for part in vr_parts):
            partial_matches.append((cat_info, len(cat_name)))
    
    if partial_matches:
        partial_matches.sort(key=lambda x: x[1], reverse=True)
        print(f"🔍 Fallback match for '{vr_category}': {partial_matches[0][0]['full_path']}")
        return partial_matches[0][0]
    
    print(f"❌ NO MATCH for '{vr_category}'")
    return None

def analyze_vr_categories():
    """Main function to analyze V&R categories and match them"""
    
    # Load V&R inventory CSV
    vr_csv = "scripts/vr/vintageandrare_inventory.csv"
    print(f"📊 Loading V&R inventory from {vr_csv}")
    
    try:
        df = pd.read_csv(vr_csv)
        print(f"✅ Loaded {len(df)} rows")
    except FileNotFoundError:
        print(f"❌ File not found: {vr_csv}")
        return
    
    # Check for category_name column
    if 'category name' not in df.columns:
        print("❌ No 'category name' column found!")
        print(f"Available columns: {df.columns.tolist()}")
        return
    
    # Count unique categories from V&R
    vr_categories = df['category name'].value_counts(dropna=False)
    print(f"\n🔍 Found {len(vr_categories)} unique V&R categories")
    print(f"📈 Top 10 V&R categories:")
    for cat, count in vr_categories.head(10).items():
        print(f"  {cat}: {count} items")
    
    # Load category mapping JSON
    print(f"\n📂 Loading category mapping JSON...")
    category_map = load_category_map()
    
    # Build all possible category paths
    print(f"🔗 Building category path lookup...")
    category_paths = build_category_paths(category_map)
    print(f"✅ Built {len(category_paths)} category path mappings")
    
    # Match V&R categories to paths
    print(f"\n🎯 Matching V&R categories to hierarchical paths...")
    
    results = []
    matched_count = 0
    unmatched_count = 0
    
    # Counters for match types
    full_match_count = 0
    partial_match_count = 0
    no_match_count = 0
    
    for vr_category, count in vr_categories.items():
        if pd.isna(vr_category):
            vr_category = "NULL/Empty"
        
        # Try to find matching path
        match = find_best_category_match(str(vr_category), category_paths)
        
        if match:
            # Check if it's a full or partial match
            vr_parts = [part.strip().lower() for part in str(vr_category).split('>')]
            path_parts = [part.strip().lower() for part in match['full_path'].split('>')]
            
            matching_parts = 0
            for i in range(min(len(vr_parts), len(path_parts))):
                if vr_parts[i] == path_parts[i]:
                    matching_parts += 1
                else:
                    break
            
            is_full_match = (matching_parts == len(vr_parts))
            
            if is_full_match:
                full_match_count += 1
                match_type = "FULL"
            else:
                partial_match_count += 1
                match_type = "PARTIAL"
            
            results.append({
                'vr_category': vr_category,
                'count': count,
                'matched': True,
                'match_type': match_type,
                'full_path': match['full_path'],
                'category_id': match['id'],
                'full_id_path': match['full_id_path'],
                'hierarchy_level': match['level']
            })
            matched_count += 1
            print(f"✅ {match_type}: {vr_category} → {match['full_path']} (ID Path: {match['full_id_path']})")
        else:
            no_match_count += 1
            results.append({
                'vr_category': vr_category,
                'count': count,
                'matched': False,
                'match_type': 'NO_MATCH',
                'full_path': 'NO_MATCH_FOUND',
                'category_id': '',
                'full_id_path': '',
                'hierarchy_level': 0
            })
            unmatched_count += 1
            print(f"❌ NO_MATCH: {vr_category}")

    # Save results to CSV
    output_csv = "vr_category_mapping_results.csv"
    
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['vr_category', 'count', 'matched', 'match_type', 'full_path', 'category_id', 'full_id_path', 'hierarchy_level']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        writer.writerows(results)
    
    print(f"\n💾 **RESULTS SAVED TO CSV**")
    print(f"File: {output_csv}")
    print(f"Total categories: {len(results)}")
    
    # Match type summary
    print(f"\n📊 **MATCH TYPE SUMMARY**")
    print("=" * 25)
    print(f"🎯 Full matches: {full_match_count}")
    print(f"⚡ Partial matches: {partial_match_count}")
    print(f"❌ No matches: {no_match_count}")
    print(f"📊 Total: {full_match_count + partial_match_count + no_match_count}")
    
    # Overall summary
    print(f"\n📊 **OVERALL SUMMARY**")
    print("=" * 20)
    print(f"✅ Matched: {matched_count}")
    print(f"❌ Unmatched: {unmatched_count}")
    print(f"📈 Overall match rate: {matched_count/len(vr_categories)*100:.1f}%")
    print(f"📈 Full match rate: {full_match_count/len(vr_categories)*100:.1f}%")
    
    # Show hierarchy breakdown
    hierarchy_counts = defaultdict(int)
    for result in results:
        if result['matched']:
            hierarchy_counts[result['hierarchy_level']] += 1
    
    print(f"\n🌳 **HIERARCHY BREAKDOWN**")
    print("=" * 25)
    for level in sorted(hierarchy_counts.keys()):
        print(f"Level {level}: {hierarchy_counts[level]} categories")
    
    # Show unmatched categories for manual review
    unmatched = [r for r in results if not r['matched']]
    if unmatched:
        print(f"\n❌ **UNMATCHED CATEGORIES NEED MANUAL REVIEW**")
        print("=" * 45)
        for result in unmatched:
            print(f"  - {result['vr_category']} ({result['count']} items)")
    
    # Show partial matches for review
    partial = [r for r in results if r.get('match_type') == 'PARTIAL']
    if partial:
        print(f"\n⚡ **PARTIAL MATCHES NEED REVIEW**")
        print("=" * 35)
        for result in partial:
            print(f"  - {result['vr_category']} → {result['full_path']} ({result['count']} items)")

if __name__ == "__main__":
    analyze_vr_categories()