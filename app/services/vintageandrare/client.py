import asyncio
import logging
import requests
import re
import io
import tempfile
import os
import pandas as pd
import shutil # Added for MediaHandler cleanup


from typing import Dict, Any, Optional, List # Added List
from datetime import datetime, timezone
from pathlib import Path

# Assuming CategoryMappingService is correctly located
try:
    from app.services.category_mapping_service import CategoryMappingService
except ImportError:
    # Provide a fallback or handle the error appropriately if running standalone
    CategoryMappingService = None
    print("Warning: CategoryMappingService not found. Category mapping will use defaults.")

# Assuming inspect_form and media_handler are in the same directory
try:
    from .inspect_form import login_and_navigate
    from .media_handler import MediaHandler # Now used directly if needed, or via inspect_form
except ImportError:
    login_and_navigate = None
    MediaHandler = None
    print("Warning: inspect_form or media_handler not found. Selenium operations will fail.")

logger = logging.getLogger(__name__)

class VintageAndRareClient:
    """
    Client for interacting with the Vintage & Rare marketplace.

    Handles authentication, inventory CSV download (using requests),
    and listing creation/modification (using Selenium automation via inspect_form).
    Consolidates functionality previously in VintageAndRareClient and VRInventoryManager.
    """

    BASE_URL = "https://www.vintageandrare.com"
    LOGIN_URL = f"{BASE_URL}/do_login"
    EXPORT_URL = f"{BASE_URL}/instruments/export_inventory/export_inventory"

    def __init__(self, username: str, password: str, db_session=None):
        """
        Initialize the V&R client.

        Args:
            username: V&R login username.
            password: V&R login password.
            db_session: Optional SQLAlchemy async session for database operations (like category mapping).
        """
        self.username = username
        self.password = password
        self.session = requests.Session() # requests session for HTTP interactions
        self.authenticated = False
        self.db_session = db_session

        # Default headers for requests
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7', # Updated Accept
            'Accept-Language': 'en-US,en;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
        }

        # Initialize mapping service if DB session is provided
        if CategoryMappingService:
            self.mapping_service = CategoryMappingService(db_session) if db_session else None
        else:
            self.mapping_service = None

        # Temporary files tracking (for saved inventory CSV)
        self.temp_files = []


    async def authenticate(self) -> bool:
        """
        Authenticate with V&R website using the requests Session.
        Updates self.authenticated state.

        Returns:
            bool: True if authentication is successful.
        """
        if self.authenticated:
            print("Already authenticated with V&R")
            return True
        try:
            # First get the main page to set up cookies
            print(f"Authenticating V&R user: {self.username}")
            response = self.session.get(self.BASE_URL, headers=self.headers)
            print(f"Initial page load status: {response.status_code}")
            
            # Prepare login data
            login_data = {
                'username': self.username,
                'pass': self.password,
                'open_where': 'header'
            }
            
            # Submit login form
            print("Submitting V&R login form...")
            response = self.session.post(
                self.LOGIN_URL,
                data=login_data,
                headers=self.headers,
                allow_redirects=True
            )
            print(f"Login response status: {response.status_code}")
            
            # Check if login was successful
            self.authenticated = 'Sign out' in response.text or '/account' in response.url
            print(f"Authentication check - 'Sign out' in response: {'Sign out' in response.text}")
            print(f"Authentication check - '/account' in URL: {'/account' in response.url}")
            print(f"Authentication result: {'Successful' if self.authenticated else 'Failed'}")
            
            return self.authenticated
            
        except Exception as e:
            print(f"Error during V&R authentication: {str(e)}")
            import traceback
            print(f"Authentication traceback: {traceback.format_exc()}")
            self.authenticated = False
            return False

    # --- Inventory Download Methods (from VRInventoryManager) ---

    async def download_inventory_dataframe(self, save_to_file: bool = False, output_path: Optional[str] = None) -> Optional[pd.DataFrame]:
        """
        Download inventory CSV from V&R and return as a pandas DataFrame.
        Uses HTTP requests for efficiency.

        Args:
            save_to_file: Whether to also save the raw data to a file.
            output_path: Path where to save the file (if save_to_file is True).
                         If not provided, a temporary file will be created.

        Returns:
            pandas.DataFrame: Processed inventory data, or None if any step failed.
        """
        logger.info("Attempting to download V&R inventory CSV...")
        print("Starting V&R inventory download...")
        if not self.authenticated:
            print("Not authenticated. Attempting authentication first.")
            if not await self.authenticate():
                print("Authentication failed. Cannot download inventory.")
                return None
                
        try:
            # Download the inventory file using the authenticated session
            print(f"Requesting inventory CSV from {self.EXPORT_URL}")
            response = self.session.get(
                self.EXPORT_URL,
                headers=self.headers,
                allow_redirects=True,
                stream=True
            )
            print(f"Inventory export response status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"Error: Received non-200 status code: {response.status_code}")
                print(f"Response headers: {dict(response.headers)}")
                print(f"Response content (first 500 chars): {response.content[:500]}")
                return None
                
            # Stream data directly into an in-memory buffer
            csv_data = io.StringIO()
            content_length = 0
            for chunk in response.iter_content(chunk_size=8192):
                content_length += len(chunk)
                # Decode safely, replacing errors
                csv_data.write(chunk.decode('utf-8', errors='replace'))
            
            print(f"Downloaded {content_length} bytes of CSV data")
            csv_data.seek(0)  # Rewind buffer
            
            # Read the CSV data into a DataFrame
            print("Parsing CSV data into DataFrame...")
            df = pd.read_csv(csv_data)
            print(f"Successfully parsed CSV data: {len(df)} rows, {len(df.columns)} columns")
            
            # Save to file if requested
            if save_to_file:
                try:
                    file_path = None
                    if output_path:
                        file_path = Path(output_path)
                    else:
                        # Create a temporary file
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='w', encoding='utf-8') as temp_file_obj:
                            file_path = Path(temp_file_obj.name)
                            self.temp_files.append(str(file_path))
                            
                    print(f"Saving inventory data to {file_path}")
                    df.to_csv(file_path, index=False)
                except Exception as save_error:
                    print(f"Error saving inventory to file: {save_error}")
            
            # Apply basic processing
            df = self._process_inventory_dataframe(df)
            
            return df
            
        except pd.errors.EmptyDataError:
            print("Error: CSV data is empty")
            return None
        except pd.errors.ParserError as e:
            print(f"Error parsing CSV data: {str(e)}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"HTTP error downloading V&R inventory: {str(e)}")
            return None
        except Exception as e:
            print(f"Unexpected error downloading V&R inventory: {str(e)}")
            import traceback
            print(f"Download traceback: {traceback.format_exc()}")
            return None

    def _process_inventory_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply basic processing to the raw inventory DataFrame.

        Args:
            df: Raw inventory DataFrame from CSV download.

        Returns:
            pandas.DataFrame: Processed inventory data.
        """
        # Standardize column names (lowercase, strip whitespace, replace spaces with underscores)
        df.columns = [str(col).lower().strip().replace(' ', '_') for col in df.columns]
        logger.debug(f"Standardized DataFrame columns: {df.columns.tolist()}")

        # Add more processing as needed:
        # - Convert data types (e.g., 'product_price' to numeric)
        # - Handle missing values
        # - Map 'product_sold' ('yes'/'no') to boolean or status enum

        return df

    def compare_with_database(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Placeholder method to compare downloaded inventory with database records.
        Requires implementation based on the database schema and comparison logic.

        Args:
            df: Inventory DataFrame downloaded from V&R.

        Returns:
            Dict containing difference statistics (or placeholder).
        """
        logger.warning("compare_with_database is a placeholder and needs implementation.")
        # TODO: Implement comparison logic using self.db_session if available
        # This method should likely be async if it interacts with the async db_session.
        return {
            'total_records_in_csv': len(df),
            'comparison_status': 'Not Implemented'
        }

    # --- Listing Creation/Modification Methods (using Selenium via inspect_form) ---

    async def map_category(self, category_name: str, category_id: Optional[str] = None) -> Dict[str, Optional[str]]:
        """
        Map an internal category name/ID to V&R category/subcategory IDs using the CategoryMappingService.

        Args:
            category_name: Category name from our system.
            category_id: Optional category ID from our system for more specific mapping.

        Returns:
            Dict with 'category_id' and 'subcategory_id' for V&R, or defaults/None if not found.
        """
        if not self.mapping_service or not self.db_session:
            logger.warning("CategoryMappingService or DB session not available. Returning default V&R category.")
            # Fallback to hardcoded default (Guitars -> Electric solid body)
            return {"category_id": "51", "subcategory_id": "83"} # Adjusted default

        mapping = None
        target_platform = "vintageandrare" # Or "vr" depending on your mapping table

        # Try to find mapping by internal ID if available
        if category_id:
            logger.debug(f"Attempting category mapping for internal ID: {category_id}")
            mapping = await self.mapping_service.get_mapping("internal", str(category_id), target_platform)

        # If no mapping found by ID, try by internal name
        if not mapping and category_name:
            logger.debug(f"Attempting category mapping for internal name: {category_name}")
            mapping = await self.mapping_service.get_mapping_by_name("internal", category_name, target_platform)

        # If still no mapping, log warning and get default for V&R
        if not mapping:
            logger.warning(f"No specific V&R mapping found for '{category_name}' (ID: {category_id}). Using default V&R mapping.")
            mapping = await self.mapping_service.get_default_mapping(target_platform)

        if mapping:
            logger.info(f"Mapped '{category_name}' to V&R category: {mapping.target_id}, subcategory: {mapping.target_subcategory_id}")
            return {
                "category_id": mapping.target_id,
                "subcategory_id": mapping.target_subcategory_id
                # Add target_sub_subcategory_id if your mapping includes it
            }
        else:
            # Ultimate fallback if even default fails
            logger.error(f"FATAL: No V&R mapping found for '{category_name}' and no default mapping available. Falling back to hard-coded default.")
            return {"category_id": "51", "subcategory_id": "83"} # Hardcoded fallback


    async def create_listing_selenium(self, product_data: Dict[str, Any], test_mode: bool = True) -> Dict[str, Any]:
        """
        Create a listing on V&R using Selenium automation via inspect_form.py.
        This is an async method that runs the blocking Selenium code in an executor thread.

        Args:
            product_data: Dictionary containing the product details to list.
            test_mode: If True, the form will be filled but not submitted.

        Returns:
            Dict with status, message, and potentially vr_product_id (currently None).
        """
        if not login_and_navigate:
             logger.error("inspect_form.login_and_navigate not available. Cannot create listing.")
             return {"status": "error", "message": "Selenium automation module not loaded"}

        logger.info(f"Initiating V&R listing creation for product ID (internal): {product_data.get('id')}")
        try:
            # 1. Map Category
            category_mapping = await self.map_category(
                product_data.get('category', ''), # Pass internal category name
                str(product_data.get('category_id', '')) # Pass internal category ID if available
            )

            # 2. Prepare Form Data (Translate internal product_data to V&R form field names)
            form_data = {
                'brand': product_data.get('brand', ''),
                'model_name': product_data.get('model', ''), # Assuming 'model' is the field in product_data
                'price': str(product_data.get('price', 0)), # V&R expects string

                # Use mapped category IDs
                'category': category_mapping['category_id'],
                'subcategory': category_mapping['subcategory_id'],
                # Add sub_subcategory if needed based on mapping

                'year': str(product_data.get('year', '')) if product_data.get('year') else None, # V&R might expect string or handle None
                'decade': str(product_data.get('decade', '')) if product_data.get('decade') else None, # V&R might expect string or handle None

                'finish_color': str(product_data.get('finish', '') or ''),
                'description': str(product_data.get('description', '') or ''),
                'external_id': str(product_data.get('sku', '') or ''), # Send our SKU as V&R external_id

                 # Optional V&R specific fields - get from product_data if stored, else use defaults
                'show_vat': product_data.get('vr_show_vat', True),
                'call_for_price': product_data.get('vr_call_for_price', False),
                'discounted_price': str(product_data.get('vr_discounted_price','')) if product_data.get('vr_discounted_price') else None,
                'in_collective': product_data.get('vr_in_collective', False),
                'in_inventory': product_data.get('vr_in_inventory', True),
                'in_reseller': product_data.get('vr_in_reseller', False),
                'collective_discount': str(product_data.get('vr_collective_discount','')) if product_data.get('vr_collective_discount') else None,
                'buy_now': product_data.get('vr_buy_now', False), # Check V&R template if needed

                # Processing Time
                'processing_time': str(product_data.get('processing_time', '3') or '3'), # Default to 3 if not provided
                'time_unit': product_data.get('time_unit', 'Days'), # Default to Days

                # Shipping info
                'shipping': product_data.get('available_for_shipment', True),
                'local_pickup': product_data.get('local_pickup', False),
                'shipping_fees': {
                    # Get these from product_data or global settings
                    'europe': str(product_data.get('shipping_europe_fee', '50') or '50'),
                    'usa': str(product_data.get('shipping_usa_fee', '100') or '100'),
                    'uk': str(product_data.get('shipping_uk_fee', '75') or '75'), # Example fee
                    'world': str(product_data.get('shipping_world_fee', '150') or '150')
                },

                # Media
                'images': [], # Initialize empty list
                'youtube_url': str(product_data.get('video_url', '') or ''),
                'external_url': str(product_data.get('external_link', '') or '') # External link to product page?
            }

            # Add primary image URL
            primary_image = product_data.get('primary_image')
            if primary_image:
                form_data['images'].append(primary_image)

            # Add additional image URLs (handle list or JSON string)
            additional_images = product_data.get('additional_images')
            if additional_images:
                if isinstance(additional_images, list):
                    form_data['images'].extend(additional_images)
                elif isinstance(additional_images, str):
                    try:
                        import json
                        parsed_images = json.loads(additional_images)
                        if isinstance(parsed_images, list):
                            form_data['images'].extend(parsed_images)
                        else:
                             logger.warning(f"Parsed additional_images is not a list: {type(parsed_images)}")
                    except json.JSONDecodeError:
                        # Assume it's a single URL string if JSON parsing fails
                        form_data['images'].append(additional_images)
                        logger.warning("additional_images field was a string but not valid JSON, treated as single URL.")
                    except Exception as e:
                         logger.error(f"Error processing additional_images string: {e}")

            # Limit images (V&R might have a limit, e.g., 20)
            MAX_VR_IMAGES = 20
            if len(form_data['images']) > MAX_VR_IMAGES:
                 logger.warning(f"Too many images ({len(form_data['images'])}). Truncating to {MAX_VR_IMAGES}.")
                 form_data['images'] = form_data['images'][:MAX_VR_IMAGES]

            logger.debug(f"Prepared form data for V&R Selenium: {form_data}")

            # 3. Run Selenium Automation in Executor Thread
            loop = asyncio.get_event_loop()
            # _run_selenium_automation needs to be defined or adapted from _run_form_automation
            result = await loop.run_in_executor(
                None, # Default thread pool executor
                lambda: self._run_selenium_automation(form_data, test_mode) # Pass prepared data
            )

            logger.info(f"V&R Selenium listing creation result: {result}")
            return result

        except Exception as e:
            logger.error(f"Error preparing or executing V&R listing creation: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "status": "error",
                "message": f"Failed to create V&R listing: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    def _run_selenium_automation(self, form_data: Dict[str, Any], test_mode: bool) -> Dict[str, Any]:
        """
        Wrapper function to execute the blocking Selenium login_and_navigate function.
        This runs in a separate thread via run_in_executor.

        Args:
            form_data: The dictionary of data prepared for the V&R form.
            test_mode: Boolean indicating if the form should be submitted.

        Returns:
            Dictionary containing the result status, message, and vr_product_id (None).
        """
        if not login_and_navigate:
            raise RuntimeError("Selenium automation function (login_and_navigate) not loaded.")

        try:
            logger.info(f"Starting Selenium automation in executor thread (Test Mode: {test_mode})...")
            # Call the imported function from inspect_form.py
            login_and_navigate(
                username=self.username,
                password=self.password,
                item_data=form_data,
                test_mode=test_mode
            )

            # Note: The actual V&R product ID is not retrieved here.
            # Reconciliation needed after inventory download.
            message = "Listing created successfully" if not test_mode else "Test mode: form filled but not submitted"
            logger.info(f"Selenium automation completed: {message}")
            return {
                "status": "success",
                "message": message,
                "vr_product_id": None, # Explicitly None, requires reconciliation
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            import traceback
            logger.error(f"Error during V&R Selenium automation: {traceback.format_exc()}")
            return {
                "status": "error",
                "message": f"Selenium automation failed: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    # --- Cleanup Methods ---

    def cleanup_temp_files(self):
        """Remove any temporary inventory CSV files created during operation."""
        if not self.temp_files:
            return
        logger.info(f"Cleaning up {len(self.temp_files)} temporary V&R inventory files...")
        for temp_file_path in self.temp_files:
            try:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    logger.debug(f"Removed temporary file: {temp_file_path}")
            except Exception as e:
                logger.error(f"Error removing temporary file {temp_file_path}: {str(e)}")
        self.temp_files = [] # Clear the list

    def __del__(self):
        """Destructor to ensure cleanup of temporary files."""
        self.cleanup_temp_files()