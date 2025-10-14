import os
import re
import json
import base64
import asyncio
import aiofiles
import logging

from decimal import Decimal
from enum import Enum
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Union

from fastapi import (
    APIRouter, 
    Depends, 
    Request, 
    HTTPException, 
    BackgroundTasks,
    Form, 
    File, 
    UploadFile,
)

from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.encoders import jsonable_encoder

from sqlalchemy import select, or_, distinct, func, desc, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.enums import PlatformName, ProductCondition
from app.core.events import StockUpdateEvent
from app.core.exceptions import ProductCreationError, PlatformIntegrationError
from app.dependencies import get_db, templates
from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.shipping import ShippingProfile
from app.models.vr import VRListing
from app.models.reverb import ReverbListing
from app.models.ebay import EbayListing
from app.models.shopify import ShopifyListing
from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
from app.services.category_mapping_service import CategoryMappingService
from app.services.product_service import ProductService
from app.services.ebay_service import EbayService
from app.services.reverb_service import ReverbService
from app.services.shopify_service import ShopifyService
from app.services.shopify.client import ShopifyGraphQLClient
from app.services.vr_service import VRService
from app.services.vintageandrare.brand_validator import VRBrandValidator
from app.services.vintageandrare.client import VintageAndRareClient
from app.services.vintageandrare.export import VRExportService
from app.schemas.product import ProductCreate
from app.services.sync_services import SyncService

router = APIRouter()

# Configuration for file uploads
UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

DRAFT_UPLOAD_DIR = Path(get_settings().DRAFT_UPLOAD_DIR).expanduser()
DRAFT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DRAFT_UPLOAD_URL_PREFIX = "/static/drafts"

DEFAULT_VR_BRAND = "Justin" # <<< ***IMPORTANT: CHOOSE A VALID BRAND FROM YOUR VRAcceptedBrand TABLE***
# DEFAULT_EBAY_BRAND = "Gibson" # <<< ***IMPORTANT: CHOOSE A VALID BRAND FROM YOUR eBay Accepted Brands TABLE***
# DEFAULT_REVERB_BRAND = "Gibson" # <<< ***IMPORTANT: CHOOSE A VALID BRAND FROM YOUR Reverb Accepted Brands TABLE***

logger = logging.getLogger(__name__)


UPLOAD_DIR_PATH = Path(UPLOAD_DIR)
DROPBOX_UPLOAD_ROOT = "/InventorySystem/auto-uploads"


def _is_local_upload(url: Optional[str]) -> bool:
    return bool(url and url.startswith("/static/uploads/"))


def _parse_price_to_decimal(value: Optional[Any]) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except Exception:
            logger.warning("Unable to parse price value '%s'", value)
            return None
    return None


def _decimal_to_str(value: Decimal) -> str:
    try:
        return format(value.quantize(Decimal("0.01")), "f")
    except Exception:
        return format(value, "f")


async def _upload_local_image_to_dropbox(
    local_url: str,
    sku: str,
    dropbox_client: AsyncDropboxClient,
    dropbox_root: str,
) -> Optional[str]:
    try:
        filename = os.path.basename(local_url)
        local_path = UPLOAD_DIR_PATH / filename
        if not local_path.exists():
            logger.warning("Local upload missing on disk: %s", local_path)
            return None

        async with aiofiles.open(local_path, "rb") as fh:
            data = await fh.read()

        base64_payload = base64.b64encode(data).decode("utf-8")
        dropbox_path = f"{dropbox_root.rstrip('/')}/{sku}/{filename}"
        if not dropbox_path.startswith("/"):
            dropbox_path = f"/{dropbox_path}"

        remote_url = await dropbox_client.upload_base64_image(base64_payload, dropbox_path)
        if remote_url:
            logger.info("Uploaded image %s to Dropbox path %s", filename, dropbox_path)
        return remote_url
    except Exception as exc:
        logger.warning("Failed to upload %s to Dropbox: %s", local_url, exc)
        return None


async def ensure_remote_media_urls(
    primary_image: Optional[str],
    additional_images: List[str],
    sku: str,
    settings: Settings,
) -> tuple[Optional[str], List[str]]:
    dropbox_client: Optional[AsyncDropboxClient] = None
    dropbox_available = bool(settings.DROPBOX_ACCESS_TOKEN)
    dropbox_root = getattr(settings, "DROPBOX_UPLOAD_ROOT", DROPBOX_UPLOAD_ROOT)

    async def convert(url: Optional[str]) -> Optional[str]:
        nonlocal dropbox_client
        if not _is_local_upload(url):
            return url
        if not dropbox_available:
            logger.warning("Local image %s will be used as-is (Dropbox not configured)", url)
            return url
        if dropbox_client is None:
            dropbox_client = AsyncDropboxClient(
                access_token=settings.DROPBOX_ACCESS_TOKEN,
                refresh_token=settings.DROPBOX_REFRESH_TOKEN,
                app_key=settings.DROPBOX_APP_KEY,
                app_secret=settings.DROPBOX_APP_SECRET,
            )
        remote = await _upload_local_image_to_dropbox(url, sku, dropbox_client, dropbox_root)
        return remote or url

    converted_primary = await convert(primary_image) if primary_image else primary_image
    converted_additional = []
    for image_url in additional_images:
        converted_additional.append(await convert(image_url))

    return converted_primary, converted_additional


def generate_shopify_handle(brand: Optional[str], model: Optional[str], sku: Optional[str]) -> str:
    parts = [str(part) for part in [brand, model, sku] if part]
    text = "-".join(parts).lower()
    text = re.sub(r"[^a-z0-9\-]+", "-", text)
    return text.strip('-')


_reverb_to_platforms_map_cache = None
_ebay_to_platforms_map_cache = None
_vr_to_platforms_map_cache = None
_shopify_to_platforms_map_cache = None

def get_reverb_to_platforms_map(logger_instance: logging.Logger) -> Dict[str, Any]:
    """Loads the Reverb to other platforms category mapping file."""
    global _reverb_to_platforms_map_cache
    if _reverb_to_platforms_map_cache is None:
        map_path_str = "" # For logging in case of error before path is set
        try:
            # Path relative to this file (inventory.py in app/routes)
            # to where you placed the new map file: app/services/vintageandrare/reverb_to_platforms_map.json
            map_path = Path(__file__).parent.parent / "services" / "vintageandrare" / "reverb_to_platforms_map.json"
            map_path_str = str(map_path) # For logging
            with open(map_path, 'r') as f:
                _reverb_to_platforms_map_cache = json.load(f)
            logger_instance.info(f"Reverb-to-Platforms category map loaded successfully from {map_path_str}")
        except FileNotFoundError:
            logger_instance.error(f"CRITICAL: Reverb-to-Platforms category map file not found at {map_path_str}. V&R/eBay category mapping will fail.")
            _reverb_to_platforms_map_cache = {} # Return empty dict to prevent repeated load attempts
        except json.JSONDecodeError:
            logger_instance.error(f"CRITICAL: Error decoding JSON from Reverb-to-Platforms map file at {map_path_str}.")
            _reverb_to_platforms_map_cache = {}
        except Exception as e:
            logger_instance.error(f"CRITICAL: Failed to load Reverb-to-Platforms category map from {map_path_str}: {e}", exc_info=True)
            _reverb_to_platforms_map_cache = {}
    return _reverb_to_platforms_map_cache

def get_ebay_to_platforms_map(logger_instance: logging.Logger) -> Dict[str, Any]:
    """Placeholder for loading eBay to other platforms category mapping."""
    # global _ebay_to_platforms_map_cache
    # if _ebay_to_platforms_map_cache is None:
    #     # Logic to load a map like:
    #     # map_path = Path(__file__).parent.parent / "services" / "mappings" / "ebay_to_platforms_map.json"
    #     # ... load logic ...
    #     logger_instance.info("eBay-to-Platforms category map loaded (placeholder).")
    # return _ebay_to_platforms_map_cache or {}
    logger_instance.info("get_ebay_to_platforms_map is a placeholder and not yet implemented.")
    return {} # Return empty dict for now

def get_shopify_to_platforms_map(logger_instance: logging.Logger) -> Dict[str, Any]:
    """Placeholder for loading &Shopify to other platforms category mapping."""
    # global _vr_to_platforms_map_cache
    # if _vr_to_platforms_map_cache is None:
    #     # Logic to load a map like:
    #     # map_path = Path(__file__).parent.parent / "services" / "mappings" / "vr_to_platforms_map.json"
    #     # ... load logic ...
    #     logger_instance.info("V&R-to-Platforms category map loaded (placeholder).")
    # return _vr_to_platforms_map_cache or {}
    logger_instance.info("get_shopify_to_platforms_map is a placeholder and not yet implemented.")
    return {} # Return empty dict for now

def get_vr_to_platforms_map(logger_instance: logging.Logger) -> Dict[str, Any]:
    """Placeholder for loading V&R to other platforms category mapping."""
    # global _vr_to_platforms_map_cache
    # if _vr_to_platforms_map_cache is None:
    #     # Logic to load a map like:
    #     # map_path = Path(__file__).parent.parent / "services" / "mappings" / "vr_to_platforms_map.json"
    #     # ... load logic ...
    #     logger_instance.info("V&R-to-Platforms category map loaded (placeholder).")
    # return _vr_to_platforms_map_cache or {}
    logger_instance.info("get_vr_to_platforms_map is a placeholder and not yet implemented.")
    return {} # Return empty dict for now

async def _prepare_vr_payload_from_product_object(
    product: Product, 
    db: AsyncSession,
    logger_instance: logging.Logger,
    use_fallback_brand: bool = False  # NEW PARAMETER
) -> tuple[Dict[str, Any], bool]:
    """
    Prepares the rich dictionary payload for V&R export from an existing Product object.
    
    Args:
        use_fallback_brand: If True, uses DEFAULT_VR_BRAND instead of product.brand
    
    Note: Brand validation should be performed via VRBrandValidator.validate_brand() 
    before calling this function to ensure the brand is accepted by V&R.
    """
    
    brand_was_defaulted = False
    payload = {}
    logger_instance.debug(f"Preparing V&R payload for product SKU '{product.sku}'.")


    # --- ITEM INFORMATION ---
    
    # Category (Mandatory for V&R). Ensure product.category is a string, strip whitespace for reliable key lookup
    product_reverb_category = str(product.category).strip() if product.category else None
    
    if not product_reverb_category:
        logger_instance.error(f"Product SKU '{product.sku}' has no Reverb category (product.category is None or empty). Cannot map to V&R.")
        raise ValueError(f"Product SKU '{product.sku}' has no Reverb category set, which is needed for V&R mapping.")

    # Load the new mapping file (reverb_to_platforms_map.json) using the new helper
    reverb_map_data = get_reverb_to_platforms_map(logger_instance) 
    
    # Attempt to get the mapping for the product's Reverb category
    # The keys in reverb_to_platforms_map.json are the Reverb category strings
    platform_specific_mappings = reverb_map_data.get(product_reverb_category) 

    if not platform_specific_mappings:
        logger_instance.error(f"No entry found for Reverb category '{product_reverb_category}' (SKU: '{product.sku}') in the reverb_to_platforms_map.json file.")
        # This is where you'll later trigger the UI for user selection if you build that feature.
        # For now, we raise an error to indicate the mapping is missing and needs to be added to the JSON map.
        raise ValueError(f"Category mapping missing for Reverb category '{product_reverb_category}' (SKU: '{product.sku}'). Please add this Reverb category to the reverb_to_platforms_map.json file.")

    vr_category_settings = platform_specific_mappings.get("vr_categories")

    if not vr_category_settings: # Check if the "vr_categories" sub-object exists in the map
        logger_instance.error(f"'vr_categories' section not found in reverb_to_platforms_map.json for Reverb category '{product_reverb_category}' (SKU: '{product.sku}').")
        raise ValueError(f"V&R category settings ('vr_categories' object) are missing in the map for '{product_reverb_category}' (SKU: '{product.sku}').")
    
    # Extract V&R category names from the map based on the structure we agreed on
    # (e.g., {"vr_categories": {"vr_category_1_name": "...", "vr_category_2_name": "..."}})
    payload["Category"] = vr_category_settings.get("vr_category_1_id")
    payload["SubCategory1"] = vr_category_settings.get("vr_category_2_id")
    payload["SubCategory2"] = vr_category_settings.get("vr_category_3_id")
    payload["SubCategory3"] = vr_category_settings.get("vr_category_4_id") # For V&R, often up to 2 or 3 levels are used

    if not payload["Category"]:
        # i.e. mapping structure was present for the Reverb category but "vr_category_1_id" itself was missing or null within that structure.
        logger_instance.error(f"V&R main category ('vr_category_1_id') is not defined or is null in reverb_to_platforms_map.json for Reverb category '{product_reverb_category}' (SKU: '{product.sku}'). This field is mandatory for V&R.")
        raise ValueError(f"V&R main category (vr_category_1_id) is missing in the map details for '{product_reverb_category}' (SKU: '{product.sku}').")

    # Clean up payload by removing any subcategory keys that ended up with a None value
    # This prevents sending {"SubCategory2": null} if "vr_category_2_id" was missing or null in the map.
    keys_to_delete = []
    for i in range(1, 5): # Check SubCategory1 through SubCategory4 (assuming max 4 levels for now)
        key = f"SubCategory{i}"
        # Ensure the key was added to payload (i.e., it was in vr_category_settings) before checking if its value is None
        if key in payload and payload[key] is None:
            keys_to_delete.append(key)
    for key in keys_to_delete:
        del payload[key]
    
    # Construct log message for mapped categories
    log_message_parts = [f"Cat1='{payload.get('Category')}'"]
    if "SubCategory1" in payload: log_message_parts.append(f"Cat2='{payload.get('SubCategory1')}'")
    if "SubCategory2" in payload: log_message_parts.append(f"Cat3='{payload.get('SubCategory2')}'")
    if "SubCategory3" in payload: log_message_parts.append(f"Cat4='{payload.get('SubCategory3')}'") 
    
    logger_instance.info(
        f"Mapped Reverb category '{product_reverb_category}' to V&R categories: {', '.join(log_message_parts)} for SKU '{product.sku}'."
    )    

    # --- Brand / Maker (With fallback support) ---
    if not product.brand:
        logger_instance.warning(f"Product SKU '{product.sku}' has no brand set. Using '{DEFAULT_VR_BRAND}' for V&R.")
        payload["brand"] = DEFAULT_VR_BRAND
        brand_was_defaulted = True
    elif use_fallback_brand:
        # User chose to proceed with fallback brand for unrecognized brand
        logger_instance.info(f"Using fallback brand '{DEFAULT_VR_BRAND}' for SKU '{product.sku}' (original brand '{product.brand}' not recognized by V&R).")
        payload["brand"] = DEFAULT_VR_BRAND
        brand_was_defaulted = True
    else:
        # Use the validated brand
        payload["brand"] = product.brand
        logger_instance.info(f"Using validated brand '{product.brand}' for SKU '{product.sku}'.")
    
    
    # --- Model Name --- (Mandatory)
    if not product.model:
        raise ValueError(f"Model name is mandatory for V&R listing (product SKU: {product.sku}).")
    payload["model"] = product.model

    # --- Year --- (Optional)
    if product.year:
        payload["year"] = str(product.year)
        payload["decade"] = f"{str(product.year // 10 * 10)}s"

    # --- Finish/Color --- (Optional)
    if product.finish:
        payload["finish"] = product.finish # V&R uses "FinishColour"

    # --- Item Description --- (User-side mandatory for you)
    if not product.description: # Ensuring it's not empty, as per your requirement
        raise ValueError(f"Description is mandatory for V&R listing (product SKU: {product.sku}).")
    payload["description"] = product.description

    # --- SKU --- 
    if product.sku:
        # payload["sku"] = product.sku  # ✅ Keep this for reference  
        payload["external_id"] = product.sku  # ✅ Add this - what client.py expects
            
    #  --- Condition --- (not a value in V&R)
    if product.condition:
        payload["condition"] = product.condition.value if isinstance(product.condition, Enum) else str(product.condition)

    # --- Item Price ---
    if product.base_price is None:
        raise ValueError(f"Price is mandatory for V&R listing (product SKU: {product.sku}).")
    try:
        payload["price"] = float(Decimal(str(product.base_price))) # Ensure no commas; V&R expects number or string number
    except Exception:
        raise ValueError(f"Invalid price format for product SKU '{product.sku}': {product.base_price}")
    payload["currency"] = "GBP"

    # --- Media (Structured for client.py) ---
    payload['primary_image'] = product.primary_image if product.primary_image and isinstance(product.primary_image, str) else None
    
    additional_images_list: List[str] = []
    if product.additional_images:
        source_images = product.additional_images
        if isinstance(source_images, str): # If it's a JSON string
            try:
                parsed_images = json.loads(source_images)
                if isinstance(parsed_images, list): source_images = parsed_images
                else: source_images = [str(parsed_images)]
            except json.JSONDecodeError: source_images = [source_images] # Treat as single URL string
        
        if isinstance(source_images, list):
            for img_item in source_images:
                url_to_add: Optional[str] = None
                if isinstance(img_item, dict) and 'url' in img_item and isinstance(img_item['url'], str):
                    url_to_add = img_item['url']
                elif isinstance(img_item, str):
                    url_to_add = img_item
                
                if url_to_add and url_to_add != payload['primary_image'] and url_to_add not in additional_images_list:
                    additional_images_list.append(url_to_add)
        else:
            logger_instance.warning(f"product.additional_images for SKU {product.sku} unhandled type: {type(source_images)}")
            
    payload['additional_images'] = additional_images_list

    payload['video_url'] = product.video_url
    payload['external_link'] = product.external_link

    # # --- V&R Specific Fields (sourcing from Product model if attributes exist) ---
    # payload['vr_show_vat'] = product.show_vat if hasattr(product, 'show_vat') and product.show_vat is not None else True
    # payload['vr_in_collective'] = product.in_collective if hasattr(product, 'in_collective') and product.in_collective is not None else False
    # payload['vr_in_inventory'] = product.in_inventory if hasattr(product, 'in_inventory') and product.in_inventory is not None else True
    # payload['vr_in_reseller'] = product.in_reseller if hasattr(product, 'in_reseller') and product.in_reseller is not None else False
    # # Add others like 'vr_call_for_price', 'vr_discounted_price', 'vr_collective_discount', 'vr_buy_now' if on Product model

    # payload['processing_time'] = str(product.processing_time) if hasattr(product, 'processing_time') and product.processing_time is not None else '3'
    # # payload['time_unit'] = 'Days' # Default in client, or add from product if it varies

    # payload['available_for_shipment'] = product.available_for_shipment if hasattr(product, 'available_for_shipment') and product.available_for_shipment is not None else True
    # payload['local_pickup'] = product.local_pickup if hasattr(product, 'local_pickup') and product.local_pickup is not None else False

    # if not product.shipping_profile_id:
    #     logger_instance.warning(f"No shipping profile ID for {product.sku}. V&R shipping details in client will use defaults.")
    # # Else: If you have shipping profile logic, populate keys like 'shipping_europe_fee', etc.
    # # payload['shipping_europe_fee'] = ...


    # --- Shipping --- (Placeholder - requires detailed logic)
    if product.shipping_profile_id:
        logger_instance.info(f"Shipping profile ID {product.shipping_profile_id} for {product.sku} needs mapping to V&R fields.")
        # TODO: Implement logic to fetch ShippingProfile by ID, then extract and map details to:
        # payload["ShippingAvailableForLocalPickup"] = resolved_profile.allows_pickup 
        # payload["ShippingAvailableForShipment"] = resolved_profile.allows_shipment
        # payload["ShippingCostsUK"] = resolved_profile.get_cost("UK") 
        # payload["ShippingCostsEurope"] = resolved_profile.get_cost("Europe")
        # payload["ShippingCostsUSA"] = resolved_profile.get_cost("USA")
        # payload["ShippingCostsROW"] = resolved_profile.get_cost("ROW")
        # This depends on your ShippingProfile model and how V&R expects these.
        # For now, these fields will be omitted or rely on V&R exporter defaults if not explicitly set.
    else:
        logger_instance.warning(f"No shipping profile ID for {product.sku}. V&R shipping details will be default/minimal.")

    # Log the final payload before returning
    try:
        payload_json_for_log = json.dumps(payload, indent=2, default=str)
        logger_instance.debug(f"Prepared V&R payload for SKU '{product.sku}': {payload_json_for_log}")
    except TypeError: # In case something non-serializable is in payload (shouldn't be)
        logger_instance.debug(f"Prepared V&R payload for SKU '{product.sku}' (contains non-serializable elements, showing dict): {payload}")

    return payload, brand_was_defaulted


def _sanitize_path_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "-", value or "")
    sanitized = sanitized.strip("-_")
    return sanitized or datetime.now().strftime("%Y%m%d%H%M%S")


def _sanitize_filename(filename: Optional[str]) -> str:
    name = Path(filename or "upload").name
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return sanitized or "upload"


def _draft_media_subdir(draft_id: Optional[int], sku: Optional[str]) -> str:
    if draft_id is not None:
        return f"id-{_sanitize_path_component(str(draft_id))}"
    if sku:
        return f"sku-{_sanitize_path_component(sku)}"
    return f"draft-{datetime.now().strftime('%Y%m%d%H%M%S')}"


async def save_draft_upload_file(upload_file: UploadFile, subdir: str) -> str:
    """Save an uploaded draft file under the configured draft media directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}_{_sanitize_filename(upload_file.filename)}"

    target_dir = DRAFT_UPLOAD_DIR / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / filename

    async with aiofiles.open(filepath, "wb") as out_file:
        content = await upload_file.read()
        await out_file.write(content)

    return f"{DRAFT_UPLOAD_URL_PREFIX}/{subdir}/{filename}"


async def save_upload_file(upload_file: UploadFile) -> str:
    """Save an uploaded file and return its path"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{_sanitize_filename(upload_file.filename)}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    async with aiofiles.open(filepath, 'wb') as out_file:
        content = await upload_file.read()
        await out_file.write(content)

    return f"/static/uploads/{filename}"


def cleanup_draft_media(subdir: str, keep_urls: List[str]) -> None:
    """Remove orphaned files from a draft media directory."""
    directory = DRAFT_UPLOAD_DIR / subdir
    if not directory.exists() or not directory.is_dir():
        return

    keep_filenames: set[str] = set()
    for url in keep_urls:
        if not url:
            continue
        parsed = urlparse(url)
        path = parsed.path
        prefix = f"{DRAFT_UPLOAD_URL_PREFIX}/{subdir}/"
        if path.startswith(prefix):
            keep_filenames.add(Path(path).name)

    try:
        for file_path in directory.iterdir():
            if file_path.is_file() and file_path.name not in keep_filenames:
                file_path.unlink(missing_ok=True)

        if not any(directory.iterdir()):
            directory.rmdir()
    except Exception as cleanup_error:
        logger.warning(
            "Failed to tidy draft media directory %s: %s",
            subdir,
            cleanup_error,
        )

def process_platform_data(form_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract platform-specific data from form fields"""
    platform_data = {}
    
    # Process eBay data
    ebay_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__ebay__"):
            field_name = key.replace("platform_data__ebay__", "")
            # Handle boolean values (checkboxes)
            if value in [True, 'true', 'True', 'on']:
                ebay_data[field_name] = True
            elif value in [False, 'false', 'False']:
                ebay_data[field_name] = False
            else:
                ebay_data[field_name] = value
    
    if ebay_data:
        platform_data["ebay"] = ebay_data
    
    # Process Reverb data
    reverb_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__reverb__"):
            field_name = key.replace("platform_data__reverb__", "")
            # Handle boolean values (checkboxes)
            if value in [True, 'true', 'True', 'on']:
                reverb_data[field_name] = True
            elif value in [False, 'false', 'False']:
                reverb_data[field_name] = False
            else:
                reverb_data[field_name] = value
    
    if reverb_data:
        platform_data["reverb"] = reverb_data
    
    # Process V&R data
    vr_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__vr__"):
            field_name = key.replace("platform_data__vr__", "")
            vr_data[field_name] = value
    
    if vr_data:
        platform_data["vr"] = vr_data
    
    # Process shopify data
    shopify_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__shopify__"):
            field_name = key.replace("platform_data__shopify__", "")
            shopify_data[field_name] = value
    
    if shopify_data:
        platform_data["shopify"] = shopify_data
    
    return platform_data

@router.get("/api/products/{product_id}")
async def get_product_json(
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    """API endpoint to get product data for copy from existing feature"""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Convert to dict and exclude sensitive fields
    product_dict = jsonable_encoder(product)
    
    # Return JSON response
    return product_dict

@router.get("/", response_class=HTMLResponse)
async def list_products(
    request: Request,
    page: int = 1,
    per_page: Union[int, str] = 100,  # Default to 100
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    platform: Optional[str] = None,  
    status: Optional[str] = None,
    state: Optional[str] = None,
    sort: Optional[str] = None,      # NEW: Sort column
    order: Optional[str] = 'asc',    # NEW: Sort direction
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    # Handle the case when per_page is 'all'
    if per_page == 'all':
        pagination_limit = None  # No limit
        pagination_offset = 0
    else:
        try:
            per_page = int(per_page)
        except (ValueError, TypeError):
            per_page = 100  # Default to 100 if conversion fails
            
        pagination_limit = per_page
        pagination_offset = (page - 1) * per_page
    
    # Handle status/state parameter (state is alias for status)
    filter_status = status or state
    
    # Build query using async style
    if platform:
        # If platform filter is specified, join with PlatformCommon to filter by platform
        from app.models.platform_common import PlatformCommon
        
        query = (
            select(Product)
            .join(PlatformCommon, Product.id == PlatformCommon.product_id)
            .where(PlatformCommon.platform_name.ilike(f"%{platform}%"))
        )
        
        # Add status filter if specified
        if filter_status:
            # Map common status values
            status_mapping = {
                'active': 'active',
                'live': 'active',
                'draft': 'draft',
                'sold': 'sold',
                'ended': 'ended',
                'pending': 'pending'
            }
            
            mapped_status = status_mapping.get(filter_status.lower(), filter_status)
            query = query.where(PlatformCommon.status.ilike(f"%{mapped_status}%"))
            
    else:
        # No platform filter - query products directly
        query = select(Product)
        
        # Add status filter on Product table if specified
        if filter_status:
            # Convert string to enum for comparison
            from app.models.product import ProductStatus
            
            # Map frontend values to ProductStatus enum
            status_mapping = {
                'active': ProductStatus.ACTIVE,
                'live': ProductStatus.ACTIVE,     # Alias
                'draft': ProductStatus.DRAFT,
                'sold': ProductStatus.SOLD,
                'archived': ProductStatus.ARCHIVED,
                'ended': ProductStatus.ARCHIVED,  # Map "ended" to archived
                'pending': ProductStatus.DRAFT,   # Map "pending" to draft
            }
            
            # Get the enum value
            enum_status = status_mapping.get(filter_status.lower())
            if enum_status:
                query = query.where(Product.status == enum_status)
    
    # Apply existing filters
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Product.brand.ilike(search_term),
                Product.model.ilike(search_term),
                Product.sku.ilike(search_term),
                Product.description.ilike(search_term)
            )
        )
    
    if category:
        query = query.filter(Product.category == category)
    
    if brand:
        query = query.filter(Product.brand == brand)
    
    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()
    
    # Apply pagination and ordering
    # Add sorting logic BEFORE the default ordering
    if sort and sort in ['brand', 'model', 'category', 'price', 'status']:
        if sort == 'price':
            sort_column = Product.base_price
        elif sort == 'brand':
            sort_column = Product.brand
        elif sort == 'model':
            sort_column = Product.model
        elif sort == 'category':
            sort_column = Product.category
        elif sort == 'status':
            sort_column = Product.status
        
        # Apply sort direction
        if order == 'desc':
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(sort_column)
    else:
        # Default ordering - newest first
        query = query.order_by(desc(Product.created_at))
    
    # Apply pagination and ordering
    # query = query.order_by(desc(Product.created_at))
    
    if pagination_limit:
        query = query.offset(pagination_offset).limit(pagination_limit)
    
    # Execute query
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Get unique categories and brands for filters
    # Configuration for dropdown sort order - Options: 'alphabetical' or 'count'
    CATEGORY_DROPDOWN_SORT = 'count'  # Sort by most common first
    BRAND_DROPDOWN_SORT = 'alphabetical'  # Sort alphabetically
    
    # Build categories query
    categories_query = (
        select(Product.category, func.count(Product.id).label("count"))
        .filter(Product.category.isnot(None))
        .group_by(Product.category)
    )
    if CATEGORY_DROPDOWN_SORT == 'count':
        categories_query = categories_query.order_by(desc(func.count(Product.id)))
    else:  # 'alphabetical'
        categories_query = categories_query.order_by(Product.category)
    
    categories_result = await db.execute(categories_query)
    categories_with_counts = [(c[0], c[1]) for c in categories_result.all() if c[0]]
    
    # Build brands query
    brands_query = (
        select(Product.brand, func.count(Product.id).label("count"))
        .filter(Product.brand.isnot(None))
        .group_by(Product.brand)
    )
    if BRAND_DROPDOWN_SORT == 'count':
        brands_query = brands_query.order_by(desc(func.count(Product.id)))
    else:  # 'alphabetical'
        brands_query = brands_query.order_by(Product.brand)
    brands_result = await db.execute(brands_query)
    brands_with_counts = [(b[0], b[1]) for b in brands_result.all() if b[0]]
    
    # Calculate pagination info
    if per_page != 'all' and per_page > 0:
        total_pages = (total + per_page - 1) // per_page
        start_page = max(1, page - 2)
        end_page = min(total_pages, page + 2)
        
        # Calculate start and end items for display
        start_item = (page - 1) * per_page + 1 if total > 0 else 0
        end_item = min(page * per_page, total)
    else:
        total_pages = 1
        page = 1
        start_page = 1
        end_page = 1
        # For "all" pages
        start_item = 1 if total > 0 else 0
        end_item = total
    
    return templates.TemplateResponse(
        "inventory/list.html",
        {
            "request": request,
            "products": products,
            "total_products": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "start_page": start_page,
            "end_page": end_page,
            "start_item": start_item,
            "end_item": end_item,
            "categories": categories_with_counts,
            "brands": brands_with_counts,
            "selected_category": category,
            "selected_brand": brand,
            "selected_platform": platform,    # NEW: Pass to template
            "selected_status": filter_status,  # NEW: Pass to template
            "search": search,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "current_sort": sort,          # NEW: Pass current sort
            "current_order": order,        # NEW: Pass current order
        }
    )

# Alias list_products to list_inventory_route for compatibility with tests
list_inventory_route = list_products

# Explicitly export the alias
__all__ = ["list_inventory_route", "router"]

@router.get("/product/{product_id}", response_class=HTMLResponse)
async def product_detail(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"Fetching details for product ID: {product_id}")
    try:
        # 1. Fetch Product
        product_query = select(Product).where(Product.id == product_id)
        product_result = await db.execute(product_query)
        product = product_result.scalar_one_or_none()

        if not product:
            logger.warning(f"Product with ID {product_id} not found.")
            return templates.TemplateResponse(
                "errors/404.html",
                {"request": request, "error_message": f"Product ID {product_id} not found."},
                status_code=404
            )

        # 2. Fetch Existing PlatformCommon Listings for this Product
        common_listings_query = (
            select(PlatformCommon)
            .options(selectinload(PlatformCommon.ebay_listing))
            .where(PlatformCommon.product_id == product_id)
        )
        common_listings_result = await db.execute(common_listings_query)
        existing_common_listings = common_listings_result.scalars().all()

        common_listings_map = {
            listing.platform_name.upper(): listing for listing in existing_common_listings
        }
        logger.debug(f"Fetched {len(existing_common_listings)} PlatformCommon records for product {product_id}.")

        # 3. Construct `all_platforms_status` for the template
        all_platforms_status = []

        for platform_enum in PlatformName:
            platform_display_name = platform_enum.value # This will be "EBAY", "REVERB", "VR", "SHOPIFY"
            platform_url_slug = platform_enum.slug # Uses the @property from your enum

            entry = {
                "name": platform_display_name, # For display in template
                "slug": platform_url_slug,     # For URL generation in template
                "is_listed": False,
                "details": None
            }

            # platform_enum.value (e.g., "VR") is used to check against keys in common_listings_map
            if platform_enum.value in common_listings_map:
                common_listing_record = common_listings_map[platform_enum.value]
                entry["is_listed"] = True

                sync_status_for_template = "Unknown"
                if common_listing_record.status:
                    status_upper = common_listing_record.status.upper()
                    if status_upper == "ACTIVE":
                        sync_status_for_template = "SYNCED"
                    elif status_upper == "DRAFT":
                        sync_status_for_template = "PENDING"
                    elif status_upper == "ERROR":
                        sync_status_for_template = "ERROR"
                    else:
                        sync_status_for_template = common_listing_record.status
                
                # Ensure these getattr calls use the correct attribute names from your PlatformCommon model
                entry["details"] = {
                    "external_id": getattr(common_listing_record, 'external_id', None) or \
                                    getattr(common_listing_record, 'platform_product_id', 'N/A'),
                    "status": getattr(common_listing_record, 'status', None),
                    "sync_status": sync_status_for_template,
                    "last_sync": getattr(common_listing_record, 'last_synced', None) or \
                                    getattr(common_listing_record, 'updated_at', None),
                    "message": getattr(common_listing_record, 'platform_message', None),
                    "listing_url": getattr(common_listing_record, 'listing_url', None)
                }

                if platform_enum.value == "EBAY":
                    ebay_listing = getattr(common_listing_record, "ebay_listing", None)
                    uses_crazylister = False
                    description_sources: List[str] = []

                    if ebay_listing and getattr(ebay_listing, "listing_data", None):
                        listing_data_raw = ebay_listing.listing_data
                        listing_data_obj = {}

                        if isinstance(listing_data_raw, dict):
                            listing_data_obj = listing_data_raw
                        elif isinstance(listing_data_raw, str):
                            try:
                                listing_data_obj = json.loads(listing_data_raw)
                            except json.JSONDecodeError:
                                listing_data_obj = {"Description": listing_data_raw}

                        if listing_data_obj:
                            if "uses_crazylister" in listing_data_obj:
                                uses_crazylister = bool(listing_data_obj.get("uses_crazylister"))
                            else:
                                potential_html = []

                                direct_desc = listing_data_obj.get("Description")
                                if isinstance(direct_desc, str):
                                    potential_html.append(direct_desc)

                                raw_block = listing_data_obj.get("Raw")
                                if isinstance(raw_block, dict):
                                    raw_desc = raw_block.get("Description")
                                    if isinstance(raw_desc, str):
                                        potential_html.append(raw_desc)

                                    item_block = raw_block.get("Item")
                                    if isinstance(item_block, dict):
                                        item_desc = item_block.get("Description")
                                        if isinstance(item_desc, str):
                                            potential_html.append(item_desc)

                                listing_section = listing_data_obj.get("listing_data")
                                if isinstance(listing_section, dict):
                                    section_desc = listing_section.get("Description")
                                    if isinstance(section_desc, str):
                                        potential_html.append(section_desc)

                                for html_snippet in potential_html:
                                    if html_snippet:
                                        description_sources.append(html_snippet)

                    if not uses_crazylister and product and product.description:
                        description_sources.append(product.description)

                    if not uses_crazylister:
                        for source_html in description_sources:
                            if source_html and "crazylister" in source_html.lower():
                                uses_crazylister = True
                                break

                    entry["details"]["uses_crazylister"] = uses_crazylister

            all_platforms_status.append(entry)
        
        logger.debug(f"Constructed all_platforms_status for product {product_id}: {all_platforms_status}")

        # 4. Check for platform status messages from Add Product redirect
        platform_messages = []
        show_status = request.query_params.get("show_status") == "true"

        if show_status:
            from urllib.parse import unquote
            for platform in ["reverb", "ebay", "shopify", "vr"]:
                status = request.query_params.get(f"{platform}_status")
                message = request.query_params.get(f"{platform}_message")

                if status and message:
                    platform_messages.append({
                        "platform": platform.upper(),
                        "status": status,
                        "message": unquote(message)
                    })

        # 5. Prepare context for the template
        context = {
            "request": request,
            "product": product,
            "all_platforms_status": all_platforms_status,
            "platform_messages": platform_messages,
            "show_status": show_status
        }

        return templates.TemplateResponse("inventory/detail.html", context)

    except Exception as e:
        logger.error(f"Error in product_detail for product_id {product_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.post("/product/{product_id}/list_on/{platform_slug}", name="create_platform_listing_from_detail")
async def handle_create_platform_listing_from_detail(
    request: Request,
    product_id: int,
    platform_slug: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings) # Inject settings
  ):
        
    product_service = ProductService(db)
    product = await product_service.get_product_model_instance(product_id) # Using the new method name in ProductService Class

    if not product:
        logger.error(f"Product ID {product_id} not found for listing on {platform_slug}.")
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found.")
    
    redirect_url = request.url_for('product_detail', product_id=product_id)
    message = f"An error occurred." # Default
    message_type = "error" # Default
    
    try:
        if platform_slug == "vr":
            logger.info(f"Processing Vintage & Rare listing for product {product.sku}.")
            
            # Prepare the V&R payload using the helper function
            vr_payload_dict, brand_defaulted = await _prepare_vr_payload_from_product_object(product, db, logger) # NEW
        
            # Fast AJAX brand validation BEFORE expensive Selenium process
            logger.info(f"Validating brand '{product.brand}' with V&R before listing...")
            validation = VRBrandValidator.validate_brand(product.brand)

            if not validation["is_valid"]:
                # Brand not recognized by V&R - offer to proceed with fallback
                logger.warning(f"Brand '{product.brand}' not recognized by V&R for {product.sku}")
                
                # Check if user explicitly wants to use fallback (via query parameter)
                use_fallback = request.query_params.get('use_fallback_brand', 'false').lower() == 'true'
                
                if not use_fallback:
                    # First time - ask user if they want to proceed with fallback
                    error_message = f"Brand '{product.brand}' is not recognized by Vintage & Rare. Would you like to proceed using '{DEFAULT_VR_BRAND}' as the brand instead?"
                    fallback_url = f"{redirect_url}?use_fallback_brand=true"
                    
                    # You could render a confirmation template or redirect with options
                    return RedirectResponse(
                        url=f"{redirect_url}?message={error_message}&message_type=warning&fallback_url={fallback_url}", 
                        status_code=303
                    )
                else:
                    # User confirmed - proceed with fallback brand
                    logger.info(f"Using fallback brand '{DEFAULT_VR_BRAND}' for {product.sku} (original: '{product.brand}')")
                    # Set a flag so payload preparation knows to use fallback
                    vr_payload_dict, brand_defaulted = await _prepare_vr_payload_from_product_object(
                        product, db, logger, use_fallback_brand=True
                    )
            else:
                # Brand is valid - proceed normally
                logger.info(f"✅ Brand '{product.brand}' validated successfully (V&R ID: {validation['brand_id']})")
                vr_payload_dict, brand_defaulted = await _prepare_vr_payload_from_product_object(
                    product, db, logger, use_fallback_brand=False
                )

            # Instantiate VintageAndRareClient correctly
            vintage_rare_client = VintageAndRareClient(
                username=settings.VINTAGE_AND_RARE_USERNAME,
                password=settings.VINTAGE_AND_RARE_PASSWORD,
                db_session=db 
            )
            
            logger.info(f"Calling create_listing_selenium for product SKU {product.sku} with payload.")
            # The `raise RuntimeError` for debugging is inside create_listing_selenium in client.py
            
            export_result = await vintage_rare_client.create_listing_selenium(
                product_data=vr_payload_dict, # This is the payload from _prepare_vr_payload_from_product_object
                test_mode=False,
                from_scratch=False,
                db_session=db   
            )
        
        # # ... (elif for ebay, reverb) ...
        
            # Handle the result from create_listing_selenium
            if export_result and export_result.get("status") == "success":
                # Get the SKU before the async operation
                product_sku = product.sku  # ✅ Get it early
                message = f"Successfully initiated V&R listing process for SKU '{product_sku}'. Action: {export_result.get('message', '')}"
                if brand_defaulted:
                    # Ensure vr_payload_dict contains the brand key used (e.g., 'brand')
                    defaulted_brand_name = vr_payload_dict.get('brand', 'the default brand')
                    message += f" NOTE: Product brand '{product.brand}' was not V&R recognized; defaulted to '{defaulted_brand_name}'. Please verify on V&R."
                message_type = "success"
            elif export_result and export_result.get("status") == "debug": # Handling the debug halt
                message = f"DEBUG: Halted in V&R client for payload inspection. SKU: {product.sku}. Client Message: {export_result.get('message')}"
                message_type = "info"
                # Optionally log the detailed payloads if returned in export_result for debug status
                if "received_payload" in export_result and "prepared_form_data" in export_result:
                    logger.info(f"DEBUG PAYLOADS for SKU {product.sku}:\nRECEIVED BY CLIENT:\n{json.dumps(export_result['received_payload'], indent=2, default=str)}\nPREPARED FORM DATA:\n{json.dumps(export_result['prepared_form_data'], indent=2, default=str)}")

            else: # Handles "error" status or unexpected structure
                error_detail = export_result.get("message", "Unknown V&R client error.") if export_result else "No result from V&R client."
                message = f"Failed to process V&R listing for SKU '{product.sku}': {error_detail}"
                # message_type is already "error"
            
            logger.info(f"V&R processing result for {product.sku}: {message}")
        
        elif platform_slug == "shopify":
            logger.info(f"=== SINGLE PLATFORM LISTING: SHOPIFY ===")
            logger.info(f"Product ID: {product.id}, SKU: {product.sku}")
            logger.info(f"Product: {product.brand} {product.model}")
            
            try:
                # Initialize Shopify service
                shopify_service = ShopifyService(db, settings)
                
                # Prepare enriched data similar to what would come from Reverb
                enriched_data = {
                    "title": f"{product.year} {product.brand} {product.model}" if product.year else f"{product.brand} {product.model}",
                    "description": product.description,
                    "photos": [],
                    "cloudinary_photos": [],
                    "condition": {"display_name": product.condition},
                    "price": {"amount": str(product.base_price), "currency": "GBP"},
                    "inventory": product.quantity if product.quantity else 1,
                    "finish": product.finish,
                    "year": str(product.year) if product.year else None,
                    "model": product.model,
                    "brand": product.brand
                }
                
                # Add images
                if product.primary_image:
                    enriched_data["cloudinary_photos"].append({"preview_url": product.primary_image, "url": product.primary_image})
                if product.additional_images:
                    for img_url in product.additional_images:
                        enriched_data["cloudinary_photos"].append({"preview_url": img_url, "url": img_url})
                
                result = await shopify_service.create_listing_from_product(product, enriched_data)
                
                if result.get("status") == "success":
                    message = f"Successfully created Shopify listing with ID: {result.get('shopify_product_id')}"
                    message_type = "success"
                else:
                    message = f"Failed to create Shopify listing: {result.get('message', 'Unknown error')}"
                    message_type = "error"
                    
            except Exception as e:
                logger.error(f"Error creating Shopify listing: {str(e)}")
                message = f"Error creating Shopify listing: {str(e)}"
                message_type = "error"
        
        elif platform_slug == "ebay":
            logger.info(f"=== SINGLE PLATFORM LISTING: EBAY ===")
            logger.info(f"Product ID: {product.id}, SKU: {product.sku}")
            logger.info(f"Product: {product.brand} {product.model}")
            logger.warning("⚠️  NOTE: eBay requires proper shipping profiles to be configured")
            
            try:
                # Initialize eBay service
                ebay_service = EbayService(db, settings)
                
                # Prepare enriched data
                enriched_data = {
                    "title": f"{product.year} {product.brand} {product.model}" if product.year else f"{product.brand} {product.model}",
                    "description": product.description,
                    "photos": [],
                    "condition": {"display_name": product.condition},
                    "categories": [],  # Will be populated with Reverb category UUID if available
                    "price": {"amount": str(product.base_price), "currency": "GBP"},
                    "inventory": product.quantity if product.quantity else 1,
                    "finish": product.finish,
                    "year": str(product.year) if product.year else None,
                    "model": product.model,
                    "brand": product.brand
                }
                
                # Add images
                if product.primary_image:
                    enriched_data["photos"].append({"url": product.primary_image})
                if product.additional_images:
                    for img_url in product.additional_images:
                        enriched_data["photos"].append({"url": img_url})
                
                # Get Reverb category UUID if the product has a Reverb listing
                reverb_uuid = None
                if product.sku.startswith('REV-'):
                    # Check if we have a Reverb listing with category info
                    reverb_listing_query = select(ReverbListing).join(
                        PlatformCommon
                    ).where(
                        PlatformCommon.product_id == product.id,
                        PlatformCommon.platform_name == 'reverb'
                    )
                    reverb_result = await db.execute(reverb_listing_query)
                    reverb_listing = reverb_result.scalar_one_or_none()
                    
                    if reverb_listing and reverb_listing.extended_attributes:
                        categories = reverb_listing.extended_attributes.get('categories', [])
                        if categories and len(categories) > 0:
                            reverb_uuid = categories[0].get('uuid')
                            logger.info(f"Found Reverb UUID from listing: {reverb_uuid}")
                
                # Add category UUID to enriched data if found
                if reverb_uuid:
                    enriched_data["categories"] = [{"uuid": reverb_uuid}]
                
                # Get policies from product's platform data if available
                # Default to Business Policies with the profile IDs from existing listings
                policies = {
                    'shipping_profile_id': '252277357017',
                    'payment_profile_id': '252544577017',
                    'return_profile_id': '252277356017'
                }
                if hasattr(product, 'platform_data') and product.platform_data and 'ebay' in product.platform_data:
                    ebay_data = product.platform_data['ebay']
                    # Override with product-specific policies if they exist
                    if ebay_data.get('shipping_policy'):
                        policies['shipping_profile_id'] = ebay_data.get('shipping_policy')
                    if ebay_data.get('payment_policy'):
                        policies['payment_profile_id'] = ebay_data.get('payment_policy')
                    if ebay_data.get('return_policy'):
                        policies['return_profile_id'] = ebay_data.get('return_policy')
                
                result = await ebay_service.create_listing_from_product(
                    product=product,
                    reverb_api_data=enriched_data,
                    use_shipping_profile=True,  # Always use Business Policies
                    **policies
                )
                
                if result.get("status") == "success":
                    message = f"Successfully created eBay listing with ID: {result.get('external_id', result.get('ItemID'))}"
                    message_type = "success"
                else:
                    message = f"Failed to create eBay listing: {result.get('message', result.get('error', 'Unknown error'))}"
                    message_type = "error"
                    
            except Exception as e:
                logger.error(f"Error creating eBay listing: {str(e)}")
                message = f"Error creating eBay listing: {str(e)}"
                message_type = "error"
        
        elif platform_slug == "reverb":
            logger.info(f"Processing Reverb listing for product {product.sku}")
            try:
                reverb_service = ReverbService(db, settings)

                # Check if already listed on Reverb
                existing_listing = await db.execute(
                    select(PlatformCommon)
                    .where(
                        and_(
                            PlatformCommon.product_id == product_id,
                            PlatformCommon.platform_name == "reverb"
                        )
                    )
                )
                if existing_listing.scalar_one_or_none():
                    message = "Product is already listed on Reverb"
                    message_type = "warning"
                else:
                    # Create listing on Reverb
                    result = await reverb_service.create_listing_from_product(product_id)

                    if result.get("status") == "success":
                        message = f"Successfully created Reverb listing with ID: {result.get('reverb_listing_id')}"
                        message_type = "success"

                        # Update product status to ACTIVE if it was DRAFT
                        if product.status == ProductStatus.DRAFT:
                            product.status = ProductStatus.ACTIVE
                            await db.commit()
                    else:
                        message = f"Error creating Reverb listing: {result.get('error', 'Unknown error')}"
                        message_type = "error"

            except Exception as e:
                logger.error(f"Error creating Reverb listing: {str(e)}")
                message = f"Error creating Reverb listing: {str(e)}"
                message_type = "error"
        
        else:
            message = f"Listing on platform '{platform_slug}' is not yet implemented."
            message_type = "info"
            logger.info(message)

    except ValueError as ve: # Catch data validation/mapping errors from our helper
        logger.error(f"Data error for {platform_slug} listing (product {product_id}): {str(ve)}", exc_info=True)
        message = f"Data error for {platform_slug}: {str(ve)}"
        message_type = "error"
    except HTTPException: # Re-raise HTTPExceptions to let FastAPI handle them
        raise
    except Exception as e:
        logger.error(f"Unexpected error listing product {product_id} on {platform_slug}: {str(e)}", exc_info=True)
        message = f"Server error listing on {platform_slug}. Check logs."
        message_type = "error"

    # Using quote_plus to safely encode the message for URL and avoid truncation at ampersand
    return RedirectResponse(
        url=f"{redirect_url}?message={quote_plus(message)}&message_type={message_type}", 
        status_code=303
    )

@router.get("/add", response_class=HTMLResponse)
async def add_product_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    # Get existing brands for dropdown (alphabetically sorted)
    existing_brands = await db.execute(
        select(Product.brand)
        .distinct()
        .filter(Product.brand.isnot(None))
        .order_by(Product.brand)
    )
    existing_brands = [b[0] for b in existing_brands.all() if b[0]]

    # Get existing categories for dropdown (alphabetically sorted)
    categories_result = await db.execute(
        select(Product.category)
        .distinct()
        .filter(Product.category.isnot(None))
        .order_by(Product.category)
    )
    categories = [c[0] for c in categories_result.all() if c[0]]

    # Get existing products for "copy from" feature
    # Limit to 100 most recent products
    existing_products_result = await db.execute(
        select(Product)
        .order_by(desc(Product.created_at))
        .limit(100)
    )
    existing_products = existing_products_result.scalars().all()

    return templates.TemplateResponse(
        "inventory/add.html",
        {
            "request": request,
            "existing_brands": existing_brands,
            "categories": categories,
            "existing_products": existing_products,
            "ebay_status": "pending",
            "reverb_status": "pending",
            "vr_status": "pending",
            "shopify_status": "pending",
            "tinymce_api_key": settings.TINYMCE_API_KEY  # This is important
        }
    )

@router.post("/add")
async def add_product(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    brand: str = Form(...),
    model: str = Form(...),
    sku: str = Form(...),
    category: str = Form(...),
    condition: str = Form(...),
    base_price: float = Form(...),
    cost_price: Optional[float] = Form(None),
    description: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    decade: Optional[int] = Form(None),
    finish: Optional[str] = Form(None),
    status: str = Form("DRAFT"),
    processing_time: Optional[int] = Form(None),
    price: Optional[float] = Form(None),
    price_notax: Optional[float] = Form(None),
    collective_discount: Optional[float] = Form(None),
    offer_discount: Optional[float] = Form(None),
    # Checkbox fields
    in_collective: Optional[bool] = Form(False),
    in_inventory: Optional[bool] = Form(True),
    in_reseller: Optional[bool] = Form(False),
    free_shipping: Optional[bool] = Form(False),
    buy_now: Optional[bool] = Form(True),
    show_vat: Optional[bool] = Form(True),
    local_pickup: Optional[bool] = Form(False),
    available_for_shipment: Optional[bool] = Form(True),
    is_stocked_item: Optional[bool] = Form(False),
    quantity_raw: Optional[str] = Form(None),
    # Media fields
    primary_image_file: Optional[UploadFile] = File(None),
    primary_image_url: Optional[str] = Form(None),
    additional_images_files: List[UploadFile] = File([]),
    additional_images_urls: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    external_link: Optional[str] = Form(None),
    # Platform sync fields
    sync_all: Optional[str] = Form("true"),
    sync_platforms: Optional[List[str]] = Form(None)
):
    """
    Creates a new product from form data and optionally sets up platform listings.

    1. Removed duplicated code: The route is now structured in a clear, logical flow with no duplicate processing.
    2. Better error handling:
        - Added specific error handling for different types of errors
        - Separated validation errors from processing errors
        - Added proper platform service error handling
    3. Improved structure:
        - Clear step-by-step process: validate → process → create → redirect
        - Non-critical errors in platform operations don't fail the whole request
        - Clear separation of concerns
    4. Added proper exception classes:
        - Created a comprehensive exception hierarchy
        - Each module has its own exception types
        - Allows more targeted error handling

    25.02.25: Enhanced product creation endpoint that handles the comprehensive form.

    This implementation:

    1. Properly processes all fields including platform-specific data
    2. Handles image uploads more robustly
    3. Integrates with multiple platforms in parallel
    4. Provides detailed feedback on each platform's status

    """

    # Debug logging
    print("===== POST REQUEST TO /add =====")
    print("Method:", request.method)
    form_data = await request.form()

    # Parse quantity (allow blank strings from form submissions)
    if quantity_raw in (None, "", " "):
        quantity = None
    else:
        try:
            quantity = int(str(quantity_raw).strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="Quantity must be a valid integer")

    # Sanitize form data for logging (remove base64 image data)
    log_form_data = {}
    for key, value in form_data.items():
        if isinstance(value, str) and value.startswith('data:image'):
            log_form_data[key] = f"[base64 image data - {len(value)} chars]"
        elif key == 'image_files' and hasattr(value, 'filename'):
            log_form_data[key] = f"[file upload: {value.filename}]"
        else:
            log_form_data[key] = value

    print("Form data received:", log_form_data)

    # Get existing brands - needed for error responses (alphabetically sorted)
    existing_brands = await db.execute(
        select(Product.brand)
        .distinct()
        .filter(Product.brand.isnot(None))
        .order_by(Product.brand)
    )
    existing_brands = [b[0] for b in existing_brands.all() if b[0]]

    categories_result = await db.execute(
        select(Product.category)
        .distinct()
        .filter(Product.category.isnot(None))
        .order_by(Product.category)
    )
    categories = [c[0] for c in categories_result.all() if c[0]]
    
    existing_products_result = await db.execute(
        select(Product)
        .order_by(desc(Product.created_at))
        .limit(100)
    )
    existing_products = existing_products_result.scalars().all()

    # Platform statuses to track integration results
    platform_statuses = {
        "ebay": {"status": "pending", "message": "Waiting for sync"},
        "reverb": {"status": "pending", "message": "Waiting for sync"},
        "vr": {"status": "pending", "message": "Waiting for sync"},
        "shopify": {"status": "pending", "message": "Waiting for sync"}
    }

    try:
        # Initialize services
        product_service = ProductService(db)
        ebay_service = EbayService(db, settings)
        reverb_service = ReverbService(db, settings)
        shopify_service = ShopifyService(db, settings)

        # Process brand
        brand = brand.title()
        is_new_brand = brand not in existing_brands

        # Validate status
        try:
            status_enum = ProductStatus[status.upper()]
        except KeyError:
            return templates.TemplateResponse(
                "inventory/add.html",
                {
                    "request": request,
                    "error": f"Invalid status value: {status}. Must be one of: {', '.join(ProductStatus.__members__.keys())}",
                    "form_data": request.form,
                    "existing_brands": existing_brands,
                    "categories": categories,
                    "existing_products": existing_products,
                    "ebay_status": "error",
                    "reverb_status": "error",
                    "vr_status": "error",
                    "shopify_status": "error"
                },
                status_code=400
            )

        # Validate condition
        try:
            condition_enum = ProductCondition(condition)
        except ValueError:
            return templates.TemplateResponse(
                "inventory/add.html",
                {
                    "request": request,
                    "error": f"Invalid condition value: {condition}",
                    "form_data": request.form,
                    "existing_brands": existing_brands,
                    "categories": categories,
                    "existing_products": existing_products,
                    "ebay_status": "error",
                    "reverb_status": "error",
                    "vr_status": "error",
                    "shopify_status": "error"
                },
                status_code=400
            )

        # Handle images
        primary_image = None
        if primary_image_file and primary_image_file.filename:
            primary_image = await save_upload_file(primary_image_file)
        elif primary_image_url:
            primary_image = primary_image_url

        additional_images = []
        if additional_images_files:
            for file in additional_images_files:
                if file.filename:
                    path = await save_upload_file(file)
                    additional_images.append(path)

        if additional_images_urls:
            parsed_urls: List[str] = []
            stripped = additional_images_urls.strip()
            if stripped.startswith('['):
                try:
                    maybe_list = json.loads(stripped)
                    if isinstance(maybe_list, list):
                        parsed_urls = [str(u).strip() for u in maybe_list if str(u).strip()]
                except json.JSONDecodeError:
                    parsed_urls = []
            if not parsed_urls:
                parsed_urls = [url.strip() for url in additional_images_urls.split('\n') if url.strip()]
            additional_images.extend(parsed_urls)

        # Convert local static paths to full URLs for external platforms
        def make_full_url(path):
            if path and path.startswith('/static/'):
                # Get the base URL from the request
                base_url = str(request.base_url).rstrip('/')
                return f"{base_url}{path}"
            return path

        # Apply URL conversion
        primary_image, additional_images = await ensure_remote_media_urls(
            primary_image,
            additional_images,
            sku,
            settings,
        )

        if primary_image:
            primary_image = make_full_url(primary_image)
        additional_images = [make_full_url(img) for img in additional_images]
            
        # Process platform-specific data from form
        platform_data = {}
        for key, value in form_data.items():
            if key.startswith("platform_data__"):
                parts = key.split("__")
                if len(parts) >= 3:
                    platform = parts[1]
                    field = parts[2]
                    
                    if platform not in platform_data:
                        platform_data[platform] = {}
                    
                    # Handle boolean values properly
                    if isinstance(value, str) and value.lower() in ['true', 'on']:
                        platform_data[platform][field] = True
                    elif isinstance(value, str) and value.lower() == 'false':
                        platform_data[platform][field] = False
                    else:
                        platform_data[platform][field] = value

        # Create product data
        product_data = ProductCreate(
            brand=brand,
            model=model,
            sku=sku,
            category=category,
            condition=condition_enum.value,
            base_price=base_price,
            cost_price=cost_price,
            description=description,
            year=year,
            decade=decade,
            finish=finish,
            status=status_enum.value,
            price=price,
            price_notax=price_notax,
            collective_discount=collective_discount,
            offer_discount=offer_discount,
            in_collective=in_collective,
            in_inventory=in_inventory,
            in_reseller=in_reseller,
            free_shipping=free_shipping,
            buy_now=buy_now,
            show_vat=show_vat,
            local_pickup=local_pickup,
            available_for_shipment=available_for_shipment,
            is_stocked_item=is_stocked_item,
            quantity=quantity if is_stocked_item else None,
            processing_time=processing_time,
            primary_image=primary_image,
            additional_images=additional_images,
            video_url=video_url,
            external_link=external_link
        )

        # Step 1: Create the product
        product_read = await product_service.create_product(product_data)
        print(f"Product created successfully: {product_read.id}")

        # Get the actual SQLAlchemy model instance for platform services
        product = await product_service.get_product_model_instance(product_read.id)
        if not product:
            raise ValueError(f"Could not retrieve created product with ID {product_read.id}")

        # Step 2: Determine which platforms to sync
        platforms_to_sync = []
        if sync_all == "true":
            platforms_to_sync = ["shopify", "ebay", "vr", "reverb"]
        elif sync_platforms:
            platforms_to_sync = sync_platforms
        
        logger.info(f"=== PLATFORM SYNC CONFIGURATION ===")
        logger.info(f"Sync all: {sync_all}")
        logger.info(f"Selected platforms: {platforms_to_sync}")
        logger.info(f"Product created: ID={product.id}, SKU={product.sku}")
        
        # Step 3: Create platform listings based on selection

        # Initialize enriched_data - will be populated from Reverb if creating there first
        enriched_data = None

        # If Reverb is selected, create it FIRST to get enriched data
        if "reverb" in platforms_to_sync:
            logger.info(f"=== CREATING REVERB LISTING FIRST ===")
            logger.info(f"Product: {product.sku} - {product.brand} {product.model}")

            try:
                # Initialize Reverb client
                from app.services.reverb.client import ReverbClient
                reverb_client = ReverbClient(api_key=settings.REVERB_API_KEY)

                # Check if a Reverb listing already exists for this SKU
                logger.info(f"Checking if Reverb listing already exists for SKU: {product.sku}")
                existing_listings = await reverb_client.find_listing_by_sku(product.sku)

                if existing_listings.get('total', 0) > 0:
                    # Listing already exists, update it with new data
                    existing_listing = existing_listings['listings'][0]
                    reverb_id = str(existing_listing['id'])
                    logger.info(f"Found existing Reverb listing with ID: {reverb_id} - will update it")

                    # Prepare update data with photos and shipping
                    update_data = {}

                    # Add photos if we have valid URLs
                    valid_photos = []
                    if product.primary_image and product.primary_image.startswith(('http://', 'https://')):
                        valid_photos.append(product.primary_image)
                    if product.additional_images:
                        for img_url in product.additional_images:
                            if img_url.startswith(('http://', 'https://')):
                                valid_photos.append(img_url)

                    if valid_photos:
                        update_data["photos"] = valid_photos
                        logger.info(f"Updating with {len(valid_photos)} photos")

                    # Add shipping profile if provided
                    shipping_profile_id = platform_data.get("reverb", {}).get("shipping_profile")
                    if shipping_profile_id:
                        update_data["shipping_profile_id"] = shipping_profile_id
                        logger.info(f"Updating with shipping profile ID: {shipping_profile_id}")

                    # Update the listing if we have changes
                    if update_data:
                        logger.info(f"Updating Reverb listing {reverb_id} with: {list(update_data.keys())}")
                        updated_listing = await reverb_client.update_listing(reverb_id, update_data)
                        # Reverb often returns an empty body for async updates; fetch the listing to get fresh data
                        reverb_response = updated_listing or {}
                        if not reverb_response or not reverb_response.get("listing"):
                            logger.info("Fetching latest Reverb listing snapshot after update")
                            reverb_response = await reverb_client.get_listing(reverb_id)
                    else:
                        logger.info("No updates needed for existing Reverb listing")
                        # Get full listing details
                        reverb_response = await reverb_client.get_listing(reverb_id)

                    listing_data = reverb_response.get("listing", reverb_response) or {}

                    # Check if local database entries already exist
                    existing_platform_common = await db.execute(
                        select(PlatformCommon)
                        .where(
                            and_(
                                PlatformCommon.product_id == product.id,
                                PlatformCommon.platform_name == "reverb"
                            )
                        )
                    )
                    platform_common = existing_platform_common.scalar_one_or_none()

                    if platform_common:
                        # Update existing platform_common
                        logger.info(f"Found existing PlatformCommon record for product {product.id}, updating it")
                        platform_common.external_id = reverb_id
                        platform_common.status = "ACTIVE"
                        platform_common.listing_url = f"https://reverb.com/item/{reverb_id}"
                        platform_common.platform_specific_data = listing_data
                        platform_common.last_sync = datetime.utcnow()
                    else:
                        # Create new platform_common entry
                        logger.info(f"Creating new PlatformCommon record for product {product.id}")
                        platform_common = PlatformCommon(
                            product_id=product.id,
                            platform_name="reverb",
                            external_id=reverb_id,
                            status="ACTIVE",
                            listing_url=f"https://reverb.com/item/{reverb_id}",
                            platform_specific_data=listing_data,
                            last_sync=datetime.utcnow()
                        )
                        db.add(platform_common)

                    await db.flush()

                    # Extract category UUID
                    category_uuid = reverb_options.get("primary_category")
                    if not category_uuid:
                        categories_payload = listing_data.get('categories') or reverb_response.get('categories')
                        if categories_payload:
                            first_category = categories_payload[0] if isinstance(categories_payload, list) else categories_payload
                            if isinstance(first_category, dict):
                                category_uuid = first_category.get('uuid')

                    # Check if reverb_listing already exists by reverb_listing_id
                    existing_reverb_listing = await db.execute(
                        select(ReverbListing)
                        .where(ReverbListing.reverb_listing_id == reverb_id)
                    )
                    reverb_listing = existing_reverb_listing.scalar_one_or_none()

                    if reverb_listing:
                        # Update existing reverb_listing
                        logger.info(f"Found existing ReverbListing record for reverb ID {reverb_id}, updating it")
                        reverb_listing.reverb_listing_id = reverb_id
                        reverb_listing.reverb_category_uuid = category_uuid
                        reverb_listing.reverb_state = (listing_data.get('state', {}) or {}).get('slug', 'draft')
                        reverb_listing.extended_attributes = listing_data
                    else:
                        # Create new reverb_listing entry
                        logger.info(f"Creating new ReverbListing record for reverb ID {reverb_id}")
                        reverb_listing = ReverbListing(
                            platform_id=platform_common.id,
                            reverb_listing_id=reverb_id,
                            reverb_category_uuid=category_uuid,
                            reverb_state=(listing_data.get('state', {}) or {}).get('slug', 'draft'),
                            extended_attributes=listing_data
                        )
                        db.add(reverb_listing)

                    await db.commit()

                    platform_statuses["reverb"] = {
                        "status": "success",
                        "message": f"Listed on Reverb with ID: {reverb_id}"
                    }

                    # Use the listing as enriched data for other platforms
                    enriched_data = listing_data

                    # Remove Reverb from platforms_to_sync since we handled it
                    platforms_to_sync = [p for p in platforms_to_sync if p != "reverb"]
                else:
                    # No existing listing, proceed with creation
                    logger.info("No existing Reverb listing found, creating new one")

                    # Prepare listing data for Reverb
                    # Build title from product attributes since ProductRead doesn't have title
                    title = f"{product.year} {product.brand} {product.model}" if product.year else f"{product.brand} {product.model}"
                    # Get condition UUID - either from platform_data or map it
                    condition_uuid = platform_data.get("reverb", {}).get("condition_uuid")
                    if not condition_uuid and product.condition:
                            # Load condition mappings from JSON file
                            import json
                            from pathlib import Path
                            mappings_file = Path(__file__).parent.parent.parent / "data" / "reverb_condition_mappings.json"
                            with open(mappings_file, 'r') as f:
                                mappings_data = json.load(f)
                            condition_map = {k: v["uuid"] for k, v in mappings_data["condition_mappings"].items()}
                            condition_uuid = condition_map.get(product.condition.upper(), "df268ad1-c462-4ba6-b6db-e007e23922ea")  # Default to Excellent
                            logger.info(f"Mapped condition '{product.condition}' to UUID: {condition_uuid}")

                    reverb_options = platform_data.get("reverb", {})
                    reverb_price_override = _parse_price_to_decimal(
                        reverb_options.get("price") or reverb_options.get("price_display")
                    )
                    price_amount = reverb_price_override or _parse_price_to_decimal(product.base_price)
                    if price_amount is None:
                        price_amount = Decimal(str(product.base_price or 0))

                    reverb_listing_data = {
                        "title": title,
                        "make": product.brand,
                        "model": product.model,
                        "description": product.description or f"{product.brand} {product.model} in {product.condition} condition",
                        "condition": {"uuid": condition_uuid} if condition_uuid else None,
                        "categories": [{"uuid": platform_data.get("reverb", {}).get("primary_category")}],
                        "price": {
                            "amount": _decimal_to_str(price_amount),
                            "currency": "GBP"
                        },
                        "shipping": {
                            "local": product.local_pickup if hasattr(product, 'local_pickup') else False,
                            "rates": []  # Will use shipping profile if provided
                        },
                        "has_inventory": product.is_stocked_item if hasattr(product, 'is_stocked_item') else False,
                        "inventory": product.quantity if product.is_stocked_item else 1,
                        "finish": product.finish,
                        "year": str(product.year) if product.year else None,
                        "sku": product.sku,
                        "publish": True,  # Publish immediately
                        "photos": []
                    }

                    # Handle images - use URLs directly
                    valid_photos = []

                    # Process primary image
                    if product.primary_image:
                        # Skip local server paths and base64 - Reverb needs external URLs
                        if product.primary_image.startswith('/static/'):
                            logger.warning(f"Skipping local server image {product.primary_image} - Reverb requires external URLs")
                        elif product.primary_image.startswith('data:'):
                            logger.warning(f"Skipping base64 image - Reverb requires external URLs")
                        elif product.primary_image.startswith(('http://', 'https://')):
                            # It's a valid external URL (Dropbox or other)
                            valid_photos.append(product.primary_image)
                        else:
                            logger.warning(f"Skipping invalid image URL: {product.primary_image}")

                    # Process additional images
                    if product.additional_images:
                        for idx, img_url in enumerate(product.additional_images):
                            if img_url.startswith('/static/'):
                                logger.warning(f"Skipping local server image {img_url} - Reverb requires external URLs")
                            elif img_url.startswith('data:'):
                                logger.warning(f"Skipping base64 additional image {idx} - Reverb requires external URLs")
                            elif img_url.startswith(('http://', 'https://')):
                                valid_photos.append(img_url)
                            else:
                                logger.warning(f"Skipping invalid additional image {idx}: {img_url}")

                    # Only add photos if we have valid URLs
                    if valid_photos:
                        reverb_listing_data["photos"] = valid_photos
                        logger.info(f"Added {len(valid_photos)} photos to Reverb listing")
                    else:
                        logger.warning("No valid external image URLs for Reverb after processing")
                        # Remove photos key entirely if no valid URLs
                        if "photos" in reverb_listing_data:
                            del reverb_listing_data["photos"]

                    # Add shipping profile if provided
                    shipping_profile_id = platform_data.get("reverb", {}).get("shipping_profile")
                    if shipping_profile_id:
                        reverb_listing_data["shipping_profile_id"] = shipping_profile_id
                        logger.info(f"Using shipping profile ID: {shipping_profile_id}")
                    else:
                        logger.warning("No shipping profile ID provided for Reverb listing")

                    # Create the listing on Reverb
                    # Log data without images to avoid massive base64 strings in terminal
                    log_data = {k: v for k, v in reverb_listing_data.items() if k != 'photos'}
                    log_data['photos'] = f"[{len(reverb_listing_data.get('photos', []))} images]"
                    logger.info(f"Creating Reverb listing with data: {json.dumps(log_data, indent=2)}")
                    reverb_response = await reverb_client.create_listing(reverb_listing_data)

                    listing_data = reverb_response.get("listing", reverb_response) or {}
                    reverb_id_value = listing_data.get("id") or listing_data.get("uuid")
                    if not reverb_id_value:
                        raise RuntimeError("Reverb API response did not include a listing ID")

                    reverb_id = str(reverb_id_value)
                    logger.info(f"✅ Created Reverb listing with ID: {reverb_id}")

                    # Create or update local database entries
                    # 1. Check if platform_common entry exists
                    existing_platform_common = await db.execute(
                        select(PlatformCommon)
                        .where(
                            and_(
                                PlatformCommon.product_id == product.id,
                                PlatformCommon.platform_name == "reverb"
                            )
                        )
                    )
                    platform_common = existing_platform_common.scalar_one_or_none()

                    if platform_common:
                        # Update existing platform_common
                        logger.info(f"Found existing PlatformCommon record for product {product.id}, updating it")
                        platform_common.external_id = reverb_id
                        platform_common.status = "ACTIVE"
                        platform_common.listing_url = f"https://reverb.com/item/{reverb_id}"
                        platform_common.platform_specific_data = listing_data
                        platform_common.last_sync = datetime.utcnow()
                    else:
                        # Create new platform_common entry
                        logger.info(f"Creating new PlatformCommon record for product {product.id}")
                        platform_common = PlatformCommon(
                            product_id=product.id,
                            platform_name="reverb",
                            external_id=reverb_id,
                            status="ACTIVE",
                            listing_url=f"https://reverb.com/item/{reverb_id}",
                            platform_specific_data=listing_data,
                            last_sync=datetime.utcnow()
                        )
                        db.add(platform_common)

                    await db.flush()

                    # 2. Create or update reverb_listings entry
                    # Extract category UUID from the request data
                    category_uuid = reverb_options.get("primary_category")
                    if not category_uuid:
                        categories_payload = listing_data.get('categories') or reverb_response.get('categories')
                        if categories_payload:
                            first_category = categories_payload[0] if isinstance(categories_payload, list) else categories_payload
                            if isinstance(first_category, dict):
                                category_uuid = first_category.get('uuid')

                    # Check if reverb_listing already exists by reverb_listing_id
                    existing_reverb_listing = await db.execute(
                        select(ReverbListing)
                        .where(ReverbListing.reverb_listing_id == reverb_id)
                    )
                    reverb_listing = existing_reverb_listing.scalar_one_or_none()

                    if reverb_listing:
                        # Update existing reverb_listing
                        logger.info(f"Found existing ReverbListing record for reverb ID {reverb_id}, updating it")
                        reverb_listing.reverb_listing_id = reverb_id
                        reverb_listing.reverb_category_uuid = category_uuid
                        reverb_listing.reverb_state = (listing_data.get("state", {}) or {}).get("slug", "live")
                        reverb_listing.extended_attributes = listing_data
                    else:
                        # Create new reverb_listing entry
                        logger.info(f"Creating new ReverbListing record for reverb ID {reverb_id}")
                        reverb_listing = ReverbListing(
                            platform_id=platform_common.id,
                            reverb_listing_id=reverb_id,
                            reverb_category_uuid=category_uuid,
                            reverb_state=(listing_data.get("state", {}) or {}).get("slug", "live"),
                            extended_attributes=listing_data
                        )
                        db.add(reverb_listing)

                    await db.commit()

                    platform_statuses["reverb"] = {
                        "status": "success",
                        "message": f"Listed on Reverb with ID: {reverb_id}"
                    }

                    # NOW use the Reverb response as enriched data for other platforms
                    enriched_data = reverb_response

                    # Remove Reverb from platforms_to_sync since we already created it
                    platforms_to_sync = [p for p in platforms_to_sync if p != "reverb"]

            except Exception as e:
                logger.error(f"Reverb listing error: {str(e)}", exc_info=True)
                platform_statuses["reverb"] = {
                    "status": "error",
                    "message": f"Error: {str(e)}"
                }

                # If Reverb fails, DO NOT create on other platforms
                logger.warning("❌ Reverb creation failed - skipping other platforms")

                # Set other platforms as skipped
                for platform in ["ebay", "shopify", "vr"]:
                    if platform in platforms_to_sync:
                        platform_statuses[platform] = {
                            "status": "info",
                            "message": "Skipped - Reverb creation failed"
                        }

                # Clear platforms_to_sync so no other platforms are attempted
                platforms_to_sync = []
                enriched_data = None

        # If no enriched data from Reverb, create from product data
        if not enriched_data and len(platforms_to_sync) > 0:
            logger.info("No Reverb data available - creating enriched data from product")

        # Create enriched data from product if needed
        if not enriched_data:
            enriched_data = {
                "title": f"{product.year} {product.brand} {product.model}" if product.year else f"{product.brand} {product.model}",
                "description": product.description,
                "photos": [],  # Will be populated with images
                "cloudinary_photos": [],  # For high-res images
                "condition": {"display_name": product.condition},
                "categories": [{"uuid": platform_data.get("reverb", {}).get("primary_category")}] if platform_data.get("reverb") else [],
                "price": {"amount": str(product.base_price), "currency": "GBP"},
                "inventory": product.quantity if product.is_stocked_item else 1,
                "shipping": {},
                "finish": product.finish,
                "year": str(product.year) if product.year else None,
                "model": product.model,
                "brand": product.brand
            }

            # Add images to enriched data
            if product.primary_image:
                enriched_data["photos"].append({
                    "_links": {"large": {"href": product.primary_image}},
                    "url": product.primary_image
                })
                enriched_data["cloudinary_photos"].append({"preview_url": product.primary_image, "url": product.primary_image})

            if product.additional_images:
                for img_url in product.additional_images:
                    enriched_data["photos"].append({
                        "_links": {"large": {"href": img_url}},
                        "url": img_url
                    })
                    enriched_data["cloudinary_photos"].append({"preview_url": img_url, "url": img_url})
        
        # Create listings on each selected platform
        if "shopify" in platforms_to_sync:
            logger.info(f"=== CREATING SHOPIFY LISTING ===")
            logger.info(f"Product: {product.sku} - {product.brand} {product.model}")
            try:
                # Initialize Shopify service if not already done
                if 'shopify_service' not in locals():
                    shopify_service = ShopifyService(db, settings)
                
                shopify_options = platform_data.get("shopify", {})
                logger.info("Calling shopify_service.create_listing_from_product()...")
                result = await shopify_service.create_listing_from_product(
                    product=product,
                    reverb_data=enriched_data,
                    platform_options=shopify_options
                )
                logger.info(f"Shopify result: {result}")

                if result.get("status") == "success":
                    external_id = str(result.get("external_id") or result.get("shopify_product_id") or "")
                    product_gid = result.get("product_gid") or (f"gid://shopify/Product/{external_id}" if external_id else None)

                    existing_platform_common = await db.execute(
                        select(PlatformCommon).where(
                            and_(
                                PlatformCommon.product_id == product.id,
                                PlatformCommon.platform_name == "shopify"
                            )
                        )
                    )
                    platform_common = existing_platform_common.scalar_one_or_none()

                    handle = generate_shopify_handle(product.brand, product.model, product.sku)
                    listing_url = None

                    if product_gid:
                        try:
                            shopify_client = ShopifyGraphQLClient()
                            snapshot = shopify_client.get_product_snapshot_by_id(product_gid)
                            if snapshot:
                                listing_url = snapshot.get("onlineStoreUrl") or snapshot.get("onlineStorePreviewUrl")
                                handle = snapshot.get("handle", handle) or handle
                        except Exception as fetch_error:
                            logger.warning("Could not fetch Shopify listing snapshot: %s", fetch_error)

                    if not listing_url and settings.SHOPIFY_SHOP_URL and handle:
                        listing_url = f"{settings.SHOPIFY_SHOP_URL.rstrip('/')}/products/{handle}"

                    if platform_common:
                        platform_common.external_id = external_id
                        platform_common.status = "ACTIVE"
                        platform_common.listing_url = listing_url
                        platform_common.sync_status = SyncStatus.SYNCED.value
                        platform_common.last_sync = datetime.utcnow()
                        platform_common.platform_specific_data = result
                    else:
                        platform_common = PlatformCommon(
                            product_id=product.id,
                            platform_name="shopify",
                            external_id=external_id,
                            status="ACTIVE",
                            listing_url=listing_url,
                            sync_status=SyncStatus.SYNCED.value,
                            last_sync=datetime.utcnow(),
                            platform_specific_data=result
                        )
                        db.add(platform_common)

                    await db.flush()

                    # Upsert ShopifyListing
                    listing_stmt = select(ShopifyListing).where(ShopifyListing.platform_id == platform_common.id)
                    existing_listing = await db.execute(listing_stmt)
                    shopify_listing = existing_listing.scalar_one_or_none()

                    price_decimal = _parse_price_to_decimal(
                        shopify_options.get("price") or shopify_options.get("price_display")
                    ) or _parse_price_to_decimal(product.base_price)
                    price_float = float(price_decimal) if price_decimal is not None else None

                    category_gid = shopify_options.get("category") or shopify_options.get("category_gid")
                    seo_keywords_raw = shopify_options.get("seo_keywords")
                    seo_keywords = None
                    if seo_keywords_raw:
                        seo_keywords = [kw.strip() for kw in seo_keywords_raw.split(',') if kw.strip()]

                    if shopify_listing:
                        shopify_listing.shopify_product_id = product_gid
                        shopify_listing.shopify_legacy_id = external_id
                        shopify_listing.handle = handle
                        shopify_listing.title = product.title or product.generate_title()
                        shopify_listing.status = "active"
                        shopify_listing.vendor = product.brand
                        shopify_listing.price = price_float
                        shopify_listing.category_gid = category_gid
                        shopify_listing.seo_keywords = seo_keywords
                        shopify_listing.extended_attributes = result
                        shopify_listing.last_synced_at = datetime.utcnow()
                    else:
                        shopify_listing = ShopifyListing(
                            platform_id=platform_common.id,
                            shopify_product_id=product_gid,
                            shopify_legacy_id=external_id,
                            handle=handle,
                            title=product.title or product.generate_title(),
                            status="active",
                            vendor=product.brand,
                            price=price_float,
                            category_gid=category_gid,
                            seo_keywords=seo_keywords,
                            extended_attributes=result,
                            last_synced_at=datetime.utcnow()
                        )
                        db.add(shopify_listing)

                    await db.commit()

                    platform_statuses["shopify"] = {
                        "status": "success",
                        "message": f"Listed on Shopify with ID: {external_id}"
                    }
                    logger.info(f"✅ Shopify listing created successfully: ID={external_id}")
                else:
                    await db.rollback()
                    platform_statuses["shopify"] = {
                        "status": "error",
                        "message": result.get("message", "Failed to create Shopify listing")
                    }
                    logger.warning(f"❌ Shopify listing failed: {result.get('message')}")
            except Exception as e:
                logger.error(f"Shopify listing error: {str(e)}", exc_info=True)
                platform_statuses["shopify"] = {
                    "status": "error",
                    "message": f"Error: {str(e)}"
                }
        
        if "ebay" in platforms_to_sync:
            logger.info(f"=== CREATING EBAY LISTING ===")
            logger.info(f"Product: {product.sku} - {product.brand} {product.model}")
            logger.warning("⚠️  NOTE: eBay listing creation may fail due to shipping profile requirements")
            logger.warning("⚠️  eBay requires business policies to be configured properly")
            try:
                # Get policies from platform data
                ebay_options = platform_data.get("ebay", {})
                ebay_policies = {
                    "shipping_profile_id": ebay_options.get("shipping_policy"),
                    "payment_profile_id": ebay_options.get("payment_policy"),
                    "return_profile_id": ebay_options.get("return_policy")
                }
                price_override = _parse_price_to_decimal(
                    ebay_options.get("price") or ebay_options.get("price_display")
                )
                logger.info(f"eBay policies: {ebay_policies}")
                
                logger.info("Calling ebay_service.create_listing_from_product()...")
                result = await ebay_service.create_listing_from_product(
                    product=product,
                    reverb_api_data=enriched_data,
                    use_shipping_profile=bool(ebay_policies.get("shipping_profile_id")),
                    price_override=price_override,
                    **ebay_policies
                )
                logger.info(f"eBay result: {result}")
                
                if result.get("status") == "success":
                    platform_statuses["ebay"] = {
                        "status": "success",
                        "message": f"Listed on eBay with ID: {result.get('external_id') or result.get('ItemID')}"
                    }
                    logger.info(f"✅ eBay listing created successfully: ID={result.get('external_id') or result.get('ItemID')}")
                else:
                    platform_statuses["ebay"] = {
                        "status": "error",
                        "message": result.get("error", "Failed to create eBay listing")
                    }
                    logger.warning(f"❌ eBay listing failed: {result.get('error')}")
            except Exception as e:
                logger.error(f"eBay listing error: {str(e)}", exc_info=True)
                platform_statuses["ebay"] = {
                    "status": "error",
                    "message": f"Error: {str(e)}"
                }
        
        if "vr" in platforms_to_sync:
            logger.info(f"=== CREATING V&R LISTING ===")
            logger.info(f"Product: {product.sku} - {product.brand} {product.model}")
            try:
                # Initialize VR service if not already done
                if 'vr_service' not in locals():
                    vr_service = VRService(db)
                
                logger.info("Calling vr_service.create_listing_from_product()...")
                result = await vr_service.create_listing_from_product(
                    product=product,
                    reverb_data=enriched_data,
                    platform_options=platform_data.get("vr")
                )
                logger.info(f"V&R result: {result}")
                
                if result.get("status") == "success":
                    vr_message = "Successfully created V&R listing"
                    if result.get("vr_listing_id"):
                        vr_message = f"V&R listing ID: {result.get('vr_listing_id')}"
                    platform_statuses["vr"] = {
                        "status": "success",
                        "message": vr_message
                    }
                    logger.info("✅ V&R listing created successfully")
                else:
                    platform_statuses["vr"] = {
                        "status": "error",
                        "message": result.get("message", "Failed to create V&R listing")
                    }
                    logger.warning(f"❌ V&R listing failed: {result.get('message')}")
            except Exception as e:
                logger.error(f"V&R listing error: {str(e)}", exc_info=True)
                platform_statuses["vr"] = {
                    "status": "error",
                    "message": f"Error: {str(e)}"
                }
        
        # Reverb is already handled above if it was selected
        
        # Log final summary
        logger.info(f"=== PLATFORM SYNC SUMMARY ===")
        for platform, status in platform_statuses.items():
            if status["status"] == "success":
                logger.info(f"✅ {platform}: {status['message']}")
            elif status["status"] == "error":
                logger.error(f"❌ {platform}: {status['message']}")
            else:
                logger.info(f"ℹ️  {platform}: {status['message']}")

        # Step 4: Check if we need to rollback due to failures
        # Count successes and failures
        successful_platforms = [p for p, s in platform_statuses.items() if s["status"] == "success"]
        failed_platforms = [p for p, s in platform_statuses.items() if s["status"] == "error"]

        # Only rollback if Reverb failed (since it's the primary platform)
        # If other platforms fail, we keep the successful ones
        if "reverb" in failed_platforms:
            logger.warning(f"🔄 ROLLBACK INITIATED - Failed platforms: {failed_platforms}")
            logger.warning(f"Rolling back successful platforms: {successful_platforms}")

            # Rollback each successful platform
            for platform in successful_platforms:
                try:
                    logger.info(f"Rolling back {platform} listing...")

                    if platform == "reverb":
                        # Delete from Reverb API
                        reverb_listing = await db.execute(
                            select(ReverbListing).join(PlatformCommon).where(
                                PlatformCommon.product_id == product.id,
                                PlatformCommon.platform_name == "reverb"
                            )
                        )
                        reverb_listing = reverb_listing.scalar_one_or_none()
                        if reverb_listing and reverb_listing.reverb_listing_id:
                            try:
                                reverb_client = ReverbClient(api_key=settings.REVERB_API_KEY)
                                await reverb_client.delete_listing(reverb_listing.reverb_listing_id)
                                logger.info(f"✅ Deleted Reverb listing {reverb_listing.reverb_listing_id}")
                            except Exception as e:
                                logger.error(f"Failed to delete Reverb listing: {e}")

                    elif platform == "ebay":
                        # End eBay listing
                        ebay_listing = await db.execute(
                            select(EbayListing).join(PlatformCommon).where(
                                PlatformCommon.product_id == product.id,
                                PlatformCommon.platform_name == "ebay"
                            )
                        )
                        ebay_listing = ebay_listing.scalar_one_or_none()
                        if ebay_listing and ebay_listing.ebay_item_id:
                            try:
                                await ebay_service.end_listing(ebay_listing.ebay_item_id)
                                logger.info(f"✅ Ended eBay listing {ebay_listing.ebay_item_id}")
                            except Exception as e:
                                logger.error(f"Failed to end eBay listing: {e}")

                    elif platform == "shopify":
                        # Delete Shopify product
                        shopify_listing = await db.execute(
                            select(ShopifyListing).join(PlatformCommon).where(
                                PlatformCommon.product_id == product.id,
                                PlatformCommon.platform_name == "shopify"
                            )
                        )
                        shopify_listing = shopify_listing.scalar_one_or_none()
                        if shopify_listing and shopify_listing.shopify_product_id:
                            try:
                                await shopify_service.delete_product(shopify_listing.shopify_product_id)
                                logger.info(f"✅ Deleted Shopify product {shopify_listing.shopify_product_id}")
                            except Exception as e:
                                logger.error(f"Failed to delete Shopify product: {e}")

                    elif platform == "vr":
                        # V&R doesn't have API delete, just mark as deleted in our DB
                        logger.info("V&R listings cannot be deleted via API - will be cleaned up in database")

                except Exception as e:
                    logger.error(f"Error during {platform} rollback: {e}")

            # Delete all platform_common and related listing entries
            await db.execute(
                delete(PlatformCommon).where(PlatformCommon.product_id == product.id)
            )

            # Update product status to DRAFT
            product.status = ProductStatus.DRAFT
            await db.commit()

            logger.info("✅ Rollback complete - Product reverted to DRAFT status")

            # Update platform statuses for response
            for platform in successful_platforms:
                platform_statuses[platform] = {
                    "status": "rolled_back",
                    "message": "Rolled back due to other platform failures"
                }

        # Step 4.5: Update product status to ACTIVE if any platform creation succeeded
        if successful_platforms and product.status == ProductStatus.DRAFT:
            logger.info(f"✅ Updating product status to ACTIVE - successful platforms: {successful_platforms}")
            product.status = ProductStatus.ACTIVE
            await db.commit()

        # Step 5: Queue for platform sync (if stock manager is available)
        try:
            print("About to queue product")
            if hasattr(request.app.state, 'stock_manager') and hasattr(request.app.state.stock_manager, 'queue_product'):
                print("queue_product method exists, calling it")
                await request.app.state.stock_manager.queue_product(product.id)
                print("Product queued successfully")
            else:
                print("queue_product method doesn't exist - skipping")
        except Exception as e:
            print(f"Queue error (non-critical): {type(e).__name__}: {str(e)}")

        print("About to return redirect response")

        # Step 5: Redirect to product detail page with platform status
        # Encode platform statuses as query parameters for display
        query_params = []
        for platform, status_info in platform_statuses.items():
            if status_info["status"] != "pending":  # Only show platforms that were processed
                query_params.append(f"{platform}_status={status_info['status']}")
                # URL encode the message to handle special characters
                from urllib.parse import quote
                query_params.append(f"{platform}_message={quote(status_info['message'])}")

        query_string = "&".join(query_params) if query_params else ""
        redirect_url = f"/inventory/product/{product.id}"
        if query_string:
            redirect_url += f"?{query_string}&show_status=true"

        # Return JSON response for AJAX request
        return JSONResponse({
            "status": "success",
            "product_id": product.id,
            "redirect_url": redirect_url,
            "platform_statuses": platform_statuses
        })

    except ProductCreationError as e:
        # Handle specific product creation errors
        await db.rollback()
        error_message = str(e)
        if "Failed to create product:" in error_message:
            inner_message = error_message.split("Failed to create product:", 1)[1].strip()
            error_message = f"Failed to create product: {inner_message}"

        # Check if this is a duplicate SKU error
        if "already exists" in error_message and "SKU" in error_message:
            # Get next available SKU suggestion
            query = select(func.max(Product.sku)).where(Product.sku.like('RIFF-%'))
            result = await db.execute(query)
            highest_sku = result.scalar_one_or_none()

            if highest_sku and highest_sku.startswith('RIFF-'):
                try:
                    numeric_part = highest_sku.replace('RIFF-', '')
                    next_sku = f"RIFF-{int(numeric_part) + 1:08d}"
                    error_message += f". Suggested next SKU: {next_sku}"
                except:
                    pass

        return JSONResponse({
            "status": "error",
            "error": error_message,
            "platform_statuses": platform_statuses
        }, status_code=400)
    except PlatformIntegrationError as e:
        # Product was created but platform integration failed
        error_message = f"Product created but platform integration failed: {str(e)}"
        print(error_message)
        
        # Don't rollback the transaction since the product was created
        return JSONResponse({
            "status": "warning",
            "warning": error_message,
                "ebay_status": platform_statuses["ebay"]["status"],
                "ebay_message": platform_statuses["ebay"]["message"],
                "reverb_status": platform_statuses["reverb"]["status"],
                "reverb_message": platform_statuses["reverb"]["message"],
                "vr_status": platform_statuses["vr"]["status"],
                "vr_message": platform_statuses["vr"]["message"],
                "shopify_status": platform_statuses["shopify"]["status"],
                "shopify_message": platform_statuses["shopify"]["message"]
            },
            status_code=400
        )
    except Exception as e:
        print(f"Overall error (detail): {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()

        # Handle all other exceptions
        await db.rollback()

        # Convert existing_products to simple dictionaries to avoid SQLAlchemy async issues
        existing_products_dicts = []
        # Re-fetch existing products after rollback to avoid detached instance issues
        try:
            existing_products_result = await db.execute(
                select(Product)
                .order_by(desc(Product.created_at))
                .limit(100)
            )
            existing_products = existing_products_result.scalars().all()
            for product in existing_products:
                existing_products_dicts.append({
                    "id": product.id,
                    "brand": product.brand or "Unknown Brand",
                    "model": product.model or ""
                })
        except Exception as fetch_error:
            logger.error(f"Error fetching existing products after rollback: {fetch_error}")
            # Use empty list if we can't fetch products
            existing_products_dicts = []

        return templates.TemplateResponse(
            "inventory/add.html",
            {
                "request": request,
                "error": f"Failed to create product: {str(e)}",
                "form_data": dict(form_data),
                "existing_brands": existing_brands,
                "categories": categories,
                "existing_products": existing_products_dicts,
                "ebay_status": "error",
                "reverb_status": "error",
                "vr_status": "error",
                "shopify_status": "error"
            },
            status_code=400
        )


@router.post("/inspect-payload")
async def inspect_payload(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    brand: str = Form(...),
    model: str = Form(...),
    sku: str = Form(...),
    category: str = Form(...),
    condition: str = Form(...),
    base_price: float = Form(...),
    quantity: int = Form(1),
    description: str = Form(""),
    decade: Optional[int] = Form(None),
    year: Optional[int] = Form(None),
    finish: Optional[str] = Form(None),
    processing_time: int = Form(3),
    primary_image: Optional[str] = Form(None),
    additional_images: Optional[str] = Form(None),
    # Platform-specific fields - accept strings and convert to bool
    sync_ebay: str = Form("false"),
    sync_reverb: str = Form("false"),
    sync_vr: str = Form("false"),
    sync_shopify: str = Form("false"),
    # eBay fields
    ebay_category: Optional[str] = Form(None),
    ebay_category_name: Optional[str] = Form(None),
    ebay_price: Optional[float] = Form(None),
    ebay_payment_policy: Optional[str] = Form(None),
    ebay_return_policy: Optional[str] = Form(None),
    ebay_shipping_policy: Optional[str] = Form(None),
    ebay_location: Optional[str] = Form(None),
    ebay_country: Optional[str] = Form("GB"),
    ebay_postal_code: Optional[str] = Form(None),
    # Reverb fields
    reverb_product_type: Optional[str] = Form(None),
    reverb_primary_category: Optional[str] = Form(None),
    reverb_price: Optional[float] = Form(None),
    shipping_profile: Optional[str] = Form(None),
    # V&R fields
    vr_category_id: Optional[str] = Form(None),
    vr_subcategory_id: Optional[str] = Form(None),
    vr_sub_subcategory_id: Optional[str] = Form(None),
    vr_sub_sub_subcategory_id: Optional[str] = Form(None),
    vr_price: Optional[float] = Form(None),
    # Shopify fields
    shopify_category_gid: Optional[str] = Form(None),
    shopify_price: Optional[float] = Form(None),
    shopify_product_type: Optional[str] = Form(None)
):
    """Generate platform payloads without creating the product"""
    
    # Log all received form data
    print("=== INSPECT PAYLOAD FORM DATA ===")
    print(f"Brand: {brand}")
    print(f"Model: {model}")
    print(f"SKU: {sku}")
    print(f"Category: {category}")
    print(f"Condition: {condition}")
    print(f"Base Price: {base_price}")
    print(f"Quantity: {quantity}")
    print(f"Description: {description[:100] if description else 'None'}...")
    print(f"Sync Shopify: {sync_shopify}")
    print(f"Sync eBay: {sync_ebay}")
    print(f"Sync V&R: {sync_vr}")
    print(f"Sync Reverb: {sync_reverb}")
    print(f"Reverb Primary Category: {reverb_primary_category}")
    print(f"eBay Category: {ebay_category}")
    print(f"Primary Image: {primary_image}")
    print(f"Additional Images: {additional_images}")
    print("=================================")
    
    # Convert string booleans to actual booleans
    sync_shopify = sync_shopify.lower() == 'true'
    sync_ebay = sync_ebay.lower() == 'true'
    sync_vr = sync_vr.lower() == 'true'
    sync_reverb = sync_reverb.lower() == 'true'
    
    # Process images
    images_array = []
    if primary_image:
        images_array.append(primary_image)
    if additional_images:
        try:
            additional = json.loads(additional_images)
            images_array.extend(additional)
        except:
            pass
    
    # Add standard footer to description if not already present
    standard_footer = '''<br/><br/>
<p><strong>ALL EU PURCHASES ARE DELIVERED WITH TAXES AND DUTIES PAID</strong></p>
<p>All purchases include EU Taxes / Duties paid, i.e., nothing further is due on receipt of goods to any EU State.</p>
<br/>
<p><strong>WHY BUY FROM US</strong></p>
<p>We are one of the world's leading specialists in used and vintage gear with over 30 years of experience. Prior to shipping, each item will be fully serviced and professionally packed.</p>
<br/>
<p><strong>SELL - TRADE - CONSIGN</strong></p>
<p>If you are looking to sell, trade, or consign any of your classic gear, please contact us by message.</p>
<br/>
<p><strong>WORLDWIDE COLLECTION - DELIVERY</strong></p>
<p>We offer personal delivery and collection services worldwide with offices/locations in London, Amsterdam, and Chicago.</p>
<br/>
<p><strong>VALUATION SERVICE</strong></p>
<p>If you require a valuation of any of your classic gear, please forward a brief description and pictures, and we will come back to you ASAP.</p>'''
    
    if description and standard_footer not in description:
        description_with_footer = description + standard_footer
    else:
        description_with_footer = description or ""
    
    # Map condition to Reverb condition UUID
    import json
    from pathlib import Path
    mappings_file = Path(__file__).parent.parent.parent / "data" / "reverb_condition_mappings.json"
    with open(mappings_file, 'r') as f:
        mappings_data = json.load(f)
    condition_map = {k: v["uuid"] for k, v in mappings_data["condition_mappings"].items()}
    reverb_condition_uuid = condition_map.get(condition, "ae4d9114-1bd7-4ec5-a4ba-6653af5ac84d")
    
    # Build response with payloads for each platform
    payloads = {}
    
    # Shopify payload
    if sync_shopify:
        # Build title with year if available
        title_parts = []
        if year:
            title_parts.append(str(year))
        title_parts.extend([brand, model])
        if finish:
            title_parts.append(finish)
        title = " ".join(filter(None, title_parts))
        
        shopify_payload = {
            "platform": "shopify",
            "product_data": {
                "title": title,
                "descriptionHtml": description_with_footer,  # Changed from body_html
                "vendor": brand,
                "productType": shopify_product_type or category,  # Changed from product_type
                "status": "ACTIVE",  # Changed from "active" to uppercase
                "tags": [condition, category, brand],
                # Note: variants and images are added via separate API calls in the actual service
                "images": [{"src": url} for url in images_array],
            },
            "category_gid": shopify_category_gid
        }
        
        # Add metafields if needed (these are added via separate API calls in the actual service)
        metafields = []
        if decade:
            metafields.append({
                "namespace": "custom",
                "key": "decade",
                "value": decade,
                "type": "single_line_text_field"
            })
        if year:
            metafields.append({
                "namespace": "custom",
                "key": "year",
                "value": str(year),
                "type": "number_integer"
            })
        if metafields:
            shopify_payload["product_data"]["metafields"] = metafields
        
        payloads["shopify"] = shopify_payload
    
    # eBay payload
    if sync_ebay:
        # Build title with year if available
        title_parts = []
        if year:
            title_parts.append(str(year))
        title_parts.extend([brand, model])
        if finish:
            title_parts.append(finish)
        title = " ".join(filter(None, title_parts))
        
        ebay_payload = {
            "platform": "ebay",
            "listing_data": {
                "Title": title,
                "Description": description_with_footer,
                "CategoryID": ebay_category,  # Changed from nested PrimaryCategory
                "Price": str(ebay_price or base_price),  # Changed from StartPrice
                "Currency": "GBP",
                "CurrencyID": "GBP",  # Added CurrencyID
                "Country": ebay_country,
                "Location": ebay_location or "United Kingdom",
                "PostalCode": ebay_postal_code,
                "Quantity": str(quantity),
                "ConditionID": "3000",  # Used condition
                "PictureDetails": {
                    "PictureURL": images_array[:12]  # eBay supports max 12 images
                },
                "ListingType": "FixedPriceItem",
                "ListingDuration": "GTC",
                "DispatchTimeMax": str(processing_time),
                "SKU": sku
            },
            "policies": {
                "payment": ebay_payment_policy if ebay_payment_policy else None,
                "return": ebay_return_policy if ebay_return_policy else None,
                "shipping": ebay_shipping_policy if ebay_shipping_policy else None
            }
        }
        
        # Add item specifics in the format expected by the trading API
        item_specifics = {}
        if brand:
            item_specifics["Brand"] = brand
        if model:
            item_specifics["Model"] = model
        if year:
            item_specifics["Year"] = str(year)
        if finish:
            item_specifics["Finish"] = finish
        
        if item_specifics:
            ebay_payload["listing_data"]["ItemSpecifics"] = item_specifics
        
        payloads["ebay"] = ebay_payload
    
    # V&R payload
    if sync_vr:
        # Build title with year if available
        title_parts = []
        if year:
            title_parts.append(str(year))
        title_parts.extend([brand, model])
        if finish:
            title_parts.append(finish)
        title = " ".join(filter(None, title_parts))
        
        vr_payload = {
            "platform": "vr",
            "listing_data": {
                # Category mapping - using the expected field names
                "Category": vr_category_id,
                "SubCategory1": vr_subcategory_id,
                "SubCategory2": vr_sub_subcategory_id,
                "SubCategory3": vr_sub_sub_subcategory_id,
                
                # Product details
                "title": title,
                "description": description_with_footer,
                "price": vr_price or base_price,
                "brand": brand,
                "model": model,
                "year": str(year) if year else "",  # V&R expects string
                "finish": finish or "",
                "condition": condition,
                
                # Images in the correct format
                "primary_image": images_array[0] if images_array else "",
                "additional_images": images_array[1:] if len(images_array) > 1 else [],
                
                # Shipping fees
                "shipping_fees": {
                    "uk": "45",
                    "europe": "50",
                    "usa": "100",
                    "world": "150"
                },
                
                # Options
                "in_collective": False,
                "in_inventory": True,
                "buy_now": False,
                "processing_time": str(processing_time),
                "time_unit": "Days",
                "shipping": True,
                "local_pickup": False,
                "quantity": quantity
            }
        }
        payloads["vr"] = vr_payload
    
    # Reverb payload (more complex, needs more fields)
    if sync_reverb:
        reverb_payload = {
            "platform": "reverb",
            "listing_data": {
                "title": f"{brand} {model}",
                "description": description_with_footer,
                "condition": {
                    "uuid": reverb_condition_uuid
                },
                "price": {
                    "amount": str(reverb_price or base_price),
                    "currency": "GBP"
                },
                "categories": [{"uuid": reverb_primary_category}] if reverb_primary_category else [],
                "make": brand,
                "model": model,
                "year": year,
                "finish": finish,
                "has_inventory": True,
                "inventory": quantity,
                "shipping": {
                    "local": True,
                    "rates": []
                },
                "photos": images_array,
                "sku": sku,
                "upc_does_not_apply": True,
                "publish": True,
                "state": {
                    "slug": "live"
                }
            }
        }
        
        # Add shipping profile if provided
        if shipping_profile:
            reverb_payload["shipping_profile_id"] = shipping_profile
        payloads["reverb"] = reverb_payload
    
    return {
        "status": "success",
        "message": "Payloads generated successfully",
        "payloads": payloads,
        "summary": {
            "product": {
                "brand": brand,
                "model": model,
                "sku": sku,
                "price": base_price,
                "quantity": quantity
            },
            "platforms_selected": {
                "shopify": sync_shopify,
                "ebay": sync_ebay,
                "vr": sync_vr,
                "reverb": sync_reverb
            }
        }
    }


@router.post("/save-draft")
async def save_draft(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    # Basic product fields
    brand: str = Form(...),
    model: str = Form(...),
    sku: str = Form(...),
    title: Optional[str] = Form(None),
    category: str = Form(...),
    condition: str = Form(...),
    base_price: float = Form(...),
    quantity: int = Form(1),
    description: str = Form(""),
    # Optional fields
    decade: Optional[int] = Form(None),
    year: Optional[int] = Form(None),
    finish: Optional[str] = Form(None),
    processing_time: int = Form(3),
    # Inventory fields
    location: Optional[str] = Form(None),
    stock_warning_level: Optional[int] = Form(None),
    offer_price: Optional[float] = Form(None),
    offer_discount: Optional[float] = Form(None),
    # Checkbox fields
    in_collective: Optional[bool] = Form(False),
    in_inventory: Optional[bool] = Form(True),
    in_reseller: Optional[bool] = Form(False),
    free_shipping: Optional[bool] = Form(False),
    buy_now: Optional[bool] = Form(True),
    show_vat: Optional[bool] = Form(True),
    local_pickup: Optional[bool] = Form(False),
    available_for_shipment: Optional[bool] = Form(True),
    is_stocked_item: Optional[bool] = Form(False),
    # Media fields
    primary_image_file: Optional[UploadFile] = File(None),
    primary_image_url: Optional[str] = Form(None),
    additional_images_files: List[UploadFile] = File([]),
    additional_images_urls: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    external_link: Optional[str] = Form(None),
    # Platform sync fields
    sync_all: Optional[str] = Form("true"),
    sync_platforms: Optional[List[str]] = Form(None),
    # Platform-specific fields (for generating payloads)
    # eBay fields
    ebay_category: Optional[str] = Form(None),
    ebay_category_name: Optional[str] = Form(None),
    ebay_price: Optional[float] = Form(None),
    ebay_payment_policy: Optional[str] = Form(None),
    ebay_return_policy: Optional[str] = Form(None),
    ebay_shipping_policy: Optional[str] = Form(None),
    ebay_location: Optional[str] = Form(None),
    ebay_country: Optional[str] = Form("GB"),
    ebay_postal_code: Optional[str] = Form(None),
    # Reverb fields
    reverb_product_type: Optional[str] = Form(None),
    reverb_primary_category: Optional[str] = Form(None),
    reverb_price: Optional[float] = Form(None),
    shipping_profile: Optional[str] = Form(None),
    # V&R fields
    vr_category_id: Optional[str] = Form(None),
    vr_subcategory_id: Optional[str] = Form(None),
    vr_sub_subcategory_id: Optional[str] = Form(None),
    vr_sub_sub_subcategory_id: Optional[str] = Form(None),
    vr_price: Optional[float] = Form(None),
    # Shopify fields
    shopify_category_gid: Optional[str] = Form(None),
    shopify_price: Optional[float] = Form(None),
    shopify_product_type: Optional[str] = Form(None),
    shopify_seo_keywords: Optional[str] = Form(None),
    # Draft ID for updating existing draft
    draft_id: Optional[int] = Form(None)
):
    """Save product as draft without creating platform listings"""

    try:
        # Debug logging
        print(f"[SAVE DRAFT] Received description: {description[:100] if description else 'NONE'}...")
        print(f"[SAVE DRAFT] Description length: {len(description) if description else 0}")

        # Initialize product service
        product_service = ProductService(db)

        # Process images
        primary_image = None
        additional_images = []

        draft_subdir = _draft_media_subdir(draft_id, sku)

        # Handle primary image
        if primary_image_file and primary_image_file.filename:
            primary_image = await save_draft_upload_file(primary_image_file, draft_subdir)
        elif primary_image_url:
            primary_image = primary_image_url

        # Handle additional images - files
        for img_file in additional_images_files:
            if img_file.filename:
                image_url = await save_draft_upload_file(img_file, draft_subdir)
                additional_images.append(image_url)

        # Handle additional images - URLs
        if additional_images_urls:
            try:
                urls = json.loads(additional_images_urls)
                additional_images.extend(urls)
            except:
                pass

        local_media_urls: List[str] = []
        if primary_image:
            local_media_urls.append(primary_image)
        local_media_urls.extend(additional_images)
        cleanup_draft_media(draft_subdir, local_media_urls)

        # Create or update product data - only include fields that exist in Product model
        product_data = {
            "sku": sku,
            "brand": brand.title(),
            "model": model,
            "title": title,
            "category": category,
            "condition": condition,
            "base_price": base_price,
            "quantity": quantity,
            "description": description,
            "decade": decade,
            "year": year,
            "finish": finish,
            "processing_time": processing_time,
            "offer_discount": offer_discount,
            "in_collective": in_collective,
            "in_inventory": in_inventory,
            "in_reseller": in_reseller,
            "free_shipping": free_shipping,
            "buy_now": buy_now,
            "show_vat": show_vat,
            "local_pickup": local_pickup,
            "available_for_shipment": available_for_shipment,
            "is_stocked_item": is_stocked_item,
            "primary_image": primary_image,
            "additional_images": additional_images,
            "video_url": video_url,
            "external_link": external_link,
            "status": "DRAFT"  # Always save as DRAFT
        }

        # Store platform data as JSON for later use
        platform_data = {
            "sync_all": sync_all == "true",
            "sync_platforms": sync_platforms or [],
            "ebay": {
                "category": ebay_category,
                "category_name": ebay_category_name,
                "price": ebay_price,
                "payment_policy": ebay_payment_policy,
                "return_policy": ebay_return_policy,
                "shipping_policy": ebay_shipping_policy,
                "location": ebay_location,
                "country": ebay_country,
                "postal_code": ebay_postal_code
            },
            "reverb": {
                "product_type": reverb_product_type,
                "primary_category": reverb_primary_category,
                "price": reverb_price,
                "shipping_profile": shipping_profile
            },
            "vr": {
                "category_id": vr_category_id,
                "subcategory_id": vr_subcategory_id,
                "sub_subcategory_id": vr_sub_subcategory_id,
                "sub_sub_subcategory_id": vr_sub_sub_subcategory_id,
                "price": vr_price
            },
            "shopify": {
                "category_gid": shopify_category_gid,
                "price": shopify_price,
                "product_type": shopify_product_type,
                "seo_keywords": shopify_seo_keywords
            }
        }

        # Store platform data in package_dimensions temporarily (since attributes field doesn't exist)
        # This is a temporary solution - ideally we'd add a proper platform_data JSONB field
        product_data["package_dimensions"] = {"platform_data": platform_data}

        if draft_id:
            # Update existing draft
            product = await db.get(Product, draft_id)
            if not product:
                raise HTTPException(status_code=404, detail="Draft not found")

            # Update product fields
            for key, value in product_data.items():
                setattr(product, key, value)

            await db.commit()
            await db.refresh(product)
        else:
            # Create new draft
            product = Product(**product_data)
            db.add(product)
            await db.commit()
            await db.refresh(product)

        # Return JSON response for AJAX request
        return JSONResponse({
            "status": "success",
            "message": f"Draft saved successfully with SKU: {product.sku}",
            "product_id": product.id,
            "redirect_url": f"/inventory?message=Draft saved successfully&message_type=success"
        })

    except Exception as e:
        await db.rollback()
        logger.error(f"Error saving draft: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Failed to save draft: {str(e)}"
            }
        )


@router.get("/drafts", response_class=JSONResponse)
async def get_drafts(
    db: AsyncSession = Depends(get_db)
):
    """Get all draft products for resuming editing"""
    drafts = await db.execute(
        select(Product)
        .where(Product.status == "DRAFT")
        .order_by(desc(Product.updated_at))
    )
    drafts = drafts.scalars().all()

    return {
        "drafts": [
            {
                "id": d.id,
                "sku": d.sku,
                "brand": d.brand,
                "model": d.model,
                "created_at": d.created_at.isoformat(),
                "updated_at": d.updated_at.isoformat()
            }
            for d in drafts
        ]
    }


@router.get("/drafts/{draft_id}", response_class=JSONResponse)
async def get_draft_details(
    draft_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific draft for editing"""
    draft = await db.get(Product, draft_id)
    if not draft or draft.status != "DRAFT":
        raise HTTPException(status_code=404, detail="Draft not found")

    # Return all draft data including platform data - only fields that exist in Product model
    draft_data = {
        "id": draft.id,
        "sku": draft.sku,
        "brand": draft.brand,
        "model": draft.model,
        "title": draft.title,
        "category": draft.category,
        "condition": draft.condition,
        "base_price": draft.base_price,
        "quantity": draft.quantity,
        "description": draft.description,
        "decade": draft.decade,
        "year": draft.year,
        "finish": draft.finish,
        "processing_time": draft.processing_time,
        "offer_discount": draft.offer_discount,
        "in_collective": draft.in_collective,
        "in_inventory": draft.in_inventory,
        "in_reseller": draft.in_reseller,
        "free_shipping": draft.free_shipping,
        "buy_now": draft.buy_now,
        "show_vat": draft.show_vat,
        "local_pickup": draft.local_pickup,
        "available_for_shipment": draft.available_for_shipment,
        "is_stocked_item": draft.is_stocked_item,
        "primary_image": draft.primary_image,
        "additional_images": draft.additional_images or [],
        "video_url": draft.video_url,
        "external_link": draft.external_link
    }

    # Extract platform data from package_dimensions (temporary location)
    if draft.package_dimensions and "platform_data" in draft.package_dimensions:
        draft_data["platform_data"] = draft.package_dimensions["platform_data"]

    return draft_data


@router.get("/products/{product_id}/edit")
async def edit_product_form(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Show product edit form"""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Get platform statuses
    platform_links = await db.execute(
        select(PlatformCommon).where(PlatformCommon.product_id == product_id)
    )
    platform_links = platform_links.scalars().all()
    
    platforms = {
        link.platform_name: {
            'status': link.status,
            'external_id': link.external_id,
            'url': link.listing_url
        }
        for link in platform_links
    }
    
    return templates.TemplateResponse(
        "inventory/edit.html",
        {
            "request": request,
            "product": product,
            "platforms": platforms,
            "conditions": ProductCondition,
            "statuses": ProductStatus
        }
    )

@router.post("/products/{product_id}/edit")
async def update_product(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Update product details"""
    form_data = await request.form()
    
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    original_values = {
        "title": product.title,
        "brand": product.brand,
        "model": product.model,
        "description": product.description,
        "quantity": product.quantity,
        "base_price": product.base_price,
    }
    
    # Update product fields with validation
    product.title = form_data.get('title') or product.title
    product.brand = form_data.get('brand') or product.brand
    product.model = form_data.get('model') or product.model
    
    # Handle year - can be empty
    year_str = form_data.get('year', '').strip()
    if year_str:
        try:
            product.year = int(year_str)
        except ValueError:
            pass  # Keep existing year if invalid
    
    product.finish = form_data.get('finish') or product.finish
    product.category = form_data.get('category') or product.category
    product.description = form_data.get('description') or product.description
    
    # Handle price with validation
    try:
        product.base_price = float(form_data.get('base_price', product.base_price))
    except (ValueError, TypeError):
        pass  # Keep existing price if invalid
    
    # Handle quantity with validation
    try:
        product.quantity = int(form_data.get('quantity', product.quantity))
    except (ValueError, TypeError):
        pass  # Keep existing quantity if invalid
    
    product.is_stocked_item = form_data.get('is_stocked_item') == 'on'
    
    # Update condition if changed
    if form_data.get('condition'):
        try:
            product.condition = ProductCondition(form_data.get('condition'))
        except ValueError:
            # If invalid condition value, keep existing
            pass
    
    await db.commit()

    changed_fields = {
        field
        for field, original in original_values.items()
        if getattr(product, field) != original
    }

    message = "Product updated successfully."

    if changed_fields:
        vr_executor = getattr(request.app.state, "vr_executor", None)
        sync_service = SyncService(db, vr_executor=vr_executor)
        try:
            propagation_result = await sync_service.propagate_product_edit(
                product_id,
                original_values,
                changed_fields,
            )
            logger.info("Edit propagation result for product %s: %s", product.sku, propagation_result)
        except Exception as exc:
            logger.error("Error propagating product edits: %s", exc, exc_info=True)
            message += " (Warning: some platform updates may have failed)"

    # Check if any platforms were selected for sync
    sync_platforms = []
    for platform in ['reverb', 'ebay', 'shopify', 'vr']:
        if form_data.get(f'sync_{platform}'):
            sync_platforms.append(platform)
    
    if sync_platforms:
        message += f" (Note: Platform sync for {', '.join(sync_platforms)} is pending implementation)"
    
    # Redirect back to detail page
    return RedirectResponse(
        url=f"/inventory/product/{product_id}",
        status_code=303
    )

@router.put("/products/{product_id}/stock")
async def update_product_stock(
    product_id: int,
    quantity: int,
    request: Request
):
    try:
        event = StockUpdateEvent(
            product_id=product_id,
            platform="local",
            new_quantity=quantity,
            timestamp=datetime.now()
        )
        await request.app.state.stock_manager.process_stock_update(event)
        return {"status": "success", "new_quantity": quantity}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/next-sku", response_model=dict)
async def get_next_sku(db: AsyncSession = Depends(get_db)):
    """Generate the next available SKU in format RIFF-1xxxxxxx (8 digit number starting with 1)"""
    try:
        # Get the highest existing SKU with RIFF- pattern
        query = select(func.max(Product.sku)).where(Product.sku.like('RIFF-%'))
        result = await db.execute(query)
        highest_sku = result.scalar_one_or_none()
        
        if not highest_sku or not highest_sku.startswith('RIFF-'):
            # If no existing SKUs with this pattern, start from RIFF-10000001
            next_num = 10000001
        else:
            # Extract the numeric part after RIFF-
            try:
                numeric_part = highest_sku.replace('RIFF-', '')
                next_num = int(numeric_part) + 1
                # Ensure it stays within 8 digits starting with 1
                if next_num >= 20000000:
                    # If we somehow exceed the range, find a gap
                    next_num = 10000001
            except (ValueError, IndexError):
                next_num = 10000001
        
        # Format the new SKU
        new_sku = f"RIFF-{next_num}"
        return {"sku": new_sku}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {"error": str(e)}

@router.get("/export/vintageandrare", response_class=StreamingResponse)
async def export_vintageandrare(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    try:
        export_service = VRExportService(db)
        csv_content = await export_service.generate_csv()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"vintageandrare_export_{timestamp}.csv"
        
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/csv'
        }
        
        return StreamingResponse(
            iter([csv_content.getvalue()]),
            headers=headers
        )
        
    except Exception as e:
        print(f"Export error: {str(e)}")
        return templates.TemplateResponse(
            "errors/500.html",
            {
                "request": request,
                "error_message": "Error generating export file"
            },
            status_code=500
        )

@router.get("/metrics")
async def get_metrics(request: Request):
    """Get current metrics for all platforms and queue status"""
    return request.app.state.stock_manager.get_metrics()

@router.get("/test")
async def test_route():
    return {"message": "Test route working"}

@router.get("/sync/vintageandrare", response_class=HTMLResponse)
async def sync_vintageandrare_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None
):
    """Show form for selecting products to sync to VintageAndRare"""
    # Base query for products
    query = select(Product).outerjoin(
        PlatformCommon, 
        and_(
            PlatformCommon.product_id == Product.id,
            PlatformCommon.platform_name == 'vintageandrare'
        )
    ).where(PlatformCommon.id == None)  # Only products not yet on V&R
    
    # Apply filters
    if search:
        search = f"%{search}%"
        query = query.filter(
            or_(
                Product.brand.ilike(search),
                Product.model.ilike(search),
                Product.category.ilike(search)
            )
        )
    if category:
        query = query.filter(Product.category == category)
    if brand:
        query = query.filter(Product.brand == brand)
    
    # Execute query
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Get categories and brands for filters
    categories_result = await db.execute(select(Product.category).distinct())
    categories = [c[0] for c in categories_result.all() if c[0]]
    
    brands_result = await db.execute(select(Product.brand).distinct())
    brands = [b[0] for b in brands_result.all() if b[0]]
    
    return templates.TemplateResponse(
        "inventory/sync_vr.html",
        {
            "request": request,
            "products": products,
            "categories": categories,
            "brands": brands,
            "selected_category": category,
            "selected_brand": brand,
            "search": search
        }
    )

@router.post("/sync/vintageandrare", response_class=HTMLResponse)
async def sync_vintageandrare_submit(
    request: Request,
    product_ids: List[int] = Form(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Process selected products and sync to VintageAndRare"""
    results = {
        "success": 0,
        "errors": 0,
        "messages": []
    }
    
    from app.services.vintageandrare.client import VintageAndRareClient
    from app.services.category_mapping_service import CategoryMappingService
    
    # Initialize services
    mapping_service = CategoryMappingService(db)
    vr_client = VintageAndRareClient(
        settings.VINTAGE_AND_RARE_USERNAME,
        settings.VINTAGE_AND_RARE_PASSWORD,
        db_session=db
    )
    
    # Authenticate first
    is_authenticated = await vr_client.authenticate()
    if not is_authenticated:
        results["errors"] += len(product_ids)
        results["messages"].append("Failed to authenticate with Vintage & Rare")
        return templates.TemplateResponse(
            "inventory/sync_vr_results.html",
            {
                "request": request,
                "results": results
            }
        )
    
    # Process each product
    for product_id in product_ids:
        try:
            # Get product
            query = select(Product).where(Product.id == product_id)
            result = await db.execute(query)
            product = result.scalar_one_or_none()
            
            if not product:
                results["errors"] += 1
                results["messages"].append(f"Product {product_id} not found")
                continue
            
            # Check for existing platform listing
            query = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "vintageandrare"
            )
            platform_result = await db.execute(query)
            platform_common = platform_result.scalar_one_or_none()
            
            # Create new platform listing if needed
            if not platform_common:
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="vintageandrare",
                    status=ListingStatus.DRAFT.value,
                    sync_status=SyncStatus.PENDING.value,
                    last_sync=datetime.now(timezone.utc)()
                )
                db.add(platform_common)
                await db.flush()
            
            # Check VR permissions first before attempting to create VRListing
            try:
                # Try to create a VRListing record
                vr_listing = VRListing(
                    platform_id=platform_common.id,
                    in_collective=product.in_collective or False,
                    in_inventory=product.in_inventory or True,
                    in_reseller=product.in_reseller or False,
                    collective_discount=product.collective_discount,
                    price_notax=product.price_notax,
                    show_vat=product.show_vat or True,
                    processing_time=product.processing_time,
                    inventory_quantity=1,
                    vr_state="draft",
                    created_at=datetime.now(timezone.utc)(),
                    updated_at=datetime.now(timezone.utc)(),
                    last_synced_at=datetime.now(timezone.utc)()
                )
                db.add(vr_listing)
                await db.flush()
            except Exception as e:
                # If permissions error, continue without VRListing
                logger.warning(f"Unable to create VRListing: {str(e)}")
                # For demo, continue without VRListing
            
            # Prepare data for V&R client
            product_data = {
                "id": product.id,  # Include ID for mapping lookup
                "brand": product.brand,
                "model": product.model,
                "year": product.year,
                "decade": product.decade,
                "finish": product.finish,
                "description": product.description,
                "price": product.base_price,
                "price_notax": product.price_notax,
                "category": product.category,
                "in_collective": product.in_collective,
                "in_inventory": product.in_inventory,
                "in_reseller": product.in_reseller,
                "collective_discount": product.collective_discount,
                "show_vat": product.show_vat,
                "local_pickup": product.local_pickup,
                "available_for_shipment": product.available_for_shipment,
                "processing_time": product.processing_time,
                "primary_image": product.primary_image,
                "additional_images": product.additional_images,
                "video_url": product.video_url,
                "external_link": product.external_link
            }
            
            # Call V&R client to create listing (test mode for now)
            vr_response = await vr_client.create_listing(product_data, test_mode=False)
            
            # Update platform_common with response data
            if vr_response.get("status") == "success":
                if vr_response.get("external_id"):
                    platform_common.external_id = vr_response["external_id"]
                platform_common.sync_status = SyncStatus.SYNCED.value
                platform_common.last_sync = datetime.now(timezone.utc)()
                
                results["success"] += 1
                results["messages"].append(f"Created draft for {product.brand} {product.model}")
            else:
                platform_common.sync_status = SyncStatus.FAILED.value
                platform_common.last_sync = datetime.now(timezone.utc)()
                
                results["errors"] += 1
                results["messages"].append(f"Error creating draft for {product.brand} {product.model}: {vr_response.get('message', 'Unknown error')}")
            
        except Exception as e:
            results["errors"] += 1
            results["messages"].append(f"Error syncing product {product_id}: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    await db.commit()
    
    return templates.TemplateResponse(
        "inventory/sync_vr_results.html",
        {
            "request": request,
            "results": results
        }
    )

@router.get("/sync/ebay", response_class=HTMLResponse)
async def sync_ebay_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None
):
    """Show form for selecting products to sync to eBay"""
    # Base query for products
    query = select(Product).outerjoin(
        PlatformCommon, 
        and_(
            PlatformCommon.product_id == Product.id,
            PlatformCommon.platform_name == 'ebay'
        )
    ).where(PlatformCommon.id == None)  # Only products not yet on eBay
    
    # Apply filters
    if search:
        search = f"%{search}%"
        query = query.filter(
            or_(
                Product.brand.ilike(search),
                Product.model.ilike(search),
                Product.category.ilike(search)
            )
        )
    if category:
        query = query.filter(Product.category == category)
    if brand:
        query = query.filter(Product.brand == brand)
    
    # Execute query
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Get categories and brands for filters
    categories_result = await db.execute(select(Product.category).distinct())
    categories = [c[0] for c in categories_result.all() if c[0]]
    
    brands_result = await db.execute(select(Product.brand).distinct())
    brands = [b[0] for b in brands_result.all() if b[0]]
    
    return templates.TemplateResponse(
        "inventory/sync_ebay.html",  # You'll need to create this template
        {
            "request": request,
            "products": products,
            "categories": categories,
            "brands": brands,
            "selected_category": category,
            "selected_brand": brand,
            "search": search
        }
    )

@router.post("/sync/ebay", response_class=HTMLResponse)
async def sync_ebay_submit(
    request: Request,
    product_ids: List[int] = Form(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Process selected products and sync to eBay"""
    results = {
        "success": 0,
        "errors": 0,
        "messages": []
    }
    
    # Initialize services
    mapping_service = CategoryMappingService(db)
    ebay_service = EbayService(db, settings)
    
    # Process each product
    for product_id in product_ids:
        try:
            # Get product
            query = select(Product).where(Product.id == product_id)
            result = await db.execute(query)
            product = result.scalar_one_or_none()
            
            if not product:
                results["errors"] += 1
                results["messages"].append(f"Product {product_id} not found")
                continue
            
            # Check for existing platform listing
            query = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "ebay"
            )
            platform_result = await db.execute(query)
            platform_common = platform_result.scalar_one_or_none()
            
            # Create new platform listing if needed
            if not platform_common:
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="ebay",
                    status=ListingStatus.DRAFT.value,
                    sync_status=SyncStatus.PENDING.value,
                    last_sync=datetime.now(timezone.utc)()
                )
                db.add(platform_common)
                await db.flush()
            
            # Map category from our system to eBay category ID
            category_mapping = await mapping_service.get_mapping(
                "internal", 
                str(product.category) if product.category else "default",
                "ebay"
            )
            
            if not category_mapping:
                # Try by name if ID mapping failed
                category_mapping = await mapping_service.get_mapping_by_name(
                    "internal",
                    product.category,
                    "ebay"
                )
            
            if not category_mapping:
                # Use default if no mapping found
                category_mapping = await mapping_service.get_default_mapping("ebay")
                if not category_mapping:
                    results["errors"] += 1
                    results["messages"].append(f"No category mapping found for {product.category}")
                    continue
            
            # Prepare data for eBay listing
            ebay_item_specifics = {
                "Brand": product.brand,
                "Model": product.model,
                "Year": str(product.year) if product.year else "",
                "MPN": product.sku or "Does Not Apply",
                "Type": product.category or "",
                "Condition": product.condition or "Used"
            }
            
            # Add any other product attributes that might be relevant
            if product.finish:
                ebay_item_specifics["Finish"] = product.finish
            
            # Create eBay listing data
            ebay_data = {
                "category_id": category_mapping.target_id,
                "condition_id": map_condition_to_ebay(product.condition),
                "price": float(product.base_price) if product.base_price else 0.0,
                "duration": "GTC",  # Good Till Cancelled
                "item_specifics": ebay_item_specifics
            }
            
            # Create eBay listing
            try:
                ebay_listing = await ebay_service.create_draft_listing(
                    platform_common.id,
                    ebay_data
                )
                
                results["success"] += 1
                results["messages"].append(f"Created eBay draft for {product.brand} {product.model}")
                
            except Exception as e:
                platform_common.sync_status = SyncStatus.FAILED.value
                platform_common.last_sync = datetime.now(timezone.utc)()
                
                results["errors"] += 1
                results["messages"].append(f"Error creating eBay draft for {product.brand} {product.model}: {str(e)}")
            
        except Exception as e:
            results["errors"] += 1
            results["messages"].append(f"Error syncing product {product_id} to eBay: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    await db.commit()
    
    return templates.TemplateResponse(
        "inventory/sync_ebay_results.html",  # You'll need to create this template based on sync_vr_results.html
        {
            "request": request,
            "results": results
        }
    )

def map_condition_to_ebay(condition: str) -> str:
    """Map our condition values to eBay condition IDs"""
    # eBay condition IDs: https://developer.ebay.com/devzone/finding/callref/enums/conditionIdList.html
    condition_mapping = {
        "NEW": "1000",       # New
        "EXCELLENT": "1500", # New other (see details)
        "VERYGOOD": "2000", # Manufacturer refurbished
        "GOOD": "2500",      # Seller refurbished
        "FAIR": "3000",      # Used
        "POOR": "7000"       # For parts or not working
    }
    
    if condition and condition.upper() in condition_mapping:
        return condition_mapping[condition.upper()]
    
    # Default to Used if no mapping found
    return "3000"

@router.get("/api/dropbox/folders", response_class=JSONResponse)
async def get_dropbox_folders(
    request: Request,
    background_tasks: BackgroundTasks,
    path: str = "",
    settings: Settings = Depends(get_settings)
):
    """
    API endpoint to get Dropbox folders for navigation with token refresh support.
    
    This endpoint:
    1. Handles token refresh if needed
    2. Uses the cached folder structure when available
    3. Returns folder and file information for UI navigation
    4. Initializes a background scan if needed
    """
    try:
        # Check if scan is already in progress
        if hasattr(request.app.state, 'dropbox_scan_in_progress') and request.app.state.dropbox_scan_in_progress:
            progress = getattr(request.app.state, 'dropbox_scan_progress', {'status': 'scanning', 'progress': 0})
            return JSONResponse(
                status_code=202,  # Accepted but processing
                content={
                    "status": "processing", 
                    "message": "Dropbox scan in progress", 
                    "progress": progress
                }
            )
        
        # Get credentials
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        # Direct fallback to environment variables if not in settings
        if not access_token:
            access_token = os.environ.get('DROPBOX_ACCESS_TOKEN')
            print(f"Loading access token directly from environment: {bool(access_token)}")
        
        if not refresh_token:
            refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
            print(f"Loading refresh token directly from environment: {bool(refresh_token)}")
            
        if not app_key:
            app_key = os.environ.get('DROPBOX_APP_KEY')
            print(f"Loading app key directly from environment: {bool(app_key)}")
            
        if not app_secret:
            app_secret = os.environ.get('DROPBOX_APP_SECRET')
            print(f"Loading app secret directly from environment: {bool(app_secret)}")
        
        # Check if all credentials are available now
        if not access_token and not refresh_token:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "message": "Dropbox credentials not available. Please configure DROPBOX_ACCESS_TOKEN or DROPBOX_REFRESH_TOKEN in .env file."
                }
            )
            
        
        # Create client first to check for cached data
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )

        # Check if we need to initialize a scan
        if (not hasattr(request.app.state, 'dropbox_map') or
            request.app.state.dropbox_map is None):

            # Check if the service has cached folder structure
            logger.info(f"Checking client folder structure: {bool(client.folder_structure)}, entries: {len(client.folder_structure) if client.folder_structure else 0}")
            if client.folder_structure:
                logger.info("Found cached folder structure in service, using it")

                # Also update app state for consistency
                request.app.state.dropbox_map = {
                    'folder_structure': client.folder_structure,
                    'temp_links': {}
                }
                request.app.state.dropbox_last_updated = datetime.now()

                # Use the service's cached data
                folder_contents = await client.get_folder_contents(path)

                # For root path, extract top-level folders from the structure
                if not path:
                    folders = []
                    logger.info(f"Extracting folders from structure with {len(client.folder_structure)} entries")
                    for folder_path, folder_data in client.folder_structure.items():
                        logger.debug(f"Checking {folder_path}: is_dict={isinstance(folder_data, dict)}, starts_with_slash={folder_path.startswith('/')}, slash_count={folder_path.count('/')}")
                        if isinstance(folder_data, dict) and folder_path.startswith('/') and folder_path.count('/') == 1:
                            folder_entry = {
                                'name': folder_path.strip('/'),
                                'path': folder_path,
                                'is_folder': True
                            }
                            folders.append(folder_entry)
                            logger.debug(f"Added folder: {folder_entry}")

                    logger.info(f"Found {len(folders)} folders to return")
                    return JSONResponse(
                        content={
                            "folders": sorted(folders, key=lambda x: x['name'].lower()),
                            "files": [],
                            "current_path": path,
                            "cached": True
                        }
                    )
                else:
                    return JSONResponse(
                        content={
                            "folders": folder_contents.get("folders", []),
                            "files": folder_contents.get("images", []),
                            "current_path": path,
                            "cached": True
                        }
                    )

            # No cache available anywhere
            return JSONResponse(
                content={
                    "folders": [],
                    "files": [],
                    "current_path": path,
                    "message": "No Dropbox data cached. Please use the sync button to load data."
                }
            )

        # Get cached data
        dropbox_map = request.app.state.dropbox_map
        logger.info(f"App state dropbox_map exists: {dropbox_map is not None}, has structure: {'folder_structure' in dropbox_map if dropbox_map else False}")

        # If the token might be expired, verify it
        last_updated = getattr(request.app.state, 'dropbox_last_updated', None)
        token_age_hours = ((datetime.now() - last_updated).total_seconds() / 3600) if last_updated else None
        
        if token_age_hours and token_age_hours > 3:  # Check if token is older than 3 hours
            # Test connection and refresh if needed
            test_result = await client.test_connection()
            if not test_result:
                # Connection failed - token might be expired
                # This function handles refresh internally
                print("Token may be expired, getting fresh folder data")
                
                # Get specific folder contents
                if path:
                    folder_data = await client.get_folder_contents(path)
                    return folder_data
                else:
                    # For root, just list top-level folders
                    entries = await client.list_folder_recursive(path="", max_depth=1)
                    folders = []
                    for entry in entries:
                        if entry.get('.tag') == 'folder':
                            folder_path = entry.get('path_lower', '')
                            folder_name = os.path.basename(folder_path)
                            folders.append({
                                'name': folder_name,
                                'path': folder_path,
                                'is_folder': True
                            })
                    return {"folders": sorted(folders, key=lambda x: x['name'])}
            
        # If we get here, we can use the cached structure
        folder_structure = dropbox_map['folder_structure']
        
        # If first request, return top-level folders
        if not path:
            # Return top-level folders
            folders = []
            for folder_name, folder_data in folder_structure.items():
                if isinstance(folder_data, dict) and folder_name.startswith('/'):
                    folders.append({
                        'name': folder_name.strip('/'),
                        'path': folder_name,
                        'is_folder': True
                    })
            
            return {"folders": sorted(folders, key=lambda x: x['name'].lower())}
        else:
            # Navigate to the requested path
            current_level = folder_structure
            current_path = ""
            path_parts = path.strip('/').split('/')
            
            for part in path_parts:
                if part:
                    current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
                    if current_path in current_level:
                        current_level = current_level[current_path]
                    else:
                        # Path not found
                        return {"items": [], "current_path": path, "error": f"Path {path} not found"}
            
            # Get folders and files at this level
            items = []
            
            # Process each key in the current level
            for key, value in current_level.items():
                # Skip non-string keys or special keys
                if not isinstance(key, str):
                    continue
                
                if key.startswith('/'):
                    # This is a subfolder
                    name = os.path.basename(key)
                    items.append({
                        'name': name,
                        'path': key,
                        'is_folder': True
                    })
                elif key == 'files' and isinstance(value, list):
                    # This is the files list
                    for file in value:
                        if not isinstance(file, dict) or 'path' not in file:
                            continue
                            
                        # Only include image files
                        if any(file['path'].lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            # Get temp link from the map if available
                            temp_link = None
                            if 'temp_links' in dropbox_map and file['path'] in dropbox_map['temp_links']:
                                temp_link = dropbox_map['temp_links'][file['path']]
                            
                            items.append({
                                'name': file.get('name', os.path.basename(file['path'])),
                                'path': file['path'],
                                'is_folder': False,
                                'temp_link': temp_link
                            })
            
            # Sort items (folders first, then files)
            items.sort(key=lambda x: (not x['is_folder'], x['name'].lower()))
            
            return {"items": items, "current_path": path}
            
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"Error accessing Dropbox: {str(e)}"}
        )

@router.get("/api/dropbox/images", response_class=JSONResponse)
async def get_dropbox_images(
    request: Request,
    folder_path: str
):
    """
    API endpoint to get images from a Dropbox folder.
    
    This function uses two approaches to find images:
    1. First it directly searches for images in the temp_links cache with matching paths
    2. Then it tries to navigate the folder structure if no direct matches are found
    
    Args:
        request: The FastAPI request object
        folder_path: The Dropbox folder path to get images from
        
    Returns:
        JSON response with list of images and their temporary links
    """
    try:
        # Check for cached structure
        dropbox_map = getattr(request.app.state, 'dropbox_map', None)
        if not dropbox_map:
            return {"images": [], "error": "No Dropbox cache found. Please refresh the page."}
        
        # Normalize the folder path for consistent comparisons
        normalized_folder_path = folder_path.lower().rstrip('/')
        
        # APPROACH 1: First directly look in temp_links for images in this folder
        images = []
        temp_links = dropbox_map.get('temp_links', {})
        
        # Search for images directly in the requested folder
        for path, link_data in temp_links.items():
            path_lower = path.lower()

            # Match files directly in this folder (not in subfolders)
            folder_part = os.path.dirname(path_lower)

            if folder_part == normalized_folder_path:
                if any(path_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    # Handle new format with thumbnail and full URLs
                    if isinstance(link_data, dict):
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'url': link_data.get('thumbnail', link_data.get('full')),  # Use thumbnail for display
                            'full_url': link_data.get('full'),  # Include full URL for when image is selected
                            'thumbnail_url': link_data.get('thumbnail')
                        })
                    else:
                        # Old format compatibility
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'url': link_data,
                            'full_url': link_data,
                            'thumbnail_url': link_data
                        })
        
        # If images found directly, return them
        if images:
            print(f"Found {len(images)} images directly in folder {folder_path}")
            # Sort images by name for consistent ordering
            images.sort(key=lambda x: x.get('name', ''))
            return {"images": images}
            
        # APPROACH 2: If no images found directly, try navigating the folder structure
        folder_structure = dropbox_map.get('folder_structure', {})
        path_parts = folder_path.strip('/').split('/')
        current = folder_structure
        current_path = ""
        
        # Navigate to the folder
        for part in path_parts:
            if part:
                current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
                if current_path in current:
                    current = current[current_path]
                else:
                    # Try a more flexible path search in temp_links as a fallback
                    fallback_images = []
                    search_prefix = f"{normalized_folder_path}/"
                    
                    for path, link_data in temp_links.items():
                        if path.lower().startswith(search_prefix) and any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            # Handle new format with thumbnail and full URLs
                            if isinstance(link_data, dict):
                                fallback_images.append({
                                    'name': os.path.basename(path),
                                    'path': path,
                                    'url': link_data.get('thumbnail', link_data.get('full')),
                                    'full_url': link_data.get('full'),
                                    'thumbnail_url': link_data.get('thumbnail')
                                })
                            else:
                                # Old format compatibility
                                fallback_images.append({
                                    'name': os.path.basename(path),
                                    'path': path,
                                    'url': link_data,
                                    'full_url': link_data,
                                    'thumbnail_url': link_data
                                })
                    
                    if fallback_images:
                        print(f"Found {len(fallback_images)} images using fallback search for {folder_path}")
                        fallback_images.sort(key=lambda x: x.get('name', ''))
                        return {"images": fallback_images}
                    
                    # If no fallback images found either, return empty list
                    print(f"Folder {folder_path} not found in structure")
                    return {"images": [], "error": f"Folder {folder_path} not found"}
        
        # Extract images from specified folder using recursive helper function
        def extract_images_from_folder(folder_data, prefix=""):
            result = []
            
            # Check if folder contains files array
            if isinstance(folder_data, dict) and 'files' in folder_data and isinstance(folder_data['files'], list):
                for file in folder_data['files']:
                    if (file.get('path') and any(file['path'].lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif'])):
                        # Get temp link from the map
                        temp_link = None
                        if 'temp_links' in dropbox_map and file['path'] in dropbox_map['temp_links']:
                            temp_link = dropbox_map['temp_links'][file['path']]
                            
                        if temp_link:
                            result.append({
                                'name': file.get('name', os.path.basename(file['path'])),
                                'path': file['path'],
                                'url': temp_link
                            })
            
            # Look through subfolders with a priority for specific resolution folders
            resolution_folders = []
            other_folders = []
            
            for key, value in folder_data.items():
                if isinstance(key, str) and key.startswith('/') and isinstance(value, dict):
                    folder_name = os.path.basename(key.rstrip('/'))
                    # Prioritize resolution folders
                    if any(res in folder_name.lower() for res in ['1500px', 'hi-res', '640px']):
                        resolution_folders.append((key, value))
                    else:
                        other_folders.append((key, value))
            
            # Check resolution folders first
            for key, subfolder in resolution_folders:
                result.extend(extract_images_from_folder(subfolder, f"{prefix}{os.path.basename(key)}/"))
            
            # If no images found in resolution folders, check other folders
            if not result and other_folders:
                for key, subfolder in other_folders:
                    result.extend(extract_images_from_folder(subfolder, f"{prefix}{os.path.basename(key)}/"))
            
            return result
        
        # Extract images from the current folder and its subfolders
        images = extract_images_from_folder(current)
        
        # APPROACH 3: Final fallback - if still no images found, search entire temp_links
        if not images and 'temp_links' in dropbox_map:
            search_prefix = f"{normalized_folder_path}/"
            
            for path, link in dropbox_map['temp_links'].items():
                path_lower = path.lower()
                if path_lower.startswith(search_prefix) and any(path_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    images.append({
                        'name': os.path.basename(path),
                        'path': path,
                        'url': link
                    })
        
        # Sort images by name for consistent ordering
        images.sort(key=lambda x: x.get('name', ''))
        
        print(f"Found {len(images)} images in folder {folder_path}")
        return {"images": images}
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"Error getting Dropbox images: {str(e)}"}
        )

@router.get("/api/dropbox/init", response_class=JSONResponse)
async def init_dropbox_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Initialize Dropbox scan in the background and report progress"""
    
    # Check if already scanning
    if hasattr(request.app.state, 'dropbox_scan_in_progress') and request.app.state.dropbox_scan_in_progress:
        # Get progress if available
        progress = getattr(request.app.state, 'dropbox_scan_progress', {'status': 'scanning', 'progress': 0})
        return JSONResponse(content=progress)
    
    # Check if already scanned
    if hasattr(request.app.state, 'dropbox_map') and request.app.state.dropbox_map:
        return JSONResponse(content={
            'status': 'complete', 
            'last_updated': request.app.state.dropbox_last_updated.isoformat()
        })
    
    # Start scan in background
    request.app.state.dropbox_scan_in_progress = True
    request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
    
    background_tasks.add_task(perform_dropbox_scan, request.app, settings.DROPBOX_ACCESS_TOKEN)
    
    return JSONResponse(content={
        'status': 'started',
        'message': 'Dropbox scan initiated in background'
    })

@router.get("/api/dropbox/debug-scan")
async def debug_dropbox_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to trigger Dropbox scan"""
    # Reset scan state
    request.app.state.dropbox_scan_in_progress = False
    
    # Check token
    token = settings.DROPBOX_ACCESS_TOKEN
    if not token:
        return {"status": "error", "message": "No Dropbox access token configured"}
    
    # Start scan
    print(f"Manually starting Dropbox scan with token (length: {len(token)})")
    request.app.state.dropbox_scan_in_progress = True
    request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
    
    # Add to background tasks
    background_tasks.add_task(perform_dropbox_scan, request.app, token)
    
    return {
        "status": "started", 
        "message": "Dropbox scan initiated in background", 
        "token_available": bool(token)
    }

@router.get("/api/dropbox/debug-token")
async def debug_dropbox_token(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to check Dropbox tokens and refresh if needed"""
    try:
        # Get tokens from settings and environment
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        # Create detailed response with token info
        response = {
            "access_token": {
                "available": bool(access_token),
                "preview": f"{access_token[:5]}...{access_token[-5:]}" if access_token and len(access_token) > 10 else None,
                "length": len(access_token) if access_token else 0,
                "source": "settings" if hasattr(settings, 'DROPBOX_ACCESS_TOKEN') and settings.DROPBOX_ACCESS_TOKEN else "environment" if access_token else None
            },
            "refresh_token": {
                "available": bool(refresh_token),
                "preview": f"{refresh_token[:5]}...{refresh_token[-5:]}" if refresh_token and len(refresh_token) > 10 else None,
                "length": len(refresh_token) if refresh_token else 0,
                "source": "settings" if hasattr(settings, 'DROPBOX_REFRESH_TOKEN') and settings.DROPBOX_REFRESH_TOKEN else "environment" if refresh_token else None
            },
            "app_credentials": {
                "app_key_available": bool(app_key),
                "app_secret_available": bool(app_secret),
                "source": "settings" if hasattr(settings, 'DROPBOX_APP_KEY') and settings.DROPBOX_APP_KEY else "environment" if app_key else None
            }
        }
        
        # Test current access token if available
        if access_token:
            from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
            client = AsyncDropboxClient(access_token=access_token)
            test_result = await client.test_connection()
            response["token_status"] = "valid" if test_result else "invalid"
        else:
            response["token_status"] = "missing"
        
        # Try to refresh token if invalid and we have refresh credentials
        if (response["token_status"] in ["invalid", "missing"] and 
            refresh_token and app_key and app_secret):
            
            print("Attempting to refresh token...")
            from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
            refresh_client = AsyncDropboxClient(
                refresh_token=refresh_token,
                app_key=app_key,
                app_secret=app_secret
            )
            
            refresh_success = await refresh_client.refresh_access_token()
            
            if refresh_success:
                # We got a new token
                new_token = refresh_client.access_token
                
                # Save it to use in future requests
                if hasattr(request.app.state, 'settings'):
                    request.app.state.settings.DROPBOX_ACCESS_TOKEN = new_token
                
                # Update environment variable
                os.environ["DROPBOX_ACCESS_TOKEN"] = new_token
                
                # Start background scan with new token
                request.app.state.dropbox_scan_in_progress = True
                request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
                background_tasks.add_task(perform_dropbox_scan, request.app, new_token)
                
                response["refresh_result"] = {
                    "success": True,
                    "new_token_preview": f"{new_token[:5]}...{new_token[-5:]}",
                    "new_token_length": len(new_token),
                    "scan_initiated": True
                }
            else:
                response["refresh_result"] = {
                    "success": False,
                    "error": "Failed to refresh token"
                }
        
        return response
    except Exception as e:
        import traceback
        print(f"Debug token error: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }

@router.get("/api/dropbox/direct-scan")
async def direct_dropbox_scan(
    request: Request,
    settings: Settings = Depends(get_settings)
):
    """
    Direct scan endpoint for debugging - attempts to scan a folder directly
    without using background tasks for immediate feedback
    """
    try:
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        
        # Get tokens from settings and environment
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        if not access_token and not refresh_token:
            return {
                "status": "error", 
                "message": "No Dropbox access token or refresh token configured"
            }
            
        # Create the client with all credentials
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Try to refresh token if we have refresh credentials but no access token
        if refresh_token and app_key and app_secret and not access_token:
            print("Attempting to refresh token before direct scan...")
            refresh_success = await client.refresh_access_token()
            if refresh_success:
                # We got a new token
                access_token = client.access_token
                # Update in app state if settings exist
                if hasattr(request.app.state, 'settings'):
                    request.app.state.settings.DROPBOX_ACCESS_TOKEN = access_token
                # Update in environment
                os.environ['DROPBOX_ACCESS_TOKEN'] = access_token
                print("Successfully refreshed access token for direct scan")
            else:
                return {
                    "status": "error",
                    "message": "Failed to refresh access token"
                }
        
        # Test connection first
        test_result = await client.test_connection()
        if not test_result:
            return {
                "status": "error", 
                "message": "Failed to connect to Dropbox API - invalid token"
            }
            
        # Start scan of top-level folders for quick test
        print("Starting direct scan of top-level folders...")
        
        # Just list top folders with max_depth=1 for quicker results
        entries = await client.list_folder_recursive(path="", max_depth=1)
        
        # Collect folder information
        folders = []
        files = []
        
        for entry in entries:
            entry_type = entry.get('.tag', '')
            path = entry.get('path_lower', '')
            name = os.path.basename(path)
            
            if entry_type == 'folder':
                folders.append({
                    "name": name, 
                    "path": path
                })
            elif entry_type == 'file' and client._is_image_file(path):
                files.append({
                    "name": name, 
                    "path": path,
                    "size": entry.get('size', 0),
                })
        
        # Get a sample of temp links for quick testing (max 5 files)
        sample_files = files[:5]
        temp_links = {}
        
        if sample_files:
            sample_paths = [f['path'] for f in sample_files]
            temp_links = await client.get_temporary_links_async(sample_paths)
        
        return {
            "status": "success", 
            "message": f"Directly scanned {len(folders)} top-level folders and {len(files)} files", 
            "folders": folders[:10],  # Limit to first 10
            "files": files[:10],      # Limit to first 10
            "temp_links_sample": len(temp_links),
            "token_refreshed": access_token != getattr(settings, 'DROPBOX_ACCESS_TOKEN', None)
        }
        
    except Exception as e:
        import traceback
        traceback_str = traceback.format_exc()
        print(f"Error in direct scan: {str(e)}")
        print(traceback_str)
        return {
            "status": "error", 
            "message": f"Error in direct scan: {str(e)}",
            "traceback": traceback_str.split("\n")[-10:] if len(traceback_str) > 0 else []
        }

@router.get("/api/dropbox/sync-status")
async def get_dropbox_sync_status(request: Request):
    """Get current Dropbox sync status and statistics"""
    try:
        from app.services.dropbox.scheduled_sync import DropboxSyncScheduler
        
        if not hasattr(request.app.state, 'dropbox_scheduler'):
            request.app.state.dropbox_scheduler = DropboxSyncScheduler(request.app.state)
        
        scheduler = request.app.state.dropbox_scheduler
        return scheduler.get_sync_status()
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/api/dropbox/sync-now")
async def trigger_dropbox_sync(
    request: Request,
    force: bool = False,
    background_tasks: BackgroundTasks = None
):
    """Manually trigger a Dropbox sync"""
    try:
        from app.services.dropbox.scheduled_sync import DropboxSyncScheduler
        
        if not hasattr(request.app.state, 'dropbox_scheduler'):
            request.app.state.dropbox_scheduler = DropboxSyncScheduler(request.app.state)
        
        scheduler = request.app.state.dropbox_scheduler
        
        # Run sync in background
        if background_tasks:
            background_tasks.add_task(scheduler.full_sync, force=force)
            return {
                "status": "started",
                "message": "Sync started in background"
            }
        else:
            # Run sync directly
            result = await scheduler.full_sync(force=force)
            return result
            
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/api/dropbox/refresh-token")
async def force_refresh_dropbox_token(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Force refresh of the Dropbox access token using refresh token"""
    try:
        # Get refresh credentials
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        if not refresh_token or not app_key or not app_secret:
            return {
                "status": "error",
                "message": "Missing required refresh credentials",
                "refresh_token_available": bool(refresh_token),
                "app_key_available": bool(app_key),
                "app_secret_available": bool(app_secret)
            }
        
        # Create client for token refresh
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Attempt to refresh the token
        print("Forcing Dropbox token refresh...")
        refresh_success = await client.refresh_access_token()
        
        if refresh_success:
            # We got a new token
            new_token = client.access_token
            
            # Update in app state if settings exist
            if hasattr(request.app.state, 'settings'):
                request.app.state.settings.DROPBOX_ACCESS_TOKEN = new_token
            
            # Update in environment
            os.environ['DROPBOX_ACCESS_TOKEN'] = new_token
            
            # Start background scan with new token if requested
            start_scan = request.query_params.get('start_scan', 'false').lower() == 'true'
            if start_scan:
                request.app.state.dropbox_scan_in_progress = True
                request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
                background_tasks.add_task(perform_dropbox_scan, request.app, new_token)
                
            return {
                "status": "success",
                "message": "Successfully refreshed access token",
                "new_token_preview": f"{new_token[:5]}...{new_token[-5:]}",
                "new_token_length": len(new_token),
                "scan_initiated": start_scan
            }
        else:
            return {
                "status": "error",
                "message": "Failed to refresh access token",
                "refresh_token_preview": f"{refresh_token[:5]}...{refresh_token[-5:]}" if len(refresh_token) > 10 else None
            }
    
    except Exception as e:
        import traceback
        print(f"Error in token refresh: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Exception during token refresh: {str(e)}",
            "error_type": type(e).__name__
        }

@router.get("/api/dropbox/test-credentials", response_class=JSONResponse)
async def test_dropbox_credentials(
    settings: Settings = Depends(get_settings)
):
    """Test that Dropbox credentials are being loaded correctly"""
    return {
        "app_key_available": bool(settings.DROPBOX_APP_KEY),
        "app_secret_available": bool(settings.DROPBOX_APP_SECRET),
        "refresh_token_available": bool(settings.DROPBOX_REFRESH_TOKEN),
        "access_token_available": bool(settings.DROPBOX_ACCESS_TOKEN),
        "app_key_preview": settings.DROPBOX_APP_KEY[:5] + "..." if settings.DROPBOX_APP_KEY else None,
        "refresh_token_preview": settings.DROPBOX_REFRESH_TOKEN[:5] + "..." if settings.DROPBOX_REFRESH_TOKEN else None
    }

@router.get("/api/dropbox/debug-cache")
async def debug_dropbox_cache(request: Request):
    """Debug endpoint to see what's in the Dropbox cache"""
    dropbox_map = getattr(request.app.state, 'dropbox_map', None)
    
    if not dropbox_map:
        return {"status": "no_cache", "message": "No Dropbox cache found"}
    
    # Count temporary links
    temp_links_count = len(dropbox_map.get('temp_links', {}))
    
    # Get some sample paths with temporary links
    sample_links = {}
    for i, (path, link) in enumerate(dropbox_map.get('temp_links', {}).items()):
        if i >= 5:  # Just get 5 samples
            break
        sample_links[path] = link[:50] + "..." if link else None
    
    return {
        "status": "ok",
        "last_updated": getattr(request.app.state, 'dropbox_last_updated', None),
        "has_folder_structure": "folder_structure" in dropbox_map,
        "temp_links_count": temp_links_count,
        "sample_links": sample_links,
        "sample_folder_paths": list(dropbox_map.get('folder_structure', {}).keys())[:5]
    }

@router.get("/api/dropbox/debug-credentials")
async def debug_dropbox_credentials(
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to check how credentials are loaded"""
    
    # Check settings first
    settings_creds = {
        "settings_access_token": bool(getattr(settings, 'DROPBOX_ACCESS_TOKEN', None)),
        "settings_refresh_token": bool(getattr(settings, 'DROPBOX_REFRESH_TOKEN', None)),
        "settings_app_key": bool(getattr(settings, 'DROPBOX_APP_KEY', None)),
        "settings_app_secret": bool(getattr(settings, 'DROPBOX_APP_SECRET', None))
    }
    
    # Check environment variables directly
    env_creds = {
        "env_access_token": bool(os.environ.get('DROPBOX_ACCESS_TOKEN')),
        "env_refresh_token": bool(os.environ.get('DROPBOX_REFRESH_TOKEN')),
        "env_app_key": bool(os.environ.get('DROPBOX_APP_KEY')),
        "env_app_secret": bool(os.environ.get('DROPBOX_APP_SECRET'))
    }
    
    # Sample values (first 5 chars only)
    samples = {
        "access_token_sample": os.environ.get('DROPBOX_ACCESS_TOKEN', '')[:5] + "..." if os.environ.get('DROPBOX_ACCESS_TOKEN') else None,
        "refresh_token_sample": os.environ.get('DROPBOX_REFRESH_TOKEN', '')[:5] + "..." if os.environ.get('DROPBOX_REFRESH_TOKEN') else None
    }
    
    return {
        "settings_loaded": settings_creds,
        "environment_loaded": env_creds,
        "samples": samples
    }

@router.get("/api/dropbox/debug-folder-images")
async def debug_folder_images(
    request: Request,
    folder_path: str
):
    """Debug endpoint to check what images exist for a specific folder"""
    dropbox_map = getattr(request.app.state, 'dropbox_map', None)
    
    if not dropbox_map:
        return {"status": "no_cache", "message": "No Dropbox cache found"}
    
    # Count all temporary links
    all_temp_links = dropbox_map.get('temp_links', {})
    
    # Find images in this folder from temp_links
    folder_images = []
    for path, link in all_temp_links.items():
        normalized_path = path.lower()
        normalized_folder = folder_path.lower()
        
        # Check if this path is in the requested folder
        if normalized_path.startswith(normalized_folder + '/') or normalized_path == normalized_folder:
            if any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                folder_images.append({
                    'path': path,
                    'link': link[:50] + "..." if link else None
                })
    
    # Get folder structure info
    folder_structure = dropbox_map.get('folder_structure', {})
    current = folder_structure
    
    # Try to navigate to the folder (if it exists in structure)
    path_parts = folder_path.strip('/').split('/')
    current_path = ""
    for part in path_parts:
        if not part:
            continue
        current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
        if current_path in current:
            current = current[current_path]
        else:
            current = None
            break
    
    return {
        "status": "ok",
        "folder_path": folder_path,
        "folder_exists_in_structure": current is not None,
        "folder_structure_details": current if isinstance(current, dict) and len(str(current)) < 1000 else "(too large to display)",
        "images_found_in_temp_links": len(folder_images),
        "sample_images": folder_images[:5]
    }

@router.get("/api/dropbox/generate-links", response_class=JSONResponse)
async def generate_folder_links(
    request: Request,
    folder_path: str,
    settings: Settings = Depends(get_settings)
):
    """Generate temporary links for all images in a specific folder"""
    try:
        # Get access token
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        
        # Create client
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(access_token=access_token)
        
        # Check connection
        test_result = await client.test_connection()
        if not test_result:
            return {
                "status": "error", 
                "message": "Failed to connect to Dropbox API - invalid token"
            }
            
        # Get the folder structure from cache if available
        dropbox_map = getattr(request.app.state, 'dropbox_map', None)
        if not dropbox_map:
            return {"status": "error", "message": "No Dropbox cache available"}
        
        # Use our new dedicated method to get links for this folder
        temp_links = await client.get_temp_links_for_folder(folder_path)
        
        print(f"Generated {len(temp_links)} temporary links for folder {folder_path}")
        
        # Update the cache with new temporary links
        if dropbox_map and 'temp_links' in dropbox_map:
            dropbox_map['temp_links'].update(temp_links)
            print(f"Updated cache with {len(temp_links)} new temporary links")
        
        # Return images with links for UI
        images = []
        for path, link in temp_links.items():
            images.append({
                'name': os.path.basename(path),
                'path': path,
                'url': link
            })
            
        return {
            "status": "success",
            "message": f"Generated {len(temp_links)} temporary links",
            "images": images
        }
            
    except Exception as e:
        import traceback
        print(f"Error generating links: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error", 
            "message": f"Error generating links: {str(e)}"
        }

@router.get("/shipping-profiles")
async def get_shipping_profiles(
    db: AsyncSession = Depends(get_db)
):
    """Get all shipping profiles."""
    from app.models.shipping import ShippingProfile
    
    profiles = await db.execute(select(ShippingProfile).order_by(ShippingProfile.name))
    result = profiles.scalars().all()
    
    # Convert to dict for JSON response compatible with your frontend
    return [
        {
            "id": profile.id,
            "reverb_profile_id": profile.reverb_profile_id,
            "ebay_profile_id": profile.ebay_profile_id,
            "name": profile.name,
            "display_name": f"{profile.name} ({profile.reverb_profile_id})" if profile.reverb_profile_id else profile.name,
            "description": profile.description,
            "package_type": profile.package_type,
            "dimensions": profile.dimensions,  # Return dimensions as JSONB 
            "weight": profile.weight,
            "carriers": profile.carriers,
            "options": profile.options,
            "rates": profile.rates,
            "is_default": profile.is_default
        }
        for profile in result
    ]

@router.get("/platform-categories/{platform}")
async def get_platform_categories(
    platform: str,
    db: AsyncSession = Depends(get_db)
):
    """Get all available categories for a specific platform."""
    from sqlalchemy import text
    
    if platform == "ebay":
        # Get eBay categories from mappings table
        query = text("""
            SELECT DISTINCT target_category_id, target_category_name
            FROM platform_category_mappings
            WHERE target_platform = 'ebay'
            AND target_category_id IS NOT NULL
            ORDER BY target_category_name
        """)
        
        result = await db.execute(query)
        categories = [
            {"id": row[0], "name": row[1]}
            for row in result.fetchall()
        ]
        
    elif platform == "shopify":
        # Get Shopify categories from mappings table
        query = text("""
            SELECT DISTINCT shopify_gid, merchant_type, target_category_name
            FROM platform_category_mappings
            WHERE target_platform = 'shopify'
            AND shopify_gid IS NOT NULL
            ORDER BY merchant_type
        """)
        
        result = await db.execute(query)
        categories = [
            {
                "id": row[0], 
                "name": row[1],  # merchant_type as display name
                "full_name": row[2]  # full category path
            }
            for row in result.fetchall()
        ]
        
    elif platform == "vr":
        # Load V&R category names
        import json
        from pathlib import Path
        vr_names_file = Path(__file__).parent.parent.parent / "scripts" / "mapping_work" / "vr_category_map.json"
        vr_names = {}
        if vr_names_file.exists():
            with open(vr_names_file, 'r') as f:
                vr_names = json.load(f)
        
        # Get V&R categories - need to build hierarchy
        query = text("""
            SELECT DISTINCT 
                vr_category_id,
                vr_subcategory_id,
                vr_sub_subcategory_id,
                vr_sub_sub_subcategory_id
            FROM platform_category_mappings
            WHERE target_platform = 'vintageandrare'
            AND vr_category_id IS NOT NULL
            ORDER BY vr_category_id, vr_subcategory_id
        """)
        
        result = await db.execute(query)
        categories = []
        for row in result.fetchall():
            # Build the ID path and name
            id_parts = [str(row[0])]
            name_parts = []
            
            # Get category name
            if str(row[0]) in vr_names:
                name_parts.append(vr_names[str(row[0])].get('name', f'Category {row[0]}'))
                
                # Get subcategory name
                if row[1] and str(row[1]) in vr_names[str(row[0])].get('subcategories', {}):
                    id_parts.append(str(row[1]))
                    name_parts.append(vr_names[str(row[0])]['subcategories'][str(row[1])].get('name', f'Subcategory {row[1]}'))
                    
                    # Get sub-subcategory name if exists
                    if row[2] and str(row[2]) in vr_names[str(row[0])]['subcategories'][str(row[1])].get('subcategories', {}):
                        id_parts.append(str(row[2]))
                        name_parts.append(vr_names[str(row[0])]['subcategories'][str(row[1])]['subcategories'][str(row[2])].get('name', f'Sub-subcategory {row[2]}'))
                elif row[1]:
                    id_parts.append(str(row[1]))
                    name_parts.append(f'Subcategory {row[1]}')
            else:
                name_parts.append(f'Category {row[0]}')
                if row[1]:
                    id_parts.append(str(row[1]))
                    name_parts.append(f'Subcategory {row[1]}')
            
            categories.append({
                "id": "/".join(id_parts),
                "name": " > ".join(name_parts) if name_parts else f"Category {'/'.join(id_parts)}"
            })
    else:
        return {"error": f"Unknown platform: {platform}"}
    
    return {"categories": categories}

@router.get("/category-mappings/{reverb_category:path}")
async def get_category_mappings(
    reverb_category: str,
    sku: Optional[str] = None,
    uuid: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get platform category mappings for a Reverb category.
    
    Can be called with either:
    1. A category name (legacy support)
    2. A SKU parameter to look up the UUID from reverb_listings
    """
    from sqlalchemy import text
    
    # URL decode the category name
    from urllib.parse import unquote
    reverb_category = unquote(reverb_category)
    
    print(f"Looking up category: {reverb_category}, SKU: {sku}, UUID: {uuid}")
    
    # If we have a UUID directly, use it
    reverb_uuid = uuid
    
    # If no direct UUID but we have a SKU, try to get UUID from database
    if not reverb_uuid and sku and sku.upper().startswith('REV-'):
        # Extract reverb ID from SKU
        reverb_id = sku.upper().replace('REV-', '')
        
        # Look up the UUID from reverb_listings
        uuid_query = text("""
            SELECT rl.reverb_category_uuid
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id
            JOIN reverb_listings rl ON pc.id = rl.platform_id
            WHERE p.sku = :sku
        """)
        
        result = await db.execute(uuid_query, {"sku": sku})
        row = result.fetchone()
        if row and row.reverb_category_uuid:
            reverb_uuid = row.reverb_category_uuid
            print(f"Found UUID from SKU: {reverb_uuid}")
    
    # Query using the new normalized tables
    if reverb_uuid:
        # Use UUID for precise lookup
        query = text("""
            SELECT
                rc.id as reverb_cat_id,
                rc.name as reverb_cat_name,
                rc.uuid as reverb_cat_uuid,
                -- eBay mapping
                ec.ebay_category_id,
                ec.ebay_category_name,
                -- Shopify mapping
                sc.shopify_gid,
                sc.shopify_category_name,
                sc.merchant_type,
                -- VR mapping
                vc.vr_category_id,
                vc.vr_category_name,
                vc.vr_subcategory_id,
                vc.vr_subcategory_name,
                vc.vr_sub_subcategory_id,
                vc.vr_sub_sub_subcategory_id
            FROM reverb_categories rc
            LEFT JOIN ebay_category_mappings ec ON rc.id = ec.reverb_category_id
            LEFT JOIN shopify_category_mappings sc ON rc.id = sc.reverb_category_id
            LEFT JOIN vr_category_mappings vc ON rc.id = vc.reverb_category_id
            WHERE rc.uuid = :uuid
        """)
        
        result = await db.execute(query, {"uuid": reverb_uuid})
        row = result.fetchone()
    else:
        # Fallback: Try exact match on reverb category name
        query = text("""
            SELECT
                rc.id as reverb_cat_id,
                rc.name as reverb_cat_name,
                rc.uuid as reverb_cat_uuid,
                -- eBay mapping
                ec.ebay_category_id,
                ec.ebay_category_name,
                -- Shopify mapping
                sc.shopify_gid,
                sc.shopify_category_name,
                sc.merchant_type,
                -- VR mapping
                vc.vr_category_id,
                vc.vr_category_name,
                vc.vr_subcategory_id,
                vc.vr_subcategory_name,
                vc.vr_sub_subcategory_id,
                vc.vr_sub_sub_subcategory_id
            FROM reverb_categories rc
            LEFT JOIN ebay_category_mappings ec ON rc.id = ec.reverb_category_id
            LEFT JOIN shopify_category_mappings sc ON rc.id = sc.reverb_category_id
            LEFT JOIN vr_category_mappings vc ON rc.id = vc.reverb_category_id
            WHERE rc.name = :category
        """)
        
        result = await db.execute(query, {"category": reverb_category})
        row = result.fetchone()
    
    if row:
        print(f"Found mappings for Reverb category: {row.reverb_cat_name} (ID: {row.reverb_cat_id})")
        if row.ebay_category_id:
            print(f"  eBay: {row.ebay_category_id} - {row.ebay_category_name}")
        if row.shopify_gid:
            print(f"  Shopify: {row.shopify_gid} - {row.merchant_type}")
        if row.vr_category_id:
            print(f"  VR: {row.vr_category_id}/{row.vr_subcategory_id}")
    
    # Build response with mappings for each platform
    mappings = {
        "reverb_uuid": None,
        "ebay": None,
        "shopify": None,
        "vr": None
    }

    if row:
        # Add Reverb UUID
        if hasattr(row, 'reverb_cat_uuid'):
            mappings['reverb_uuid'] = row.reverb_cat_uuid
        # eBay mapping
        if row.ebay_category_id:
            mappings['ebay'] = {
                "id": row.ebay_category_id,
                "name": row.ebay_category_name
            }
        
        # Shopify mapping
        if row.shopify_gid:
            mappings['shopify'] = {
                "gid": row.shopify_gid,
                "name": row.merchant_type or row.shopify_category_name,  # Prefer merchant_type
                "full_name": row.shopify_category_name
            }
        
        # VR mapping
        if row.vr_category_id:
            # Build the V&R category hierarchy
            vr_ids = []
            vr_ids.append(row.vr_category_id)
            if row.vr_subcategory_id:
                vr_ids.append(row.vr_subcategory_id)
            if row.vr_sub_subcategory_id:
                vr_ids.append(row.vr_sub_subcategory_id)
            if row.vr_sub_sub_subcategory_id:
                vr_ids.append(row.vr_sub_sub_subcategory_id)
            
            # Get VR names if available
            vr_name = row.vr_category_name
            if row.vr_subcategory_name:
                vr_name = f"{vr_name} / {row.vr_subcategory_name}"
            
            mappings['vr'] = {
                "id": "/".join(vr_ids),
                "category_id": row.vr_category_id,
                "subcategory_id": row.vr_subcategory_id,
                "sub_subcategory_id": row.vr_sub_subcategory_id,
                "sub_sub_subcategory_id": row.vr_sub_sub_subcategory_id,
                "name": vr_name
            }
    
    print(f"Returning mappings: {mappings}")
    return {"mappings": mappings}

async def perform_dropbox_scan(app, access_token=None):
    """Background task to scan Dropbox with token refresh support"""
    try:
        print("Starting Dropbox scan background task...")
        
        # Mark scan as in progress
        app.state.dropbox_scan_in_progress = True
        app.state.dropbox_scan_progress = {'status': 'scanning', 'progress': 0}
        
        # Get tokens and credentials from settings
        settings = getattr(app.state, 'settings', None)
        
        # Fallback to environment variables if settings not available
        if settings:
            refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None)
            app_key = getattr(settings, 'DROPBOX_APP_KEY', None)
            app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None)
        else:
            # Get from environment
            refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
            app_key = os.environ.get('DROPBOX_APP_KEY')
            app_secret = os.environ.get('DROPBOX_APP_SECRET')
            
        print(f"Access token available: {bool(access_token)}")
        print(f"Refresh token available: {bool(refresh_token)}{' (starts with: ' + refresh_token[:5] + '...)' if refresh_token else ''}")
        print(f"App key available: {bool(app_key)}{' (starts with: ' + app_key[:5] + '...)' if app_key else ''}")
        print(f"App secret available: {bool(app_secret)}{' (starts with: ' + app_secret[:5] + '...)' if app_secret else ''}")
        
        if not access_token and not refresh_token:
            print("ERROR: No access token or refresh token provided")
            app.state.dropbox_scan_progress = {'status': 'error', 'message': 'No token available', 'progress': 0}
            app.state.dropbox_scan_in_progress = False
            return
        
        # Create the async client
        print("Creating client instance...")
        
        # Initialize with all available credentials
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Try to refresh token first if we have refresh credentials
        if refresh_token and app_key and app_secret:
            print("Attempting to refresh token before scan...")
            try:
                refresh_success = await client.refresh_access_token()
                if refresh_success:
                    print("Successfully refreshed access token")
                    # Save the new token
                    access_token = client.access_token
                    # Update in environment
                    os.environ['DROPBOX_ACCESS_TOKEN'] = access_token
                    # Update in app state if settings exist
                    if hasattr(app.state, 'settings'):
                        app.state.settings.DROPBOX_ACCESS_TOKEN = access_token
                else:
                    print("Failed to refresh access token")
                    app.state.dropbox_scan_progress = {
                        'status': 'error', 
                        'message': 'Failed to refresh access token', 
                        'progress': 0
                    }
                    app.state.dropbox_scan_in_progress = False
                    return
            except Exception as refresh_error:
                print(f"Error refreshing token: {str(refresh_error)}")
                app.state.dropbox_scan_progress = {
                    'status': 'error', 
                    'message': f'Error refreshing token: {str(refresh_error)}', 
                    'progress': 0
                }
                app.state.dropbox_scan_in_progress = False
                return
                
        # Try a simple operation first to test the token
        print("Testing connection...")
        test_result = await client.test_connection()
        if not test_result:
            print("ERROR: Could not connect to Dropbox API")
            app.state.dropbox_scan_progress = {
                'status': 'error', 
                'message': 'Could not connect to Dropbox API', 
                'progress': 0
            }
            app.state.dropbox_scan_in_progress = False
            return
            
        print("Connection successful, starting full scan...")
        app.state.dropbox_scan_progress = {'status': 'scanning', 'progress': 10}
        
        # Perform the scan with cache support
        dropbox_map = await client.scan_and_map_folder()
        
        # Store results
        print("Scan complete, saving results...")
        app.state.dropbox_map = dropbox_map
        app.state.dropbox_last_updated = datetime.now()
        app.state.dropbox_scan_progress = {'status': 'complete', 'progress': 100}
        
        # If we got a new token via refresh, store it
        if client.access_token != access_token:
            # Update in environment
            os.environ['DROPBOX_ACCESS_TOKEN'] = client.access_token
            # Update in app state if settings exist
            if hasattr(app.state, 'settings'):
                app.state.settings.DROPBOX_ACCESS_TOKEN = client.access_token
            print("Updated access token from refresh")
        
        print(f"Dropbox background scan completed successfully. Mapped {len(dropbox_map.get('all_entries', []))} entries and {len(dropbox_map.get('temp_links', {}))} temporary links.")
    except Exception as e:
        print(f"ERROR in Dropbox scan: {str(e)}")
        import traceback
        print(traceback.format_exc())
        app.state.dropbox_scan_progress = {'status': 'error', 'message': f"Error: {str(e)}", 'progress': 0}
    finally:
        app.state.dropbox_scan_in_progress = False
        print("Background scan task finished")
