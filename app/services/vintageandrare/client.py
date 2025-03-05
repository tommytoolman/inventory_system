# app/services/vintageandrare/client.py

import asyncio
import os
import logging
from typing import Dict, Any, Optional, List, Union
from datetime import datetime

import requests
from pathlib import Path

logger = logging.getLogger(__name__)

class VintageAndRareClient:
    """
    Client for interacting with the Vintage & Rare marketplace.
    
    This client handles authentication and API operations for V&R,
    leveraging both HTTP requests and Selenium for form automation.
    """
    
    BASE_URL = "https://www.vintageandrare.com"
    LOGIN_URL = f"{BASE_URL}/do_login"
    
    def __init__(self, username: str, password: str):
        """
        Initialize the V&R client.
        
        Args:
            username: V&R login username
            password: V&R login password
        """
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.authenticated = False
        
        # Default headers
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
        }
    
    async def authenticate(self) -> bool:
        """
        Authenticate with V&R website.
        
        Returns:
            bool: True if authentication is successful
        """
        try:
            # First get the main page to set up cookies
            self.session.get(self.BASE_URL, headers=self.headers)
            
            # Prepare login data
            login_data = {
                'username': self.username,
                'pass': self.password,
                'open_where': 'header'
            }
            
            # Submit login form
            response = self.session.post(
                self.LOGIN_URL,
                data=login_data,
                headers=self.headers,
                allow_redirects=True
            )
            
            # Check if login was successful
            self.authenticated = 'Sign out' in response.text or 'account' in response.url
            
            logger.info(f"V&R Authentication {'successful' if self.authenticated else 'failed'}")
            return self.authenticated
            
        except Exception as e:
            logger.error(f"V&R Authentication error: {str(e)}")
            self.authenticated = False
            return False
    
    async def create_listing(self, product_data: Dict[str, Any], test_mode: bool = True) -> Dict[str, Any]:
        """
        Create a listing on V&R using Selenium automation.
        
        Args:
            product_data: Product data for the listing
            test_mode: If True, form will be filled but not submitted
            
        Returns:
            Dict with status and message
        """
        # Import the Selenium automation code
        from app.services.vintageandrare.inspect_form import login_and_navigate, fill_item_form
        
        try:
            # Define category mapping here to ensure it's in scope
            category_mapping = {
                'Electric Guitars': '51',
                'Electric Guitars / Solid Body': '51',
                'Acoustic Guitars': '82',
                'Bass Guitars': '52',
                'Amplifiers': '53',
                'Effects': '90'
            }
            
            # Convert product data to the format expected by the form automation
            form_data = {
                # Required fields
                'brand': product_data.get('brand', ''),
                'model_name': product_data.get('model', ''),
                # Default to Guitars (51)
                'category': '51',
                'price': str(product_data.get('price', 0)),
                
                # Optional fields
                'year': product_data.get('year'),
                'decade': product_data.get('decade'),
                'finish_color': product_data.get('finish', ''),
                'description': product_data.get('description', ''),
                'processing_time': product_data.get('processing_time'),
                'time_unit': product_data.get('time_unit', 'Days'),
                'youtube_url': product_data.get('video_url', ''),
                'external_url': product_data.get('external_link', ''),
                'show_vat': product_data.get('show_vat', True),
                
                # V&R specific fields
                'in_collective': product_data.get('in_collective', False),
                'in_inventory': product_data.get('in_inventory', True),
                'in_reseller': product_data.get('in_reseller', False),
                'collective_discount': product_data.get('collective_discount'),
                'price_notax': product_data.get('price_notax'),
                
                # Shipping info
                'shipping': product_data.get('available_for_shipment', True),
                'local_pickup': product_data.get('local_pickup', False),
                'shipping_fees': {
                    'europe': product_data.get('europe_shipping', '50'),
                    'usa': product_data.get('usa_shipping', '100'),
                    'uk': product_data.get('uk_shipping', '20'),
                    'world': product_data.get('world_shipping', '150')
                },
                
                # Images
                'images': []
            }
            
            # Map category names to IDs if needed
            category_name = product_data.get('category', '')
            if category_name:
                # Use the mapped ID or default to '51' (Guitars)
                form_data['category'] = category_mapping.get(category_name, '51')
            
            # Add primary image if available
            if product_data.get('primary_image'):
                form_data['images'].append(product_data['primary_image'])
            
            # Add additional images if available
            if product_data.get('additional_images'):
                if isinstance(product_data['additional_images'], list):
                    form_data['images'].extend(product_data['additional_images'])
                else:
                    # Parse as JSON if it's a string
                    try:
                        import json
                        additional = json.loads(product_data['additional_images'])
                        if isinstance(additional, list):
                            form_data['images'].extend(additional)
                    except Exception:
                        # If parsing fails, assume it's a single URL
                        form_data['images'].append(product_data['additional_images'])
            
            # Print the form data for debugging
            print(f"Sending form data to V&R: {form_data}")
            
            # Run the form automation in a separate thread
            # since Selenium is blocking and we're in an async function
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._run_form_automation(form_data, test_mode)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error creating V&R listing: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "status": "error",
                "message": f"Error: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    def _run_form_automation(self, form_data: Dict[str, Any], test_mode: bool) -> Dict[str, Any]:
        """
        Run the Selenium form automation.
        This is a blocking function that should be run in a separate thread.
        
        Args:
            form_data: Form data for the listing
            test_mode: If True, form will be filled but not submitted
            
        Returns:
            Dict with status and message
        """
        from app.services.vintageandrare.inspect_form import login_and_navigate
        
        # Run the form automation with the provided data
        try:
            # This function is blocking and will run the Selenium automation
            login_and_navigate(
                username=self.username,
                password=self.password,
                item_data=form_data,
                test_mode=test_mode
            )
            
            # Since we can't get the listing ID easily from the automation,
            # we'll generate a fake one for now
            external_id = f"VR-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            return {
                "status": "success",
                "message": "Listing created successfully" if not test_mode else "Test mode: form filled but not submitted",
                "external_id": external_id,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            import traceback
            logger.error(f"Selenium automation error: {traceback.format_exc()}")
            return {
                "status": "error",
                "message": f"Selenium automation error: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }