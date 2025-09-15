import json
import sys
from pathlib import Path

# Add project root to path to allow importing the transformer
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import the class containing the map
from scripts.ebay.create_ebay_listings_from_csv import ReverbToEbayTransformer

def generate_json_file():
    """
    Extracts the category mapping dictionary and saves it to a JSON file.
    """
    print("Extracting category map...")
    transformer = ReverbToEbayTransformer()
    mapping_data = transformer.get_comprehensive_reverb_to_ebay_mapping()
    
    output_filename = 'reverb_to_ebay_categories.json'
    
    print(f"Saving map with {len(mapping_data)} entries to {output_filename}...")
    # FIX: The 'indent' argument is correctly passed to the json.dump() function
    with open(output_filename, 'w') as f:
        json.dump(mapping_data, f, indent=4)
        
    print(f"✅ Success! {output_filename} has been created in your project's root directory.")

if __name__ == "__main__":
    generate_json_file()