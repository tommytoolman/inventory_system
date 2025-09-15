#!/usr/bin/env python3
"""
Create eBay listings from CSV data.

Supports two modes:
1. Transform Reverb CSV → eBay CSV (for editing categories/prices)
2. Create eBay listings from CSV data

Usage Examples:

# Transform Reverb CSV to eBay CSV (for editing)
python scripts/ebay/create_ebay_listings_from_csv.py --reverb-csv reverb_live.csv --output-csv ebay_ready.csv

# Create listings from edited eBay CSV  
python scripts/ebay/create_ebay_listings_from_csv.py --ebay-csv ebay_ready.csv --create-listings --sandbox

# One-step: Reverb → eBay listings directly
python scripts/ebay/create_ebay_listings_from_csv.py --reverb-csv reverb_live.csv --create-listings --test-mode
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv()

from app.services.ebay.trading import EbayTradingLegacyAPI
from app.services.reverb.client import ReverbClient


class ReverbToEbayTransformer:
    """Transform Reverb CSV data to eBay listing format"""
    
    def __init__(self, reverb_api_key: Optional[str] = None):
        self.reverb_client = ReverbClient(reverb_api_key) if reverb_api_key else None
        
    def get_comprehensive_reverb_to_ebay_mapping(self):
        """Complete mapping of all Reverb category UUIDs to eBay categories"""

        return {
            
            'e57deb7a-382b-4e18-a008-67d4fbcb2879': {  # Electric Guitars / Solid Body (1,194)
                'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'
            },
            'dfd39027-d134-4353-b9e4-57dc6be791b9': {  # Electric Guitars (398)
                'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'
            },
            '6a63ac2e-f2a5-4064-b6ea-0393f42ee497': {  # Electric Guitars / Semi-Hollow (217)
                'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'
            },
            '5db35d7e-2b7e-4dcf-a73b-6a144c710956': {  # Electric Guitars / Hollow Body (162)
                'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'
            },
            '367e1d5d-1185-4a1e-b283-8ec860dc1d5f': {  # Electric Guitars / Archtop (58)
                'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'
            },
            '80d6ce96-487c-4ac1-ad10-d4bef6336fe6': {  # Electric Guitars / 12-String (20)
                'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'
            },
            'c86f64cf-43df-4430-a2bf-b4126d81c5bd': {  # Electric Guitars / Left-Handed (8)
                'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'
            },
            'ddd7553e-68d5-4005-a356-3f94202682a8': {  # Electric Guitars / Lap Steel (5)
                'CategoryID': '181220', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Lap & Pedal Steel Guitars (181220)'  # Special category for Lap Steel
            },
            '69edc7c9-a145-4e7d-bab2-26e9df982c57': {  # Electric Guitars / Tenor (1)
                'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'
            },
            '8f8b1f88-83f5-449c-8c93-b57cf3ba1fd7': {  # Electric Guitars / Baritone (1)
                'CategoryID': '33034', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Electric Guitars (33034)'
            },

  
            '630dc140-45e2-4371-b569-19405de321cc': {  # Acoustic Guitars / Dreadnought (140)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            '3ca3eb03-7eac-477d-b253-15ce603d2550': {  # Acoustic Guitars (84)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            'db34e833-b352-45b9-9976-4f674a7e6d8c': {  # Acoustic Guitars / OM and Auditorium (52)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            '09ea109a-5df1-4156-b00c-7456a3e5abf3': {  # Acoustic Guitars / Built-in Electronics (47)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            'c58c6c12-4b50-4568-90c9-e071ec8e6a26': {  # Acoustic Guitars / Jumbo (39)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            'a7f470d1-266d-4495-b4d6-998cc84b7474': {  # Acoustic Guitars / Classical (35)
                'CategoryID': '119544', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Classical (119544)'  # Special category for Classical
            },
            '18bdeae7-e834-42a8-aeee-0e8ae33f8709': {  # Acoustic Guitars / Concert (23)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            'be24976f-ab6e-42e1-a29b-275e5fbca68f': {  # Acoustic Guitars / Archtop (19)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            '8b531867-88ee-46c5-b6d1-40d2d6b9dc35': {  # Acoustic Guitars / Resonator (17)
                'CategoryID': '181219', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Resonators (181219)'  # Special category for Resonator
            },
            '15cedc86-0e56-4800-b3f0-0f99fab350cb': {  # Acoustic Guitars / Parlor (17)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            '14d6cc96-ed7b-4521-bc21-7713c61e9dc5': {  # Acoustic Guitars / 12-String (13)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            '090748e6-9ca8-4083-896b-d59e0aa42582': {  # Acoustic Guitars / Mini/Travel (2)
                'CategoryID': '159948', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Travel Guitars (159948)'
            },
            'af33fcd5-f10a-407d-a39d-92765a7d4796': {  # Acoustic Guitars / Left-Handed (1)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },
            'd63135ba-55a8-4742-9891-a01d91538d96': {  # Acoustic Guitars / Baritone (1)
                'CategoryID': '33021', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Acoustic Guitars (33021)'
            },

            # BASS GUITARS (213 items total)
            'ac571749-28c7-4eec-a1d9-09dca3cf3e5f': {  # Bass Guitars / 4-String (112)
                'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858)  Bass Guitars (4713)'
            },
            '53a9c7d7-d73d-4e7f-905c-553503e50a90': {  # Bass Guitars (39)
                'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858)  Bass Guitars (4713)'
            },
            '07276aa7-6f18-4cae-a691-e6043b002fa4': {  # Bass Guitars / Short Scale (21)
                'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858)  Bass Guitars (4713)'
            },
            '3178be7d-f1cd-4da5-a606-bf3c1b8e834d': {  # Bass Guitars / 5-String or More (9)
                'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858)  Bass Guitars (4713)'
            },
            '0cd005a7-90ce-4f51-8e3c-b7acc4fa82f0': {  # Bass Guitars / Left-Handed (7)
                'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858)  Bass Guitars (4713)'
            },
            'a69d9614-7635-45f4-8fd5-4931ce756655': {  # Bass Guitars / Active Electronics (4)
                'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858)  Bass Guitars (4713)'
            },
            '5b9e2d05-0797-4c53-a653-390516aef1e9': {  # Bass Guitars / Fretless (2)
                'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Bass Guitars (4713)'
            },
            'bd0f2bd8-714b-4d19-ad87-05c5695a3b02': {  # Bass Guitars / Acoustic Bass Guitars (2)
                'CategoryID': '4713', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Bass Guitars (4713)'
            },



            '19d53222-297e-410c-ba4f-b48678e917f9': {  # Amps / Guitar Amps / Guitar Heads (231)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            '09055aa7-ed49-459d-9452-aa959f288dc2': {  # Amps (223)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            '10335451-31e5-418a-8ed8-f48cd738f17d': {  # Amps / Guitar Amps / Guitar Combos (218)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            'f1b3d127-4158-43c3-934b-e402adc3d6ca': {  # Amps / Guitar Amps / Guitar Cabinets (61)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            '66d136cb-02f2-4d04-b617-9215e972cc29': {  # Amps / Guitar Amps / Guitar Amp Stacks (10)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            'edd6e048-a378-4f6f-b2b5-dd46016c6118': {  # Amps / Small Amps (8)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            '4ca4f473-567f-46b0-8b66-9936a1179cd6': {  # Amps / Boutique Amps (7)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            '0338462f-285a-4273-afde-47c4fc752e3f': {  # Amps / Guitar Amps / Guitar Modeling Amps (3)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            '4069c185-c9a4-4354-b09f-31e83fbde2f1': {  # Amps / Amp Attenuators (3)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            'b6722b4b-4a2b-4d8f-82e9-0eacd20841aa': {  # Amps / Guitar Amps / Guitar Preamps (2)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },

            '892aa8b2-a209-49db-8ad2-eed758025a9d': {  # Amps / Bass Amps / Bass Heads (18)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            '6c664a95-048a-4795-b0ad-c7c03d9eee4c': {  # Amps / Bass Amps / Bass Cabinets (5)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },
            '052c7288-b2e0-42d2-8927-2c9176ef1699': {  # Amps / Bass Amps / Bass Combos (4)
                'CategoryID': '38072', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Guitar Amplifiers (38072)'
            },


            # EFFECTS AND PEDALS (390 items total) - Using 180014 (Pro Audio Equipment)
            'fa10f97c-dd98-4a8f-933b-8cb55eb653dd': {  # Effects and Pedals (138)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals (226699)'
            },
            '305e09a1-f9cb-4171-8a70-6428ad1b55a8': {  # Effects and Pedals / Fuzz (114)
                'CategoryID': '41418', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Fuzz (41418)'
            },
            '9bee8b39-c5f1-4fa7-90af-38740fc21a73': {  # Effects and Pedals / Overdrive and Boost (93)
                'CategoryID': '41416', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Distortion & Overdrive (41416)'
            },
            '3b09f948-3462-4ac2-93b3-59dd66da787e': {  # Effects and Pedals / Delay (39)
                'CategoryID': '41415', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Delay, Echo & Reverb (41415)'
            },
            '1738a9ae-6485-46c2-8ead-0807bb2e20e9': {  # Effects and Pedals / Reverb (19)
                'CategoryID': '41415', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Delay, Echo & Reverb (41415)'
            },
            '732e30f0-21cf-4960-a3d4-bb90c68081db': {  # Effects and Pedals / Distortion (18)
                'CategoryID': '41416', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Distortion & Overdrive (41416)'
            },    
            'a92165b2-2281-4dc2-850f-2789f513ec10': {  # Effects and Pedals / Wahs and Filters (18)
                'CategoryID': '41422', 'full_name':  'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Wah & Volume (41422)'
            },
            '2d6093b4-6b33-474e-b07c-25f6657d7956': {  # Effects and Pedals / Multi-Effect Unit (13)
                'CategoryID': '41419', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Multi-Effects (41419)'
            },
            '66fd5c3b-3227-4182-9337-d0e4893be9a2': {  # Effects and Pedals / Pedalboards and Power Supplies (8)
                'CategoryID': '101975', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Power Supplies (101975)'
            },
            '6bd92034-d59c-4d78-a6c1-1e8a3c31b31e': {  # Effects and Pedals / Controllers, Volume and Expression (8)
                'CategoryID': '41422', 'full_name':  'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Wah & Volume (41422)'
            },
            '86d377ed-c038-4353-a391-f592ebd6d921': {  # Effects and Pedals / Compression and Sustain (7)
                'CategoryID': '41414', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Compressors & Sustainers (41414)'
            },
            '8dab3e10-a7f8-444b-aa9d-ccdab4fe66c6': {  # Effects and Pedals / Octave and Pitch (7)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals" (22669)'
            },
            '15800d29-53a1-446e-8560-7a74a6d8d962': {  # Effects and Pedals / Chorus and Vibrato (7)
                'CategoryID': '41413', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Chorus (41413)'
            },
            '75e55b59-f57b-4e39-87b1-fcda4c1ed562': {  # Effects and Pedals / Phase Shifters (7)
                'CategoryID': '41420', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Phasers & Shifters (41420)'
            },
            '66170426-1b4d-4361-8002-3282f4907217': {  # Effects and Pedals / Loop Pedals and Samplers (7)
                'CategoryID': '101974', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Loopers & Samplers (101974)'
            },
            'ec612b9c-6227-4249-9010-b85b6b0eb5b0': {  # Effects and Pedals / EQ (7)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals" (22669)'
            },
            'fc775402-66a5-4248-8e71-fd9be6b2214a': {  # Effects and Pedals / Amp Simulators (4)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals" (22669)'
            },
            'b753bcd4-2cc5-4ea1-8f01-c8b034012372': {  # Effects and Pedals / Flanger (4)
                'CategoryID': '41417', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Flangers (41417)'
            },
            '69a7e38f-0ce8-42ea-a0f6-8a30b7f6886e': {  # Effects and Pedals / Tuning Pedals (3)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals" (22669)'
            },
            'e5553727-8786-4932-8761-dab396640ff0': {  # Effects and Pedals / Vocal (3)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals" (22669)'
            },
            'c6602a28-e2e7-4e70-abeb-0fa38b320be6': {  # Effects and Pedals / Bass Pedals (3)
                'CategoryID': '41411', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Bass (41411)'
            },
            '4d45f512-4dd5-4dae-95b7-7eb400ce406b': {  # Effects and Pedals / Preamps (3)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals" (22669)'
            },
            '38f7f86b-5d7a-499a-9bdc-c3198395dfa6': {  # Effects and Pedals / Tremolo (2)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals" (22669)'
            },
            '8745626e-3273-4f9d-b7a1-ca5b202a8e6e': {  # Effects and Pedals / Noise Reduction and Gates (1)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals" (22669)'
            },
            '7e6b6d7c-cdd5-4a42-bceb-6ea12899137b': {  # Effects and Pedals / Guitar Synths (1)
                'CategoryID': '22669', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Other Guitar Effects Pedals" (22669)'
            },


            # KEYBOARDS AND SYNTHS (96 items total) - Using 38088 (Electronic Keyboards)
            'c577b406-a405-45ec-a8eb-56fbe628fa19': {  # Keyboards and Synths / Synths / Analog Synths (26)
                'CategoryID': '38088', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Analog Synths'
            },
            'd002db05-ab63-4c79-999c-d49bbe8d7739': {  # Keyboards and Synths (21)
                'CategoryID': '38088', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Electronic Keyboards (38088)'
            },
            '75b1e4a3-dbb4-46c5-8386-fa18546e097a': {  # Keyboards and Synths / Synths / Digital Synths (20)
                'CategoryID': '38071', 'full_name': 'Keyboards and Synths / Synths / Digital Synths'
            },
            '9854a2b4-5db3-4dfd-85f1-dcb444d5d7f6': {  # Keyboards and Synths / Synths / Rackmount Synths (11)
                'CategoryID': '38071', 'full_name': 'Keyboards and Synths / Synths / Rackmount Synths'
            },
            'd2688e49-3cca-4cf6-95d0-c105e8e5c3bd': {  # Keyboards and Synths / Synths / Keyboard Synths (10)
                'CategoryID': '38071', 'full_name': 'Keyboards and Synths / Synths / Keyboard Synths'
            },
            'f4499585-f591-4401-9191-f7ba9fdeb02c': {  # Keyboards and Synths / Organs (8)
                'CategoryID': 'python', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Electronic Keyboards (38088)'
            },
            'e36bdc32-abba-45e2-948b-ce60153cbdd9': {  # Keyboards and Synths / Drum Machines (6)
                'CategoryID': '181174', 'full_name': 'Keyboards and Synths / Drum Machines'
            },
            '0f4ee318-296a-4dfb-8bee-be46d7531b60': {  # Keyboards and Synths / MIDI Controllers / Keyboard MIDI Controllers (4)
                'CategoryID': '178896', 'full_name': 'Keyboards and Synths / MIDI Controllers / Keyboard MIDI Controllers'
            },
            '148977b8-b308-4364-89fc-95859d2b3bc3': {  # Keyboards and Synths / Electric Pianos (4)
                'CategoryID': '85860', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Digital Pianos (85860)'
            },
            '4caba01d-fef3-4f67-9c2c-a5116d1faf0a': {  # Keyboards and Synths / Workstation Keyboards (3)
                'CategoryID': '38088', 'full_name': 'Keyboards and Synths / Workstation Keyboards'
            },
            '5e3c7bdb-469a-4a22-bbb2-85ddf8bff3c9': {  # Keyboards and Synths / Samplers (1)
                'CategoryID': '38088', 'full_name': 'Keyboards and Synths / Samplers'
            },
            '10250c4e-e0db-47b4-aa25-767a8bdd54f0': {  # Keyboards and Synths / MIDI Controllers / Keytar MIDI Controllers (1)
                'CategoryID': '38088', 'full_name': 'Keyboards and Synths / MIDI Controllers / Keytar MIDI Controllers'
            },
            'fa8d98c5-3538-46d1-b74a-d48c5222f889': {  # Keyboards and Synths / MIDI Controllers (1)
                'CategoryID': '38088', 'full_name': 'Keyboards and Synths / MIDI Controllers'
            },
            '206ee409-a7e6-4c15-8ef9-eee27139a5fc': {  # Keyboards and Synths / Keyboard and Synth Accessories / Keyboard Sustain Pedals (1)
                'CategoryID': '38088', 'full_name': 'Keyboards and Synths / Keyboard and Synth Accessories / Keyboard Sustain Pedals'
            },

            # PRO AUDIO (111 items total) - Using 180014 (Pro Audio Equipment)
            '0f2bbf76-3225-44d5-8a5b-c540cc1fd058': {  # Pro Audio / Microphones (58)
                'CategoryID': '29946', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Microphones & Wireless Systems (29946)'
            },
            'b021203f-1ed8-476c-a8fc-32d4e3b0ef9e': {  # Pro Audio (25)
                'CategoryID': '3278', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Other Pro Audio Equipment (3278)'
            },
            '36a0faca-93b7-4ad1-ab09-02629ec1e900': {  # Pro Audio / Recording (8)
                'CategoryID': '15199', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Recorders (15199)'
            },
            '10187eaa-7746-4978-9f44-7670e95a40da': {  # Pro Audio / Outboard Gear / Gates and Expanders (4)
                'CategoryID': '3278', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Other Pro Audio Equipment (3278)'
            },
            '8865016e-edbb-4ee7-a704-6ea0652d6bf4': {  # Pro Audio / Outboard Gear / Compressors and Limiters (3)
                'CategoryID': '177028', 'full_name':  'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Studio/Live Equipment Packages (177028)'
            },
            'c63d7668-c0d1-421d-97ef-587959f7282c': {  # Pro Audio / Mixers (3)
                'CategoryID': '177028', 'full_name':  'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Studio/Live Equipment Packages (177028)'
            },
            'd02b5dfa-38f1-4eec-9ebb-1eba6b108c53': {  # Pro Audio / Outboard Gear / Delay (2)
                'CategoryID': '177028', 'full_name':  'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Studio/Live Equipment Packages (177028)'
            },
            '0bbe9f3e-7a6e-4654-862f-96dd6136c9b3': {  # Pro Audio / DI Boxes (2)
                'CategoryID': '3278', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Other Pro Audio Equipment (3278)'
            },
            '7d314252-3de4-494c-9e49-27edc5ef6482': {  # Pro Audio / Speakers / Passive Speakers (2)
                'CategoryID': '3278', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Other Pro Audio Equipment (3278)'
            },
            '1db56ead-c657-4a26-ac8b-2e441d5c6e76': {  # Pro Audio / Outboard Gear / Equalizers (2)
                'CategoryID': '177028', 'full_name':  'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Studio/Live Equipment Packages (177028)'
            },
            'd3c6e84c-5bb2-41a3-9a60-0e8b88edc515': {  # Pro Audio / Outboard Gear / Microphone Preamps (2)
                'CategoryID': '29946', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Microphones & Wireless Systems (29946)'
            },
            'f4104d52-a9ee-4256-8753-15bf5ff1b71d': {  # Pro Audio / Speakers / Studio Monitors (1)
                'CategoryID': '177028', 'full_name':  'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Studio/Live Equipment Packages (177028)'
            },
            '101acc1f-ae38-4e27-9fde-1948498618aa': {  # Pro Audio / Outboard Gear / Multi-Effect (1)
                'CategoryID': '177028', 'full_name':  'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Studio/Live Equipment Packages (177028)'
            },
            'a509367a-6d89-4692-9e28-796357b009a7': {  # Pro Audio / Powered Mixers (1)
                'CategoryID': '159955', 'full_name':  'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Audio Power Conditioners (159955)'
            },
            '760ffd05-b7e1-4dc9-a293-5e3f1da33483': {  # Pro Audio / Portable Recorders (1)
                'CategoryID': '15199', 'full_name': 'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Recorders (15199)'
            },
            'af9cb76e-0fd3-43fe-9f2d-6f53a4e60371': {  # Pro Audio / Outboard Gear / Reverb (1)
                'CategoryID': '177028', 'full_name':  'Musical Instruments & Gear (619) / Pro Audio Equipment (180014) / Studio/Live Equipment Packages (177028)'
            },

            # DRUMS AND PERCUSSION (24 items total) - Using 16210 (Drums & Percussion)
            'b3cb9f8e-4cb6-4325-8215-1efcd9999daf': {  # Drums and Percussion (11)
                'CategoryID': '181227', 'full_name': 'Musical Instruments & Gear (619) / Percussion (180012) / Drums (181227)'
            },
            'b905874b-ecdd-43f0-99e5-5c4d6857ff99': {  # Drums and Percussion / Acoustic Drums / Full Acoustic Kits (5)
                'CategoryID': '38097', 'full_name': 'Musical Instruments & Gear (619) / Percussion (180012) / Sets & Kits (38097)'
            },
            '4fe438c3-8312-4c52-b8d6-9f502174cbe7': {  # Drums and Percussion / Parts and Accessories / Pedals (3)
                'CategoryID': '41452', 'full_name': 'Musical Instruments & Gear (619) / Parts (181254) / Pedals (41452)'
            },
            'caa94b2b-d52b-499c-b4bb-412568747078': {  # Drums and Percussion / Electronic Drums / Modules (2)
                'CategoryID': '38069', 'full_name': 'Musical Instruments & Gear (619) / Percussion (180012) / Electronic Drums (38069)'
            },
            '93d86ecd-27e6-452c-9a43-16a0c5d547ab': {  # Drums and Percussion / Cymbals / Other (Splash, China, etc) (2)
                'CategoryID': '41441', 'full_name': 'Musical Instruments & Gear (619) / Percussion (180012) / Cymbals (41441)'
            },
            'ecb1bc0c-1f79-40a9-9429-0696defa7b19': {  # Drums and Percussion / Marching Percussion / Marching Cymbals (1)
                'CategoryID': '41441', 'full_name': 'Musical Instruments & Gear (619) / Percussion (180012) / Cymbals (41441)'
            },
            '7a28aae1-de39-4c8b-ae37-b621fc46a5e9': {  # Drums and Percussion / Parts and Accessories / Heads (1)
                'CategoryID': '41450', 'full_name': 'Musical Instruments & Gear (619) / Parts (181254) / Heads (41450)'
            },
            '8f8e21ff-aa89-4f79-943c-dfaab20251f4': {  # Drums and Percussion / Pad Controllers (1)
                'CategoryID': '38069', 'full_name': 'Musical Instruments & Gear (619) / Percussion (180012) / Electronic Drums (38069)'
            },

            # PARTS AND ACCESSORIES (175 items total) - Using 180014 (Pro Audio Equipment)
            'eb1827f3-c02c-46ff-aea9-7983e2aae1b4': {  # Parts / Amp Parts (94)
                'CategoryID': '183389', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Amplifier Parts (183389)'
            },
            '6a00326e-3acc-4a53-be16-389d7b6a228c': {  # Parts / Replacement Speakers (12)
                'CategoryID': '183389', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Amplifier Parts (183389)'
            },
            '1f99c852-9d20-4fd3-a903-91da9c805a5e': {  # Parts (11)
                'CategoryID': '46678', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Other Guitar & Bass Parts (46678)'
            },
            '7ddd7fc0-59cc-42ca-b52d-181e1eea4294': {  # Parts / Tubes (9)
                'CategoryID': '183389', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Amplifier Parts (183389)'
            },
            'ed9714d2-2b98-4e1e-b85e-eb2f948a8985': {  # Parts / Guitar Pickups (7)
                'CategoryID': '22670', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Pickups (22670)'
            },
            'ae1822ce-4a55-42b0-a094-b9be6b27fc62': {  # Parts / Guitar Parts / Bridges (5)
                'CategoryID': '41407', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Bridges (41407)'
            },
            '2015ef45-0261-4fb5-a5ca-f33e76e5f8da': {  # Parts / Pickguards (4)
                'CategoryID': '41424', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Pickguards (41424)'
            },
            '92aef906-a2fd-47be-85f5-8595cc61bedb': {  # Parts / Guitar Bodies (4)
                'CategoryID': '41406', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Bodies (41406)'
            },
            'f87eeadc-82f0-4e67-97df-8ac363f28e1a': {  # Parts / Knobs (4)
                'CategoryID': '47076', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Knobs, Jacks & Switches (47076)'
            },
            '3852c31e-5019-4cd6-8c60-ba5fd397cf43': {  # Parts / Bass Guitar Parts (3)
                'CategoryID': '46678', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Other Guitar & Bass Parts (46678)'
            },
            '33095a65-5662-414a-b86d-0e874911da16': {  # Parts / Guitar Parts / Tailpieces (3)
                'CategoryID': '46678', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Other Guitar & Bass Parts (46678)'
            },
            '3b1bc5f2-e783-4a53-b21c-61d54bff9837': {  # Parts / Tuning Heads (1)
                'CategoryID': '41434', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Tuning Pegs (41434)'
            },
            'c33e4de7-7ec0-4de9-912c-98a4dcb268c8': {  # Parts / Guitar Parts / Necks (1)
                'CategoryID': '41423', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Necks (41423)'
            },
            '9614b33f-20dc-4381-9d16-aa1c086f0e7e': {  # Parts / Pedal Parts (1)
                'CategoryID': '46678', 'full_name': 'Musical Instruments & Gear (619) / Guitars & Basses (3858) / Parts & Accessories (180009) / Guitar & Bass Parts (181223) / Other Guitar & Bass Parts (46678)'
            },
            
            
            # DJ AND LIGHTING GEAR (2 items) - Using 180014 (Pro Audio Equipment)
            'f8c37b8b-a8c6-4967-a2a4-7d50717a52ab': {  # DJ and Lighting Gear / Turntables (1)
                'CategoryID': '48460', 'full_name': 'Musical Instruments & Gear (619) / DJ Equipment (48458) / DJ Turntables (48460)'
            },
            '58d889f7-0aa1-4689-a9d3-da16dd225e8d': {  # DJ and Lighting Gear (1)
                'CategoryID': '177024', 'full_name': 'Musical Instruments & Gear (619) / Stage Lighting & Effects (12922) / DJ Lighting: Systems & Kits (177024)'
            },

            # HOME AUDIO (3 items) - Using 14324 (Home Audio)
            '010855a4-d387-405f-929d-ec22667abadc': {  # Home Audio / Tape Decks (2)
                'CategoryID': '48645', 'full_name': 'Consumer Electronics (293) / TV, Video & Home Audio (32852) / Home Audio (184973) / Home Audio Components (14969) / Cassette Tape Decks (48645)'
            },
            'b7c14414-a2fb-4345-bd3d-887ce076769c': {  # Home Audio / Amplifiers (1)
                'CategoryID': '14970', 'full_name': 'Consumer Electronics (293) / TV, Video & Home Audio (32852) / Home Audio (184973) / Home Audio (184973) / Receivers & Amplifiers (184974) / Amplifiers & Preamps (14970)'
            },


            # ACCESSORIES (155 items total) - Using 180014 (Pro Audio Equipment)
            '7681b711-435c-4923-bdc3-65076d15d78c': {  # Accessories / Books and DVDs (54)
                'CategoryID': '180014', 'full_name': 'Accessories / Books and DVDs'
            },
            '62835d2e-ac92-41fc-9b8d-4aba8c1c25d5': {  # Accessories (42)
                'CategoryID': '180014', 'full_name': 'Accessories'
            },
            'b1f4ce46-26e5-4f27-8b8a-66bd0f41a8eb': {  # Accessories / Cases and Gig Bags / Guitar Cases (18)
                'CategoryID': '180014', 'full_name': 'Accessories / Cases and Gig Bags / Guitar Cases'
            },
            '5cb132e1-1a42-42f4-bcd1-cf17405e7aff': {  # Accessories / Case Candy (11)
                'CategoryID': '180014', 'full_name': 'Accessories / Case Candy'
            },
            '22af0079-d5e7-48d1-9e5c-108105a2156c': {  # Accessories / Merchandise (6)
                'CategoryID': '180014', 'full_name': 'Accessories / Merchandise'
            },
            '1b357626-300e-47dd-85b0-bf657bca1a96': {  # Accessories / Straps (3)
                'CategoryID': '180014', 'full_name': 'Accessories / Straps'
            },
            'aff19d6a-ad5e-4b3b-b21c-8aa71ae834c6': {  # Accessories / Tuners (3)
                'CategoryID': '180014', 'full_name': 'Accessories / Tuners'
            },
            '5004a624-03c4-436b-81bf-78a108eb595d': {  # Accessories / Headphones (2)
                'CategoryID': '14985', 'full_name': 'Accessories / Headphones'
            },
            '516cfd7e-e745-44cf-bb72-053b3edcddaf': {  # Accessories / Cables (2)
                'CategoryID': '69963', 'full_name': 'Accessories / Cables'
            },
            '98a45e2d-2cc2-4b17-b695-a5d198c8f6d3': {  # Accessories / Picks (2)
                'CategoryID': '104408   ', 'full_name': 'Accessories / Picks'
            },
            'cdadd9b5-9d6d-4193-b0ee-b94d9ffd02ec': {  # Accessories / Amp Covers (2)
                'CategoryID': '180014', 'full_name': 'Accessories / Amp Covers'
            },
            'f5b5d030-51db-0134-7b64-2cbc3295deb9': {  # Accessories / Slides (1)
                'CategoryID': '180014', 'full_name': 'Accessories / Slides'
            },
            '4ca6d5e9-f00f-468d-bcae-8c7497537281': {  # Accessories / Tools (1)
                'CategoryID': '180014', 'full_name': 'Accessories / Tools'
            },
            'bb1ca93f-5dcc-48ec-adad-77d22f61b588': {  # Accessories / Stands (1)
                'CategoryID': '180014', 'full_name': 'Accessories / Stands'
            },

            # FOLK INSTRUMENTS (12 items total) - Using 16228 (Folk & World Instruments)
            'd6322534-edf5-43dd-b1c0-99f0c28e3053': {  # Folk Instruments / Mandolins (9)
                'CategoryID': '10179', 'full_name': 'Musical Instruments & Gear (619) / String (180016) / Folk & World (181282) / Mandolins (10179)'
            },
            'fb60628c-be4b-4be2-9c0f-bc5d31e3996c': {  # Folk Instruments (1)
                'CategoryID': '623', 'full_name': 'Musical Instruments & Gear (619) / / String (180016) / Other String Instruments (623)'
            },
            'e70f504b-eee7-4b71-89bc-eb925e802b3d': {  # Folk Instruments / Ukuleles (1)
                'CategoryID': '16224', 'full_name': 'Musical Instruments & Gear (619) / String (180016) / Folk & World (181282) / Ukuleles (16224)'
            },
            '45ba2a33-add3-4f9d-a2d4-842fa663924f': {  # Folk Instruments / Banjos (1)
                'CategoryID': '10177', 'full_name': 'Musical Instruments & Gear (619) / String (180016) / Folk & World (181282) / Banjos (10177)'
            },

            # BAND AND ORCHESTRA (1 item) - Using 16224 (Wind Instruments)
            '5c89d4ef-7652-4f89-b766-bb257e746099': {  # Band and Orchestra / Woodwind / Saxophones (1)
                'CategoryID': '16231', 'full_name': 'Musical Instruments & Gear (619) / Wind & Woodwind (10181) / Other Wind & Woodwind (624) / Band & Orchestral (181267) / Saxophones (16231)'
            },

            # Default fallback
            'default': {
                'CategoryID': '33034',  # Electric Guitars as default
                'full_name': 'Default - Electric Guitars'
            }
        }
        
        # eBay category mapping for common Reverb categories
        # self.category_mapping = {
        #     # Electric Guitars
        #     'Electric Guitars': {'CategoryID': '33034', 'Brand': 'required'},
        #     'Electric Guitars / Solid Body': {'CategoryID': '33034', 'Brand': 'required'},
        #     'Electric Guitars / Semi-Hollow': {'CategoryID': '33035', 'Brand': 'required'},
        #     'Electric Guitars / Hollow Body': {'CategoryID': '33036', 'Brand': 'required'},
        #     'Electric Guitars / Archtop': {'CategoryID': '33036', 'Brand': 'required'},
        #     'Electric Guitars / Lap Steel': {'CategoryID': '33037', 'Brand': 'required'},
            
        #     # Acoustic Guitars  
        #     'Acoustic Guitars': {'CategoryID': '33038', 'Brand': 'required'},
        #     'Acoustic Guitars / Dreadnought': {'CategoryID': '33038', 'Brand': 'required'},
        #     'Acoustic Guitars / Classical': {'CategoryID': '33039', 'Brand': 'required'},
        #     'Acoustic Guitars / Jumbo': {'CategoryID': '33038', 'Brand': 'required'},
        #     'Acoustic Guitars / OM and Auditorium': {'CategoryID': '33038', 'Brand': 'required'},
        #     'Acoustic Guitars / Concert': {'CategoryID': '33038', 'Brand': 'required'},
        #     'Acoustic Guitars / Resonator': {'CategoryID': '33040', 'Brand': 'required'},
        #     'Acoustic Guitars / 12-String': {'CategoryID': '33041', 'Brand': 'required'},
        #     'Acoustic Guitars / Archtop': {'CategoryID': '33042', 'Brand': 'required'},
            
        #     # Bass Guitars
        #     'Bass Guitars': {'CategoryID': '4713', 'Brand': 'required'},
        #     'Bass Guitars / 4-String': {'CategoryID': '4713', 'Brand': 'required'},
        #     'Bass Guitars / 5-String': {'CategoryID': '4713', 'Brand': 'required'},
        #     'Bass Guitars / 6-String': {'CategoryID': '4713', 'Brand': 'required'},
        #     'Bass Guitars / Acoustic Bass': {'CategoryID': '4714', 'Brand': 'required'},
            
        #     # Effects and Pedals
        #     'Effects and Pedals': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Distortion': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Overdrive and Boost': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Delay': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Reverb': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Fuzz': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Chorus and Vibrato': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Compression and Sustain': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Controllers, Volume and Expression': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / EQ': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Flanger': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Guitar Synths': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Loop Pedals and Samplers': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Multi-Effect Unit': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Noise Reduction and Gates': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Octave and Pitch': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Pedalboards and Power Supplies': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Phase Shifters': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Preamps': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Tremolo': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Tuning Pedals': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Vocal': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Wahs and Filters': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Amp Simulators': {'CategoryID': '41428', 'Brand': 'required'},
        #     'Effects and Pedals / Bass Pedals': {'CategoryID': '41428', 'Brand': 'required'},
            
        #     # Amps
        #     'Amps': {'CategoryID': '38076', 'Brand': 'required'},
        #     'Amps / Guitar Amps / Guitar Combos': {'CategoryID': '38076', 'Brand': 'required'},
        #     'Amps / Guitar Amps / Guitar Heads': {'CategoryID': '38077', 'Brand': 'required'},
        #     'Amps / Guitar Amps / Guitar Amp Stacks': {'CategoryID': '38078', 'Brand': 'required'},
        #     'Amps / Bass Amps / Bass Heads': {'CategoryID': '38079', 'Brand': 'required'},
        #     'Amps / Bass Amps / Bass Combos': {'CategoryID': '38080', 'Brand': 'required'},
        #     'Amps / Small Amps': {'CategoryID': '38076', 'Brand': 'required'},
            
        #     # Keyboards and Synths
        #     'Keyboards and Synths': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Keyboard and Synth Accessories / Keyboard Sustain Pedals': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Drum Machines': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Electric Pianos': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / MIDI Controllers': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / MIDI Controllers / Keyboard MIDI Controllers': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / MIDI Controllers / Keytar MIDI Controllers': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Organs': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Samplers': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Synths / Analog Synths': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Synths / Digital Synths': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Synths / Keyboard Synths': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Synths / Rackmount Synths': {'CategoryID': '39619', 'Brand': 'required'},
        #     'Keyboards and Synths / Workstation Keyboards': {'CategoryID': '39619', 'Brand': 'required'},
            
        #     # Drums and Percussion
        #     'Drums and Percussion / Marching Percussion / Marching Cymbals': {'CategoryID': '16210', 'Brand': 'required'},
        #     'Drums and Percussion / Parts and Accessories / Heads': {'CategoryID': '16210', 'Brand': 'required'},
            
        #     # Parts and Accessories
        #     'Parts / Amp Parts': {'CategoryID': '3858', 'Brand': 'required'},
        #     'Parts / Tubes': {'CategoryID': '3858', 'Brand': 'required'},
            
        #     # Accessories
        #     'Accessories': {'CategoryID': '3858', 'Brand': 'required'},
        #     'Accessories / Case Candy': {'CategoryID': '3858', 'Brand': 'required'},
        #     'Accessories / Cables': {'CategoryID': '3858', 'Brand': 'required'},
        #     'Accessories / Headphones': {'CategoryID': '3858', 'Brand': 'required'},
            
        #     # Pro Audio
        #     'Pro Audio / Microphones': {'CategoryID': '48446', 'Brand': 'required'},
        #     'Pro Audio / Mixers': {'CategoryID': '48446', 'Brand': 'required'},
        #     'Pro Audio / Recording': {'CategoryID': '48446', 'Brand': 'required'},
        #     'Pro Audio / Outboard Gear / Gates and Expanders': {'CategoryID': '48446', 'Brand': 'required'},
        #     'Pro Audio / Outboard Gear / Compressors and Limiters': {'CategoryID': '48446', 'Brand': 'required'},
            
        #     # Folk Instruments
        #     'Folk Instruments / Mandolin': {'CategoryID': '16228', 'Brand': 'required'},
            
        #     # Home Audio
        #     'Home Audio / Tape Decks': {'CategoryID': '14324', 'Brand': 'required'},
            
        #     # Default fallback
        #     'Other': {'CategoryID': '33034', 'Brand': 'required'}
        # }


    async def transform_reverb_csv(self, csv_file_path: str, output_csv_path: Optional[str] = None) -> List[Dict]:
        """Transform Reverb CSV to eBay format"""
        
        print(f"🔄 Reading Reverb CSV: {csv_file_path}")
        
        reverb_data = []
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                reverb_data.append(row)
        
        print(f"📊 Found {len(reverb_data)} Reverb listings to transform")
        
        # Transform each row
        ebay_data = []
        for i, reverb_row in enumerate(reverb_data, 1):
            try:
                print(f"🔄 Transforming {i}/{len(reverb_data)}: {reverb_row.get('title', 'Unknown')[:50]}...")
                ebay_row = await self._transform_row(reverb_row)
                ebay_data.append(ebay_row)
                
            except Exception as e:
                print(f"❌ Error transforming row {i}: {str(e)}")
                # Continue with other rows
        
        print(f"✅ Transformed {len(ebay_data)} rows successfully")
        
        # Save to CSV if requested
        if output_csv_path:
            await self._save_to_csv(ebay_data, output_csv_path)
        
        return ebay_data
    
    async def _transform_row(self, reverb_row: Dict) -> Dict:
        """Transform single Reverb row to eBay format"""
        
        try:  # ✅ Fixed syntax
            # Extract basic fields
            title = reverb_row.get('title', '')
            brand = reverb_row.get('make', '')
            model = reverb_row.get('model', '')
            price = self._extract_price(reverb_row.get('price', ''))
            year = reverb_row.get('year', '')
            
            # Process condition once
            condition_raw = reverb_row.get('condition', '')
            condition = self._map_condition(condition_raw)
            clean_condition = self._extract_clean_condition(condition_raw)
            
            # Map category
            category_info = self._map_category(reverb_row.get('categories', ''))
            
            # Extract images
            images = self._extract_images(reverb_row)
            
            # Build eBay description (uses reverb_row internally)
            ebay_description = self._build_ebay_description(reverb_row)
            
            # Extract shipping info
            shipping_info = self._extract_shipping(reverb_row)
                
            # --- MODIFIED SECTION ---
            # Prepare the ItemSpecifics dictionary first to handle the conditional key name.
            item_specifics = {
                'Brand': brand,
                'Model': model,
                'Year': year,
                'Condition': clean_condition,
                'UPC': 'Does not apply',
                'MPN': 'Does not apply'
            }

            # Now, add the correct 'Type' or 'Amplifier Type' specific.
            if category_info['CategoryID'] == '38072':
                # For amplifiers, use the 'Amplifier Type' key you verified.
                amp_value = self._extract_amplifier_type(reverb_row.get('categories', ''))
                item_specifics['Amplifier Type'] = amp_value
            elif category_info['CategoryID'] == '29946':
                # For Microphones we need to assign a 'Form Factor'
                form_factor = "Condenser Microphone"  # Default value
                item_specifics['Amplifier Type'] = form_factor
            else:
                # For all other gear, use the standard 'Type' key.
                type_value = self._extract_guitar_type(reverb_row)
                item_specifics['Type'] = type_value
            
            # Build eBay listing data using the prepared ItemSpecifics
            ebay_data = {
                # Required eBay fields
                'Title': self._truncate_title(title),
                'Description': ebay_description,
                'CategoryID': category_info['CategoryID'],
                'Price': str(price),
                'Currency': 'GBP',
                'Quantity': '1',
                'ListingDuration': 'GTC',
                'ConditionID': condition,
                'Country': 'GB',
                'Location': 'London, UK',
                
                # Use the fully prepared item_specifics dictionary here
                'ItemSpecifics': item_specifics,
                
                # Images
                'PictureURLs': images,
                
                # Shipping
                'ShippingDetails': shipping_info,
                
                # Payment
                'PaymentMethods': ['PayPal'],
                'PayPalEmailAddress': 'payments@londonvintage.co.uk',
                
                # Return policy
                'ReturnPolicy': {
                    'ReturnsAccepted': 'ReturnsAccepted',
                    'Refund': 'MoneyBack',
                    'ReturnsWithin': 'Days_30',
                    'ShippingCostPaidBy': 'Buyer'
                },
                
                # Store original Reverb data for reference
                '_reverb_data': reverb_row
            }
            
            return ebay_data

        
        except Exception as e:
            print(f"❌ Error transforming row with ID {reverb_row.get('id', 'unknown')}: {str(e)}")
            print(f"   Title: {reverb_row.get('title', 'Unknown')[:50]}")
            # Return a minimal valid structure
            return {
                'Title': 'ERROR - ' + reverb_row.get('title', 'Unknown')[:70],
                'Description': 'Data transformation error',
                'CategoryID': '33034',
                'Price': '0',
                'Currency': 'GBP'
            }

    def _extract_clean_condition(self, condition_raw: str) -> str:
        """Extract clean condition display name"""
        if isinstance(condition_raw, str) and condition_raw.startswith('{'):
            try:
                import ast
                condition_dict = ast.literal_eval(condition_raw)
                return condition_dict.get('display_name', 'Excellent')
            except:
                return 'Excellent'
        return condition_raw or 'Excellent'
    
    def _extract_price(self, price_str: str) -> float:
        """Extract numeric price from string or dict"""
        if not price_str:
            return 0.0
        
        try:
            # If it's already a string representation of a dict
            if isinstance(price_str, str) and price_str.startswith('{'):
                import ast
                price_dict = ast.literal_eval(price_str)
                return float(price_dict.get('amount', '0'))
            
            # If it's a simple string
            import re
            price_clean = re.sub(r'[£$€,]', '', str(price_str))
            return float(price_clean)
            
        except (ValueError, TypeError, SyntaxError):
            print(f"⚠️ Could not parse price: {price_str}")
            return 0.0
    
    def _map_condition(self, reverb_condition: str) -> str:
        """Map Reverb condition to eBay ConditionID"""
        
        # Handle dict-like condition strings
        if isinstance(reverb_condition, str) and reverb_condition.startswith('{'):
            try:
                import ast
                condition_dict = ast.literal_eval(reverb_condition)
                reverb_condition = condition_dict.get('display_name', 'Excellent')
            except:
                reverb_condition = 'Excellent'  # Default
        
        condition_map = {
            'Mint': '1500',
            'Excellent': '3000', 
            'Very Good': '3000',
            'Good': '4000',
            'Fair': '5000',
            'Poor': '6000',
            'Brand New': '1000'  # Add this
        }
        
        return condition_map.get(reverb_condition, '3000')  # Default to Very Good
    
    def _map_category(self, categories_str: str) -> Dict:
        """Map Reverb category UUID to eBay CategoryID using comprehensive mapping"""
        
        mapping = self.get_comprehensive_reverb_to_ebay_mapping()
        
        if not categories_str:
            return mapping['default']
        
        try:
            # Handle string representation of list
            if categories_str.startswith('['):
                import ast
                categories_list = ast.literal_eval(categories_str)
                if categories_list and isinstance(categories_list, list):
                    category_uuid = categories_list[0].get('uuid', '')
                    if category_uuid in mapping:
                        return mapping[category_uuid]
            
            # Try direct string match for testing
            for uuid, category_mapping in mapping.items():
                if uuid in categories_str:
                    return category_mapping
                    
        except Exception as e:
            print(f"⚠️ Error parsing categories: {str(e)}")
        
        # Return default
        return mapping['default']

    def _extract_images(self, reverb_row: Dict) -> List[str]:
        """Extract image URLs from Reverb data - HIGH QUALITY VERSION"""
        images = []
        
        try:
            # Try cloudinary_photos first
            cloudinary_str = reverb_row.get('cloudinary_photos', '')
            if cloudinary_str:
                import ast
                cloudinary_data = ast.literal_eval(cloudinary_str)
                for photo in cloudinary_data:
                    # ✅ USE preview_url instead of constructing from path
                    if 'preview_url' in photo:
                        images.append(photo['preview_url'])
                    # Fallback to constructed URL if preview_url not available
                    elif 'path' in photo:
                        url = f"https://rvb-img.reverb.com/image/upload/v{photo['version']}/{photo['public_id']}.{photo['format']}"
                        images.append(url)
            
            # Fallback to photos field
            if not images:
                photos_str = reverb_row.get('photos', '')
                if photos_str:
                    photos_data = ast.literal_eval(photos_str)
                    for photo in photos_data:
                        if '_links' in photo and 'full' in photo['_links']:
                            url = photo['_links']['full']['href']
                            images.append(url)
        
        except Exception as e:
            print(f"⚠️ Could not extract images: {str(e)}")
        
        return images[:12]  # eBay limit
    
    def _build_ebay_description(self, reverb_row: Dict) -> str:
        """Build eBay HTML description"""
        description = reverb_row.get('description', '')
        brand = reverb_row.get('make', '')
        model = reverb_row.get('model', '')
        year = reverb_row.get('year', '')
        
        # Extract clean condition display name
        clean_condition = self._extract_clean_condition(reverb_row.get('condition', ''))
        
    # Build HTML description
        html_parts = [
            '<div style="font-family: Arial, sans-serif; max-width: 800px;">',
            f'<h2>{brand} {model}</h2>',
        ]
        
        if year:
            html_parts.append(f'<p><strong>Year:</strong> {year}</p>')
        
        if clean_condition:  # Use clean condition here
            html_parts.append(f'<p><strong>Condition:</strong> {clean_condition}</p>')
        
        if description:
            # Clean HTML from description and limit length for eBay
            import re
            clean_desc = re.sub('<[^<]+?>', '', description)  # Strip HTML tags
            if len(clean_desc) > 1000:  # Limit for readability
                clean_desc = clean_desc[:1000] + '...'
            
            html_parts.extend([
                '<h3>Description</h3>',
                f'<div>{description}</div>'  # Keep original HTML formatting
            ])
        
        # Add standard footer
        html_parts.extend([
            '<hr>',
            '<p><strong>London Vintage Guitars</strong></p>',
            '<p>We are a specialist vintage guitar dealer based in London, UK.</p>',
            '<p>All items are professionally inspected and come with our quality guarantee.</p>',
            '</div>'
        ])
        
        return '\n'.join(html_parts)
    
    # --- NEW METHOD ---
    def _extract_amplifier_type(self, categories_str: str) -> str:
        """Deduce amplifier type from Reverb categories for the 'Type' item specific."""
        categories_str = categories_str.lower()
        
        # Mapping from Reverb category UUIDs to eBay enum values
        amp_type_map = {
            '19d53222-297e-410c-ba4f-b48678e917f9': 'Head',    # Amps / Guitar Amps / Guitar Heads
            '66d136cb-02f2-4d04-b617-9215e972cc29': 'Stack',   # Amps / Guitar Amps / Guitar Amp Stacks
            '10335451-31e5-418a-8ed8-f48cd738f17d': 'Combo',   # Amps / Guitar Amps / Guitar Combos
            'f1b3d127-4158-43c3-934b-e402adc3d6ca': 'Cabinet', # Amps / Guitar Amps / Guitar Cabinets
            '09055aa7-ed49-459d-9452-aa959f288dc2': 'Combo'    # Amps (default to Combo)
        }
        
        for uuid, amp_type in amp_type_map.items():
            if uuid in categories_str:
                return amp_type
        
        # Default fallback for any other amp category not explicitly mapped
        return 'Combo'
    
    def _extract_guitar_type(self, reverb_row: Dict) -> str:
        """Extract guitar type from categories or title"""
        title = reverb_row.get('title', '').lower()
        categories = reverb_row.get('categories', '').lower()
        brand = reverb_row.get('make', '').lower()
        
        # Check for effects/pedals first (more specific)
        if any(keyword in title for keyword in ['pedal', 'effect', 'mistress', 'flanger', 'delay', 'reverb', 'sustain pedal']):
            return 'Effects Pedal'
        elif any(keyword in categories for keyword in ['effects', 'pedal']):
            return 'Effects Pedal'
        elif 'electro-harmonix' in brand and any(word in title for word in ['mistress', 'flanger', 'delay']):
            return 'Effects Pedal'
        elif 'splitter' in title or 'footswitch' in title:
            return 'Effects Pedal'
        elif 'electric' in title or 'electric' in categories:
            return 'Electric Guitar'
        elif 'acoustic' in title or 'acoustic' in categories:
            return 'Acoustic Guitar'
        elif 'bass' in title or 'bass' in categories:
            return 'Bass Guitar'
        elif 'amp' in title or 'amp' in categories:
            return 'Amplifier'
        else:
            return 'Musical Instrument'
    
    def _extract_shipping(self, reverb_row: Dict) -> List[Dict]:
        """Extract shipping information"""
        # Default UK shipping options
        return [
            {
                'Priority': '1',
                'Service': 'UK_OtherCourier24',
                'Cost': '25.00',
                'CurrencyID': 'GBP'
            },
            {
                'Priority': '2',
                'Service': 'UK_OtherCourier48',
                'Cost': '15.00',
                'CurrencyID': 'GBP'
            }
        ]
    
    def _truncate_title(self, title: str) -> str:
        """Ensure title meets eBay 80 character limit"""
        if len(title) <= 80:
            return title
        
        # Truncate but try to preserve whole words
        truncated = title[:77]
        last_space = truncated.rfind(' ')
        if last_space > 60:  # Don't truncate too aggressively
            truncated = truncated[:last_space]
        
        return truncated + '...'
    
    async def _save_to_csv(self, ebay_data: List[Dict], output_path: str):
        """Save eBay data to CSV file"""
        
        print(f"💾 Saving eBay CSV to: {output_path}")
        
        # Create output directory
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Flatten data for CSV
        flattened_data = []
        for row in ebay_data:
            flat_row = {}  # Create new dict instead of copying
            
            # Process each field
            for key, value in row.items():
                if isinstance(value, (dict, list)):
                    # Convert complex objects to JSON strings
                    flat_row[f'{key}_json'] = json.dumps(value, default=str)
                else:
                    # Keep simple values as-is
                    flat_row[key] = value
            
            flattened_data.append(flat_row)
        
        # Write CSV
        if flattened_data:
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = flattened_data[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(flattened_data)
            
            print(f"✅ Saved {len(flattened_data)} eBay listings to CSV")
        else:
            print("❌ No data to save")



class EbayListingCreator:
    """Create eBay listings using Trading API"""
    
    def __init__(self, sandbox: bool = False):
        self.ebay_api = EbayTradingLegacyAPI(sandbox=sandbox)
        self.sandbox = sandbox
    
    async def create_listings_from_data(self, listing_data: List[Dict], test_mode: bool = True) -> Dict:
        """Create eBay listings from transformed data"""
        
        results = {
            'total': len(listing_data),
            'successful': 0,
            'failed': 0,
            'details': [],
            'failed_items': []  # ✅ Add this to track failed items
        }
        
        print(f"🚀 Creating {len(listing_data)} eBay listings...")
        if test_mode:
            print("🧪 TEST MODE: Data validation only - no actual listings created")
        elif self.sandbox:
            print("🧪 SANDBOX MODE: Creating test listings on eBay sandbox")
        else:
            print("🔴 LIVE MODE: Creating real eBay listings")
        
        for i, item_data in enumerate(listing_data, 1):
            try:
                title = item_data.get('Title', 'Unknown')
                print(f"\n📦 Processing {i}/{len(listing_data)}: {title[:50]}...")
                
                # Create the listing
                if test_mode:
                    result = await self._validate_listing_data(item_data)
                    if result.get('valid'):
                        result = {
                            'success': True,
                            'item_id': f'TEST_{i}_123456789',
                            'message': 'Test mode: Listing validated successfully'
                        }
                    else:
                        result = {
                            'success': False,
                            'errors': result.get('errors', ['Validation failed'])
                        }
                else:
                    result = await self.ebay_api.add_fixed_price_item(item_data)
                
                # Process result
                if result.get('success'):
                    results['successful'] += 1
                    item_id = result.get('item_id')
                    print(f"✅ Success: {item_id}")
                    
                    results['details'].append({
                        'success': True,
                        'item_id': item_id,
                        'title': title,
                        'original_reverb_id': item_data.get('_reverb_data', {}).get('id')
                    })
                else:
                    results['failed'] += 1
                    errors = result.get('errors', ['Unknown error'])
                    print(f"❌ Failed: {'; '.join(errors)}")
                    
                    # ✅ Store the failed item data for retry file
                    results['failed_items'].append(item_data)
                    
                    results['details'].append({
                        'success': False,
                        'errors': errors,
                        'title': title,
                        'original_reverb_id': item_data.get('_reverb_data', {}).get('id')
                    })
                
                # Small delay between requests
                if not test_mode:
                    await asyncio.sleep(1)
                    
            except Exception as e:
                results['failed'] += 1
                error_msg = str(e)
                print(f"❌ Exception: {error_msg}")
                
                # ✅ Store the failed item data for retry file (with safety check)
                if isinstance(item_data, dict):
                    results['failed_items'].append(item_data)
                    title = item_data.get('Title', 'Unknown')
                    reverb_id = None
                    reverb_data = item_data.get('_reverb_data')
                    if isinstance(reverb_data, dict):
                        reverb_id = reverb_data.get('id')
                else:
                    # If item_data is not a dict, create a safe representation
                    title = 'Invalid Data Structure'
                    reverb_id = None
                    results['failed_items'].append({'Title': title, 'Error': 'Data structure issue'})
                
                results['details'].append({
                    'success': False,
                    'errors': [error_msg],
                    'title': title,
                    'original_reverb_id': reverb_id
                })
        
        # Print summary
        print(f"\n📊 **CREATION SUMMARY**")
        print("=" * 50)
        print(f"Total items processed: {results['total']}")
        print(f"✅ Successful: {results['successful']}")
        print(f"❌ Failed: {results['failed']}")
        
        return results
    
    async def _validate_listing_data(self, item_data: Dict) -> Dict:
        """Validate listing data without creating actual listing"""
        errors = []
        
        # Required fields check
        required_fields = ['Title', 'Description', 'CategoryID', 'Price']
        for field in required_fields:
            if not item_data.get(field):
                errors.append(f"Missing required field: {field}")
        
        # Title length check
        title = item_data.get('Title', '')
        if len(title) > 80:
            errors.append(f"Title too long: {len(title)} chars (max 80)")
        
        # Price validation
        try:
            price = float(item_data.get('Price', 0))
            if price <= 0:
                errors.append("Price must be greater than 0")
        except (ValueError, TypeError):
            errors.append("Invalid price format")
        
        # Category ID validation
        category_id = item_data.get('CategoryID', '')
        if not category_id.isdigit():
            errors.append("Invalid CategoryID format")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }

    def _save_failed_listings(self, failed_items: List[Dict], original_csv_path: str):
        """Save failed listings to ebay_ready_retries.csv in same format as input"""
        
        if not failed_items:
            print("🎉 No failed items to save!")
            return
        
        # Determine output path
        input_path = Path(original_csv_path)
        output_dir = input_path.parent
        output_file = output_dir / "ebay_ready_retries.csv"
        
        print(f"\n💾 Saving {len(failed_items)} failed listings to: {output_file}")
        
        try:
            # ✅ ENHANCED: Flatten complex objects to JSON strings (same as original CSV)
            flattened_items = []
            for item in failed_items:
                flattened_item = {}
                
                for key, value in item.items():
                    if isinstance(value, (dict, list)) and key not in ['_reverb_data']:
                        # Convert complex objects to JSON strings with '_json' suffix
                        flattened_item[f'{key}_json'] = json.dumps(value, default=str)
                    elif key == '_reverb_data' and isinstance(value, dict):
                        # Special handling for reverb data
                        flattened_item['_reverb_data_json'] = json.dumps(value, default=str)
                    else:
                        # Keep simple values as-is
                        flattened_item[key] = value
                
                flattened_items.append(flattened_item)
            
            # Write the flattened data
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                if flattened_items:
                    fieldnames = flattened_items[0].keys()
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(flattened_items)
            
            print(f"✅ Failed listings saved to: {output_file}")
            print(f"📝 Fields saved: {len(flattened_items[0].keys()) if flattened_items else 0}")
            print(f"📝 You can review and fix these {len(failed_items)} items, then retry with:")
            print(f"    python scripts/ebay/create_ebay_listings_from_csv.py --ebay-csv {output_file} --create-listings --sandbox")
            
            # ✅ DEBUG: Show sample of what was saved
            if flattened_items:
                print(f"\n🔍 DEBUG: Sample saved fields:")
                sample_keys = list(flattened_items[0].keys())[:10]
                for key in sample_keys:
                    value = flattened_items[0][key]
                    value_preview = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                    print(f"   {key}: {value_preview}")
            
        except Exception as e:
            print(f"❌ Error saving failed listings: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")

async def main():
    """Main execution function with comprehensive debugging"""
    parser = argparse.ArgumentParser(description='Create eBay listings from CSV')
    
    # Input mode - mutually exclusive
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--reverb-csv', help='Path to Reverb CSV file')
    input_group.add_argument('--ebay-csv', help='Path to eBay-formatted CSV file')
    
    # Output options
    parser.add_argument('--output-csv', help='Save transformed eBay data to CSV file')
    parser.add_argument('--create-listings', action='store_true', help='Create actual eBay listings')
    
    # eBay options
    parser.add_argument('--test-mode', action='store_true', help='Test mode: validate data without creating listings')
    parser.add_argument('--sandbox', action='store_true', help='Use eBay sandbox environment')
    
    # Processing options
    parser.add_argument('--limit', type=int, help='Limit number of items to process')
    parser.add_argument('--skip', type=int, default=0, help='Skip first N items')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.reverb_csv and not Path(args.reverb_csv).exists():
        print(f"❌ Error: Reverb CSV file not found: {args.reverb_csv}")
        sys.exit(1)
    
    if args.ebay_csv and not Path(args.ebay_csv).exists():
        print(f"❌ Error: eBay CSV file not found: {args.ebay_csv}")
        sys.exit(1)
    
    if args.reverb_csv and not args.output_csv and not args.create_listings:
        print("❌ Error: When using --reverb-csv, you must specify either --output-csv or --create-listings")
        sys.exit(1)
    
    try:
        ebay_data = []
        
        if args.reverb_csv:
            # Transform Reverb CSV to eBay format
            print("🔄 Reverb CSV mode: Transforming data...")
            
            reverb_api_key = os.environ.get('REVERB_API_KEY')
            transformer = ReverbToEbayTransformer(reverb_api_key)
            
            # Transform the data
            ebay_data = await transformer.transform_reverb_csv(
                csv_file_path=args.reverb_csv,
                output_csv_path=args.output_csv
            )
            
            # If only transforming to CSV, stop here
            if args.output_csv and not args.create_listings:
                print(f"✅ Transformation complete. eBay-ready CSV saved to: {args.output_csv}")
                return
            
        else:
            # Load eBay CSV directly with comprehensive debugging
            print("📁 Loading eBay CSV format...")
            print(f"📂 DEBUG: File path: {args.ebay_csv}")
            print(f"📂 DEBUG: File exists: {Path(args.ebay_csv).exists()}")
            
            # Check file stats
            file_path = Path(args.ebay_csv)
            if file_path.exists():
                file_stats = file_path.stat()
                print(f"📂 DEBUG: File size: {file_stats.st_size} bytes")
                print(f"📂 DEBUG: Modified time: {datetime.fromtimestamp(file_stats.st_mtime)}")
            
            # Count total lines first
            with open(args.ebay_csv, 'r', encoding='utf-8') as file:
                line_count = sum(1 for _ in file)
            print(f"📂 DEBUG: Total lines in file: {line_count}")
            
            # Count actual data lines (non-empty)
            with open(args.ebay_csv, 'r', encoding='utf-8') as file:
                reader = csv.reader(file)
                data_lines = 0
                empty_lines = 0
                for i, row in enumerate(reader):
                    if i == 0:  # Header
                        print(f"📂 DEBUG: Header row: {len(row)} columns")
                        print(f"📂 DEBUG: First 5 headers: {row[:5]}")
                        continue
                    if any(cell.strip() for cell in row):
                        data_lines += 1
                    else:
                        empty_lines += 1
                        
            print(f"📂 DEBUG: Data lines (non-empty): {data_lines}")
            print(f"📂 DEBUG: Empty lines: {empty_lines}")
            
            # Now actually load the data with detailed tracking
            # Now actually load the data with detailed tracking
            with open(args.ebay_csv, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                row_count = 0
                processed_count = 0
                skipped_count = 0
                
                for row_num, row in enumerate(reader, 1):
                    row_count += 1
                    
                    # Debug first few rows in detail
                    if row_count <= 5:
                        print(f"\n🔍 DEBUG Row {row_count}:")
                        print(f"   Raw row keys: {list(row.keys())[:5]}...")
                        print(f"   Row values sample: {list(row.values())[:3]}")
                        print(f"   Title field: '{row.get('Title', 'MISSING')}'")
                        print(f"   Has any values: {any(row.values())}")
                        print(f"   Non-empty values: {sum(1 for v in row.values() if v and v.strip())}")
                    
                    # Skip completely empty rows
                    if not any(v and v.strip() for v in row.values()):
                        if row_count <= 10:  # Debug first 10 empty rows
                            print(f"⚠️ DEBUG: Skipping empty row {row_count}")
                        skipped_count += 1
                        continue
                    
                    # Skip rows without essential data
                    if not row.get('Title', '').strip():
                        if row_count <= 10:  # Debug first 10 missing title rows
                            print(f"⚠️ DEBUG: Skipping row {row_count} - no title")
                        skipped_count += 1
                        continue
                    
                    # ✅ ENHANCED: Process the row with comprehensive JSON parsing
                    processed_row = {}
                    json_fields_converted = 0
                    
                    # List of fields that should be parsed as JSON
                    json_fields = ['ItemSpecifics', 'PictureURLs', 'ShippingDetails', 'PaymentMethods', 'ReturnPolicy', '_reverb_data']
                    
                    for key, value in row.items():
                        if not value or not value.strip():
                            processed_row[key] = value
                            continue
                            
                        # Handle _json suffix fields
                        if key.endswith('_json') and value and value.strip():
                            try:
                                # Convert JSON string back to object
                                new_key = key.replace('_json', '')
                                parsed_value = json.loads(value)
                                processed_row[new_key] = parsed_value
                                json_fields_converted += 1
                                
                                # Debug JSON parsing for first few rows
                                if row_count <= 3:
                                    print(f"🔄 DEBUG: Converted {key} -> {new_key} (type: {type(parsed_value).__name__})")
                                    
                            except json.JSONDecodeError as e:
                                if row_count <= 5:
                                    print(f"⚠️ DEBUG: JSON decode error for {key}: {str(e)[:100]}")
                                # Keep original if JSON parse fails
                                processed_row[key] = value
                                
                        # Handle fields that should be JSON but don't have _json suffix
                        elif key in json_fields and isinstance(value, str) and value.strip():
                            # Check if it looks like JSON (starts with { or [)
                            if value.strip().startswith(('{', '[')):
                                try:
                                    parsed_value = json.loads(value)
                                    processed_row[key] = parsed_value
                                    json_fields_converted += 1
                                    if row_count <= 3:
                                        print(f"🔄 DEBUG: Direct JSON parsing for {key} (type: {type(parsed_value).__name__})")
                                except json.JSONDecodeError:
                                    processed_row[key] = value
                            else:
                                processed_row[key] = value
                        else:
                            processed_row[key] = value
                    
                    # ✅ CRITICAL: Validate processed_row is a proper dict with required fields
                    if not isinstance(processed_row, dict):
                        print(f"❌ DEBUG: Row {row_count} - processed_row is not a dict! Type: {type(processed_row)}")
                        skipped_count += 1
                        continue
                    
                    # ✅ CRITICAL: Ensure essential fields are present and valid
                    required_fields = ['Title', 'Description', 'CategoryID', 'Price']
                    missing_fields = [field for field in required_fields if not processed_row.get(field)]
                    
                    if missing_fields:
                        print(f"⚠️ DEBUG: Row {row_count} missing fields: {missing_fields}")
                        skipped_count += 1
                        continue
                    
                    # ✅ CRITICAL: Validate specific problematic fields
                    # Ensure PaymentMethods is a list
                    if 'PaymentMethods' in processed_row:
                        payment_methods = processed_row['PaymentMethods']
                        if isinstance(payment_methods, str):
                            try:
                                # Try to parse as JSON first
                                payment_methods = json.loads(payment_methods)
                                processed_row['PaymentMethods'] = payment_methods
                            except json.JSONDecodeError:
                                # If not JSON, treat as single payment method
                                processed_row['PaymentMethods'] = [payment_methods]
                        elif not isinstance(payment_methods, list):
                            processed_row['PaymentMethods'] = [str(payment_methods)]
                    
                    # Ensure _reverb_data is a dict if present
                    if '_reverb_data' in processed_row and isinstance(processed_row['_reverb_data'], str):
                        try:
                            processed_row['_reverb_data'] = json.loads(processed_row['_reverb_data'])
                        except json.JSONDecodeError:
                            print(f"⚠️ DEBUG: Could not parse _reverb_data for row {row_count}")
                            processed_row['_reverb_data'] = {}
                    
                    ebay_data.append(processed_row)
                    processed_count += 1
                    
                    # Debug first few processed rows
                    if processed_count <= 3:
                        print(f"✅ DEBUG: Processed row {row_count} -> item {processed_count}")
                        print(f"   Title: '{processed_row.get('Title', 'MISSING')}'")
                        print(f"   Price: '{processed_row.get('Price', 'MISSING')}'")
                        print(f"   CategoryID: '{processed_row.get('CategoryID', 'MISSING')}'")
                        print(f"   PaymentMethods type: {type(processed_row.get('PaymentMethods', 'MISSING')).__name__}")
                        print(f"   _reverb_data type: {type(processed_row.get('_reverb_data', 'MISSING')).__name__}")
                        print(f"   JSON fields converted: {json_fields_converted}")
                        
                    # Break early if we're processing way more than expected
                    if processed_count > 50 and processed_count > line_count * 2:
                        print(f"⚠️ DEBUG: STOPPING - processed {processed_count} items but file only has {line_count} lines!")
                        print("This suggests a serious bug in data loading logic.")
                        break
            
            print(f"\n📊 DEBUG SUMMARY:")
            print(f"   Total rows read: {row_count}")
            print(f"   Processed items: {processed_count}")
            print(f"   Skipped rows: {skipped_count}")
            print(f"   Final ebay_data length: {len(ebay_data)}")
            
            # Verify data integrity
            if len(ebay_data) != processed_count:
                print(f"⚠️ DEBUG WARNING: Data length mismatch!")
                print(f"   ebay_data length: {len(ebay_data)}")
                print(f"   processed_count: {processed_count}")
            
            # Sample check final data
            if ebay_data:
                print(f"\n🔍 DEBUG: Final data sample:")
                for i, item in enumerate(ebay_data[:3]):
                    print(f"   Item {i+1}: Title='{item.get('Title', 'MISSING')}', Keys={len(item.keys())}")
        
        # Apply skip and limit with debugging
        original_count = len(ebay_data)
        
        if args.skip > 0:
            ebay_data = ebay_data[args.skip:]
            print(f"⏭️ DEBUG: Skipped first {args.skip} items, {len(ebay_data)} remaining")
        
        if args.limit:
            ebay_data = ebay_data[:args.limit]
            print(f"📏 DEBUG: Limited to {args.limit} items, final count: {len(ebay_data)}")
        
        print(f"\n📊 FINAL PROCESSING COUNTS:")
        print(f"   Original loaded: {original_count}")
        print(f"   After skip/limit: {len(ebay_data)}")
        
        # Create eBay listings if requested
        if args.create_listings and ebay_data:
            print(f"\n🚀 Starting eBay listing creation for {len(ebay_data)} items...")
            creator = EbayListingCreator(sandbox=args.sandbox)
            results = await creator.create_listings_from_data(ebay_data, test_mode=args.test_mode)
            
            # ✅ ADD THIS: Save failed items for retry
            if results.get('failed_items'):
                creator._save_failed_listings(results['failed_items'], args.ebay_csv)
    
            
            # Show successful listings
            if results['successful'] > 0:
                print(f"\n✅ **SUCCESSFUL LISTINGS:**")
                for detail in results['details']:
                    if detail.get('success'):
                        print(f"  - {detail.get('item_id')}: {detail.get('title', 'Unknown')[:60]}")
            
            # Show failed listings  
            if results['failed'] > 0:
                print(f"\n❌ **FAILED LISTINGS:**")
                for detail in results['details']:
                    if not detail.get('success'):
                        errors = '; '.join(detail.get('errors', ['Unknown error']))
                        print(f"  - {detail.get('title', 'Unknown')[:40]}: {errors}")
        
        elif not ebay_data:
            print("❌ No data to process")
    
    except KeyboardInterrupt:
        print("\n⏹️  Process interrupted by user")
    except Exception as e:
        print(f"❌ Critical error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())