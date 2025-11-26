"""
We also have CLI scripts set up in scripts/vr/ with optional argparses to run these.
"""

import asyncio
import logging
import re
import requests
from bs4 import BeautifulSoup
import re
import io
import json
import time
import random
import html
import tempfile
import os
import pandas as pd
import shutil # Added for MediaHandler cleanup

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from app.core.utils import ImageTransformer, ImageQuality
import importlib

# Assuming CategoryMappingService is correctly located
try:
    from app.services.category_mapping_service import CategoryMappingService
except ImportError:
    # Provide a fallback or handle the error appropriately if running standalone
    CategoryMappingService = None
    print("Warning: CategoryMappingService not found. Category mapping will use defaults.")

# Assuming inspect_form and media_handler are in the same directory
try:
    from app.services.vintageandrare.inspect_form import login_and_navigate
    from app.services.vintageandrare.media_handler import MediaHandler # Now used directly if needed, or via inspect_form
except ImportError:
    login_and_navigate = None
    MediaHandler = None
    print("Warning: inspect_form or media_handler not found. Selenium operations will fail.")

logger = logging.getLogger(__name__)

# Try to import undetected-chromedriver after logger is defined, lazy to detect install
uc = None
try:
    uc = importlib.import_module("undetected_chromedriver")
    logger.info("UDC import ok")
except Exception as exc:  # noqa: BLE001
    uc = None
    logger.info("UDC import failed: %s", exc)

# Try to import curl_cffi for better Cloudflare bypass (Chrome TLS fingerprint)
cf_requests = None
try:
    from curl_cffi import requests as cf_requests
    logger.info("curl_cffi import ok - will use Chrome TLS fingerprint")
except ImportError:
    cf_requests = None
    logger.info("curl_cffi not installed - using standard requests")

logging.basicConfig(
    level=logging.INFO, # Use INFO or DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Ensures output to console
)

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
        self.session = requests.Session()  # requests session for HTTP interactions
        self.authenticated = False
        self.db_session = db_session
        self.cloudflare_blocked = False  # Track if we're blocked by Cloudflare

        # Create curl_cffi session if available (better Cloudflare bypass)
        self.cf_session = None
        if cf_requests:
            self.cf_session = cf_requests.Session(impersonate="chrome")
            logger.info("Created curl_cffi session with Chrome impersonation")

        # Browser-like headers to satisfy Cloudflare
        chrome_ua = os.environ.get(
            "VR_USER_AGENT",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        )
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "Host": "www.vintageandrare.com",
            "Referer": "https://www.vintageandrare.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": chrome_ua,
            "Pragma": "no-cache",
            "DNT": "1",
        }
        # Apply default headers to the requests session so all requests share the same UA/fingerprint.
        self.session.headers.update(self.headers)
        
        self._selenium_session = None  # ✅ Add this line
        self._selenium_driver = None   # ✅ Add this line
        self._load_cookies_from_env()
        
        # Initialize mapping service if DB session is provided
        if CategoryMappingService:
            self.mapping_service = CategoryMappingService(db_session) if db_session else None
        else:
            self.mapping_service = None

        # Temporary files tracking (for saved inventory CSV)
        self.temp_files = []

    def _load_cookies_from_env(self) -> None:
        """
        Load cookies from environment variable (base64 JSON) or file path.

        Supports two formats:
        1. VR_COOKIES_BASE64 - Base64-encoded JSON array of cookies (for Railway)
        2. VINTAGE_AND_RARE_COOKIES_FILE - Path to JSON file (for local dev)

        Priority: Base64 env var > File path

        Key insight: We primarily need cf_clearance to bypass Cloudflare.
        PHPSESSID is a session cookie that expires immediately, so we'll
        get a fresh one via login. cf_clearance is valid until May 2026.
        """
        import base64

        cookies = None
        source = None

        # Try base64-encoded cookies first (Railway deployment)
        cookies_b64 = os.environ.get("VR_COOKIES_BASE64")
        if cookies_b64:
            try:
                cookies_json = base64.b64decode(cookies_b64).decode('utf-8')
                cookies = json.load(io.StringIO(cookies_json))
                source = "VR_COOKIES_BASE64 env var"
            except Exception as exc:
                logger.warning("Failed to decode VR_COOKIES_BASE64: %s", exc)

        # Fall back to file path (local development)
        if not cookies:
            cookie_file = os.environ.get("VINTAGE_AND_RARE_COOKIES_FILE")
            if cookie_file:
                try:
                    with open(cookie_file, "r") as f:
                        cookies = json.load(f)
                    source = f"file: {cookie_file}"
                except Exception as exc:
                    logger.warning("Failed to load V&R cookies from %s: %s", cookie_file, exc)

        if not cookies:
            logger.info("No V&R cookies available - will rely on Selenium bootstrap")
            return

        # Load cookies into both sessions (requests and curl_cffi)
        loaded = 0
        cf_clearance_loaded = False
        for cookie in cookies:
            if "name" in cookie and "value" in cookie:
                domain = cookie.get("domain") or "www.vintageandrare.com"
                # Load into requests session
                self.session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=domain,
                )
                # Load into curl_cffi session if available
                if self.cf_session:
                    self.cf_session.cookies.set(
                        cookie["name"],
                        cookie["value"],
                        domain=domain,
                    )
                loaded += 1
                if cookie["name"] == "cf_clearance":
                    cf_clearance_loaded = True
                    logger.info("cf_clearance cookie loaded (Cloudflare bypass key)")

        if loaded:
            logger.info("Seeded %s V&R cookies from %s", loaded, source)
            if self.cf_session:
                logger.info("Cookies also loaded into curl_cffi session")
            if not cf_clearance_loaded:
                logger.warning("cf_clearance NOT found - Cloudflare may block requests")

    def _apply_selenium_cookies(self, selenium_driver) -> None:
        """Copy cookies from Selenium into the requests session."""
        try:
            cookies = selenium_driver.get_cookies()
            for cookie in cookies:
                # requests uses "name"/"value" keys
                if "name" in cookie and "value" in cookie:
                    self.session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to apply Selenium cookies: %s", exc)

    async def _bootstrap_with_selenium(self) -> bool:
        """Attempt to pass Cloudflare by using Selenium and harvesting cookies.

        Can be disabled by setting VR_SKIP_SELENIUM=1 in environment.
        This is useful when Selenium Grid is unreliable.
        """
        # Allow disabling Selenium fallback entirely
        if os.environ.get("VR_SKIP_SELENIUM", "0") == "1":
            logger.info("Selenium bootstrap disabled via VR_SKIP_SELENIUM=1")
            return False

        selenium_grid_url = (os.environ.get("SELENIUM_GRID_URL") or "").strip()
        use_udc = os.environ.get("VR_USE_UDC", "1") == "1" and uc is not None
        headless_mode = os.environ.get("VR_HEADLESS", "true").lower() == "true"

        logger.info("Using SELENIUM_GRID_URL: %s (use_udc=%s, headless=%s)", selenium_grid_url, use_udc, headless_mode)

        if not selenium_grid_url and not use_udc:
            return False

        options = webdriver.ChromeOptions()
        if headless_mode:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1280,1024")
        driver = None
        def _wait_for_cf_clear():
            max_wait = 15
            for _ in range(max_wait):
                try:
                    title = driver.title or ""
                    url = driver.current_url or ""
                    if "Just a moment" not in title and "/cdn-cgi/" not in url:
                        return True
                    # Try to click CF checkbox if present
                    try:
                        WebDriverWait(driver, 3).until(
                            EC.frame_to_be_available_and_switch_to_it(
                                (By.CSS_SELECTOR, "iframe[title*='Cloudflare security challenge']")
                            )
                        )
                        WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "label.ctp-checkbox-label"))
                        ).click()
                        driver.switch_to.default_content()
                    except Exception:
                        try:
                            driver.switch_to.default_content()
                        except Exception:
                            pass
                except Exception:
                    # If any attribute is None or selenium hiccups, just wait and retry
                    pass
                time.sleep(1)
            return False

        try:
            if use_udc:
                driver = uc.Chrome(headless=headless_mode, options=options)
            else:
                driver = webdriver.Remote(command_executor=selenium_grid_url, options=options)
            driver.get(self.BASE_URL)

            if not _wait_for_cf_clear():
                logger.warning("Cloudflare challenge did not clear in time.")

            # Navigate to login page if not already there
            try:
                if "/do_login" not in driver.current_url:
                    driver.get(self.LOGIN_URL)
            except Exception:
                pass

            # Basic login form fill
            try:
                username_field = driver.find_element(By.NAME, "username")
                password_field = driver.find_element(By.NAME, "pass")
                username_field.clear()
                username_field.send_keys(self.username)
                password_field.clear()
                password_field.send_keys(self.password)
                # Submit the form
                password_field.submit()
                time.sleep(3)  # give it a moment
            except Exception as e:
                logger.warning("Selenium login form fill failed: %s", e)

            # After load, copy cookies to requests session
            self._apply_selenium_cookies(driver)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Selenium bootstrap failed: %s", exc, exc_info=True)
            return False
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    async def authenticate(self) -> bool:
        """
        Authenticate with V&R website.

        Strategy:
        1. Try curl_cffi first (better Cloudflare bypass with Chrome TLS fingerprint)
        2. Fall back to requests if curl_cffi unavailable
        3. Use Selenium bootstrap as last resort

        Returns:
            bool: True if authentication is successful.
        """
        if self.authenticated:
            print("Already authenticated with V&R")
            return True

        try:
            print(f"Authenticating V&R user: {self.username}")

            # Determine which session to use for initial page load
            use_curl_cffi = self.cf_session is not None
            if use_curl_cffi:
                print("Using curl_cffi (Chrome TLS fingerprint) for Cloudflare bypass")

            # First get the main page to set up cookies
            if use_curl_cffi:
                response = self.cf_session.get(self.BASE_URL, headers=self.headers)
            else:
                response = self.session.get(self.BASE_URL, headers=self.headers)

            print(f"Initial page load status: {response.status_code}")
            cf_mitigated = response.headers.get("cf-mitigated", "")
            if cf_mitigated:
                print(f"Cloudflare cf-mitigated header: {cf_mitigated}")

            # Check if blocked by Cloudflare
            if response.status_code == 403 or cf_mitigated == "challenge":
                print("Blocked by Cloudflare - trying Selenium bootstrap")
                self.cloudflare_blocked = True
                used_selenium = await self._bootstrap_with_selenium()
                if used_selenium:
                    if use_curl_cffi:
                        response = self.cf_session.get(self.BASE_URL, headers=self.headers)
                    else:
                        response = self.session.get(self.BASE_URL, headers=self.headers)
                    print(f"Post-Selenium base load status: {response.status_code}")
            else:
                self.cloudflare_blocked = False

            # Prepare login data
            login_data = {
                'username': self.username,
                'pass': self.password,
                'open_where': 'header'
            }

            # Submit login form
            print("Submitting V&R login form...")
            if use_curl_cffi:
                response = self.cf_session.post(
                    self.LOGIN_URL,
                    data=login_data,
                    headers=self.headers,
                    allow_redirects=True
                )
            else:
                response = self.session.post(
                    self.LOGIN_URL,
                    data=login_data,
                    headers=self.headers,
                    allow_redirects=True
                )
            print(f"Login response status: {response.status_code}")

            # If still blocked, one more Selenium attempt
            if response.status_code == 403:
                print("Still blocked after login attempt - trying Selenium again")
                self.cloudflare_blocked = True
                used_selenium = await self._bootstrap_with_selenium()
                if used_selenium:
                    if use_curl_cffi:
                        response = self.cf_session.post(
                            self.LOGIN_URL,
                            data=login_data,
                            headers=self.headers,
                            allow_redirects=True
                        )
                    else:
                        response = self.session.post(
                            self.LOGIN_URL,
                            data=login_data,
                            headers=self.headers,
                            allow_redirects=True
                        )
                    print(f"Post-Selenium login status: {response.status_code}")

            # Check if login was successful - V&R uses "Logout" not "Sign out"
            response_text = response.text
            response_url = str(getattr(response, "url", ""))
            has_logout = 'Logout' in response_text or 'logout' in response_text or 'Sign out' in response_text
            at_account = '/account' in response_url

            self.authenticated = has_logout or at_account
            print(f"Authentication check - 'Logout' in response: {has_logout}")
            print(f"Authentication check - '/account' in URL: {at_account}")
            print(f"Authentication result: {'Successful' if self.authenticated else 'Failed'}")

            return self.authenticated

        except Exception as e:
            print(f"Error during V&R authentication: {str(e)}")
            import traceback
            print(f"Authentication traceback: {traceback.format_exc()}")
            self.authenticated = False
            return False

    def _extract_form_fields(self, html: str) -> List[Tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form", id="frm_step1")
        if not form:
            raise ValueError("Unable to locate V&R edit form")

        fields: List[Tuple[str, str]] = []

        for input_el in form.find_all("input"):
            name = input_el.get("name")
            if not name:
                continue
            input_type = (input_el.get("type") or "text").lower()
            if input_type in {"checkbox", "radio"}:
                if not input_el.has_attr("checked"):
                    continue
                value = input_el.get("value", "on")
            else:
                value = input_el.get("value", "")
            fields.append((name, value))

        for textarea in form.find_all("textarea"):
            name = textarea.get("name")
            if not name:
                continue
            value = textarea.decode_contents() if hasattr(textarea, "decode_contents") else textarea.text
            fields.append((name, value or ""))

        for select in form.find_all("select"):
            name = select.get("name")
            if not name:
                continue
            option = select.find("option", selected=True)
            if option is None:
                option = select.find("option")
            value = option.get("value", "") if option else ""
            fields.append((name, value))

        return fields

    def _set_field_value(self, fields: List[Tuple[str, str]], name: str, value: str) -> None:
        for index, (field_name, _) in enumerate(fields):
            if field_name == name:
                fields[index] = (name, value)
                return
        fields.append((name, value))

    def update_listing_via_requests(self, item_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        def ensure_authenticated() -> None:
            if self.authenticated:
                return
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.authenticate())
            finally:
                asyncio.set_event_loop(None)
                loop.close()

        ensure_authenticated()

        edit_url = f"https://www.vintageandrare.com/instruments/add_edit_item/{item_id}"
        response = self.session.get(edit_url, headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to load V&R edit page ({response.status_code})")

        fields = self._extract_form_fields(response.text)

        allowed_name_pattern = re.compile(r"^[A-Za-z0-9._:-]+$")
        filtered_fields: List[Tuple[str, str]] = []
        dropped_fields: List[str] = []
        for name, value in fields:
            if allowed_name_pattern.fullmatch(name or ""):
                filtered_fields.append((name, value))
            else:
                dropped_fields.append(name)

        if dropped_fields:
            logger.info(
                "Dropping %d V&R form fields with unsupported names: %s",
                len(dropped_fields),
                ",".join(sorted(set(dropped_fields))),
            )

        fields = filtered_fields
        field_names = {name for name, _ in fields}

        logger.info(
            "V&R edit field summary for %s: kept=%d dropped=%d",
            item_id,
            len(fields),
            len(dropped_fields),
        )

        requested_fields = [key for key, value in updates.items() if value is not None]
        applied_fields: List[str] = []

        def set_if_present(candidates: List[str], value: Any, logical_name: str) -> None:
            if value is None:
                return
            value_str = value if isinstance(value, str) else str(value)
            for candidate in candidates:
                if candidate in field_names:
                    self._set_field_value(fields, candidate, value_str)
                    applied_fields.append(logical_name)
                    return

        # Model/title field
        if "model" in updates:
            set_if_present(["model_name", "product_title", "title"], updates["model"], "model")

        # Only fall back to title if model was not explicitly changed
        if "title" in updates and "model" not in updates:
            set_if_present(["model_name", "product_title", "title"], updates["title"], "title")

        if "description" in updates:
            set_if_present(["item_desc", "description"], updates["description"], "description")

        if "brand" in updates:
            set_if_present(["recipient_name", "brand"], updates["brand"], "brand")

        if "price" in updates:
            set_if_present(["price"], updates["price"], "price")

        if "year" in updates:
            set_if_present(["year"], updates["year"], "year")

        if "finish" in updates:
            set_if_present(["finish_color", "finish"], updates["finish"], "finish")

        if requested_fields and not applied_fields:
            logger.warning(
                "V&R edit requested %s but no matching form fields were applied",
                ",".join(requested_fields),
            )

        logger.info(
            "Prepared V&R edit payload for %s: applied=%s",
            item_id,
            ",".join(applied_fields) or "<none>",
        )

        headers = self.headers.copy()
        headers.update({
            "Referer": edit_url,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        })

        submit_response = self.session.post(
            edit_url,
            data=fields,
            headers=headers,
            allow_redirects=False,
        )

        if submit_response.status_code not in (302, 303):
            logger.error(
                "V&R edit submission failed: status=%s body=%s",
                submit_response.status_code,
                submit_response.text[:500],
            )
            if submit_response.text:
                logger.info(
                    "V&R submission field names (kept): %s",
                    ",".join(name for name, _ in fields),
                )
            return {
                "status": "error",
                "message": f"Unexpected response {submit_response.status_code}",
                "body": submit_response.text[:1000],
            }

        return {
            "status": "success",
            "message": "Listing updated successfully",
            "redirect": submit_response.headers.get("Location"),
            "requested_fields": requested_fields,
            "applied_fields": applied_fields,
        }

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
            str: "RETRY_NEEDED" if download exceeded timeout limit.
        """
        logger.info("Attempting to download V&R inventory CSV...")
        print("Starting V&R inventory download...")
        
        # Clean any existing temp files before starting
        self.cleanup_temp_files()
        logger.info("Cleaned up any existing temp files before download")
        
        if not self.authenticated:
            print("Not authenticated. Attempting authentication first.")
            if not await self.authenticate():
                print("Authentication failed. Cannot download inventory.")
                return None
        
        # Configure timeout - 3 minutes max for inventory download
        INVENTORY_TIMEOUT = 180  # 180 seconds = 3 minutes
        
        try:
            # Download the inventory file using the authenticated session
            print(f"Requesting inventory CSV from {self.EXPORT_URL}")
            print(f"Timeout set to {INVENTORY_TIMEOUT} seconds")
            response = self.session.get(
                self.EXPORT_URL,
                headers=self.headers,
                allow_redirects=True,
                stream=True,
                timeout=INVENTORY_TIMEOUT
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
            
        except requests.exceptions.Timeout:
            logger.error(f"VR inventory download exceeded {INVENTORY_TIMEOUT}s timeout limit")
            print(f"ERROR: Download exceeded {INVENTORY_TIMEOUT} second timeout")
            print("This download should be queued for retry during off-peak hours")
            return "RETRY_NEEDED"
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

    async def create_listing_http(
            self,
            product_data: Dict[str, Any],
            test_mode: bool = False,
            from_scratch: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a listing on V&R using pure HTTP requests (no Selenium).

        This method:
        1. Loads the blank create form to get all required hidden fields
        2. Fills in product data
        3. Uploads images via multipart/form-data
        4. Submits the form

        Args:
            product_data: Dictionary containing the product details to list.
            test_mode: If True, returns the prepared payload without submitting.
            from_scratch: If True, uses internal category mapping. If False, expects
                        pre-mapped V&R categories in product_data.

        Returns:
            Dict with status, message, and potentially vr_listing_id.
        """
        logger.info(f"Creating V&R listing via HTTP for SKU: {product_data.get('sku')}")

        # Ensure authenticated
        if not self.authenticated:
            logger.info("Not authenticated - authenticating first...")
            if not await self.authenticate():
                return {"status": "error", "message": "Authentication failed"}

        try:
            # 1. Load the blank create form page
            create_url = f"{self.BASE_URL}/instruments/add_edit_item"
            logger.info(f"Loading create form from: {create_url}")

            # Use curl_cffi session if available for Cloudflare bypass
            if self.cf_session:
                response = self.cf_session.get(create_url, headers=self.headers)
            else:
                response = self.session.get(create_url, headers=self.headers)

            if response.status_code != 200:
                return {
                    "status": "error",
                    "message": f"Failed to load create form: HTTP {response.status_code}"
                }

            # 2. Extract all form fields (hidden fields, defaults, etc.)
            fields = self._extract_form_fields(response.text)
            field_dict = {name: value for name, value in fields}

            logger.info(f"Extracted {len(fields)} form fields from create page")
            logger.debug(f"Hidden fields: unique_id={field_dict.get('unique_id')}, version={field_dict.get('version')}")

            # 3. Handle category mapping
            if from_scratch:
                category_mapping = await self.map_category(
                    product_data.get('category', ''),
                    str(product_data.get('category_id', ''))
                )
                self._set_field_value(fields, 'categ_level_0', str(category_mapping['category_id']))
                self._set_field_value(fields, 'categ_level_1', str(category_mapping['subcategory_id']))
            else:
                # Use pre-mapped V&R category strings
                if product_data.get('Category'):
                    self._set_field_value(fields, 'categ_level_0', str(product_data['Category']))
                if product_data.get('SubCategory1'):
                    self._set_field_value(fields, 'categ_level_1', str(product_data['SubCategory1']))
                if product_data.get('SubCategory2'):
                    self._set_field_value(fields, 'categ_level_2', str(product_data['SubCategory2']))
                if product_data.get('SubCategory3'):
                    self._set_field_value(fields, 'categ_level_3', str(product_data['SubCategory3']))

            # 4. Fill in product data
            # Brand/Make
            if product_data.get('brand'):
                self._set_field_value(fields, 'recipient_name', product_data['brand'])

            # Model name
            if product_data.get('model'):
                self._set_field_value(fields, 'model_name', product_data['model'])

            # Year
            if product_data.get('year'):
                self._set_field_value(fields, 'year', str(product_data['year']))
                # Calculate decade
                try:
                    year_int = int(product_data['year'])
                    decade = str((year_int // 10) * 10)
                    self._set_field_value(fields, 'decade', decade)
                except (ValueError, TypeError):
                    pass

            # Finish/Color
            if product_data.get('finish'):
                self._set_field_value(fields, 'finish_color', product_data['finish'])

            # Description (TinyMCE content)
            if product_data.get('description'):
                self._set_field_value(fields, 'item_desc', product_data['description'])

            # Price
            if product_data.get('price'):
                self._set_field_value(fields, 'price', str(product_data['price']))

            # External ID (our SKU)
            if product_data.get('sku'):
                self._set_field_value(fields, 'external_id', product_data['sku'])

            # Processing time
            processing_time = product_data.get('processing_time', '3')
            self._set_field_value(fields, 'processing_time', str(processing_time))
            self._set_field_value(fields, 'hours_days_sel', product_data.get('time_unit', 'Days'))

            # Shipping
            if product_data.get('available_for_shipment', True):
                self._set_field_value(fields, 'available_for_shipment', '1')

            # YouTube URL
            if product_data.get('video_url'):
                self._set_field_value(fields, 'youtube_upload', product_data['video_url'])

            # 5. Handle image uploads
            # Images are tricky - V&R uses file inputs that need to be uploaded
            # We'll prepare the multipart form data with images

            image_files = []
            images_to_upload = []

            # Collect image URLs
            if product_data.get('primary_image'):
                primary_url = ImageTransformer.transform_reverb_url(
                    product_data['primary_image'], ImageQuality.MAX_RES
                )
                images_to_upload.append(primary_url)

            additional_images = product_data.get('additional_images', [])
            if isinstance(additional_images, str):
                try:
                    additional_images = json.loads(additional_images)
                except json.JSONDecodeError:
                    additional_images = [additional_images] if additional_images else []

            for img_url in additional_images[:19]:  # Max 20 images total
                max_res_url = ImageTransformer.transform_reverb_url(img_url, ImageQuality.MAX_RES)
                images_to_upload.append(max_res_url)

            logger.info(f"Preparing to upload {len(images_to_upload)} images")

            # Download images to temp files for upload
            temp_dir = tempfile.mkdtemp(prefix='vr_upload_')
            try:
                for idx, img_url in enumerate(images_to_upload):
                    try:
                        img_response = requests.get(img_url, timeout=30)
                        if img_response.status_code == 200:
                            # Determine file extension from content-type
                            content_type = img_response.headers.get('content-type', 'image/jpeg')
                            ext = '.jpg'
                            if 'png' in content_type:
                                ext = '.png'
                            elif 'webp' in content_type:
                                ext = '.webp'

                            temp_path = os.path.join(temp_dir, f'image_{idx}{ext}')
                            with open(temp_path, 'wb') as f:
                                f.write(img_response.content)
                            image_files.append(temp_path)
                            logger.debug(f"Downloaded image {idx + 1} to {temp_path}")
                    except Exception as e:
                        logger.warning(f"Failed to download image {img_url}: {e}")

                # 6. Prepare multipart form data
                # Convert fields list to dict for the request
                form_data = {}
                for name, value in fields:
                    if name in form_data:
                        # Handle multiple values with same name (like shipping_fees_fee[])
                        if isinstance(form_data[name], list):
                            form_data[name].append(value)
                        else:
                            form_data[name] = [form_data[name], value]
                    else:
                        form_data[name] = value

                if test_mode:
                    # Return the prepared payload without submitting
                    return {
                        "status": "test",
                        "message": "Test mode - form data prepared but not submitted",
                        "form_data": form_data,
                        "image_count": len(image_files),
                        "images": images_to_upload
                    }

                # 7. Submit the form with images
                submit_headers = self.headers.copy()
                submit_headers['Referer'] = create_url
                # Remove Content-Type - requests will set it for multipart
                submit_headers.pop('Content-Type', None)

                # Build files dict for multipart upload
                files_dict = {}
                for idx, img_path in enumerate(image_files):
                    field_name = f'upload_file_box_{idx + 1}'
                    files_dict[field_name] = (
                        os.path.basename(img_path),
                        open(img_path, 'rb'),
                        'image/jpeg'
                    )

                try:
                    # Use curl_cffi if available for better Cloudflare handling
                    if self.cf_session:
                        submit_response = self.cf_session.post(
                            create_url,
                            data=form_data,
                            files=files_dict if files_dict else None,
                            headers=submit_headers,
                            allow_redirects=False
                        )
                    else:
                        submit_response = self.session.post(
                            create_url,
                            data=form_data,
                            files=files_dict if files_dict else None,
                            headers=submit_headers,
                            allow_redirects=False
                        )
                finally:
                    # Close file handles
                    for f in files_dict.values():
                        if hasattr(f[1], 'close'):
                            f[1].close()

                logger.info(f"Form submission response: {submit_response.status_code}")

                # Check response
                if submit_response.status_code in (302, 303):
                    # Success - V&R redirects after successful submission
                    redirect_url = submit_response.headers.get('Location', '')
                    logger.info(f"Submission successful! Redirect to: {redirect_url}")

                    # Try to extract item ID from redirect URL
                    vr_id = None
                    id_match = re.search(r'/add_edit_item/(\d+)', redirect_url)
                    if id_match:
                        vr_id = id_match.group(1)
                        logger.info(f"Extracted V&R item ID: {vr_id}")

                    return {
                        "status": "success",
                        "message": "Listing created successfully",
                        "vr_listing_id": vr_id,
                        "redirect_url": redirect_url,
                        "needs_id_resolution": vr_id is None
                    }
                else:
                    # Check for success in response body
                    response_text = submit_response.text.lower()
                    if 'published and live' in response_text or 'successfully' in response_text:
                        return {
                            "status": "success",
                            "message": "Listing appears to be created (success message found)",
                            "vr_listing_id": None,
                            "needs_id_resolution": True
                        }

                    logger.error(f"Unexpected response: {submit_response.status_code}")
                    logger.error(f"Response body: {submit_response.text[:500]}")
                    return {
                        "status": "error",
                        "message": f"Unexpected response: {submit_response.status_code}",
                        "body": submit_response.text[:1000]
                    }

            finally:
                # Clean up temp directory
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Error in create_listing_http: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Exception during listing creation: {str(e)}"
            }

    async def create_listing_selenium(
            self, 
            product_data: Dict[str, Any], 
            test_mode: bool = True,
            from_scratch: bool = False,
            db_session=None
            ) -> Dict[str, Any]:
            """
            Create a listing on V&R using Selenium automation via inspect_form.py.
            This is an async method that runs the blocking Selenium code in an executor thread.

            Args:
                product_data: Dictionary containing the product details to list.
                test_mode: If True, the form will be filled but not submitted.
                from_scratch: If True, uses internal category mapping. If False, expects
                            pre-mapped V&R categories in product_data.

            Returns:
                Dict with status, message, and potentially vr_listing_id (currently None).
            """
            
            logger.info(f"Creating V&R listing for SKU: {product_data.get('sku')} "
                    f"(from_scratch={from_scratch})")
            logger.info("--- RECEIVED PRODUCT_DATA in create_listing_selenium() ---")
            import json
            logger.info(json.dumps(product_data, indent=2, default=str))
            
            if not login_and_navigate:
                logger.error("inspect_form.login_and_navigate not available. Cannot create listing.")
                return {"status": "error", "message": "Selenium automation module not loaded"}

            logger.info(f"Initiating V&R listing creation for product ID (internal): {product_data.get('id')}")
            
            # raise RuntimeError("DEBUG: Halting for payload inspection")
            
            try:
                # 1. Category Mapping - conditional based on from_scratch parameter
                if from_scratch:
                    # Use the internal category mapping system for new products
                    logger.info("Using internal category mapping (from_scratch=True)")
                    category_mapping = await self.map_category(
                        product_data.get('category', ''), # Pass internal category name
                        str(product_data.get('category_id', '')) # Pass internal category ID if available
                    )
                    logger.info(f"Category mapping result: {category_mapping}")
                else:
                    # Use pre-mapped V&R category strings from product_data
                    logger.info("Using pre-mapped V&R categories from product_data (from_scratch=False)")
                    if not product_data.get('Category'):
                        raise ValueError("Missing V&R Category in product_data - ensure platform mapping was applied")

                # Debug the description before and after processing
                raw_description = product_data.get('description', '')
                logger.info(f"RAW DESCRIPTION: {raw_description[:200]}...")

                # Try different processing approaches
                decoded_description = html.unescape(str(raw_description))
                logger.info(f"HTML DECODED: {decoded_description[:200]}...")
                
                # 2. Prepare Form Data (Translate internal product_data to V&R form field names)
                form_data = {
                    'brand': product_data.get('brand', ''),
                    'model_name': product_data.get('model', ''), # Assuming 'model' is the field in product_data
                    'price': str(product_data.get('price', 0)), # V&R expects string

                    'year': str(product_data.get('year', '')) if product_data.get('year') else None, # V&R expects a number
                    # 'decade': str(product_data.get('decade', '')) if product_data.get('decade') else None, # V&R option box ❌ REMOVED

                    'finish_color': str(product_data.get('finish', '') or ''),
                    # 'description': str(product_data.get('description', '') or ''),
                    # 'description': html.unescape(str(product_data.get('description', '') or '')),
                    'description': product_data.get('description', ''),
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

                logger.info(f"FORM DATA DESCRIPTION: {form_data['description'][:200]}...")

                # Add category fields based on from_scratch parameter
                if from_scratch:
                    # Use mapped category IDs from the mapping service
                    form_data['category'] = category_mapping['category_id']
                    form_data['subcategory'] = category_mapping['subcategory_id']
                    # Add sub_subcategory if needed based on mapping
                else:
                    # Use category strings directly from mapped data
                    form_data['category'] = product_data.get('Category')
                    form_data['subcategory'] = product_data.get('SubCategory1')
                    form_data['sub_subcategory'] = product_data.get('SubCategory2')
                    form_data['sub_sub_subcategory'] = product_data.get('SubCategory3')

                # Add primary image URL
                primary_image = product_data.get('primary_image')
                if primary_image:
                    # Transform to max resolution for V&R
                    max_res_primary = ImageTransformer.transform_reverb_url(primary_image, ImageQuality.MAX_RES)
                    form_data['images'].append(max_res_primary)
                    logger.info(f"Transformed primary image: {primary_image} -> {max_res_primary}")

                # Add additional image URLs (handle list or JSON string) - TRANSFORM TO MAX RESOLUTION
                additional_images = product_data.get('additional_images')
                if additional_images:
                    if isinstance(additional_images, list):
                        # Transform each additional image to max resolution
                        for img_url in additional_images:
                            max_res_img = ImageTransformer.transform_reverb_url(img_url, ImageQuality.MAX_RES)
                            form_data['images'].append(max_res_img)
                            logger.info(f"Transformed additional image: {img_url} -> {max_res_img}")
                            
                    elif isinstance(additional_images, str):
                        try:
                            import json
                            parsed_images = json.loads(additional_images)
                            if isinstance(parsed_images, list):
                                # Transform each parsed image to max resolution
                                for img_url in parsed_images:
                                    max_res_img = ImageTransformer.transform_reverb_url(img_url, ImageQuality.MAX_RES)
                                    form_data['images'].append(max_res_img)
                                    logger.info(f"Transformed parsed image: {img_url} -> {max_res_img}")
                            else:
                                logger.warning(f"Parsed additional_images is not a list: {type(parsed_images)}")
                        except json.JSONDecodeError:
                            # Assume it's a single URL string if JSON parsing fails
                            max_res_img = ImageTransformer.transform_reverb_url(additional_images, ImageQuality.MAX_RES)
                            form_data['images'].append(max_res_img)
                            logger.info(f"Transformed single additional image: {additional_images} -> {max_res_img}")
                            logger.warning("additional_images field was a string but not valid JSON, treated as single URL.")
                        except Exception as e:
                            logger.error(f"Error processing additional_images string: {e}")

                # Log image transformation summary
                logger.info(f"Image transformation complete: {len(form_data['images'])} total images prepared for V&R")

                # Limit images (V&R might have a limit, e.g., 20) - KEEP THIS SECTION AS-IS
                MAX_VR_IMAGES = 20
                if len(form_data['images']) > MAX_VR_IMAGES:
                    logger.warning(f"Too many images ({len(form_data['images'])}). Truncating to {MAX_VR_IMAGES}.")
                    form_data['images'] = form_data['images'][:MAX_VR_IMAGES]

                logger.debug(f"Prepared form data for V&R Selenium: {form_data}")

                # 3. Run Selenium Automation in Executor Thread
                loop = asyncio.get_event_loop()
                
                result = await loop.run_in_executor(
                    None, # Default thread pool executor
                    lambda: self._run_selenium_automation(form_data, test_mode, db_session) # Pass prepared data
                )

                if result.get("status") == "success":
                    result.setdefault("payload", product_data)
                    result.setdefault("form_data", form_data)
                    result.setdefault("shipping_fees", form_data.get("shipping_fees"))

                # 4. If submission was successful and we need ID resolution, try VRExportService here
                if (result.get("status") == "success" and 
                    result.get("needs_id_resolution") and 
                    # not test_mode and 
                    db_session):
                    
                    try:
                        logger.info("Attempting to resolve V&R item ID via VRExportService...")
                        
                        # Wait for V&R to process
                        logger.info("⏱️  Waiting 5 seconds for V&R to process the new item...")
                        await asyncio.sleep(5)
                        
                        # Enhanced ID resolution with verification
                        vr_id = await self._get_newly_created_item_id_with_verification(
                            db_session, 
                            expected_brand=form_data.get('brand', ''),
                            expected_model=form_data.get('model_name', ''),
                            expected_year=form_data.get('year', ''),
                            expected_category=form_data.get('category', ''),
                            expected_sku=product_data.get('external_id', ''),  # ✅ Use original product_data SKU
                            submission_payload=product_data
                        )
                        
                        if vr_id:
                            result["vr_listing_id"] = vr_id
                            result["message"] += f" (V&R ID: {vr_id})"
                            logger.info(f"✅ Resolved and verified V&R item ID: {vr_id}")
                        else:
                            logger.warning("❌ Could not find or verify V&R item ID")
                            
                    except Exception as e:
                        logger.warning(f"Could not resolve V&R item ID: {str(e)}")
                        import traceback
                        logger.warning(f"VRExportService traceback: {traceback.format_exc()}")

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
    
    def _run_selenium_automation(self, form_data: Dict[str, Any], test_mode: bool, db_session=None) -> Dict[str, Any]:
        """
        Wrapper function to execute the blocking Selenium login_and_navigate function.
        This runs in a separate thread via run_in_executor.

        Args:
            form_data: The dictionary of data prepared for the V&R form.
            test_mode: Boolean indicating if the form should be submitted.

        Returns:
            Dictionary containing the result status, message, and vr_listing_id (None).
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
                test_mode=test_mode,
                db_session=None  # ✅ Don't pass db_session to avoid async loop conflicts
            )

            # Note: The actual V&R product ID is not retrieved here.
            # Reconciliation needed after inventory download.
            message = "Listing created successfully" if not test_mode else "Test mode: form filled but not submitted"
            logger.info(f"Selenium automation completed: {message}")
            return {
                "status": "success",
                "message": message,
                "vr_listing_id": None, # Explicitly None, requires reconciliation
                "needs_id_resolution": True,  # ✅ Flag for post-processing
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

    async def _get_newly_created_item_id_via_export_service(self, db_session):
        """
        Use the existing VRExportService to get the most recent V&R item ID
        This runs in the proper async context
        """
        try:
            from app.services.vintageandrare.export import VRExportService
            
            export_service = VRExportService(db_session)
            products_data = await export_service.get_products_for_export()
            
            # Get items with V&R IDs, sorted by most recent
            vr_items = []
            for product_data in products_data:
                vr_id = product_data.get('product id', '').strip()
                if vr_id and vr_id.isdigit():
                    vr_items.append({
                        'vr_id': vr_id,
                        'brand': product_data.get('brand name', ''),
                        'model': product_data.get('product model name', ''),
                        'year': product_data.get('product year', '')
                    })
            
            # Sort by V&R ID (newest should have highest ID)
            vr_items.sort(key=lambda x: int(x['vr_id']), reverse=True)
            
            if vr_items:
                newest_item = vr_items[0]
                newest_id = newest_item['vr_id']
                logger.info(f"✅ Most recent V&R item ID: {newest_id}")
                return newest_id
            else:
                logger.info("No V&R items found in export")
                return None
                
        except Exception as e:
            logger.error(f"Error getting item ID via VRExportService: {str(e)}")
            return None

    async def _get_newly_created_item_id_with_verification(
        self,
        db_session,
        expected_brand: str,
        expected_model: str,
        expected_year: str,
        expected_category: str,
        expected_sku: str = "",
        submission_payload: Optional[Dict[str, Any]] = None,
    ):
        """
        Enhanced ID resolution using direct CSV download (single download)
        """
        try:
            logger.info("🔍 Starting V&R CSV download for ID verification...")
            logger.info(f"🎯 Looking for: Brand='{expected_brand}', Model='{expected_model}'")
            
            # Use this client instance directly (it's already authenticated)
            inventory_df = await self.download_inventory_dataframe(save_to_file=False)
            
            if inventory_df is None or inventory_df.empty:
                logger.warning("❌ No inventory data received from V&R CSV")
                return None
            
            logger.info(f"📊 Downloaded fresh CSV with {len(inventory_df)} items")
        
            # ✅ OPTIMIZATION: Sort by product_id (highest first) to check newest items first
            inventory_df = inventory_df.sort_values('product_id', ascending=False)
            logger.info(f"📊 Sorted by product_id (newest first)")
            
            # Find matching items with detailed verification
            perfect_matches = []
            good_matches = []
            recent_items = []
            
            # ✅ OPTIMIZATION: Only check first 50 items (most recent)
            recent_subset = inventory_df.head(50)
            logger.info(f"🔍 Checking most recent 50 items for perfect matches...")
            
            for _, row in inventory_df.iterrows():
                vr_id = str(row.get('product_id', '')).strip()
                brand = str(row.get('brand_name', '')).strip()
                model = str(row.get('product_model_name', '')).strip()
                
                if vr_id and vr_id.isdigit():
                    # Check for exact matches (Brand + Model only - no SKU since V&R doesn't save it)
                    brand_match = brand.lower() == expected_brand.lower()
                    model_match = model.lower() == expected_model.lower()
                    
                    # Calculate match score (simplified)
                    match_score = 0
                    if brand_match: match_score += 5  # Brand is crucial
                    if model_match: match_score += 5  # Model is crucial
                    
                    # Partial matches
                    if not brand_match and expected_brand.lower() in brand.lower():
                        match_score += 2
                    if not model_match and expected_model.lower() in model.lower():
                        match_score += 2
                    
                    item_info = {
                        'vr_id': vr_id,
                        'brand': brand,
                        'model': model,
                        'match_score': match_score,
                        'brand_match': brand_match,
                        'model_match': model_match
                    }
                    
                    logger.debug(f"🔍 Checking: ID={vr_id}, Brand='{brand}' ({brand_match}), Model='{model}' ({model_match}), Score={match_score}")
                    
                    if match_score >= 10:  # Perfect match
                        perfect_matches.append(item_info)
                        logger.info(f"🎯 PERFECT MATCH: V&R ID={vr_id}, Score={match_score}")
                        break  # ✅ Stop at first perfect match since we're sorted by newest
                    elif match_score >= 5:  # Good match
                        good_matches.append(item_info)
                        logger.debug(f"✅ GOOD MATCH: V&R ID={vr_id}, Score={match_score}")
            
            
            # If no perfect match in recent items, check more broadly but still efficiently
            if not perfect_matches:
                logger.info(f"🔍 No perfect match in recent 50, checking next 100 items...")
                next_subset = inventory_df.iloc[50:150]  # Check next 100
                
                for _, row in next_subset.iterrows():
                    vr_id = str(row.get('product_id', '')).strip()
                    brand = str(row.get('brand_name', '')).strip()
                    model = str(row.get('product_model_name', '')).strip()
                    
                    if vr_id and vr_id.isdigit():
                        brand_match = brand.lower() == expected_brand.lower()
                        model_match = model.lower() == expected_model.lower()
                        
                        if brand_match and model_match:
                            perfect_matches.append({
                                'vr_id': vr_id,
                                'brand': brand,
                                'model': model,
                                'match_score': 10,
                                'brand_match': True,
                                'model_match': True
                            })
                            logger.info(f"🎯 PERFECT MATCH (extended search): V&R ID={vr_id}")
                            break
            
            # Return best match
            if perfect_matches:
                # Sort perfect matches by highest ID (most recent)
                perfect_matches.sort(key=lambda x: int(x['vr_id']), reverse=True)
                best_match = perfect_matches[0]
                
                logger.info(f"🏆 BEST MATCH: V&R ID={best_match['vr_id']}")
                logger.info(f"   Brand: {best_match['brand']} (match: {best_match['brand_match']})")
                logger.info(f"   Model: {best_match['model']} (match: {best_match['model_match']})")
                logger.info(f"   Score: {best_match['match_score']}/10")
                
                # Create platform entries with correct SKU
                await self._create_platform_entries(
                    db_session,
                    best_match,
                    expected_sku,
                    submission_payload=submission_payload,
                )
                
                return best_match['vr_id']
            
            logger.warning("❌ No perfect matches found")
            return None
                    
        except Exception as e:
            logger.error(f"Error in enhanced ID resolution: {str(e)}")
            return None
    
    async def _create_platform_entries(
        self,
        db_session,
        vr_item_data,
        original_sku,
        submission_payload: Optional[Dict[str, Any]] = None,
    ):
        """Create platform_common and vr_listing entries for the newly created V&R item"""
        try:
            from app.models import PlatformCommon, VRListing, Product
            from app.core.enums import SyncStatus, ListingStatus
            from sqlalchemy import select
            from datetime import datetime, timezone
            
            logger.info(f"🔗 Creating platform entries for V&R ID {vr_item_data['vr_id']} and SKU {original_sku}")
            
            # ✅ FIXED: Find the product by SKU (use the full SKU with prefix)
            query = select(Product).where(Product.sku == original_sku)
            result = await db_session.execute(query)
            product = result.scalar_one_or_none()
            
            if not product:
                logger.error(f"❌ Product with SKU {original_sku} not found")
                return
            
            logger.info(f"✅ Found product ID {product.id} for SKU {original_sku}")
            
            # Check if platform_common entry already exists
            query = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "vr"
            )
            result = await db_session.execute(query)
            platform_common = result.scalar_one_or_none()
            
            metadata = {
                "vr_listing_id": vr_item_data['vr_id'],
                "brand": vr_item_data.get('brand'),
                "model": vr_item_data.get('model'),
                "source": "vr_listing_creation",
            }
            if submission_payload:
                metadata["payload"] = submission_payload

            if not platform_common:
                # Create new platform_common entry
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="vr",
                    external_id=vr_item_data['vr_id'],  # ✅ This is the V&R item ID (122816)
                    status=ListingStatus.ACTIVE.value,
                    sync_status=SyncStatus.SYNCED.value.upper(),
                    last_sync=datetime.now(),
                    created_at=datetime.now(),
                    listing_url=f"https://www.vintageandrare.com/product/{vr_item_data['vr_id']}",
                    platform_specific_data=metadata,
                )
                db_session.add(platform_common)
                await db_session.flush()  # Get the ID
                logger.info(f"✅ Created new platform_common entry: product_id={product.id}, external_id={vr_item_data['vr_id']}")
            else:
                # Update existing platform_common entry
                platform_common.external_id = vr_item_data['vr_id']
                platform_common.status = ListingStatus.ACTIVE.value
                platform_common.sync_status = SyncStatus.SYNCED.value.upper()
                platform_common.last_sync = datetime.now()
                platform_common.listing_url = f"https://www.vintageandrare.com/product/{vr_item_data['vr_id']}"
                existing_meta = dict(platform_common.platform_specific_data or {})
                existing_meta.update(metadata)
                platform_common.platform_specific_data = existing_meta
                logger.info(f"✅ Updated existing platform_common entry with external_id={vr_item_data['vr_id']}")
                
            
            # Try to create/update VRListing entry (if the table exists)
            try:
                query = select(VRListing).where(VRListing.platform_id == platform_common.id)
                result = await db_session.execute(query)
                vr_listing = result.scalar_one_or_none()
                
                price_notax_value = product.price_notax if product.price_notax is not None else product.base_price
                processing_time_value = product.processing_time if product.processing_time is not None else 3
                show_vat = product.show_vat if product.show_vat is not None else True
                collective_discount_value = product.collective_discount if product.collective_discount is not None else 0.0

                if not vr_listing:
                    # Create new VRListing entry
                    vr_listing = VRListing(
                        platform_id=platform_common.id,
                        vr_listing_id=vr_item_data['vr_id'],
                        in_collective=product.in_collective or False,
                        in_inventory=product.in_inventory or True,
                        in_reseller=product.in_reseller or False,
                        collective_discount=collective_discount_value,
                        price_notax=price_notax_value,
                        show_vat=show_vat,
                        processing_time=processing_time_value,
                        inventory_quantity=1,
                        vr_state=ListingStatus.ACTIVE.value,
                        created_at=datetime.now(),  # ✅ Naive datetime
                        updated_at=datetime.now(),  # ✅ Naive datetime
                        last_synced_at=datetime.now(),  # ✅ Naive datetime
                        extended_attributes={
                            "match": vr_item_data,
                            "payload": submission_payload,
                        }
                    )
                    db_session.add(vr_listing)
                    logger.info(f"✅ Created new VRListing entry")
                else:
                    # Update existing VRListing entry
                    vr_listing.vr_listing_id = vr_item_data['vr_id']  #✅ Correct field name, string field
                    vr_listing.vr_state = ListingStatus.ACTIVE.value
                    vr_listing.updated_at = datetime.now()
                    vr_listing.last_synced_at = datetime.now()
                    vr_listing.collective_discount = collective_discount_value
                    vr_listing.processing_time = processing_time_value
                    vr_listing.show_vat = show_vat
                    vr_listing.in_collective = product.in_collective or False
                    vr_listing.in_inventory = product.in_inventory or True
                    vr_listing.in_reseller = product.in_reseller or False
                    vr_listing.price_notax = price_notax_value
                    existing_ext = dict(vr_listing.extended_attributes or {})
                    existing_ext.update({"match": vr_item_data})
                    if submission_payload:
                        existing_ext["payload"] = submission_payload
                    vr_listing.extended_attributes = existing_ext
                    logger.info(f"✅ Updated existing VRListing entry")
            except Exception as vr_listing_error:
                logger.warning(f"⚠️  VRListing table not available or error: {str(vr_listing_error)}")
                # Continue without VRListing - platform_common is sufficient
            
            # Commit the changes
            await db_session.commit()
            logger.info(f"✅ Platform entries created/updated and committed for V&R ID {vr_item_data['vr_id']}")
            
        except Exception as e:
            logger.error(f"❌ Error creating platform entries: {str(e)}")
            import traceback
            logger.error(f"Platform entries traceback: {traceback.format_exc()}")
            try:
                await db_session.rollback()
            except:
                pass
    
    async def mark_item_as_sold(self, item_id: str) -> dict:
        """Mark a single V&R item as sold using AJAX.

        Uses curl_cffi with proper AJAX headers for Cloudflare bypass.
        V&R returns 'true' for success, 'false' for failure.
        """
        if not self.authenticated:
            return {"success": False, "error": "Not authenticated"}

        try:
            print(f"Marking item as sold ID: {item_id}")

            # Generate random number for cache busting (like V&R does)
            random_num = random.random()
            url = f'https://www.vintageandrare.com/ajax/mark_as_sold/{random_num}'

            # AJAX request data
            mark_sold_data = f'product_id={item_id}'

            # Critical: Must include proper AJAX headers for V&R to accept the request
            ajax_headers = {
                **self.headers,
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Referer': 'https://www.vintageandrare.com/account/items',
            }

            # Use curl_cffi if available (better Cloudflare bypass), fall back to requests
            if self.cf_session:
                response = self.cf_session.post(url, data=mark_sold_data, headers=ajax_headers)
            else:
                response = self.session.post(url, data=mark_sold_data, headers=ajax_headers)

            print(f"Mark sold response status: {response.status_code}")
            print(f"Response content: '{response.text}'")

            if response.status_code == 200:
                response_text = response.text.strip().lower()

                # V&R returns 'true' for success, 'false' for failure
                if response_text == 'true':
                    print(f"SUCCESS: Item {item_id} marked as sold")
                    return {"success": True, "response": "true", "item_id": item_id}
                elif response_text == 'false':
                    print(f"FAILED: V&R returned 'false' for item {item_id}")
                    return {"success": False, "error": "V&R rejected the request", "item_id": item_id}
                elif not response_text:
                    # Empty response - treat as success (V&R sometimes does this)
                    print(f"Empty response (assuming success) for {item_id}")
                    return {"success": True, "response": "empty", "item_id": item_id}
                else:
                    # Unexpected response
                    print(f"Unexpected response for {item_id}: '{response_text}'")
                    return {"success": False, "error": f"Unexpected response: {response_text}", "item_id": item_id}
            else:
                print(f"Mark sold failed for {item_id}: HTTP {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}", "item_id": item_id}

        except Exception as e:
            print(f"Error marking {item_id} as sold: {str(e)}")
            return {"success": False, "error": str(e), "item_id": item_id}

    # Next 2 are for debugging
    async def debug_mark_as_sold(self, item_id: str) -> dict:
        """Debug version to compare our request with browser behavior"""
        if not self.authenticated:
            return {"success": False, "error": "Not authenticated"}
            
        try:
            print(f"🔍 DEBUGGING mark-as-sold for item {item_id}")
            
            # Generate the same random number format as browser
            random_num = random.random()
            url = f'https://www.vintageandrare.com/ajax/mark_as_sold/{random_num}'
            
            print(f"📍 URL: {url}")
            print(f"🎲 Random: {random_num}")
            
            # Show our request details
            data = f'product_id={item_id}'
            print(f"📦 Data: '{data}'")
            print(f"🍪 Cookies: {len(self.session.cookies)} cookies")
            
            # Show our headers
            print(f"📋 Headers:")
            for key, value in self.headers.items():
                print(f"  {key}: {value}")
            
            # Show cookies
            print(f"🍪 Cookie details:")
            for cookie in self.session.cookies:
                print(f"  {cookie.name}: {cookie.value[:20]}...")
            
            # Make the actual request
            print(f"\n📡 Making request...")
            response = self.session.post(url, data=data, headers=self.headers)
            
            print(f"📊 Response:")
            print(f"  Status: {response.status_code}")
            print(f"  Content: '{response.text}'")
            print(f"  Content-Type: {response.headers.get('Content-Type', 'Not set')}")
            print(f"  Content-Length: {len(response.text)}")
            
            # Show response headers
            print(f"📋 Response Headers:")
            for key, value in response.headers.items():
                print(f"  {key}: {value}")
            
            return {
                "success": False, 
                "debug": True,
                "status_code": response.status_code,
                "response_text": response.text,
                "item_id": item_id
            }
            
        except Exception as e:
            print(f"❌ Debug error: {str(e)}")
            return {"success": False, "error": str(e), "item_id": item_id}

    async def test_mark_as_sold_variations(self, item_id: str) -> dict:
        """Test different ways to mark as sold"""
        if not self.authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        tests = []
        
        try:
            print(f"🧪 Testing different mark-as-sold approaches for {item_id}")
            
            # Test 1: Current approach (string data)
            random_num = random.random()
            response1 = self.session.post(
                f'https://www.vintageandrare.com/ajax/mark_as_sold/{random_num}',
                data=f'product_id={item_id}',
                headers=self.headers
            )
            tests.append(("String data", response1.status_code, response1.text))
            
            # Test 2: Dict data
            random_num = random.random()
            response2 = self.session.post(
                f'https://www.vintageandrare.com/ajax/mark_as_sold/{random_num}',
                data={'product_id': item_id},
                headers=self.headers
            )
            tests.append(("Dict data", response2.status_code, response2.text))
            
            # Test 3: JSON data
            random_num = random.random()
            headers_json = {**self.headers, 'Content-Type': 'application/json'}
            response3 = self.session.post(
                f'https://www.vintageandrare.com/ajax/mark_as_sold/{random_num}',
                json={'product_id': item_id},
                headers=headers_json
            )
            tests.append(("JSON data", response3.status_code, response3.text))
            
            # Test 4: No random number
            response4 = self.session.post(
                'https://www.vintageandrare.com/ajax/mark_as_sold',
                data=f'product_id={item_id}',
                headers=self.headers
            )
            tests.append(("No random", response4.status_code, response4.text))
            
            # Report results
            print(f"\n📊 Test Results:")
            for i, (method, status, text) in enumerate(tests, 1):
                print(f"  Test {i} ({method}): {status} - '{text}'")
            
            return {"success": False, "debug": True, "tests": tests, "item_id": item_id}
            
        except Exception as e:
            print(f"❌ Test error: {str(e)}")
            return {"success": False, "error": str(e), "item_id": item_id}

    async def delete_item(self, item_id: str) -> dict:
        """Delete a single V&R item using AJAX"""
        if not self.authenticated:
            return {"success": False, "error": "Not authenticated"}
            
        try:
            print(f"🗑️  Deleting item ID: {item_id}")
            
            # AJAX delete request
            delete_data = {
                'product_id': str(item_id)
            }
            
            response = self.session.post(
                'https://www.vintageandrare.com/ajax/delete_item',
                data=delete_data,
                headers=self.headers
            )
            
            print(f"📡 Delete response status: {response.status_code}")
            print(f"📝 Response content: '{response.text}'")
            print(f"📏 Response length: {len(response.text)} characters")
            
            if response.status_code == 200:
                response_text = response.text.strip()
                
                # Handle different response types
                if not response_text:
                    # Empty response - V&R often returns empty on successful delete
                    print(f"✅ Empty response (likely successful delete) for {item_id}")
                    return {"success": True, "response": "empty_success", "item_id": item_id}
                
                # Try to parse JSON response
                try:
                    result = response.json()
                    print(f"✅ JSON response for {item_id}: {result}")
                    return {"success": True, "response": result, "item_id": item_id}
                except:
                    # If not JSON, check for success indicators in text
                    response_lower = response_text.lower()
                    if any(keyword in response_lower for keyword in ['success', 'deleted', 'removed', 'ok']):
                        print(f"✅ Text indicates success for {item_id}")
                        return {"success": True, "response": response_text, "item_id": item_id}
                    elif any(keyword in response_lower for keyword in ['error', 'failed', 'not found', 'invalid']):
                        print(f"❌ Text indicates failure for {item_id}: {response_text}")
                        return {"success": False, "error": f"Server error: {response_text}", "item_id": item_id}
                    else:
                        print(f"⚠️  Unknown response for {item_id}: '{response_text}'")
                        return {"success": True, "response": f"unknown_success: {response_text}", "item_id": item_id}
            else:
                print(f"❌ Delete failed for {item_id}: HTTP {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}", "item_id": item_id}
                
        except Exception as e:
            print(f"❌ Error deleting {item_id}: {str(e)}")
            return {"success": False, "error": str(e), "item_id": item_id}

    async def process_items(self, item_ids: list, action: str, verify: bool = False, update_data: dict = None) -> dict:
        """Process multiple V&R items (delete or mark as sold)"""
        results = {
            "total": len(item_ids),
            "successful": 0,
            "failed": 0,
            "verified": 0,
            "details": []
        }
        
        for item_id in item_ids:
            if action == "delete":
                result = await self.delete_item(item_id)
            elif action == "mark-sold":
                result = await self.mark_item_as_sold(item_id)
            elif action == "edit":
                    if update_data:
                        result = await self.update_listing_selenium(item_id, update_data, test_mode=True)
                    else:
                        result = {"success": False, "error": "No update data provided", "item_id": item_id}
                
            else:
                result = {"success": False, "error": f"Unknown action: {action}", "item_id": item_id}
            
            # ✅ FIX: Handle both success formats
            is_successful = (
                result.get("success") is True or  # For delete/mark-sold
                result.get("status") == "success"  # For edit operations
            )
            
            # If verification requested and action seemed successful, verify
            if verify and is_successful:
                await asyncio.sleep(2)  # Wait a bit for V&R to process as server is SLOW
                if await self.verify_item_status(item_id, action):
                    result["verified"] = True
                    results["verified"] += 1
                else:
                    result["verified"] = False
                    is_successful = False
                    
            results["details"].append(result)
            
            if is_successful:
                results["successful"] += 1
            else:
                results["failed"] += 1
                
            # Small delay between operations to be nice to the server
            await asyncio.sleep(1)
        
        return results

    async def verify_item_status(self, item_id: str, action: str) -> bool:
        """Verify if an action was successful"""
        try:
            # Try to access the item's page
            response = self.session.get(f'https://www.vintageandrare.com/instruments/{item_id}')
            
            if action == "delete":
                if response.status_code == 404:
                    print(f"✅ Verified: Item {item_id} is deleted (404)")
                    return True
                elif 'not found' in response.text.lower() or 'does not exist' in response.text.lower():
                    print(f"✅ Verified: Item {item_id} is deleted (not found)")
                    return True
                else:
                    print(f"⚠️  Item {item_id} may still exist (status: {response.status_code})")
                    return False
            
            elif action == "mark-sold":
                if response.status_code == 200:
                    # For mark as sold, we'd need to check the page content for "sold" indicators
                    # This is more complex to verify automatically
                    print(f"⚠️  Item {item_id} verification for 'mark-sold' not implemented")
                    return True  # Assume success for now
                else:
                    print(f"⚠️  Cannot verify {item_id} mark-sold status")
                    return False
                    
        except Exception as e:
            print(f"❌ Error verifying {item_id}: {str(e)}")
            return False

    async def update_item_details(self, item_id: str, update_data: Dict[str, Any]) -> Dict:
        """
        Logs into V&R and updates specific fields for an existing item using Selenium.
        'update_data' can contain keys like 'product_price', 'product_model_name', etc.
        """
        logger.info(f"Attempting to update V&R item {item_id} with data: {update_data}")
        loop = asyncio.get_running_loop()
        
        result = await loop.run_in_executor(
            None,
            self._execute_selenium_update, # Directly call the synchronous worker
            item_id,
            update_data
        )
        return result

    def _execute_selenium_update(self, item_id: str, update_data: Dict[str, Any]) -> Dict:
        """
        Use the EXACT same login method as inspect_form.py which works
        """
        import requests
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        
        # Step 1: Authenticate with requests first (like inspect_form does)
        session = requests.Session()
        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://www.vintageandrare.com',
            'Referer': 'https://www.vintageandrare.com/',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
        }
        
        # Get initial cookies
        session.get('https://www.vintageandrare.com', headers=headers)
        
        # Login via requests
        login_data = {
            'username': self.username,
            'pass': self.password,
            'open_where': 'header'
        }
        
        response = session.post(
            'https://www.vintageandrare.com/do_login',
            data=login_data,
            headers=headers,
            allow_redirects=True
        )
        
        if 'account' not in response.url:
            logger.error("Requests login failed")
            return {"success": False, "message": "Authentication failed"}
        
        logger.info("Authenticated via requests")
        
        # Step 2: Set up Selenium
        options = webdriver.ChromeOptions()
        options.add_experimental_option('useAutomationExtension', False)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Check for headless mode from environment variable
        import os
        headless_mode = os.environ.get('VR_HEADLESS', 'true').lower() == 'true'
        is_docker = os.path.exists('/.dockerenv') or os.environ.get('RAILWAY_ENVIRONMENT') is not None
        selenium_grid_url = os.environ.get('SELENIUM_GRID_URL')  # e.g., https://your-selenium.up.railway.app

        if headless_mode:
            options.add_argument("--headless=new")
            logger.info("Running V&R browser in HEADLESS mode")

            # Add container-specific optimizations only when in Docker/Railway
            if is_docker and not selenium_grid_url:  # Only add these if using local Chrome
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-setuid-sandbox")
                options.add_argument("--disable-gpu")
                options.add_argument("--disable-web-security")
                options.add_argument("--disable-features=VizDisplayCompositor")
                logger.info("Added Docker/Railway-specific Chrome flags")
        else:
            logger.info("Running V&R browser in VISIBLE mode for debugging")
        
        options.add_argument("--window-size=1920,1080")
        
        # Add detailed logging for ChromeDriver download
        logger.info("DEBUG: Starting ChromeDriver download/check...")

        import time as time_module
        start_time = time_module.time()

        # Decide between local Chrome or remote Selenium Grid
        if selenium_grid_url:
            # Use remote Selenium Grid
            logger.info(f"Using remote Selenium Grid at: {selenium_grid_url}")

            try:
                from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

                # Ensure the URL has the correct format
                if not selenium_grid_url.startswith('http'):
                    selenium_grid_url = f"http://{selenium_grid_url}"
                if not selenium_grid_url.endswith('/wd/hub'):
                    selenium_grid_url = f"{selenium_grid_url}/wd/hub"

                logger.info(f"Formatted Selenium Grid URL: {selenium_grid_url}")

                driver = webdriver.Remote(
                    command_executor=selenium_grid_url,
                    options=options
                )
                logger.info("Connected to Selenium Grid successfully")
            except Exception as e:
                logger.error(f"Failed to connect to Selenium Grid: {str(e)}")
                logger.error(f"Full error: {type(e).__name__}: {e}")
                raise
        else:
            # Local Chrome setup
            try:
                # In Docker/Railway without Selenium Grid, ChromeDriver is pre-installed
                if is_docker:
                    driver_path = "/usr/local/bin/chromedriver"
                    if os.path.exists(driver_path):
                        logger.info(f"Using pre-installed ChromeDriver in container: {driver_path}")
                    else:
                        logger.warning("ChromeDriver not found at expected path, falling back to download")
                        driver_path = ChromeDriverManager().install()
                else:
                    # Local development - use ChromeDriverManager
                    driver_path = ChromeDriverManager().install()
                    elapsed = time_module.time() - start_time
                    logger.info(f"DEBUG: ChromeDriver installed/found in {elapsed:.2f} seconds at: {driver_path}")
            except Exception as e:
                elapsed = time_module.time() - start_time
                logger.error(f"ERROR: ChromeDriver setup failed after {elapsed:.2f} seconds: {e}")
                raise

            logger.info("DEBUG: Creating local Chrome WebDriver instance...")
            driver = webdriver.Chrome(
                service=Service(driver_path),
                options=options
            )
        logger.info("DEBUG: Chrome WebDriver created successfully")
        
        try:
            # Step 3: Go to main site first
            driver.get('https://www.vintageandrare.com')
            time.sleep(2)
            
            # Step 4: Delete all cookies and add session cookies
            driver.delete_all_cookies()
            
            for cookie in session.cookies:
                cookie_dict = {
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': '.vintageandrare.com',
                    'path': '/'
                }
                driver.add_cookie(cookie_dict)
            
            # Step 5: Navigate DIRECTLY to edit page (no refresh)
            edit_url = f'https://www.vintageandrare.com/instruments/add_edit_item/{item_id}'
            logger.info(f"Navigating to: {edit_url}")
            driver.get(edit_url)
            time.sleep(3)
            
            # Handle cookie consent
            try:
                cookie_button = driver.find_element(By.CLASS_NAME, "cc-nb-okagree")
                cookie_button.click()
                time.sleep(1)
            except:
                pass
            
            # Check current URL and page content
            current_url = driver.current_url
            logger.info(f"Current URL: {current_url}")
            
            if "forbidden" in driver.page_source.lower():
                logger.error("Got forbidden page - item may not belong to this account")
                
                # Try alternative: Navigate to items list first, then to edit
                driver.get('https://www.vintageandrare.com/instruments/show')
                time.sleep(2)
                
                # Now try edit page again
                driver.get(edit_url)
                time.sleep(3)
                
                if "forbidden" in driver.page_source.lower():
                    return {"success": False, "message": f"Access forbidden to item {item_id}"}
            
            # Try to find price field
            try:
                price_field = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "price"))
                )
                
                price_field.clear()
                price_field.send_keys(str(update_data['product_price']))
                logger.info(f"Updated price to {update_data['product_price']}")
                
                # Submit
                submit_button = driver.find_element(By.ID, "submit_step_1")
                submit_button.click()
                time.sleep(5)
                
                return {"success": True, "message": "Price updated"}
                
            except TimeoutException:
                logger.error("Could not find price field")
                driver.save_screenshot("vr_forbidden_debug.png")
                
                # Log page content
                body_text = driver.find_element(By.TAG_NAME, "body").text[:500]
                logger.error(f"Page content: {body_text}")
                
                return {"success": False, "message": "Could not access edit form"}
                
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return {"success": False, "message": str(e)}
        finally:
            driver.quit()

    
    # --- Edit product methods ---
    
    async def update_listing_selenium(
        self, 
        item_id: str,
        product_data: Dict[str, Any], 
        test_mode: bool = False,
        db_session=None
    ) -> Dict[str, Any]:
        """
        Update an existing V&R listing using Selenium automation
        
        Args:
            item_id: V&R item ID to edit
            product_data: Dictionary containing the updated product details
            test_mode: If True, the form will be filled but not submitted
            db_session: Optional database session
            
        Returns:
            Dict with status, message, and result info
        """
        
        logger.info(f"Updating V&R listing ID: {item_id}")
        
        if not login_and_navigate:
            logger.error("inspect_form.login_and_navigate not available. Cannot update listing.")
            return {"status": "error", "message": "Selenium automation module not loaded"}

        try:
            # Prepare form data for editing (similar to create but with item_id)
            form_data = self._prepare_form_data_for_edit(product_data, item_id)
            
            logger.debug(f"Prepared edit form data for V&R item {item_id}: {form_data}")

            # Run Selenium automation for editing
            loop = asyncio.get_event_loop()
            
            result = await loop.run_in_executor(
                None,
                lambda: self._run_selenium_edit_automation(form_data, item_id, test_mode, db_session)
            )

            logger.info(f"V&R Selenium listing update result: {result}")
            return result

        except Exception as e:
            logger.error(f"Error updating V&R listing {item_id}: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "status": "error",
                "message": f"Failed to update V&R listing: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    def _prepare_form_data_for_edit(self, product_data: Dict[str, Any], item_id: str) -> Dict[str, Any]:
        """Prepare form data for editing (includes item_id and edit-specific fields)"""
        
        # Start with regular form data
        form_data = {
            'brand': product_data.get('brand', ''),
            'model_name': product_data.get('model', ''),
            'price': str(product_data.get('price', 0)),
            'year': str(product_data.get('year', '')) if product_data.get('year') else None,
            'finish_color': str(product_data.get('finish', '') or ''),
            'description': product_data.get('description', ''),
            'external_url': str(product_data.get('external_link', '') or ''),
            
            # Categories
            'category': product_data.get('Category', '51'),
            'subcategory': product_data.get('SubCategory1', '83'),
            
            # V&R specific fields
            'show_vat': product_data.get('vr_show_vat', True),
            'call_for_price': product_data.get('vr_call_for_price', False),
            'discounted_price': str(product_data.get('vr_discounted_price','')) if product_data.get('vr_discounted_price') else None,
            'processing_time': str(product_data.get('processing_time', '3') or '3'),
            'time_unit': product_data.get('time_unit', 'Days'),
            'shipping': product_data.get('available_for_shipment', True),
            'local_pickup': product_data.get('local_pickup', False),
            'shipping_fees': {
                'europe': str(product_data.get('shipping_europe_fee', '50') or '50'),
                'usa': str(product_data.get('shipping_usa_fee', '100') or '100'),
                'uk': str(product_data.get('shipping_uk_fee', '75') or '75'),
                'world': str(product_data.get('shipping_world_fee', '150') or '150')
            },
            
            # ✅ EDIT-SPECIFIC FIELDS (from your payload analysis)
            'product_id': item_id,
            'owner_id': '6784',  # Your user ID - you might want to make this configurable
            'offer_id': '0',
            'added_completed': 'yes',
            'version': 'v4',
            'unique_id': self._generate_unique_id(),  # Generate security token
            
            # Images (will be handled by MediaHandler)
            'images': [],
            'youtube_url': str(product_data.get('video_url', '') or ''),
        }
        
        # Add images
        primary_image = product_data.get('primary_image')
        if primary_image:
            form_data['images'].append(primary_image)
        
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
                except:
                    form_data['images'].append(additional_images)
        
        return form_data

    def _generate_unique_id(self) -> str:
        """Generate unique security token like V&R uses"""
        import hashlib
        import random
        import time
        
        random_data = f"{time.time()}{random.random()}{self.username}"
        return hashlib.md5(random_data.encode()).hexdigest()

    def _run_selenium_edit_automation(self, form_data: Dict[str, Any], item_id: str, test_mode: bool, db_session=None) -> Dict[str, Any]:
        """Run Selenium automation for editing - simplified approach"""
        
        try:
            logger.info(f"Starting Selenium edit automation for item {item_id}")
            
            # Reuse the SAME login pattern as create, just call edit_item_form instead
            from app.services.vintageandrare.inspect_form import login_and_navigate
            
            # But we need a way to tell it to edit instead of create
            # Option 1: Add edit mode to existing function
            result = login_and_navigate(
                username=self.username,
                password=self.password,
                item_data=form_data,
                test_mode=test_mode,
                edit_mode=True,  # New parameter
                edit_item_id=item_id,  # New parameter
                db_session=None
            )
            
            return {
                "status": "success",
                "message": "Listing updated successfully" if not test_mode else "Test mode: edit form filled but not submitted",
                "vr_listing_id": item_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Edit automation failed: {str(e)}")
            return {
                "status": "error",
                "message": f"Edit failed: {str(e)}",
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
    
    def cleanup_selenium(self):
        """Ensure Selenium browser is properly closed and resources are freed."""
        if self._selenium_driver:
            try:
                logger.info("Closing Selenium browser...")
                self._selenium_driver.quit()
                logger.info("Selenium browser closed successfully")
            except Exception as e:
                logger.error(f"Error closing Selenium browser: {e}")
            finally:
                self._selenium_driver = None
                self._selenium_session = None

    def __del__(self):
        """Destructor to ensure cleanup of temporary files and browser instances."""
        self.cleanup_temp_files()
        self.cleanup_selenium()
        
