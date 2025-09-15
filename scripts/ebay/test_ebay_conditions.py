#!/usr/bin/env python3
"""
Test script to check valid condition codes for different eBay categories.

Usage:
    python scripts/test_ebay_conditions.py
    python scripts/test_ebay_conditions.py --category 33034
"""

import asyncio
import sys
import os
import argparse
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ebay.trading import EbayTradingLegacyAPI

# Common musical instrument and audio categories
TEST_CATEGORIES = {
    "33034": "Electric Guitars / Solid Body",
    "33021": "Acoustic Guitars",
    "4713": "Bass Guitars",
    "38072": "Guitar Amplifiers",
    "619": "Musical Instruments & Gear (root)",
    "176984": "Microphones & Wireless Systems",
    "180015": "Vintage Guitars & Basses",
    "181162": "Guitar Effects Pedals",
    "23786": "Pro Audio Equipment",
    "175695": "Mixing Consoles",
    "1305": "Music Memorabilia",
    "104085": "Autographs-Original",
}


async def test_category_conditions(category_id: str = None):
    """Test getting valid conditions for eBay categories"""
    
    # Initialize Trading API
    trading_api = EbayTradingLegacyAPI(sandbox=False)
    
    # Determine which categories to test
    if category_id:
        categories_to_test = {category_id: f"Category {category_id}"}
    else:
        categories_to_test = TEST_CATEGORIES
    
    print("=" * 80)
    print("EBAY CATEGORY CONDITION TEST")
    print("=" * 80)
    
    results = {}
    
    for cat_id, cat_name in categories_to_test.items():
        print(f"\n📦 Testing Category: {cat_id} - {cat_name}")
        print("-" * 60)
        
        try:
            # Get category features
            features = await trading_api.get_category_features(cat_id)
            
            if features:
                print(f"  ✅ Conditions Enabled: {features.get('ConditionEnabled', 'Unknown')}")
                
                valid_conditions = features.get('ValidConditions', [])
                if valid_conditions:
                    print(f"  📋 Valid Conditions ({len(valid_conditions)}):")
                    for condition in valid_conditions:
                        print(f"     • {condition['ID']:5s} = {condition['DisplayName']}")
                    
                    # Store results
                    results[cat_id] = {
                        'name': cat_name,
                        'enabled': features.get('ConditionEnabled'),
                        'conditions': valid_conditions
                    }
                else:
                    print("  ⚠️  No condition values returned")
                    results[cat_id] = {
                        'name': cat_name,
                        'enabled': features.get('ConditionEnabled'),
                        'conditions': []
                    }
            else:
                print("  ❌ Failed to get category features")
                results[cat_id] = {
                    'name': cat_name,
                    'error': 'Failed to get features'
                }
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
            results[cat_id] = {
                'name': cat_name,
                'error': str(e)
            }
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    # Find commonalities
    all_condition_sets = []
    for cat_id, data in results.items():
        if 'conditions' in data and data['conditions']:
            condition_ids = {c['ID'] for c in data['conditions']}
            all_condition_sets.append(condition_ids)
    
    if all_condition_sets:
        # Find conditions that appear in ALL categories
        common_conditions = set.intersection(*all_condition_sets) if all_condition_sets else set()
        
        if common_conditions:
            print(f"\n🔄 Conditions available in ALL tested categories:")
            for cond_id in sorted(common_conditions):
                # Find display name
                for data in results.values():
                    if 'conditions' in data:
                        for cond in data['conditions']:
                            if cond['ID'] == cond_id:
                                print(f"   • {cond_id}: {cond['DisplayName']}")
                                break
                        break
        
        # Find unique conditions
        print(f"\n📊 Condition availability by category:")
        for cat_id, data in results.items():
            if 'conditions' in data and data['conditions']:
                cond_ids = [c['ID'] for c in data['conditions']]
                print(f"   {cat_id} ({data['name'][:30]:30s}): {', '.join(cond_ids)}")
    
    # Save results to file
    output_file = "data/ebay_category_conditions.json"
    os.makedirs("data", exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n💾 Results saved to {output_file}")
    
    return results


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Test eBay category conditions')
    parser.add_argument('--category', type=str, help='Specific category ID to test')
    args = parser.parse_args()
    
    results = asyncio.run(test_category_conditions(args.category))
    
    # Check if we need mapping updates
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    
    # Check if any categories don't support codes we're using
    problem_codes = ["4000", "5000", "6000"]  # Codes we currently use but might not be valid
    
    for cat_id, data in results.items():
        if 'conditions' in data:
            valid_ids = {c['ID'] for c in data['conditions']}
            used_invalid = [code for code in problem_codes if code not in valid_ids]
            
            if used_invalid and valid_ids:  # Has conditions but not our codes
                print(f"\n⚠️  Category {cat_id} ({data['name']}):")
                print(f"   Does NOT support codes: {', '.join(used_invalid)}")
                print(f"   Consider mapping to: 3000 (Used) or 7000 (For Parts)")


if __name__ == "__main__":
    main()