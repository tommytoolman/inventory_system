#!/usr/bin/env python3
"""
Script to create V&R listings from CSV data using VintageAndRareClient

Supports both:
1. Direct V&R CSV format
2. Reverb CSV format (with automatic transformation)

Usage: 
    # Transform Reverb CSV and output to file for validation
    python scripts/vr/create_vr_from_csv.py --csv-file reverb_live.csv --reverb-mode --output-csv vr_ready.csv
    
    # Transform Reverb CSV and create listings directly (no intermediate CSV)
    python scripts/vr/create_vr_from_csv.py --csv-file reverb_live.csv --reverb-mode --test-mode
    
    # Regular V&R CSV processing
    python scripts/vr/create_vr_from_csv.py --csv-file vr_products.csv --test-mode
"""

import argparse
import asyncio
import aiohttp
import csv
import json
import sys
import os
import re
import ast
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, Any, Optional, List

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / '.env')

from app.services.vintageandrare.client import VintageAndRareClient
from app.services.reverb.client import ReverbClient

class ReverbToVRTransformer:
    """Transform Reverb CSV data to V&R format"""
    
    def __init__(self, reverb_api_key: str):
        self.reverb_client = ReverbClient(api_key=reverb_api_key, use_sandbox=False)
    
    async def transform_reverb_csv(self, input_csv: str, output_csv: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Transform Reverb CSV to V&R format
        
        Args:
            input_csv: Path to Reverb CSV file
            output_csv: If provided, save transformed data to this CSV file
            
        Returns:
            List of V&R product data dictionaries
        """
        print(f"🔄 Transforming Reverb CSV: {input_csv}")
        
        # Read Reverb CSV
        with open(input_csv, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            reverb_rows = list(reader)
        
        print(f"📊 Found {len(reverb_rows)} Reverb listings")
        
        # Transform each row
        vr_data = []
        for row_num, row in enumerate(reverb_rows, 1):
            try:
                vr_row = await self._transform_row(row, row_num)
                if vr_row:
                    vr_data.append(vr_row)
                    print(f"✅ Row {row_num}: {vr_row.get('brand')} {vr_row.get('model')}")
                else:
                    print(f"⏭️  Row {row_num}: Skipped")
                    
            except Exception as e:
                print(f"❌ Row {row_num}: Error - {str(e)}")
        
        print(f"📝 Successfully transformed {len(vr_data)}/{len(reverb_rows)} rows")
        
        # Save to CSV if requested
        if output_csv and vr_data:
            self._save_to_csv(vr_data, output_csv)
        
        return vr_data
    
    async def _transform_row(self, row: dict, row_num: int) -> Optional[Dict[str, Any]]:
        """Transform single Reverb row to V&R format"""
        
        try:
            # Extract basic fields
            listing_id = row.get('id', '')
            brand = row.get('make', '').strip()
            model = row.get('model', '').strip()
            
            # Brand validation placeholder
            if not self._validate_vr_brand(brand):
                print(f"⚠️  Row {row_num}: Brand '{brand}' not allowed on V&R")
                return None
            
            # Price extraction
            price = self._extract_price(row.get('price', ''))
            if not price or price <= 0:
                print(f"⚠️  Row {row_num}: Invalid price")
                return None
            
            # Year processing
            year = self._extract_year(row.get('year', ''))
            
            # Description processing
            description = self._process_description(row.get('description', ''))
            
            # Category mapping - FIXED: Remove duplicate line
            categories_raw = row.get('categories', '')
            vr_category_mapping = self._map_reverb_category_to_vr_ids(categories_raw)
            
            # Get images from Reverb API
            images = await self._get_reverb_images(listing_id)
            primary_image = images[0] if images else ''
            additional_images = images[1:20] if len(images) > 1 else []
            
            # OLD Shipping profile mapping
            # shipping_profile = self._map_shipping_profile('Electric Guitars')  # ← FIXED: Use string not dict
            # NEW:
            shipping_data = row.get('shipping', '')
            shipping_profile = self._parse_reverb_shipping_to_vr_profile(shipping_data)
            
            # Build V&R product data
            vr_row = {
                # Required fields
                'sku': f"REV-{listing_id}",
                'brand': brand,
                'model': model,
                'price': price,
                'description': description,
                
                # Optional fields
                'year': year,
                'finish': row.get('finish', ''),
                
                # V&R Category mapping (for from_scratch=False mode)
                'Category': vr_category_mapping['category_id'],        # '51'
                'SubCategory1': vr_category_mapping['subcategory_id'], # '83'
                'SubCategory2': vr_category_mapping.get('sub_subcategory_id'),     # None for now
                'SubCategory3': vr_category_mapping.get('sub_sub_subcategory_id'), # None for now
                
                # Media
                'primary_image': primary_image,
                'additional_images': json.dumps(additional_images) if additional_images else '',
                'video_url': '',
                
                # V&R specific defaults
                'vr_show_vat': True,
                'vr_call_for_price': False,
                'vr_in_collective': False,
                'vr_in_inventory': True,
                'vr_in_reseller': False,
                'processing_time': '3',
                'time_unit': 'Days',
                'available_for_shipment': True,
                'local_pickup': False,
                
                # Shipping fees
                **shipping_profile,
                
                # Reverb metadata
                'external_url': f"https://reverb.com/uk/item/{listing_id}"
            }
            
            return vr_row
            
        except Exception as e:
            print(f"❌ Error transforming row {row_num}: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return None    
    
    def _validate_vr_brand(self, brand: str) -> bool:
        """Validate brand against V&R accepted brands - PLACEHOLDER"""
        if not brand or len(brand.strip()) < 2:
            return False
        
        invalid_brands = ['unknown', 'n/a', 'none', 'test']
        if brand.lower() in invalid_brands:
            return False
        
        # TODO: Add actual V&R brand validation
        return True
    
    def _extract_price(self, price_data: str) -> float:
        """Extract price from Reverb price structure"""
        try:
            if isinstance(price_data, str) and price_data.strip():
                if price_data.startswith('{'):
                    import ast
                    price_dict = ast.literal_eval(price_data)
                    amount = price_dict.get('amount', 0)
                else:
                    amount = price_data
                
                if isinstance(amount, str):
                    amount = re.sub(r'[,$]', '', amount.strip())
                    return float(amount)
                else:
                    return float(amount)
            return 0.0
        except (ValueError, SyntaxError, TypeError):
            return 0.0
    
    def _extract_year(self, year_data: str) -> Optional[int]:
        """Extract year from various formats"""
        if not year_data:
            return None
        
        year_str = str(year_data).strip()
        
        if '-' in year_str:
            year_str = year_str.split('-')[0].strip()
        
        if year_str.endswith('s'):
            year_str = year_str[:-1]
        
        match = re.search(r'\d{4}', year_str)
        if match:
            try:
                year = int(match.group())
                if 1800 <= year <= 2030:
                    return year
            except ValueError:
                pass
        
        return None
    
    def _process_description(self, description: str) -> str:
        """Process and clean description with proper formatting"""
        if not description:
            return ""
        
        processed_desc = str(description)
        
        # Add line breaks after bold headers (but not before the first one)
        # Pattern: </strong></b></p> should be followed by <br>
        processed_desc = re.sub(r'</strong></b></p>(?!<p><b><strong>ALL EU)', r'</strong></b></p><br>', processed_desc)
        
        # Alternative pattern for other bold header formats
        processed_desc = re.sub(r'</strong></b>(?!</p><p><b><strong>ALL EU)', r'</strong></b><br>', processed_desc)
        
        # Check for and add footer if not present
        footer_text = "<strong>ALL EU PURCHASES ARE DELIVERED WITH TAXES AND DUTIES PAID</strong>"
        
        if footer_text in processed_desc:
            print("✅ Standard footer found")
        else:
            # Add line break before footer
            full_footer = """<br>
    <p><b><strong>ALL EU PURCHASES ARE DELIVERED WITH TAXES AND DUTIES PAID</strong></b></p>
    <p>All purchases include EU Taxes / Duties paid , ie nothing further is due on receipt of goods to any EU State.</p>
    <p><b><strong>WHY BUY FROM US&nbsp;</strong></b></p>
    <p>We are one of the world's leading specialists in used and vintage gear with over 30 years of experience. Prior to shipping each item will be fully serviced and professionally packed&nbsp;</p>
    <p><b><strong>SELL - TRADE - CONSIGN&nbsp;</strong></b></p>
    <p>If you are looking to sell, trade or consign any of your classic gear please contact us by message.</p>
    <p><b><strong>WORLDWIDE COLLECTION - DELIVERY&nbsp;</strong></b></p>
    <p>We offer personal delivery and collection services worldwide with offices/locations in London, Amsterdam and Chicago.</p>
    <p><b><strong>VALUATION SERVICE&nbsp;</strong></b></p>
    <p>If you require a valuation of any of your classic year please forward a brief description and pictures and we will come back to your ASAP.</p>
    """
            processed_desc += full_footer
            print("📝 Added standard footer")
        
        return processed_desc
    
    def _map_reverb_category_to_vr_ids(self, categories_raw: str) -> Dict[str, Optional[str]]:
        """Map Reverb category JSON to V&R category IDs"""
        
        # Default fallback
        default_mapping = {
            'category_id': '51',      # Guitars
            'subcategory_id': '83',   # Electric solid body
            'sub_subcategory_id': None,
            'sub_sub_subcategory_id': None
        }
        
        if not categories_raw:
            return default_mapping
        
        try:
            # Parse Reverb categories JSON
            categories_list = ast.literal_eval(categories_raw)
            if not categories_list or not isinstance(categories_list, list):
                return default_mapping
            
            # Get first category
            category = categories_list[0]
            reverb_uuid = category.get('uuid', '')
            reverb_full_name = category.get('full_name', '')
            
            # Simple direct mapping for your test case
            mapping_table = {
                'e57deb7a-382b-4e18-a008-67d4fbcb2879': {  # Electric Guitars / Solid Body
                    'category_id': '51',      # Guitars
                    'subcategory_id': '83',   # Electric solid body
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                'dfd39027-d134-4353-b9e4-57dc6be791b9': {  # Electric Guitars (general)
                    'category_id': '51',      # Guitars  
                    'subcategory_id': '83',   # Electric solid body (default)
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '6a63ac2e-f2a5-4064-b6ea-0393f42ee497': {  # Electric Guitars / Semi-Hollow
                    'category_id': '51',      # Guitars
                    'subcategory_id': '84',   # Semi-hollow body
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '5db35d7e-2b7e-4dcf-a73b-6a144c710956': {  # Electric Guitars / Hollow Body
                    'category_id': '51',      # Guitars
                    'subcategory_id': '84',   # Semi-hollow body
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                'ddd7553e-68d5-4005-a356-3f94202682a8': {  # Electric Guitars / Lap Steel
                    'full_name': 'Electric Guitars / Lap Steel',
                    'reverb_count': 5,
                    'category_id': '51',  # Guitar 
                    'subcategory_id': '231',  # Lap & pedal steel
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '367e1d5d-1185-4a1e-b283-8ec860dc1d5f': {  # Electric Guitars / Archtop
                    'full_name': 'Electric Guitars / Archtop',
                    'reverb_count': 58,
                    'category_id': '51',  # Guitar 
                    'subcategory_id': '86',  # Archtop
                    'sub_subcategory_id': '196',  # Electric
                    'sub_sub_subcategory_id': None  #
                },
                'fa10f97c-dd98-4a8f-933b-8cb55eb653dd': {  # Effects and Pedals
                    'full_name': 'Effects and Pedals',
                    'reverb_count': 138,
                    'category_id': '90',  # Effects
                    'subcategory_id': '229',  # Other
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'fc775402-66a5-4248-8e71-fd9be6b2214a': {  # Effects and Pedals / Amp Simulators
                    'full_name': 'Effects and Pedals / Amp Simulators',
                    'reverb_count': 3,
                    'category_id': '90',  # Effects
                    'subcategory_id': '387',  # Amp Simulator
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'c6602a28-e2e7-4e70-abeb-0fa38b320be6': {  # Effects and Pedals / Bass Pedals
                    'full_name': 'Effects and Pedals / Bass Pedals',
                    'reverb_count': 3,
                    'category_id': '90',  # Effects
                    'subcategory_id': '',  #
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '15800d29-53a1-446e-8560-7a74a6d8d962': {  # Effects and Pedals / Chorus and Vibrato
                    'full_name': 'Effects and Pedals / Chorus and Vibrato',
                    'reverb_count': 7,
                    'category_id': '90',  # Effects
                    'subcategory_id': '',  #
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '86d377ed-c038-4353-a391-f592ebd6d921': {  # Effects and Pedals / Compression and Sustain
                    'full_name': 'Effects and Pedals / Compression and Sustain',
                    'reverb_count': 7,
                    'category_id': '90',  # Effects
                    'subcategory_id': '96',  #
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '6bd92034-d59c-4d78-a6c1-1e8a3c31b31e': {  # Effects and Pedals / Controllers, Volume and Expression
                    'full_name': 'Effects and Pedals / Controllers, Volume and Expression',
                    'reverb_count': 8,
                    'category_id': '90',  # Effects
                    'subcategory_id': '229',  # Other
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '3b09f948-3462-4ac2-93b3-59dd66da787e': {  # Effects and Pedals / Delay
                    'full_name': 'Effects and Pedals / Delay',
                    'reverb_count': 39,
                    'category_id': '90',  # Effects
                    'subcategory_id': '98',  # Delay & Echo
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '732e30f0-21cf-4960-a3d4-bb90c68081db': {  # Effects and Pedals / Distortion
                    'full_name': 'Effects and Pedals / Distortion',
                    'reverb_count': 18,
                    'category_id': '90', # Effects
                    'subcategory_id': '92',  # Distortion
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                'ec612b9c-6227-4249-9010-b85b6b0eb5b0': {  # Effects and Pedals / EQ
                    'full_name': 'Effects and Pedals / EQ',
                    'reverb_count': 7,
                    'category_id': '90',  # Effects
                    'subcategory_id': '249',  # Equalizer
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'b753bcd4-2cc5-4ea1-8f01-c8b034012372': {  # Effects and Pedals / Flanger
                    'full_name': 'Effects and Pedals / Flanger',
                    'reverb_count': 3,
                    'category_id': '90',  # Effects
                    'subcategory_id': '268',  # Flanger
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '305e09a1-f9cb-4171-8a70-6428ad1b55a8': {  # Effects and Pedals / Fuzz
                    'full_name': 'Effects and Pedals / Fuzz',
                    'reverb_count': 114,
                    'category_id': '90',  # Effects
                    'subcategory_id': '93',  # Fuzz
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '7e6b6d7c-cdd5-4a42-bceb-6ea12899137b': {  # Effects and Pedals / Guitar Synths
                    'full_name': 'Effects and Pedals / Guitar Synths',
                    'reverb_count': 1,
                    'category_id': '90',  # Effects
                    'subcategory_id': '229',  # Other
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '66170426-1b4d-4361-8002-3282f4907217': {  # Effects and Pedals / Loop Pedals and Samplers
                    'full_name': 'Effects and Pedals / Loop Pedals and Samplers',
                    'reverb_count': 7,
                    'category_id': '90',  # Effects
                    'subcategory_id': '250',  # Looper/Switching/Controller
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '2d6093b4-6b33-474e-b07c-25f6657d7956': {  # Effects and Pedals / Multi-Effect Unit
                    'full_name': 'Effects and Pedals / Multi-Effect Unit',
                    'reverb_count': 13,
                    'category_id': '90',  # Effects
                    'subcategory_id': '247',  # Multieffect
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '8745626e-3273-4f9d-b7a1-ca5b202a8e6e': {  # Effects and Pedals / Noise Reduction and Gates
                    'full_name': 'Effects and Pedals / Noise Reduction and Gates',
                    'reverb_count': 1,
                    'category_id': '90',  # Effects
                    'subcategory_id': '418',  # Noise gate
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '8dab3e10-a7f8-444b-aa9d-ccdab4fe66c6': {  # Effects and Pedals / Octave and Pitch
                    'full_name': 'Effects and Pedals / Octave and Pitch',
                    'reverb_count': 7,
                    'category_id': '90',  # Effects
                    'subcategory_id': '97',  # Octave
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '9bee8b39-c5f1-4fa7-90af-38740fc21a73': {  # Effects and Pedals / Overdrive and Boost'
                    'full_name': 'Effects and Pedals / Overdrive and Boost',
                    'reverb_count': 93,
                    'category_id': '90',      # Effects
                    'subcategory_id': '91',   # Overdrive
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '66fd5c3b-3227-4182-9337-d0e4893be9a2': {  # Effects and Pedals / Pedalboards and Power Supplies
                    'full_name': 'Effects and Pedals / Pedalboards and Power Supplies',
                    'reverb_count': 7,
                    'category_id': '90',  # Effects
                    'subcategory_id': '229',  # Other
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '75e55b59-f57b-4e39-87b1-fcda4c1ed562': {  # Effects and Pedals / Phase Shifters
                    'full_name': 'Effects and Pedals / Phase Shifters',
                    'reverb_count': 7,
                    'category_id': '90',  # Effects
                    'subcategory_id': '100',  # Phaser
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '4d45f512-4dd5-4dae-95b7-7eb400ce406b': {  # Effects and Pedals / Preamps
                    'full_name': 'Effects and Pedals / Preamps',
                    'reverb_count': 3,
                    'category_id': '90',  # Effects
                    'subcategory_id': '362',  # Overdrive/Pre-amp
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '1738a9ae-6485-46c2-8ead-0807bb2e20e9': {  # Effects and Pedals / Reverb
                    'full_name': 'Effects and Pedals / Reverb',
                    'reverb_count': 19,
                    'category_id': '90',  # Effects
                    'subcategory_id': '129',  # Reverb
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '38f7f86b-5d7a-499a-9bdc-c3198395dfa6': {  # Effects and Pedals / Tremolo
                    'full_name': 'Effects and Pedals / Tremolo',
                    'reverb_count': 2,
                    'category_id': '90',  # Effects
                    'subcategory_id': '127',  # Tremolo     
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '69a7e38f-0ce8-42ea-a0f6-8a30b7f6886e': {  # Effects and Pedals / Tuning Pedals
                    'full_name': 'Effects and Pedals / Tuning Pedals',
                    'reverb_count': 3,
                    'category_id': '90',  # Effects
                    'subcategory_id': '',  #
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'e5553727-8786-4932-8761-dab396640ff0': {  # Effects and Pedals / Vocal
                    'full_name': 'Effects and Pedals / Vocal',
                    'reverb_count': 3,
                    'category_id': '90',  # Effects
                    'subcategory_id': '',  #
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'a92165b2-2281-4dc2-850f-2789f513ec10': {  # Effects and Pedals / Wahs and Filters
                    'full_name': 'Effects and Pedals / Wahs and Filters',
                    'reverb_count': 18,
                    'category_id': '90',  # Effects
                    'subcategory_id': '128',  # Wah Wah
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                # [{'uuid': '010855a4-d387-405f-929d-ec22667abadc', 'full_name': 'Home Audio / Tape Decks'}]
                # [{'uuid': 'b021203f-1ed8-476c-a8fc-32d4e3b0ef9e', 'full_name': 'Pro Audio'}]
                # [{'uuid': '10187eaa-7746-4978-9f44-7670e95a40da', 'full_name': 'Pro Audio / Outboard Gear / Gates and Expanders'}, {'uuid': '8865016e-edbb-4ee7-a704-6ea0652d6bf4', 'full_name': 'Pro Audio / Outboard Gear / Compressors and Limiters'}]
                # [{'uuid': '36a0faca-93b7-4ad1-ab09-02629ec1e900', 'full_name': 'Pro Audio / Recording'}]
                # [{'uuid': 'c63d7668-c0d1-421d-97ef-587959f7282c', 'full_name': 'Pro Audio / Mixers'}]
                '0f2bbf76-3225-44d5-8a5b-c540cc1fd058': {  # Pro Audio / Microphones
                    'category_id': '51',      # Guitars
                    'subcategory_id': '356',   # Miscellaneous
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '62835d2e-ac92-41fc-9b8d-4aba8c1c25d5': {  # Accessories
                    'category_id': '51',      # Guitars
                    'subcategory_id': '211',   # Miscellaneous
                    'sub_subcategory_id': '279', # Other
                    'sub_sub_subcategory_id': None
                },
                '5cb132e1-1a42-42f4-bcd1-cf17405e7aff': {  # Accessories / Case Candy
                    'category_id': '51',      # Guitars
                    'subcategory_id': '211',   # Parts and Accessories
                    'sub_subcategory_id': '286', # Case
                    'sub_sub_subcategory_id': None
                },
                '516cfd7e-e745-44cf-bb72-053b3edcddaf': {  # Accessories / Cables
                    'full_name': 'Accessories / Cables',
                    'reverb_count': 2,
                    'category_id': '51',      # Guitars
                    'subcategory_id': '211',   # Parts and Accessories
                    'sub_subcategory_id': '279', # Other
                    'sub_sub_subcategory_id': None
                },
                '5004a624-03c4-436b-81bf-78a108eb595d': {  # Accessories / Headphones
                    'category_id': '51',      # Guitars
                    'subcategory_id': '356',   # Miscellaneous
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                'ecb1bc0c-1f79-40a9-9429-0696defa7b19': {  # Drums and Percussion / Marching Percussion / Marching Cymbals
                    'category_id': '216',      # Drums
                    'subcategory_id': '224',   # Cymbals
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '7a28aae1-de39-4c8b-ae37-b621fc46a5e9': {  # Drums and Percussion / Parts and Accessories / Heads
                    'full_name': 'Drums and Percussion / Parts and Accessories / Heads',
                    'reverb_count': 1,
                    'category_id': '216',  # Drums
                    'subcategory_id': '223',  # Hardware & Accessories
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '3ca3eb03-7eac-477d-b253-15ce603d2550': {  # Acoustic Guitars
                    'full_name': 'Acoustic Guitars',
                    'reverb_count': 84,
                    'category_id': '51',  # Guitars
                    'subcategory_id': '87',  # Flat top
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'be24976f-ab6e-42e1-a29b-275e5fbca68f': {  # Acoustic Guitars / Archtop
                    'category_id': '51',
                    'subcategory_id': '86',
                    'sub_subcategory_id': '195',
                    'sub_sub_subcategory_id': None
                },
                'c58c6c12-4b50-4568-90c9-e071ec8e6a26': {  # Acoustic Guitars / Jumbo
                    'category_id': '51',
                    'subcategory_id': '87',
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                'db34e833-b352-45b9-9976-4f674a7e6d8c': {  # Acoustic Guitars / OM and Auditorium
                    'category_id': '51',
                    'subcategory_id': '87',
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },            
                '18bdeae7-e834-42a8-aeee-0e8ae33f8709': {  # Acoustic Guitars / Concert
                    'full_name': 'Acoustic Guitars / Concert',
                    'category_id': '51', # Guitars
                    'subcategory_id': '87', # Flat top
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                'a7f470d1-266d-4495-b4d6-998cc84b7474': {  # Acoustic Guitars / Classical
                    'full_name': 'Acoustic Guitars / Classical',
                    'reverb_count':35,
                    'category_id': '51',  # Guitars
                    'subcategory_id': '88',  # Classical
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '630dc140-45e2-4371-b569-19405de321cc': {  # Acoustic Guitars / Dreadnought
                    'category_id': '51',
                    'subcategory_id': '87',
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '8b531867-88ee-46c5-b6d1-40d2d6b9dc35': {  # Acoustic Guitars / Resonator
                    'full_name': 'Acoustic Guitars / Resonator',
                    'reverb_count': 17,
                    'category_id': '51',
                    'subcategory_id': '230',
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '14d6cc96-ed7b-4521-bc21-7713c61e9dc5': {  # Acoustic Guitars / 12-String
                    'full_name': 'Acoustic Guitars / 12-String',
                    'reverb_count': 13,
                    'category_id': '51',
                    'subcategory_id': '255',
                    'sub_subcategory_id': '256',
                    'sub_sub_subcategory_id': None
                },
                '09055aa7-ed49-459d-9452-aa959f288dc2': {  # Amps
                    'full_name': 'Amps',
                    'reverb_count': 223,
                    'category_id': '53',  # Amps
                    'subcategory_id': '183',  # Combo 
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '892aa8b2-a209-49db-8ad2-eed758025a9d': {  # Amps / Bass Amps / Bass Heads
                    'full_name': 'Amps / Bass Amps / Bass Heads',
                    'reverb_count': 18,
                    'category_id': '53',  # Amps
                    'subcategory_id': '182',  # Heads (VR not separate category for bass amps) 
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '19d53222-297e-410c-ba4f-b48678e917f9': {  # Amps / Guitar Amps / Guitar Heads
                    'full_name': 'Amps / Guitar Amps / Guitar Heads',
                    'reverb_count': 231,
                    'category_id': '53',  # Amps
                    'subcategory_id': '182',  # Heads
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '66d136cb-02f2-4d04-b617-9215e972cc29': {  # Amps / Guitar Amps / Guitar Amp Stacks
                    'category_id': '53', # Amps
                    'subcategory_id': '212', # Head + Cab
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '10335451-31e5-418a-8ed8-f48cd738f17d': {  # Amps / Guitar Amps / Guitar Combos
                    'full_name': 'Amps / Guitar Amps / Guitar Combos',
                    'reverb_count': 218,
                    'category_id': '53',  # Amps
                    'subcategory_id': '183',  # Combo
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'edd6e048-a378-4f6f-b2b5-dd46016c6118': {  # Amps / Small Amps
                    'full_name': 'Amps / Small Amps',
                    'reverb_count': 8,
                    'category_id': '53',      # Amps
                    'subcategory_id': '183',   # Combo
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                'eb1827f3-c02c-46ff-aea9-7983e2aae1b4': {  # Parts / Amp Parts
                    'full_name': 'Parts / Amp Parts',
                    'reverb_count': 94,
                    'category_id': '53',      # Amps
                    'subcategory_id': '183',   # Combo (no parts)
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '7ddd7fc0-59cc-42ca-b52d-181e1eea4294': {  # Parts / Tubes
                    'full_name': 'Parts / Tubes',
                    'reverb_count': 94,
                    'category_id': '51',      # Guitars
                    'subcategory_id': '211',   # Parts & accessories
                    'sub_subcategory_id': '279', # Other
                    'sub_sub_subcategory_id': None
                },
                'ac571749-28c7-4eec-a1d9-09dca3cf3e5f': {  # Bass Guitars / 4-String
                    'full_name': 'Bass Guitars / 4-String',
                    'reverb_count': 112,
                    'category_id': '52',
                    'subcategory_id': '69',
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                '53a9c7d7-d73d-4e7f-905c-553503e50a90': {  # Bass Guitars
                    'full_name': 'Bass Guitars',
                    'reverb_count': 38,
                    'category_id': '52',
                    'subcategory_id': '69',
                    'sub_subcategory_id': None,
                    'sub_sub_subcategory_id': None
                },
                'd6322534-edf5-43dd-b1c0-99f0c28e3053': {  # Folk Instruments / Mandolin
                    'full_name': 'Folk Instruments / Mandolin',
                    'reverb_count': 9,
                    'category_id': '188',  # Stringed Instruments
                    'subcategory_id': '190',  # Mandolin & mandolin family
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },  
                'd002db05-ab63-4c79-999c-d49bbe8d7739': {  # Keyboards and Synths
                    'full_name': 'Keyboards and Synths',
                    'reverb_count': 21,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'e36bdc32-abba-45e2-948b-ce60153cbdd9': {  # Keyboards and Synths / Drum Machines
                    'full_name': 'Keyboards and Synths / Drum Machines',
                    'reverb_count': 6,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '148977b8-b308-4364-89fc-95859d2b3bc3': {  # Keyboards and Synths / Electric Pianos
                    'full_name': 'Keyboards and Synths / Electric Pianos',
                    'reverb_count': 4,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'fa8d98c5-3538-46d1-b74a-d48c5222f889': {  # Keyboards and Synths / MIDI Controllers
                    'full_name': 'Keyboards and Synths / MIDI Controllers',
                    'reverb_count': 1,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '0f4ee318-296a-4dfb-8bee-be46d7531b60': {  # Keyboards and Synths / MIDI Controllers / Keyboard MIDI Controllers
                    'full_name': 'Keyboards and Synths / MIDI Controllers / Keyboard MIDI Controllers',
                    'reverb_count': 4,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '10250c4e-e0db-47b4-aa25-767a8bdd54f0': {  # Keyboards and Synths / MIDI Controllers / Keytar MIDI Controllers
                    'full_name': 'Keyboards and Synths / MIDI Controllers / Keytar MIDI Controllers',
                    'reverb_count': 1,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'f4499585-f591-4401-9191-f7ba9fdeb02c': {  # Keyboards and Synths / Organs
                    'full_name': 'Keyboards and Synths / Organs',
                    'reverb_count': 8,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '5e3c7bdb-469a-4a22-bbb2-85ddf8bff3c9': {  # Keyboards and Synths / Samplers
                    'full_name': 'Keyboards and Synths / Samplers',
                    'reverb_count': 1,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'c577b406-a405-45ec-a8eb-56fbe628fa19': {  # Keyboards and Synths / Synths / Analog Synths
                    'full_name': 'Keyboards and Synths / Synths / Analog Synths',
                    'reverb_count': 26,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '75b1e4a3-dbb4-46c5-8386-fa18546e097a': {  # Keyboards and Synths / Synths / Digital Synths
                    'full_name': 'Keyboards and Synths / Synths / Digital Synths',
                    'reverb_count': 20,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                'd2688e49-3cca-4cf6-95d0-c105e8e5c3bd': {  # Keyboards and Synths / Synths / Keyboard Synths
                    'full_name': 'Keyboards and Synths / Synths / Keyboard Synths',
                    'reverb_count': 10,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '9854a2b4-5db3-4dfd-85f1-dcb444d5d7f6': {  # Keyboards and Synths / Synths / Rackmount Synths
                    'full_name': 'Keyboards and Synths / Synths / Rackmount Synths',
                    'reverb_count': 11,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },
                '4caba01d-fef3-4f67-9c2c-a5116d1faf0a': {  # Keyboards and Synths / Workstation Keyboards
                    'full_name': 'Keyboards and Synths / Workstation Keyboards',
                    'reverb_count': 3,
                    'category_id': '57',  # Pianos
                    'subcategory_id': '252',  # Synth & Keyboard
                    'sub_subcategory_id': None,  #
                    'sub_sub_subcategory_id': None  #
                },


            }
            

            # Look up mapping
            if reverb_uuid in mapping_table:
                print(f"✅ Mapped Reverb category '{reverb_full_name}' to V&R {mapping_table[reverb_uuid]}")
                return mapping_table[reverb_uuid]
            else:
                print(f"⚠️  No mapping found for Reverb UUID '{reverb_uuid}' ({reverb_full_name}), using default")
                return default_mapping
                
        except Exception as e:
            print(f"❌ Error parsing Reverb categories: {str(e)}")
            return default_mapping
    
    async def _get_reverb_images(self, listing_id: str) -> list:
        """Get images from Reverb API with size constraints"""
        if not self.reverb_client or not listing_id:
            return []
        
        try:
            listing_details = await self.reverb_client.get_listing(listing_id)
            
            if not listing_details or 'cloudinary_photos' not in listing_details:
                return []
            
            image_urls = []
            total_size_mb = 0
            MAX_TOTAL_SIZE_MB = 10  # V&R limit
            MAX_IMAGES = 20         # V&R limit
            
            for photo in listing_details['cloudinary_photos']:
                if 'preview_url' in photo:
                    image_url = photo['preview_url']
                    
                    # Check image file size
                    try:
                        image_size_mb = await self._check_image_size(image_url)
                        
                        # Skip if this image would exceed the total size limit
                        if total_size_mb + image_size_mb > MAX_TOTAL_SIZE_MB:
                            print(f"⚠️  Skipping image {len(image_urls) + 1}: would exceed 10MB limit (current: {total_size_mb:.1f}MB + {image_size_mb:.1f}MB)")
                            break
                        
                        image_urls.append(image_url)
                        total_size_mb += image_size_mb
                        print(f"✅ Image {len(image_urls)}: {image_size_mb:.1f}MB (total: {total_size_mb:.1f}MB)")
                        
                        # Stop at image or size limit
                        if len(image_urls) >= MAX_IMAGES:
                            print(f"📸 Reached {MAX_IMAGES} image limit")
                            break
                            
                    except Exception as e:
                        print(f"⚠️  Skipping image due to size check error: {str(e)}")
                        continue
            
            print(f"📊 Final selection: {len(image_urls)} images, {total_size_mb:.1f}MB total")
            return image_urls
            
        except Exception as e:
            print(f"❌ Error fetching images for {listing_id}: {str(e)}")
            return []

    async def _check_image_size(self, image_url: str) -> float:
        """Check image file size in MB without downloading the full file"""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(image_url) as response:
                    content_length = response.headers.get('content-length')
                    
                    if content_length:
                        size_bytes = int(content_length)
                        size_mb = size_bytes / (1024 * 1024)
                        return size_mb
                    else:
                        # Fallback: estimate based on image dimensions/quality
                        # Reverb images are typically 0.5-2MB each
                        return 1.0  # Conservative estimate
                        
        except Exception as e:
            print(f"⚠️  Could not check size for {image_url}: {str(e)}")
            return 1.0  # Conservative fallback
    
    def _parse_reverb_shipping_to_vr_profile(self, shipping_data: str) -> Dict[str, str]:
        """
        Parse Reverb shipping data and map to V&R shipping profile format
        
        Args:
            shipping_data: String containing Reverb shipping JSON data
            
        Returns:
            Dict with V&R shipping fee format
        """
        # Default fallback
        default_profile = {
            'shipping_europe_fee': '50',
            'shipping_usa_fee': '100', 
            'shipping_uk_fee': '45',
            'shipping_world_fee': '150'
        }
        
        if not shipping_data:
            return default_profile
        
        try:
            # Parse shipping JSON (handle both string and dict)
            if isinstance(shipping_data, str):
                import ast
                shipping = ast.literal_eval(shipping_data)
            else:
                shipping = shipping_data
                
            # Extract rates array
            rates = shipping.get('rates', [])
            if not rates:
                return default_profile
                
            # Parse rates by region code
            parsed_rates = {}
            for rate_info in rates:
                region_code = rate_info.get('region_code', '')
                rate_data = rate_info.get('rate', {})
                amount = rate_data.get('amount', '0')
                currency = rate_data.get('currency', 'GBP')
                
                # Convert to float for processing
                try:
                    amount_float = float(amount)
                except (ValueError, TypeError):
                    continue
                    
                # Map region codes to our system
                if region_code == 'GB':
                    parsed_rates['uk'] = amount_float
                elif region_code == 'US':
                    parsed_rates['usa'] = amount_float
                elif region_code in ['EUR_EU', 'EU', 'EUR']:
                    parsed_rates['europe'] = amount_float
                elif region_code == 'XX':  # Rest of World
                    parsed_rates['world'] = amount_float
                    
            # Build V&R profile with parsed rates
            vr_profile = {}
            
            # UK rate
            if 'uk' in parsed_rates:
                vr_profile['shipping_uk_fee'] = str(int(parsed_rates['uk']))
            else:
                vr_profile['shipping_uk_fee'] = default_profile['shipping_uk_fee']
                
            # USA rate  
            if 'usa' in parsed_rates:
                vr_profile['shipping_usa_fee'] = str(int(parsed_rates['usa']))
            else:
                vr_profile['shipping_usa_fee'] = default_profile['shipping_usa_fee']
                
            # Europe rate (try EUR_EU first, fallback to XX if no specific EU rate)
            if 'europe' in parsed_rates:
                vr_profile['shipping_europe_fee'] = str(int(parsed_rates['europe']))
            elif 'world' in parsed_rates:
                # Use world rate for Europe if no specific EU rate
                vr_profile['shipping_europe_fee'] = str(int(parsed_rates['world']))
            else:
                vr_profile['shipping_europe_fee'] = default_profile['shipping_europe_fee']
                
            # Rest of World rate
            if 'world' in parsed_rates:
                vr_profile['shipping_world_fee'] = str(int(parsed_rates['world']))
            else:
                vr_profile['shipping_world_fee'] = default_profile['shipping_world_fee']
                
            print(f"✅ Parsed shipping rates: UK=£{vr_profile['shipping_uk_fee']}, "
                f"US=£{vr_profile['shipping_usa_fee']}, "
                f"EU=£{vr_profile['shipping_europe_fee']}, "
                f"World=£{vr_profile['shipping_world_fee']}")
                
            return vr_profile
            
        except Exception as e:
            print(f"⚠️  Error parsing shipping data: {str(e)}")
            print("Using default shipping profile")
            return default_profile
    
    def _map_shipping_profile(self, category: str) -> Dict[str, str]:
        """Map category to shipping fees. Superseded by _parse_reverb_shipping_to_vr_profile"""
        shipping_profiles = {
            'Electric Guitars': {
                'shipping_europe_fee': '50',
                'shipping_usa_fee': '100',
                'shipping_uk_fee': '45',
                'shipping_world_fee': '150'
            },
            'Acoustic Guitars': {
                'shipping_europe_fee': '50',
                'shipping_usa_fee': '100',
                'shipping_uk_fee': '45',
                'shipping_world_fee': '150'
            },
            'Effects': {
                'shipping_europe_fee': '25',
                'shipping_usa_fee': '50',
                'shipping_uk_fee': '20',
                'shipping_world_fee': '75'
            }
        }
        
        return shipping_profiles.get(category, shipping_profiles['Electric Guitars'])
    
    def _save_to_csv(self, vr_data: List[Dict[str, Any]], output_csv: str):
        """Save transformed data to CSV file"""
        print(f"💾 Saving {len(vr_data)} rows to {output_csv}")
        
        with open(output_csv, 'w', newline='', encoding='utf-8') as file:
            if vr_data:
                fieldnames = vr_data[0].keys()
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(vr_data)
        
        print(f"✅ CSV saved: {output_csv}")

class VRCSVUploader:
    """Upload V&R listings using the VintageAndRareClient"""
    
    def __init__(self, username: str, password: str):
        self.client = VintageAndRareClient(username=username, password=password)
    
    async def process_csv_file(self, csv_file_path: str, test_mode: bool = True) -> dict:
        """Process CSV file and create V&R listings"""
        
        if not await self.client.authenticate():
            print("❌ Failed to authenticate with V&R")
            return {"error": "Authentication failed"}
        
        results = {
            "total": 0,
            "successful": 0,
            "failed": 0,
            "details": []
        }
        
        print(f"📁 Processing CSV file: {csv_file_path}")
        
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            
            for row_num, row in enumerate(reader, 1):
                results["total"] += 1
                
                try:
                    product_data = self._prepare_product_data(row)
                    
                    print(f"\n🔄 Processing row {row_num}: {product_data.get('brand')} {product_data.get('model')}")
                    
                    result = await self.client.create_listing_selenium(
                        product_data=product_data,
                        test_mode=test_mode,
                        from_scratch=True,
                        db_session=None
                    )
                    
                    if result.get("status") == "success":
                        results["successful"] += 1
                        print(f"✅ Success: {result.get('message')}")
                    else:
                        results["failed"] += 1
                        print(f"❌ Failed: {result.get('message')}")
                    
                    results["details"].append({
                        "row": row_num,
                        "sku": product_data.get("sku"),
                        "result": result
                    })
                    
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    results["failed"] += 1
                    error_msg = f"Error processing row {row_num}: {str(e)}"
                    print(f"❌ {error_msg}")
                    results["details"].append({
                        "row": row_num,
                        "sku": row.get("sku", "Unknown"),
                        "error": error_msg
                    })
        
        return results

    async def process_product_data_list(self, product_data_list: List[Dict[str, Any]], test_mode: bool = True) -> dict:
        """Process a list of product data dictionaries directly - ORIGINAL VERSION"""
        
        import time
        start_time = time.time()
        
        if not await self.client.authenticate():
            print("❌ Failed to authenticate with V&R")
            return {"error": "Authentication failed"}
        
        print(f"📁 Processing {len(product_data_list)} product records individually")
        
        # Your original timing structure
        results = {
            "total": len(product_data_list),
            "successful": 0,
            "failed": 0,
            "details": [],
            "timing": {
                "start_time": start_time,
                "items_processed": [],
                "total_duration": 0,
                "average_per_item": 0,
                "estimated_400_items": 0
            }
        }
        
        # Your original individual processing loop
        for row_num, product_data in enumerate(product_data_list, 1):
            item_start_time = time.time()
            
            try:
                print(f"\n🔄 Processing item {row_num}: {product_data.get('brand')} {product_data.get('model')}")
                
                result = await self.client.create_listing_selenium(
                    product_data=product_data,
                    test_mode=test_mode,
                    from_scratch=False,
                    db_session=None
                )
                
                item_end_time = time.time()
                item_duration = item_end_time - item_start_time
                
                # Your original timing structure
                results["timing"]["items_processed"].append({
                    "item": row_num,
                    "duration": item_duration,
                    "brand": product_data.get('brand'),
                    "model": product_data.get('model')
                })
                
                if result.get("status") == "success":
                    results["successful"] += 1
                    print(f"✅ Success: {result.get('message')} (took {item_duration:.1f}s)")
                else:
                    results["failed"] += 1
                    print(f"❌ Failed: {result.get('message')} (took {item_duration:.1f}s)")
                
                results["details"].append({
                    "row": row_num,
                    "sku": product_data.get("sku"),
                    "duration": item_duration,
                    "result": result
                })
                
                await asyncio.sleep(2)
                
            except Exception as e:
                item_end_time = time.time()
                item_duration = item_end_time - item_start_time
                
                results["failed"] += 1
                error_msg = f"Error processing item {row_num}: {str(e)}"
                print(f"❌ {error_msg} (took {item_duration:.1f}s)")
                results["details"].append({
                    "row": row_num,
                    "sku": product_data.get("sku", "Unknown"),
                    "duration": item_duration,
                    "error": error_msg
                })
        
        # Your original timing calculation
        end_time = time.time()
        total_duration = end_time - start_time
        
        results["timing"]["total_duration"] = total_duration
        if results["timing"]["items_processed"]:
            avg_duration = sum(item["duration"] for item in results["timing"]["items_processed"]) / len(results["timing"]["items_processed"])
            results["timing"]["average_per_item"] = avg_duration
            results["timing"]["estimated_400_items"] = avg_duration * 400
        
        # Your original timing summary
        print(f"\n⏱️  **TIMING ANALYSIS**")
        print(f"Total processing time: {total_duration:.1f} seconds ({total_duration/60:.1f} minutes)")
        if results["timing"]["average_per_item"]:
            print(f"Average per item: {results['timing']['average_per_item']:.1f} seconds")
            print(f"🎯 Estimated time for 400 items: {results['timing']['estimated_400_items']:.1f} seconds ({results['timing']['estimated_400_items']/60:.1f} minutes)")
        
        return results
    
    def _prepare_product_data(self, row: dict) -> dict:
        """Convert CSV row to product_data dict expected by client"""
        
        # Handle additional_images
        additional_images = row.get('additional_images', '')
        if additional_images:
            try:
                additional_images = json.loads(additional_images)
            except json.JSONDecodeError:
                additional_images = [additional_images] if additional_images else []
        else:
            additional_images = []
        
        # Convert year to int if present
        year = None
        if row.get('year'):
            try:
                year = int(row['year'])
            except (ValueError, TypeError):
                year = None
        
        # Convert price to float
        price = 0.0
        if row.get('price'):
            try:
                price = float(row['price'])
            except (ValueError, TypeError):
                price = 0.0
        
        product_data = {
            'sku': row.get('sku', ''),
            'brand': row.get('brand', ''),
            'model': row.get('model', ''),
            'price': price,
            'description': row.get('description', ''),
            'year': year,
            'finish': row.get('finish', ''),
            
            # ✅ FIX: Use the correct V&R category field names from your CSV
            'Category': row.get('Category', '51'),           # Default to Guitars if missing
            'SubCategory1': row.get('SubCategory1', '83'),   # Default to Electric solid body
            'SubCategory2': row.get('SubCategory2', ''),     
            'SubCategory3': row.get('SubCategory3', ''),     
            
            'primary_image': row.get('primary_image', ''),
            'additional_images': additional_images,
            'video_url': row.get('video_url', ''),
            'vr_show_vat': True,
            'vr_call_for_price': False,
            'vr_in_collective': False,
            'vr_in_inventory': True,
            'vr_in_reseller': False,
            'processing_time': '3',
            'time_unit': 'Days',
            'available_for_shipment': True,
            'local_pickup': False,
            'shipping_europe_fee': '50',
            'shipping_usa_fee': '100',
            'shipping_uk_fee': '75',
            'shipping_world_fee': '150'
        }
        
        return product_data

def main():
    parser = argparse.ArgumentParser(description='Create V&R listings from CSV')
    parser.add_argument('--csv-file', required=True, help='Path to CSV file')
    parser.add_argument('--test-mode', action='store_true', help='Test mode (fill form but don\'t submit)')
    parser.add_argument('--reverb-mode', action='store_true', help='Transform from Reverb CSV format')
    parser.add_argument('--output-csv', help='Output CSV file for transformed data (Reverb mode only)')
    parser.add_argument('--username', help='V&R username (or set in .env)')
    parser.add_argument('--password', help='V&R password (or set in .env)')
    
    args = parser.parse_args()
    
    # Get credentials
    username = args.username or os.environ.get('VINTAGE_AND_RARE_USERNAME')
    password = args.password or os.environ.get('VINTAGE_AND_RARE_PASSWORD')
    reverb_api_key = os.environ.get('REVERB_API_KEY')
    
    if not username or not password:
        print("❌ Error: V&R credentials required!")
        sys.exit(1)
    
    if args.reverb_mode and not reverb_api_key:
        print("❌ Error: Reverb API key required for --reverb-mode!")
        sys.exit(1)
    
    if not os.path.exists(args.csv_file):
        print(f"❌ Error: CSV file not found: {args.csv_file}")
        sys.exit(1)
    
    async def run():
        if args.reverb_mode:
            # Transform Reverb CSV
            transformer = ReverbToVRTransformer(reverb_api_key)
            vr_data = await transformer.transform_reverb_csv(args.csv_file, args.output_csv)
            
            if args.output_csv:
                # Just transform and save CSV - no listing creation
                print(f"✅ Transformation complete! Review {args.output_csv} before creating listings.")
                return
            else:
                # Transform and create listings directly
                uploader = VRCSVUploader(username, password)
                results = await uploader.process_product_data_list(vr_data, args.test_mode)
        else:
            # Regular V&R CSV processing
            uploader = VRCSVUploader(username, password)
            
            # Read CSV and convert to product_data_list
            product_data_list = []
            with open(args.csv_file, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    product_data = uploader._prepare_product_data(row)
                    product_data_list.append(product_data)
            
            # Use the new batch-capable method
            results = await uploader.process_product_data_list(product_data_list, args.test_mode)
        
        # Print summary
        print(f"\n📊 **SUMMARY**")
        print(f"Total items: {results['total']}")
        print(f"✅ Successful: {results['successful']}")
        print(f"❌ Failed: {results['failed']}")
        
        if results['failed'] > 0:
            print(f"\n❌ **FAILED ITEMS:**")
            for detail in results['details']:
                if 'error' in detail:
                    print(f"  Row {detail['row']} ({detail['sku']}): {detail['error']}")
    
    asyncio.run(run())

if __name__ == '__main__':
    main()