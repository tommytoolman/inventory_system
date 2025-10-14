# app.services.reverb_service.py
import asyncio
import json
import time
import uuid
import logging
import iso8601
import re

from datetime import datetime, timezone    
from fastapi import HTTPException
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from urllib.parse import urlparse, parse_qs
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select
from sqlalchemy import update, text
from sqlalchemy.orm import selectinload

from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.product import Product
from app.models.reverb import ReverbListing
from app.models.sync_event import SyncEvent
from app.services.reverb.client import ReverbClient
from app.core.config import Settings
from app.core.exceptions import ListingNotFoundError, ReverbAPIError

logger = logging.getLogger(__name__)

class ReverbService:
    """
    Service for interacting with Reverb marketplace.
    
    This class manages the integration between our inventory system and
    the Reverb platform, handling data transformation, error handling,
    and synchronization.
    """
    
    def __init__(self, db: AsyncSession, settings: Settings):
        """
        Initialize the Reverb service with database session and settings.
        
        Args:
            db: Database session for data access
            settings: Application settings including API credentials
        """
        self.db = db
        self.settings = settings
        
        # Use sandbox API for testing if enabled in settings
        use_sandbox = self.settings.REVERB_USE_SANDBOX
        # api_key = self.settings.REVERB_SANDBOX_API_KEY if use_sandbox else self.settings.REVERB_API_KEY
        
        self.client = ReverbClient(api_key=self.settings.REVERB_API_KEY, use_sandbox=use_sandbox)
    
    async def get_categories(self) -> Dict:
        """
        Get all categories from Reverb.
        
        Returns:
            Dict: Categories data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_categories()
        except Exception as e:
            logger.error(f"Error fetching categories: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch categories: {str(e)}")
    
    async def get_category(self, uuid: str) -> Dict:
        """
        Get a specific category by UUID.
        
        Args:
            uuid: Category UUID
            
        Returns:
            Dict: Category data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_category(uuid)
        except Exception as e:
            logger.error(f"Error fetching category {uuid}: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch category {uuid}: {str(e)}")
    
    async def get_conditions(self) -> Dict:
        """
        Get all listing conditions from Reverb.
        
        Returns:
            Dict: Listing conditions data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_listing_conditions()
        except Exception as e:
            logger.error(f"Error fetching conditions: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch conditions: {str(e)}")
            
    async def fetch_and_store_condition_mapping(self) -> Dict[str, str]:
        """
        Fetch conditions from Reverb and store for future use

        Returns:
            Dict[str, str]: Mapping of condition display names to UUIDs

        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            response = await self.client.get_listing_conditions()
            
            # Extract conditions and create a mapping of display names to UUIDs
            condition_mapping = {}
            
            if 'conditions' in response:
                for condition in response['conditions']:
                    if 'display_name' in condition and 'uuid' in condition:
                        condition_mapping[condition['display_name']] = condition['uuid']
            
            return condition_mapping
        except Exception as e:
            logger.error(f"Error fetching conditions: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch conditions: {str(e)}")

    async def _refresh_listing_until_state(
        self,
        listing_id: str,
        desired_state: str,
        max_attempts: int = 5,
        delay_seconds: float = 1.5,
    ) -> Optional[Dict[str, Any]]:
        """Poll Reverb until a listing reaches the desired state.

        Args:
            listing_id: Reverb listing identifier.
            desired_state: Expected state slug, e.g. "live".
            max_attempts: Number of retrieval attempts before giving up.
            delay_seconds: Seconds to wait between attempts.

        Returns:
            The latest listing payload (even if the desired state was not reached).
        """

        last_payload: Optional[Dict[str, Any]] = None
        normalized_target = (desired_state or "").lower()

        for attempt in range(1, max_attempts + 1):
            try:
                payload = await self.client.get_listing(listing_id)
                listing_payload = payload.get("listing", payload)
                last_payload = listing_payload
                current_state = listing_payload.get("state", {}).get("slug") or listing_payload.get("state")
                if (current_state or "").lower() == normalized_target:
                    return listing_payload
            except Exception as exc:
                logger.debug(
                    "Attempt %s to refresh Reverb listing %s failed: %s",
                    attempt,
                    listing_id,
                    exc,
                )

            if attempt < max_attempts:
                await asyncio.sleep(delay_seconds)

        return last_payload

    async def _wait_for_listing_assets(
        self,
        listing_id: str,
        max_attempts: int = 6,
        delay_seconds: float = 1.5,
    ) -> Optional[Dict[str, Any]]:
        """Poll until Reverb has processed photos and shipping data."""

        def _assets_ready(payload: Dict[str, Any]) -> bool:
            photos = payload.get("photos") or []
            shipping_profile = payload.get("shipping_profile")
            shipping_rates = payload.get("shipping", {}).get("rates") if isinstance(payload.get("shipping"), dict) else None
            return bool(photos) and (shipping_profile or shipping_rates)

        last_payload: Optional[Dict[str, Any]] = None
        for attempt in range(1, max_attempts + 1):
            try:
                payload = await self.client.get_listing(listing_id)
                listing_payload = payload.get("listing", payload)
                last_payload = listing_payload
                if _assets_ready(listing_payload):
                    return listing_payload
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Attempt %s to wait for listing %s assets failed: %s",
                    attempt,
                    listing_id,
                    exc,
                )

            if attempt < max_attempts:
                await asyncio.sleep(delay_seconds)

        return last_payload

    async def create_listing_from_product(
        self,
        product_id: int,
        platform_options: Optional[Dict[str, Any]] = None,
        publish: bool = True
    ) -> Dict[str, Any]:
        """
        Create a live Reverb listing from an existing product record.

        Args:
            product_id: Product primary key.
            platform_options: Optional platform-specific overrides (e.g. category UUID).
            publish: Whether to publish immediately (default True).

        Returns:
            Dict containing `status` and either `reverb_listing_id` or error details.
        """

        reverb_options: Dict[str, Any] = {}
        if platform_options:
            # Support both nested and flat structures
            reverb_options = platform_options.get("reverb", platform_options) or {}

        try:
            product_query = (
                select(Product)
                .options(selectinload(Product.shipping_profile))
                .where(Product.id == product_id)
            )
            result = await self.db.execute(product_query)
            product = result.scalars().first()

            if not product:
                return {"status": "error", "error": f"Product {product_id} not found"}

            if not product.brand or not product.model:
                return {
                    "status": "error",
                    "error": "Product requires both brand and model before creating a Reverb listing."
                }

            status_value = (
                product.status.value if hasattr(product.status, "value") else str(product.status)
            )
            if status_value and status_value.upper() == ProductStatus.SOLD.value:
                return {
                    "status": "error",
                    "error": "Cannot create a Reverb listing for a product marked as SOLD."
                }

            if product.base_price is None:
                return {
                    "status": "error",
                    "error": "Product is missing a base price; set one before listing on Reverb."
                }

            # Map condition to Reverb UUID
            condition_uuid = reverb_options.get("condition_uuid")
            if not condition_uuid and product.condition:
                mapping_paths = [
                    Path(__file__).resolve().parent.parent / "data" / "reverb_condition_mappings.json",
                    Path(__file__).resolve().parents[2] / "data" / "reverb_condition_mappings.json",
                    Path.cwd() / "data" / "reverb_condition_mappings.json",
                ]
                mapping_loaded = False
                for mapping_file in mapping_paths:
                    if mapping_file.exists():
                        try:
                            with open(mapping_file, "r") as f:
                                condition_map_data = json.load(f)
                            condition_map = {
                                key.upper(): value["uuid"]
                                for key, value in condition_map_data.get("condition_mappings", {}).items()
                            }
                            condition_uuid = condition_map.get(str(product.condition).upper())
                            mapping_loaded = True
                            break
                        except Exception as mapping_error:
                            logger.warning(
                                "Failed to parse condition mapping file %s for product %s: %s",
                                mapping_file,
                                product.sku,
                                mapping_error,
                            )
                if not mapping_loaded:
                    logger.warning(
                        "Failed to map condition for product %s: condition mapping file not found",
                        product.sku,
                    )

            if not condition_uuid:
                logger.warning(
                    "Falling back to Excellent condition for product %s due to missing mapping",
                    product.sku,
                )
                condition_uuid = "df268ad1-c462-4ba6-b6db-e007e23922ea"  # Excellent

            # Determine category UUID
            category_uuid = (
                reverb_options.get("primary_category")
                or reverb_options.get("category_uuid")
            )

            if not category_uuid:
                logger.warning(
                    "No Reverb category supplied for product %s; defaulting to Electric Guitars",
                    product.sku,
                )
                category_uuid = "dfd39027-d134-4353-b9e4-57dc6be791b9"

            # Determine shipping profile
            shipping_profile_id = reverb_options.get("shipping_profile")
            if not shipping_profile_id and getattr(product, "shipping_profile", None):
                shipping_profile_id = product.shipping_profile.reverb_profile_id

            # Prepare images
            valid_photos: List[str] = []

            def _collect_photo(url: Optional[str]) -> None:
                if not url:
                    return
                if url.startswith(("http://", "https://")):
                    valid_photos.append(url)
                else:
                    logger.warning(
                        "Skipping non-public image URL '%s' for product %s",
                        url,
                        product.sku,
                    )

            _collect_photo(product.primary_image)
            if product.additional_images:
                for extra in product.additional_images:
                    _collect_photo(extra)

            if not valid_photos:
                return {
                    "status": "error",
                    "error": "Reverb requires at least one publicly accessible image URL (http/https)."
                }

            override_price = None
            for price_key in ("price", "price_display", "reverb_price"):
                if reverb_options.get(price_key):
                    override_price = reverb_options[price_key]
                    break

            def _coerce_price(value: Any, fallback: float) -> float:
                if value is None:
                    return fallback
                try:
                    return float(str(value).replace(",", ""))
                except (TypeError, ValueError):
                    return fallback

            base_price_value = float(product.base_price or 0)
            reverb_price_value = _coerce_price(override_price, base_price_value)

            listing_payload: Dict[str, Any] = {
                "title": product.title or f"{product.brand} {product.model}".strip(),
                "make": product.brand,
                "model": product.model,
                "description": product.description
                    or f"{product.brand} {product.model} in {product.condition} condition",
                "condition": {"uuid": condition_uuid},
                "categories": [{"uuid": category_uuid}] if category_uuid else [],
                "price": {
                    "amount": f"{reverb_price_value:.2f}",
                    "currency": "GBP",
                },
                "shipping": {
                    "local": bool(product.local_pickup),
                    "rates": [],
                },
                "has_inventory": bool(product.is_stocked_item),
                "inventory": product.quantity if product.is_stocked_item and product.quantity else 1,
                "finish": product.finish,
                "year": str(product.year) if product.year else None,
                "sku": product.sku,
                "publish": publish,
                "photos": valid_photos,
            }

            video_payload = self._prepare_video_payload(product.video_url)
            if video_payload:
                listing_payload["videos"] = [video_payload]
                video_url_for_description = video_payload.get("url") or (
                    product.video_url.strip() if product.video_url else None
                )
                if video_url_for_description:
                    listing_payload["description"] = self._ensure_video_in_description(
                        listing_payload.get("description"),
                        video_url_for_description,
                        video_payload.get("video_id"),
                    )

            if shipping_profile_id:
                listing_payload["shipping_profile_id"] = shipping_profile_id
            else:
                logger.warning(
                    "No Reverb shipping profile provided for product %s; listing may use account defaults",
                    product.sku,
                )

            # Remove None values to avoid API complaints
            listing_payload = {
                key: value
                for key, value in listing_payload.items()
                if value not in (None, [], {})
            }

            log_payload = listing_payload.copy()
            log_payload["photos"] = f"[{len(valid_photos)} images]"
            logger.info(
                "Creating Reverb listing for product %s with payload: %s",
                product.sku,
                json.dumps(log_payload, indent=2),
            )

            response = await self.client.create_listing(listing_payload)
            listing_data = response.get("listing", response)
            reverb_id = str(listing_data.get("id")) if listing_data.get("id") else None

            if not reverb_id:
                await self.db.rollback()
                return {
                    "status": "error",
                    "error": "Reverb did not return a listing ID; creation may have failed",
                    "details": response,
                }

            listing_state = listing_data.get("state", {}).get("slug") or listing_data.get("state")
            publish_errors: List[str] = []

            if publish and reverb_id:
                ready_payload = await self._wait_for_listing_assets(reverb_id)
                if ready_payload:
                    listing_data = ready_payload
                    listing_state = listing_data.get("state", {}).get("slug") or listing_data.get("state")

                if listing_state != "live":
                    try:
                        await self.client.publish_listing(reverb_id)
                        refreshed_listing = await self._refresh_listing_until_state(reverb_id, desired_state="live")
                        if refreshed_listing:
                            listing_data = refreshed_listing
                            listing_state = listing_data.get("state", {}).get("slug") or listing_data.get("state")
                    except Exception as exc:
                        publish_errors.append(str(exc))
                        logger.warning(
                            "Failed to publish listing %s immediately after creation: %s",
                            reverb_id,
                            exc,
                        )

            # Upsert platform_common
            existing_common_query = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "reverb",
            )
            existing_common_result = await self.db.execute(existing_common_query)
            platform_common = existing_common_result.scalar_one_or_none()

            listing_url = listing_data.get("_links", {}).get("web", {}).get("href")
            if not listing_url:
                listing_url = f"https://reverb.com/item/{reverb_id}"

            platform_status_value = (
                ListingStatus.ACTIVE.value
                if (listing_state or "").lower() == "live"
                else ListingStatus.DRAFT.value
            )

            if platform_common:
                platform_common.external_id = reverb_id
                platform_common.status = platform_status_value
                platform_common.listing_url = listing_url
                platform_common.platform_specific_data = listing_data
                platform_common.sync_status = SyncStatus.SYNCED.value
                platform_common.last_sync = datetime.utcnow()
            else:
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="reverb",
                    external_id=reverb_id,
                    status=platform_status_value,
                    listing_url=listing_url,
                    platform_specific_data=listing_data,
                    sync_status=SyncStatus.SYNCED.value,
                    last_sync=datetime.utcnow(),
                )
                self.db.add(platform_common)
                await self.db.flush()

            await self.db.flush()

            # Upsert reverb_listings entry
            existing_listing_query = select(ReverbListing).where(
                ReverbListing.reverb_listing_id == reverb_id
            )
            existing_listing_result = await self.db.execute(existing_listing_query)
            reverb_listing = existing_listing_result.scalar_one_or_none()

            category_uuid = category_uuid or (
                listing_data.get("categories", [{}])[0] or {}
            ).get("uuid")

            slug = listing_data.get("slug")
            shipping_profile_value = None
            shipping_profile_data = listing_data.get("shipping_profile")
            if isinstance(shipping_profile_data, dict):
                shipping_profile_value = shipping_profile_data.get("id") or shipping_profile_data.get("uuid")
            elif listing_data.get("shipping_profile_id"):
                shipping_profile_value = str(listing_data.get("shipping_profile_id"))
            elif listing_payload.get("shipping_profile_id"):
                shipping_profile_value = str(listing_payload.get("shipping_profile_id"))

            stats_block = listing_data.get("stats") if isinstance(listing_data.get("stats"), dict) else {}
            price_block = listing_data.get("price") if isinstance(listing_data.get("price"), dict) else {}

            created_at = self._normalize_datetime(listing_data.get("created_at"))

            published_at = None
            for key in ("published_at", "reverb_published_at"):
                published_at = self._normalize_datetime(listing_data.get(key))
                if published_at:
                    break

            state_normalized = (listing_state or "").lower() if listing_state else None

            if reverb_listing:
                reverb_listing.reverb_category_uuid = category_uuid
                reverb_listing.reverb_state = state_normalized
                reverb_listing.reverb_slug = slug
                reverb_listing.shipping_profile_id = shipping_profile_value or reverb_listing.shipping_profile_id
                reverb_listing.inventory_quantity = listing_data.get("inventory") or reverb_listing.inventory_quantity
                if listing_data.get("has_inventory") is not None:
                    reverb_listing.has_inventory = listing_data.get("has_inventory")
                if listing_data.get("offers_enabled") is not None:
                    reverb_listing.offers_enabled = listing_data.get("offers_enabled")
                if listing_data.get("auction") is not None:
                    reverb_listing.is_auction = listing_data.get("auction")
                if price_block.get("amount") is not None:
                    try:
                        reverb_listing.list_price = float(price_block.get("amount"))
                    except (TypeError, ValueError):
                        reverb_listing.list_price = reverb_price_value
                elif reverb_price_value is not None:
                    reverb_listing.list_price = reverb_price_value
                if price_block.get("currency"):
                    reverb_listing.listing_currency = price_block.get("currency")
                if stats_block.get("views") is not None:
                    reverb_listing.view_count = stats_block.get("views")
                if stats_block.get("watches") is not None:
                    reverb_listing.watch_count = stats_block.get("watches")
                reverb_listing.reverb_created_at = created_at or reverb_listing.reverb_created_at
                reverb_listing.reverb_published_at = published_at or reverb_listing.reverb_published_at
                reverb_listing.extended_attributes = listing_data
                reverb_listing.platform_id = platform_common.id
            else:
                list_price_value = None
                if price_block.get("amount") is not None:
                    try:
                        list_price_value = float(price_block.get("amount"))
                    except (TypeError, ValueError):
                        list_price_value = None
                if list_price_value is None:
                    list_price_value = reverb_price_value

                reverb_listing = ReverbListing(
                    platform_id=platform_common.id,
                    reverb_listing_id=reverb_id,
                    reverb_category_uuid=category_uuid,
                    reverb_state=state_normalized,
                    reverb_slug=slug,
                    shipping_profile_id=shipping_profile_value,
                    inventory_quantity=listing_data.get("inventory"),
                    has_inventory=listing_data.get("has_inventory"),
                    offers_enabled=listing_data.get("offers_enabled"),
                    is_auction=listing_data.get("auction"),
                    list_price=list_price_value,
                    listing_currency=price_block.get("currency"),
                    view_count=stats_block.get("views"),
                    watch_count=stats_block.get("watches"),
                    reverb_created_at=created_at,
                    reverb_published_at=published_at,
                    extended_attributes=listing_data,
                )
                self.db.add(reverb_listing)

            await self.db.commit()

            return {
                "status": "success",
                "reverb_listing_id": reverb_id,
                "platform_common_id": platform_common.id,
                "listing_url": listing_url,
                "listing_data": listing_data,
                "publish_errors": publish_errors,
            }

        except ReverbAPIError as api_error:
            await self.db.rollback()
            logger.error(
                "Reverb API error while creating listing for product %s: %s",
                product_id,
                api_error,
            )
            return {"status": "error", "error": str(api_error)}
        except Exception as exc:
            await self.db.rollback()
            logger.error(
                "Unexpected error creating Reverb listing for product %s: %s",
                product_id,
                exc,
                exc_info=True,
            )
            return {"status": "error", "error": str(exc)}
    
    async def create_draft_listing(self, reverb_listing_id: int, listing_data: Dict[str, Any] = None) -> ReverbListing:
        """
        Create a draft listing on Reverb based on product data.
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            listing_data: Optional custom listing data overrides
            
        Returns:
            ReverbListing: Updated database record with Reverb listing ID
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and associated PlatformCommon and Product
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common or not platform_common.product_id:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} or related Product not found")
            
            product = await self._get_product(platform_common.product_id)
            if not product:
                raise ListingNotFoundError(f"Product {platform_common.product_id} not found")
            
            # Prepare the listing data for Reverb API
            api_listing_data = listing_data or self._prepare_listing_data(listing, product)
            
            # Create the listing on Reverb
            response = await self.client.create_listing(api_listing_data)
            
            # Update database with the new Reverb listing ID
            if 'listing' in response and 'id' in response['listing']:
                reverb_id = str(response['listing']['id'])
                
                # Update the ReverbListing record
                listing.reverb_listing_id = reverb_id
                
                # Update platform_common sync status
                platform_common.sync_status = SyncStatus.SYNCED.value
                
                # Save changes to database
                self.db.add(listing)
                self.db.add(platform_common)
                await self.db.flush()
                
                logger.info(f"Created draft listing on Reverb with ID {reverb_id}")
                return listing
            else:
                logger.error(f"Failed to create listing: No listing ID in response: {response}")
                raise ReverbAPIError("Failed to create listing: No listing ID in response")
                
        except Exception as e:
            logger.error(f"Error creating draft listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to create draft listing: {str(e)}")
    
    async def get_listing_details(self, reverb_listing_id: int) -> Dict:
        """
        Get detailed information about a listing from Reverb API
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            
        Returns:
            Dict: Listing details from Reverb API
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing record
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            # Fetch the listing details from Reverb API
            return await self.client.get_listing(listing.reverb_listing_id)
        
        except Exception as e:
            logger.error(f"Error getting listing details: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to get listing details: {str(e)}")
    
    async def update_inventory(self, reverb_listing_id: int, quantity: int) -> bool:
        """
        Update the inventory quantity of a listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            quantity: New inventory quantity
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing record
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            # Prepare inventory update data
            inventory_data = {
                "inventory": quantity,
                "has_inventory": quantity > 0
            }
            
            # Update the listing on Reverb
            await self.client.update_listing(listing.reverb_listing_id, inventory_data)
            
            # Update local database record
            listing.inventory_quantity = quantity
            listing.has_inventory = quantity > 0
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Updated inventory for listing {listing.reverb_listing_id} to {quantity}")
            return True
        except Exception as exc:
            logger.error("Failed to update Reverb inventory for listing %s: %s", reverb_listing_id, exc)
            raise

    async def apply_product_update(
        self,
        product: Product,
        platform_link: PlatformCommon,
        changed_fields: Set[str],
    ) -> Dict[str, Any]:
        if not platform_link.external_id:
            return {"status": "skipped", "reason": "missing_external_id"}

        payload: Dict[str, Any] = {}
        if "title" in changed_fields and product.title:
            payload["title"] = product.title
        if "model" in changed_fields and product.model:
            payload["model"] = product.model
        if "description" in changed_fields:
            payload["description"] = product.description or ""

        if "quantity" in changed_fields:
            payload["has_inventory"] = bool(product.is_stocked_item)
            payload["inventory"] = int(product.quantity or 0) if product.is_stocked_item else 1

        if not payload:
            return {"status": "no_changes"}

        try:
            response = await self.client.update_listing(platform_link.external_id, payload)
        except Exception as exc:
            logger.error("Failed to update Reverb listing %s: %s", platform_link.external_id, exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

        listing_stmt = select(ReverbListing).where(ReverbListing.platform_id == platform_link.id)
        listing_result = await self.db.execute(listing_stmt)
        listing = listing_result.scalar_one_or_none()
        if listing:
            if "title" in payload:
                listing.title = payload["title"]
            if "description" in payload:
                listing.description = payload["description"]
            if "inventory" in payload:
                listing.inventory_quantity = payload["inventory"]
            listing.updated_at = datetime.utcnow()
            self.db.add(listing)

        platform_link.last_sync = datetime.utcnow()
        platform_link.sync_status = SyncStatus.SYNCED.value
        self.db.add(platform_link)

        return {"status": "updated", "response": response}
    
    async def publish_listing(self, reverb_listing_id: int) -> bool:
        """
        Publish a draft listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and PlatformCommon records
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} not found")
            
            # Publish the listing on Reverb
            publish_data = {"publish": True}
            await self.client.update_listing(listing.reverb_listing_id, publish_data)
            
            # Update local database records
            platform_common.status = ListingStatus.ACTIVE.value
            listing.reverb_state = "published"
            
            self.db.add(platform_common)
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Published listing {listing.reverb_listing_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error publishing listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to publish listing: {str(e)}")
    
    async def end_listing(self, reverb_listing_id: int, reason: str = "not_for_sale") -> bool:
        """
        End a listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            reason: Reason for ending the listing
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and PlatformCommon records
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} not found")
            
            # End the listing on Reverb
            end_data = {"state": "ended"}
            await self.client.update_listing(listing.reverb_listing_id, end_data)
            
            # Update local database records
            platform_common.status = ListingStatus.ENDED.value
            listing.reverb_state = "ended"
            
            self.db.add(platform_common)
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Ended listing {listing.reverb_listing_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error ending listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to end listing: {str(e)}")

    # Commented out 16/08/25 ... depcrecated in favour of new process
    # async def run_import_process(self, api_key: str, sync_run_id: uuid.UUID, use_cache: bool = False, cache_file: str = "reverb_data.json"):
    #     """
    #     Run the Reverb inventory import process, with optional caching.
        
    #     Args:
    #         api_key: The Reverb API key.
    #         sync_run_id: The UUID for this synchronization run.
    #         use_cache: If True, tries to load data from cache_file instead of the API.
    #         cache_file: The path to the cache file.
    #     """
    #     listings = []
    #     cache_path = Path(cache_file)

    #     try:
    #         print(f"Starting Reverb.run_import_process (Caching {'enabled' if use_cache else 'disabled'})")

    #         # --- CACHING LOGIC ---
    #         if use_cache and cache_path.exists():
    #             print(f"Loading listings from cache file: {cache_path}")
    #             with open(cache_path, 'r') as f:
    #                 listings = json.load(f)
    #             print(f"Loaded {len(listings)} listings from cache.")
    #         else:
    #             print("Cache not used or not found. Downloading listings from Reverb API...")
    #             client = ReverbClient(api_key)
    #             start_time = time.time()
    #             listings = await client.get_all_listings_detailed(max_concurrent=10)
    #             end_time = time.time()
    #             print(f"Downloaded {len(listings)} detailed listings in {end_time - start_time:.1f} seconds")

    #             # Save the fresh download to the cache file for future runs
    #             print(f"Saving fresh API data to cache file: {cache_path}")
    #             cache_path.parent.mkdir(parents=True, exist_ok=True)
    #             with open(cache_path, 'w') as f:
    #                 json.dump(listings, f, indent=2)
    #         # --- END CACHING LOGIC ---

    #         if not listings:
    #             print("Reverb listings download failed or cache was empty.")
    #             return {"status": "error", "message": "No Reverb listings data received"}
            
    #         print(f"Successfully loaded inventory with {len(listings)} items.")
            
    #         # Process inventory updates using differential sync
    #         # NOTE: We can now switch back to the clean sync_reverb_inventory function
    #         print("Processing inventory updates using differential sync...")
    #         sync_stats = await self.sync_reverb_inventory(listings, sync_run_id)

    #         print(f"Inventory sync process complete: {sync_stats}")
    #         return {
    #             "status": "success",
    #             "message": "Reverb inventory synced successfully.",
    #             **sync_stats
    #         }
        
    #     except Exception as e:
    #         import traceback
    #         error_traceback = traceback.format_exc()
    #         print(f"Exception in ReverbService.run_import_process: {str(e)}")
    #         print(f"Traceback: {error_traceback}")
    #         return {"status": "error", "message": str(e)}

    # Private helper methods
    
    async def _get_platform_common(self, platform_id: int) -> Optional[PlatformCommon]:
        """Get platform_common record by ID with associated product"""
        query = select(PlatformCommon).where(PlatformCommon.id == platform_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def _get_product(self, product_id: int) -> Optional[Product]:
        """Get product record by ID"""
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def _get_reverb_listing(self, listing_id: int) -> Optional[ReverbListing]:
        """Get reverb_listing record by ID"""
        query = select(ReverbListing).where(ReverbListing.id == listing_id)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def _get_all_listings_from_api(self, state: str) -> List[Dict]:
        """
        Fetches all listings for a given state by paginating through results
        using the service's own client.
        """
        logger.info(f"Fetching all listings from Reverb API with state: '{state}'...")
        # This now correctly uses the service's own configured client
        return await self.client.get_all_listings(state=state)
    
    def _prepare_listing_data(self, listing: ReverbListing, product: Product) -> Dict[str, Any]:
        """
        Prepare listing data for Reverb API
        
        Args:
            listing: ReverbListing record
            product: Associated Product record
            
        Returns:
            Dict: Listing data formatted for Reverb API
        """
        data = {
            "title": product.title or f"{product.brand} {product.model}",
            "description": product.description or "",
            "make": product.brand,
            "model": product.model,
            # Format condition as object with UUID
            "condition": {
                "uuid": self._get_condition_uuid(product.condition)
            },
            # Format price as object with amount and currency
            "price": {
                "amount": str(product.base_price),  # Must be a string
                "currency": "USD" if self.client.use_sandbox else "GBP"  # USD for sandbox, GBP for production
            },
            "shipping": {
                "local": True,
                "us": True,
                "us_rate": "25.00"  # Default shipping rate
            },
            "categories": [
                {"uuid": listing.reverb_category_uuid or "dfd39027-d134-4353-b9e4-57dc6be791b9"}  # Default to Electric Guitars
            ],
            "has_inventory": listing.has_inventory,
            "inventory": listing.inventory_quantity or 1,
            "offers_enabled": listing.offers_enabled
        }
        
        # Add photos if available
        if listing.photos:
            data["photos"] = listing.photos.split(",")
            
        # Add year if available
        if product.year:
            data["year"] = str(product.year)
            
        # Add finish if available
        if product.finish:
            data["finish"] = product.finish

        video_payload = self._prepare_video_payload(product.video_url)
        if video_payload:
            data["videos"] = [video_payload]
            video_url_for_description = video_payload.get("url") or (
                product.video_url.strip() if product.video_url else None
            )
            if video_url_for_description:
                data["description"] = self._ensure_video_in_description(
                    data.get("description", product.description),
                    video_url_for_description,
                    video_payload.get("video_id"),
                )

        return data

    def _get_condition_uuid(self, condition_name: str) -> str:
        """Map condition name to UUID"""
        condition_map = {
            "Mint": "ec942c5e-fd9d-4a70-af95-ce686ed439e5",
            "Excellent": "df268ad1-c462-4ba6-b6db-e007e23922ea",
            "Very Good": "ae4d9114-1bd7-4ec5-a4ba-6653af5ac84d", 
            "Good": "ddadff2a-188c-42e0-be90-ebed197400a3",
            "Fair": "a2356006-97f9-487c-bd68-6c148a8ffe93",
            "Poor": "41b843b5-af33-4f37-9e9e-eec54aac6ce4",
            "Non Functioning": "196adee9-5415-4b5d-910f-39f2eb72e92f"
        }
        # Default to "Excellent" condition if not found
        return condition_map.get(condition_name, "df268ad1-c462-4ba6-b6db-e007e23922ea")

    def _prepare_video_payload(self, video_url: Optional[str]) -> Optional[Dict[str, str]]:
        """Normalize YouTube URLs for Reverb payloads."""
        if not video_url:
            return None

        cleaned_url = video_url.strip()
        if not cleaned_url:
            return None

        video_id = self._extract_youtube_id(cleaned_url)
        normalized_url = cleaned_url
        if video_id:
            normalized_url = f"https://www.youtube.com/watch?v={video_id}"

        payload: Dict[str, str] = {
            "type": "youtube",
            "url": normalized_url,
        }
        if video_id:
            payload["video_id"] = video_id
        return payload

    @staticmethod
    def _extract_youtube_id(url: str) -> Optional[str]:
        """Extract the YouTube video ID from common URL formats."""
        try:
            parsed = urlparse(url)
        except ValueError:
            return None

        if not parsed.netloc:
            return None

        hostname = parsed.netloc.lower()

        if hostname.endswith("youtu.be"):
            return parsed.path.lstrip("/") or None

        if "youtube" in hostname:
            if parsed.path.startswith("/watch"):
                query = parse_qs(parsed.query)
                video_values = query.get("v")
                if video_values:
                    return video_values[0]
            # Shorts or other formats (/shorts/<id> or /embed/<id>)
            path_parts = [segment for segment in parsed.path.split("/") if segment]
            if path_parts:
                candidate = path_parts[-1]
                # Strip possible query fragments already handled; remove suffixes like 'watch'
                if candidate not in {"watch", "embed", "shorts"}:
                    return candidate

        return None

    @staticmethod
    def _ensure_video_in_description(
        description: Optional[str],
        video_url: str,
        video_id: Optional[str] = None,
    ) -> str:
        """Append the YouTube link to the description if it's not already present."""
        base_description = (description or "").strip()

        if video_url in base_description:
            return base_description
        if video_id and video_id in base_description:
            return base_description

        is_html = bool(re.search(r"<[^>]+>", base_description))

        if is_html:
            snippet = (
                f'<p><strong>Video demo:</strong> '
                f'<a href="{video_url}" target="_blank" rel="noopener">{video_url}</a></p>'
            )
            return f"{base_description}\n{snippet}" if base_description else snippet

        snippet = f"Video demo: {video_url}"
        return f"{base_description}\n\n{snippet}" if base_description else snippet
    
    # Replaced by _fetch_existing_reverb_data for new sync sats 14/07
    async def _process_reverb_listings(self, listings: List[Dict]) -> Dict[str, int]:
        """Process Reverb listings (update existing, create new)"""
        stats = {"total": len(listings), "created": 0, "updated": 0, "errors": 0}
        
        try:
            for listing in listings:
                try:
                    # Extract Reverb listing ID
                    reverb_id = str(listing.get('id'))
                    sku = f"REV-{reverb_id}"
                    
                    # Check if product exists
                    stmt = text("SELECT id FROM products WHERE sku = :sku")
                    result = await self.db.execute(stmt, {"sku": sku})
                    existing_product_id = result.scalar_one_or_none()
                    
                    if existing_product_id:
                        # Update existing product
                        await self._update_existing_product(existing_product_id, listing)
                        stats["updated"] += 1
                    else:
                        # Create new product
                        await self._create_new_product(listing, sku)
                        stats["created"] += 1
                        
                except Exception as e:
                    logger.error(f"Error processing listing {listing.get('id')}: {e}")
                    stats["errors"] += 1
            
            await self.db.commit()
            return stats
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in _process_reverb_listings: {e}")
            raise

    # Fixed query to mirror eBay/V&R/Shopify pattern
    async def _fetch_existing_reverb_data_old(self) -> List[Dict]:
        """Fetches all Reverb-related data from the local database."""
        query = text("""
            WITH reverb_data AS (
                -- Get all Reverb listings with their platform_common records
                SELECT DISTINCT ON (rl.reverb_listing_id)
                    p.id as product_id, 
                    p.sku, 
                    p.base_price, 
                    p.description, 
                    p.status as product_status,
                    pc.id as platform_common_id, 
                    pc.external_id, 
                    pc.status as platform_common_status,
                    rl.id as reverb_listing_id, 
                    rl.reverb_state, 
                    rl.list_price
                FROM reverb_listings rl
                JOIN platform_common pc ON pc.id = rl.platform_id AND pc.platform_name = 'reverb'
                LEFT JOIN products p ON p.id = pc.product_id
                ORDER BY rl.reverb_listing_id, rl.id DESC
            )
            SELECT 
                product_id, sku, base_price, description, product_status,
                platform_common_id, external_id, platform_common_status,
                reverb_listing_id, reverb_state, list_price
            FROM reverb_data
            
            UNION ALL
            
            -- Also get platform_common records without reverb_listings (orphaned records)
            SELECT 
                p.id as product_id, 
                p.sku, 
                p.base_price, 
                p.description, 
                p.status as product_status,
                pc.id as platform_common_id, 
                pc.external_id, 
                pc.status as platform_common_status,
                NULL as reverb_listing_id, 
                NULL as reverb_state, 
                NULL as list_price
            FROM platform_common pc
            LEFT JOIN products p ON p.id = pc.product_id
            WHERE pc.platform_name = 'reverb'
            AND NOT EXISTS (
                SELECT 1 FROM reverb_listings rl 
                WHERE rl.platform_id = pc.id
            )
        """)
        result = await self.db.execute(query)
        return [row._asdict() for row in result.fetchall()]

    async def _fetch_existing_reverb_data(self) -> List[Dict]:
        """Fetches all Reverb-related data from the local database, focusing on the source of truth."""
        query = text("""
            SELECT 
                p.id as product_id, 
                p.sku, 
                p.base_price, -- For price comparison
                pc.id as platform_common_id, 
                pc.external_id, 
                pc.status as platform_common_status -- This is our source of truth
            FROM platform_common pc
            LEFT JOIN products p ON p.id = pc.product_id
            WHERE pc.platform_name = 'reverb'
        """)
        result = await self.db.execute(query)
        return [row._asdict() for row in result.fetchall()]

    # Remove the diagnostic version and replace with clean sync
    async def sync_reverb_inventory(self, listings: List[Dict], sync_run_id: uuid.UUID) -> Dict[str, Any]:
        """Main sync method - compares API data with DB and applies only necessary changes."""
        stats = {
            "total_from_reverb": len(listings), 
            "events_logged": 0, 
            "created": 0, 
            "updated": 0, 
            "removed": 0, 
            "unchanged": 0, 
            "errors": 0
        }
        
        try:
            # Step 1: Fetch all existing Reverb data from DB
            existing_data = await self._fetch_existing_reverb_data()
            
            # Step 2: Convert data to lookup dictionaries for O(1) access
            api_items = self._prepare_api_data(listings)
            db_items = self._prepare_db_data(existing_data)
            
            # Step 3: Calculate differences (remove pending_ids logic for simplicity)
            changes = self._calculate_changes(api_items, db_items)
            
            # Step 4: Apply changes in batches
            logger.info(f"Applying changes: {len(changes['create'])} new, "
                        f"{len(changes['update'])} updates, {len(changes['remove'])} removals")
            
            if changes['create']:
                stats['created'], events_created = await self._batch_create_products(changes['create'], sync_run_id)
                stats['events_logged'] += events_created
            if changes['update']:
                stats['updated'], events_updated = await self._batch_update_products(changes['update'], sync_run_id)
                stats['events_logged'] += events_updated
            if changes['remove']:
                stats['removed'], events_removed = await self._batch_mark_removed(changes['remove'], sync_run_id)
                stats['events_logged'] += events_removed
        
            stats['unchanged'] = len(api_items) - stats['created'] - stats['updated']
            await self.db.commit()
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Sync failed: {str(e)}", exc_info=True)
            stats['errors'] += 1
            
        return stats
    
    # Fixed batch methods to only log events (no DB updates)
    async def _batch_create_products(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Log rogue listings to sync_events only - no database records created."""
        created_count, events_logged = 0, 0
        
        # Prepare all events first
        events_to_create = []
        for item in items:
            try:
                logger.warning(f"Rogue SKU Detected: Reverb item {item['reverb_id']} ('{item.get('title')}') not found in local DB. Logging to sync_events for later processing.")
                
                event_data = {
                    'sync_run_id': sync_run_id,
                    'platform_name': 'reverb',
                    'product_id': None,
                    'platform_common_id': None,
                    'external_id': item['reverb_id'],
                    'change_type': 'new_listing',
                    'change_data': {
                        'title': item['title'],
                        'price': item['price'],
                        'state': item['state'],
                        'sku': item['sku'],
                        'brand': item['brand'],
                        'model': item['model'],
                        'raw_data': item['_raw']
                    },
                    'status': 'pending'
                }
                events_to_create.append(event_data)
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare event for Reverb item {item['reverb_id']}: {e}", exc_info=True)
        
        # Bulk insert with ON CONFLICT DO NOTHING to handle duplicates gracefully
        if events_to_create:
            try:
                stmt = insert(SyncEvent).values(events_to_create)
                stmt = stmt.on_conflict_do_nothing(
                    constraint='sync_events_platform_external_change_unique'
                )
                result = await self.db.execute(stmt)
                events_logged = len(events_to_create)
                logger.info(f"Attempted to log {len(events_to_create)} new listing events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert new listing events: {e}", exc_info=True)
        
        return created_count, events_logged

    async def _batch_update_products_old(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """SYNC PHASE: Only log changes to sync_events - NO database table updates."""
        updated_count, events_logged = 0, 0
        
        # Collect all events to insert
        all_events = []
        
        for item in items:
            try:
                api_data, db_data = item['api_data'], item['db_data']
                
                # Price change event
                db_price_for_compare = float(db_data.get('list_price') or 0.0)
                if abs(api_data['price'] - db_price_for_compare) > 0.01:
                    all_events.append({
                        'sync_run_id': sync_run_id,
                        'platform_name': 'reverb',
                        'product_id': db_data['product_id'],
                        'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['reverb_id'],
                        'change_type': 'price',
                        'change_data': {
                            'old': db_data.get('list_price'),
                            'new': api_data['price'],
                            'reverb_id': api_data['reverb_id']
                        },
                        'status': 'pending'
                    })
                
                # Status change event
                if api_data['state'] != str(db_data.get('reverb_state', '')).lower():
                    all_events.append({
                        'sync_run_id': sync_run_id,
                        'platform_name': 'reverb',
                        'product_id': db_data['product_id'],
                        'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['reverb_id'],
                        'change_type': 'status_change',
                        'change_data': {
                            'old': db_data.get('reverb_state'),
                            'new': api_data['state'],
                            'reverb_id': api_data['reverb_id'],
                            'is_sold': api_data['is_sold']
                        },
                        'status': 'pending'
                    })
                
                updated_count += 1
                
            except Exception as e:
                logger.error(f"Failed to prepare events for Reverb item {item['api_data']['reverb_id']}: {e}", exc_info=True)
        
        # Bulk insert all events with duplicate handling
        if all_events:
            try:
                stmt = insert(SyncEvent).values(all_events)
                stmt = stmt.on_conflict_do_nothing(
                    constraint='sync_events_platform_external_change_unique'
                )
                result = await self.db.execute(stmt)
                events_logged = len(all_events)
                logger.info(f"Attempted to log {len(all_events)} update events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert update events: {e}", exc_info=True)
        
        return updated_count, events_logged

    async def _batch_update_products(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """Logs price and status changes to sync_events, using the correct data keys."""
        updated_count, events_logged = 0, 0
        all_events = []
        
        for item in items:
            try:
                api_data, db_data = item['api_data'], item['db_data']
                
                # Price change event check
                db_price_for_compare = float(db_data.get('base_price') or 0.0)
                if abs(api_data['price'] - db_price_for_compare) > 0.01:
                    all_events.append({
                        'sync_run_id': sync_run_id, 'platform_name': 'reverb',
                        'product_id': db_data['product_id'], 'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['external_id'], 'change_type': 'price',
                        'change_data': {'old': db_data.get('base_price'), 'new': api_data['price']},
                        'status': 'pending'
                    })
                
                # Status change event check
                api_status = api_data.get('status')
                db_status = db_data.get('platform_common_status')
                off_market_statuses = ['sold', 'ended', 'archived']
                statuses_match = (api_status in off_market_statuses and db_status in off_market_statuses) or (api_status == db_status)

                if not statuses_match:
                    all_events.append({
                        'sync_run_id': sync_run_id, 'platform_name': 'reverb',
                        'product_id': db_data['product_id'], 'platform_common_id': db_data['platform_common_id'],
                        'external_id': api_data['external_id'], 'change_type': 'status_change',
                        'change_data': {'old': db_status, 'new': api_status},
                        'status': 'pending'
                    })
                
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare events for Reverb item {item['api_data']['external_id']}: {e}", exc_info=True)
        
        if all_events:
            stmt = insert(SyncEvent).values(all_events)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['platform_name', 'external_id', 'change_type'],
                index_where=(SyncEvent.status == 'pending')
            )
            await self.db.execute(stmt)
            events_logged = len(all_events)

        return updated_count, events_logged

    async def _batch_mark_removed(self, items: List[Dict], sync_run_id: uuid.UUID) -> Tuple[int, int]:
        """SYNC PHASE: Only log removal events to sync_events - NO database table updates."""
        removed_count, events_logged = 0, 0
        
        # Prepare all removal events
        events_to_create = []
        for item in items:
            try:
                events_to_create.append({
                    'sync_run_id': sync_run_id,
                    'platform_name': 'reverb',
                    'product_id': item['product_id'],
                    'platform_common_id': item['platform_common_id'],
                    'external_id': item['external_id'],
                    'change_type': 'removed_listing',
                    'change_data': {
                        'sku': item['sku'],
                        'reverb_id': item['external_id'],
                        'reason': 'not_found_in_api'
                    },
                    'status': 'pending'
                })
                removed_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare removal event for Reverb item {item['external_id']}: {e}", exc_info=True)
        
        # Bulk insert with duplicate handling
        if events_to_create:
            try:
                stmt = insert(SyncEvent).values(events_to_create)
                stmt = stmt.on_conflict_do_nothing(
                    constraint='sync_events_platform_external_change_unique'
                )
                result = await self.db.execute(stmt)
                events_logged = len(events_to_create)
                logger.info(f"Attempted to log {len(events_to_create)} removal events (duplicates ignored)")
            except Exception as e:
                logger.error(f"Failed to bulk insert removal events: {e}", exc_info=True)
        
        return removed_count, events_logged

    async def _fetch_pending_new_listings(self) -> set[str]:
            """Fetch external_ids for Reverb listings that are already pending creation."""
            query = text("""
                SELECT external_id FROM sync_events
                WHERE platform_name = 'reverb'
                AND change_type = 'new_listing'
                AND status = 'pending'
            """)
            result = await self.db.execute(query)
            return {row[0] for row in result.fetchall()}
    
    async def _mark_removed_reverb_products(self, listings: List[Dict]) -> Dict[str, int]:
        """Mark products that are no longer on Reverb as removed"""
        stats = {"marked_removed": 0}
        
        # Get Reverb listing IDs from current data
        current_ids = {f"REV-{listing.get('id')}" for listing in listings if listing.get('id')}
        
        # Find products in DB but not in current listings
        stmt = text("SELECT sku, id FROM products WHERE sku LIKE 'REV-%' AND sku != ALL(:current_skus)")
        result = await self.db.execute(stmt, {"current_skus": tuple(current_ids)})
        removed_products = result.fetchall()
        
        # Mark as removed
        for sku, product_id in removed_products:
            platform_update = text("""
                UPDATE platform_common 
                SET status = 'REMOVED', 
                    sync_status = 'SYNCED',
                    last_sync = timezone('utc', now()),
                    updated_at = timezone('utc', now())
                WHERE product_id = :product_id AND platform_name = 'reverb'
            """)
            await self.db.execute(platform_update, {"product_id": product_id})
            stats["marked_removed"] += 1
        
        logger.info(f"Marked {stats['marked_removed']} Reverb products as removed")
        return stats

    async def update_listing_price(self, external_id: str, new_price: float) -> bool:
        """Outbound action to update the price of a listing on Reverb."""
        logger.info(f"Received request to update Reverb listing {external_id} to price £{new_price:.2f}.")
        try:
            # Reverb's API expects the price as an object with amount and currency
            price_data = {
                "price": {
                    "amount": f"{new_price:.2f}",
                    "currency": "GBP"
                }
            }
            
            response = await self.client.update_listing(external_id, price_data)
            
            # A successful update returns the updated listing object.
            if response and 'id' in response.get('listing', {}):
                logger.info(f"Successfully sent price update for Reverb listing {external_id}.")
                return True
            
            logger.error(f"API call to update price for Reverb listing {external_id} failed. Response: {response}")
            return False
        except Exception as e:
            logger.error(f"Exception while updating price for Reverb listing {external_id}: {e}", exc_info=True)
            return False

    async def _update_existing_product(self, product_id: int, listing: Dict):
        """Update an existing product with new Reverb data"""
        # Extract data from listing
        is_sold = listing.get('state', {}).get('slug') == 'sold'
        new_status = ProductStatus.SOLD if is_sold else ProductStatus.ACTIVE
        
        # Update product
        update_stmt = text("""
            UPDATE products 
            SET base_price = :price,
                description = :description,
                status = :status,
                updated_at = timezone('utc', now())
            WHERE id = :product_id
        """)
        
        await self.db.execute(update_stmt, {
            "product_id": product_id,
            "price": float(listing.get('price', {}).get('amount', 0)) if listing.get('price') else 0,
            "description": listing.get('description', ''),
            "status": new_status.value
        })
        
        # Update platform_common
        platform_update = text("""
            UPDATE platform_common 
            SET status = :status,
                sync_status = 'SYNCED',
                last_sync = timezone('utc', now()),
                updated_at = timezone('utc', now())
            WHERE product_id = :product_id AND platform_name = 'reverb'
        """)
        
        platform_status = ListingStatus.SOLD if is_sold else ListingStatus.ACTIVE
        await self.db.execute(platform_update, {
            "product_id": product_id,
            "status": platform_status.value
        })

    async def run_import_process_old(self, sync_run_id: uuid.UUID) -> Dict[str, Any]:
        """
        Runs the differential sync for Reverb using a single, consistently
        configured client for all API calls.
        """
        stats = {"api_live_count": 0, "db_live_count": 0, "events_logged": 0, "rogue_listings": 0, "status_changes": 0, "errors": 0}
        logger.info(f"=== ReverbService: STARTING SYNC (run_id: {sync_run_id}) ===")

        try:
            # --- REFACTORED: No longer imports or calls the external script ---
            live_listings_api = await self._get_all_listings_from_api(state='live')
            
            api_live_ids = {str(item['id']) for item in live_listings_api}
            stats['api_live_count'] = len(api_live_ids)
            logger.info(f"Found {stats['api_live_count']} live listings on Reverb API.")

            # (The rest of the method remains exactly the same as before)
            # ...
            local_live_ids_map = await self._fetch_local_live_reverb_ids()
            local_live_ids = set(local_live_ids_map.keys())
            stats['db_live_count'] = len(local_live_ids)
            logger.info(f"Found {stats['db_live_count']} live listings in local DB for Reverb.")

            new_rogue_ids = api_live_ids - local_live_ids
            missing_live_ids = local_live_ids - api_live_ids
            
            logger.info(f"Detected {len(new_rogue_ids)} potential new listings and {len(missing_live_ids)} status changes.")
            stats['rogue_listings'] = len(new_rogue_ids)
            stats['status_changes'] = len(missing_live_ids)
            
            events_to_log = []

            for reverb_id in new_rogue_ids:
                events_to_log.append(self._prepare_sync_event(
                    sync_run_id, 'new_listing', external_id=reverb_id,
                    change_data={'reason': 'Live on Reverb but not in local DB'}
                ))

            for reverb_id in missing_live_ids:
                db_item = local_live_ids_map[reverb_id]
                try:
                    details = await self.client.get_listing_details(reverb_id)
                    new_status = details.get('state', {}).get('slug', 'unknown')
                    
                    events_to_log.append(self._prepare_sync_event(
                        sync_run_id, 'status_change', 
                        external_id=reverb_id,
                        product_id=db_item['product_id'],
                        platform_common_id=db_item['platform_common_id'],
                        change_data={'old': 'live', 'new': new_status, 'reverb_id': reverb_id}
                    ))
                except ReverbAPIError:
                    logger.warning(f"Logging item {reverb_id} as 'deleted' due to API error (Not Found).")
                    events_to_log.append(self._prepare_sync_event(
                        sync_run_id, 'status_change',
                        external_id=reverb_id,
                        product_id=db_item['product_id'],
                        platform_common_id=db_item['platform_common_id'],
                        change_data={'old': 'live', 'new': 'deleted', 'reverb_id': reverb_id, 'reason': 'API Not Found'}
                    ))
                    stats['errors'] += 1

            if events_to_log:
                await self._batch_log_events(events_to_log)
                stats['events_logged'] = len(events_to_log)
            
            await self.db.commit()
            logger.info(f"=== ReverbService: FINISHED SYNC === Final Stats: {stats}")
            return {"status": "success", "message": "Reverb sync complete.", **stats}

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Reverb sync failed: {e}", exc_info=True)
            stats['errors'] += 1
            return {"status": "error", "message": str(e), **stats}

    async def run_import_process(self, sync_run_id: uuid.UUID) -> Dict[str, Any]:
        """
        Runs the sync for Reverb. This method detects new live listings on Reverb
        and status changes for existing listings (e.g., live -> sold).
        """
        stats = {"api_live_count": 0, "db_live_count": 0, "events_logged": 0, "errors": 0}
        logger.info(f"=== ReverbService: STARTING SYNC (run_id: {sync_run_id}) ===")

        try:
            # 1. Fetch all LIVE listings from the Reverb API.
            live_listings_api = await self._get_all_listings_from_api(state='live')
            api_live_ids = {str(item['id']) for item in live_listings_api}
            stats['api_live_count'] = len(api_live_ids)
            logger.info(f"Found {stats['api_live_count']} live listings on Reverb API.")

            # 2. Fetch all Reverb listings marked as 'live' in our local DB.
            local_live_ids_map = await self._fetch_local_live_reverb_ids()
            local_live_ids = set(local_live_ids_map.keys())
            stats['db_live_count'] = len(local_live_ids)
            logger.info(f"Found {stats['db_live_count']} live listings in local DB for Reverb.")

            # 3. Compare the sets of IDs to find differences.
            new_rogue_ids = api_live_ids - local_live_ids
            missing_from_api_ids = local_live_ids - api_live_ids

            # Create a mapping for easy access to listing data
            api_listings_map = {str(listing['id']): listing for listing in live_listings_api}

            logger.info(f"Detected {len(new_rogue_ids)} new 'rogue' listings and {len(missing_from_api_ids)} potential status changes.")

            events_to_log = []

            # 4. Create 'new_listing' events for rogue items.
            for reverb_id in new_rogue_ids:
                listing = api_listings_map.get(reverb_id, {})

                # Extract primary image URL
                photos = listing.get('photos', [])
                primary_image_url = None
                if photos:
                    primary_image_url = photos[0].get('_links', {}).get('full', {}).get('href')

                # Extract listing details
                change_data = {
                    'reason': 'Live on Reverb but not in local DB',
                    'title': listing.get('title'),
                    'price': listing.get('price', {}).get('amount'),
                    'brand': listing.get('make'),  # Reverb uses 'make' for brand
                    'model': listing.get('model'),
                    'primary_image_url': primary_image_url
                }

                events_to_log.append(self._prepare_sync_event(
                    sync_run_id, 'new_listing', external_id=reverb_id,
                    change_data=change_data
                ))

            # 5. For items no longer 'live' on the API, fetch their details to find out WHY.
            for reverb_id in missing_from_api_ids:
                db_item = local_live_ids_map[reverb_id]
                try:
                    # This second API call is crucial to get the new status (e.g., 'sold', 'ended').
                    details = await self.client.get_listing_details(reverb_id)
                    new_status = details.get('state', {}).get('slug', 'unknown')
                    
                    events_to_log.append(self._prepare_sync_event(
                        sync_run_id, 'status_change', 
                        external_id=reverb_id,
                        product_id=db_item['product_id'],
                        platform_common_id=db_item['platform_common_id'],
                        change_data={'old': 'live', 'new': new_status, 'reverb_id': reverb_id}
                    ))
                except ReverbAPIError:
                    # If the API gives a 'Not Found' error, the listing was likely deleted.
                    logger.warning(f"Logging item {reverb_id} as 'deleted' due to API error (Not Found).")
                    events_to_log.append(self._prepare_sync_event(
                        sync_run_id, 'status_change',
                        external_id=reverb_id,
                        product_id=db_item['product_id'],
                        platform_common_id=db_item['platform_common_id'],
                        change_data={'old': 'live', 'new': 'deleted', 'reverb_id': reverb_id, 'reason': 'API Not Found'}
                    ))
                    stats['errors'] += 1

            # 6. Log all generated events to the database.
            if events_to_log:
                await self._batch_log_events(events_to_log)
                stats['events_logged'] = len(events_to_log)
            
            await self.db.commit()
            logger.info(f"=== ReverbService: FINISHED SYNC === Final Stats: {stats}")
            return {"status": "success", "message": "Reverb sync complete.", **stats}

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Reverb sync failed: {e}", exc_info=True)
            stats['errors'] += 1
            return {"status": "error", "message": str(e), **stats}

    # Ensure these helper methods are in your ReverbService class
    
    def _prepare_api_data_old(self, listings: List[Dict]) -> Dict[str, Dict]:
        """Convert API data to lookup dict by Reverb ID."""
        api_items = {}
        for listing in listings:
            reverb_id = str(listing.get('id', ''))
            if not reverb_id:
                continue
            
            state_obj = listing.get('state', {})
            state_slug = state_obj.get('slug', 'unknown') if isinstance(state_obj, dict) else 'unknown'
            
            api_items[reverb_id] = {
                'reverb_id': reverb_id,
                'sku': f"REV-{reverb_id}",
                'price': float(listing.get('price', {}).get('amount', 0)) if listing.get('price') else 0,
                'is_sold': state_slug == 'sold',
                'state': state_slug,
                'title': listing.get('title', ''),
                'brand': listing.get('make', 'Unknown'),
                'model': listing.get('model', 'Unknown'),
                'description': listing.get('description', ''),
                '_raw': listing
            }
        return api_items

    def _prepare_api_data(self, listings: List[Dict]) -> Dict[str, Dict]:
        """Convert API data to a lookup dict and translate statuses."""
        api_items = {}
        for listing in listings:
            reverb_id = str(listing.get('id', ''))
            if not reverb_id:
                continue
            
            state_slug = str(listing.get('state', {}).get('slug', 'unknown')).lower()

            # Translate Reverb's 'live' to our universal 'active'
            universal_status = 'active' if state_slug == 'live' else state_slug
            
            api_items[reverb_id] = {
                'external_id': reverb_id,
                'status': universal_status, # Use the translated status
                'price': float(listing.get('price', {}).get('amount', 0)),
                '_raw': listing
            }
        return api_items

    def _prepare_db_data(self, existing_data: List[Dict]) -> Dict[str, Dict]:
        """Convert DB data to lookup dict by external ID."""
        return {str(row['external_id']): row for row in existing_data if row.get('external_id')}

    def _calculate_changes(self, api_items: Dict, db_items: Dict) -> Dict[str, List]:
        """Calculate what needs to be created, updated, or removed."""
        changes = {'create': [], 'update': [], 'remove': []}
        
        api_ids = set(api_items.keys())
        db_ids = set(db_items.keys())
        
        for reverb_id in api_ids - db_ids:
            changes['create'].append(api_items[reverb_id])
        
        for reverb_id in api_ids & db_ids:
            if self._has_changed(api_items[reverb_id], db_items[reverb_id]):
                changes['update'].append({'api_data': api_items[reverb_id], 'db_data': db_items[reverb_id]})
        
        for reverb_id in db_ids - api_ids:
            changes['remove'].append(db_items[reverb_id])
            
        return changes

    def _has_changed_old(self, api_item: Dict, db_item: Dict) -> bool:
        """Check if an item has meaningful changes."""
        # Price check
        db_price = float(db_item.get('list_price') or 0)
        if abs(api_item['price'] - db_price) > 0.01:
            return True
        
        # Status check
        api_state = api_item['state']
        db_state = str(db_item.get('reverb_state', '')).lower()
        if api_state != db_state:
            return True
        
        return False

    def _has_changed(self, api_item: Dict, db_item: Dict) -> bool:
        """Compares API data against the new, correct fields from our database query."""
        api_status = api_item.get('status')
        db_status = db_item.get('platform_common_status')
        
        off_market_statuses = ['sold', 'ended', 'archived']
        statuses_match = (api_status in off_market_statuses and db_status in off_market_statuses) or \
                         (api_status == db_status)

        if not statuses_match:
            return True
            
        db_price = float(db_item.get('base_price') or 0.0)
        if abs(api_item['price'] - db_price) > 0.01:
            return True

        return False

    def _prepare_sync_event(self, sync_run_id, change_type, external_id, change_data, product_id=None, platform_common_id=None) -> Dict:
        """Helper to construct a SyncEvent dictionary for bulk insertion."""
        return {
            'sync_run_id': sync_run_id,
            'platform_name': 'reverb',
            'product_id': product_id,
            'platform_common_id': platform_common_id,
            'external_id': external_id,
            'change_type': change_type,
            'change_data': change_data,
            'status': 'pending'
        }

    async def _batch_log_events(self, events: List[Dict]):
        """Bulk inserts a list of sync events."""
        if not events:
            return
        logger.info(f"Logging {len(events)} events to the database.")
        try:
            # stmt = insert(SyncEvent).values(events)
            # stmt = stmt.on_conflict_do_nothing(
            #     constraint='sync_events_platform_external_change_unique'
            # )
            stmt = insert(SyncEvent).values(events)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['platform_name', 'external_id', 'change_type'],
                index_where=(SyncEvent.status == 'pending')
            )
            await self.db.execute(stmt)
        except Exception as e:
            logger.error(f"Failed to bulk insert sync events: {e}", exc_info=True)
            raise

    async def mark_item_as_sold(self, external_id: str) -> bool:
        """Outbound action to end a listing on Reverb because it sold elsewhere."""
        logger.info(f"Received request to end Reverb listing {external_id} (sold elsewhere).")
        try:
            response = await self.client.end_listing(external_id, reason="not_sold")

            # --- FINAL ROBUST CHECK ---

            # Scenario 1: The response is empty or None. We now treat this as a
            # likely success for an end_listing call that returns 200 OK but no body.
            if not response:
                logger.warning(f"Reverb API returned an empty success response for {external_id}, likely because it was already ended. Treating as success.")
                await self._mark_local_reverb_listing_ended(external_id)
                return True

            # Scenario 2: The response has a body, so we inspect it for explicit confirmation.
            listing_info = response.get('listing', {})
            state_info = listing_info.get('state')

            is_ended_nested = isinstance(state_info, dict) and state_info.get('slug') == 'ended'
            is_ended_simple = isinstance(state_info, str) and state_info.lower() == 'ended'

            if is_ended_nested or is_ended_simple:
                logger.info(f"Successfully CONFIRMED Reverb listing {external_id} is ended via response body.")
                await self._mark_local_reverb_listing_ended(external_id)
                return True
            else:
                # This covers the case of a 200 OK but with an unexpected body.
                logger.error(f"API call to end Reverb listing {external_id} returned a non-empty, unconfirmed response: {response}")
                return False

        except ReverbAPIError as e:
            # Scenario 3: The API returns a 422 error because the listing is already ended.
            error_message = str(e)
            if "This listing has already ended" in error_message:
                logger.warning(f"Reverb listing {external_id} is already ended (confirmed via 422 error). Treating as success.")
                await self._mark_local_reverb_listing_ended(external_id)
                return True 
            else:
                logger.error(f"A genuine Reverb API Error occurred for listing {external_id}: {e}", exc_info=True)
                return False
        except Exception as e:
            # Scenario 4: Any other exception (network error, etc.)
            logger.error(f"A non-API exception occurred while ending Reverb listing {external_id}: {e}", exc_info=True)
            return False

    async def _mark_local_reverb_listing_ended(self, external_id: str) -> None:
        """Update the local reverb_listings row to reflect an ended listing."""
        stmt = select(ReverbListing).where(ReverbListing.reverb_listing_id == external_id)
        listing_result = await self.db.execute(stmt)
        listing = listing_result.scalar_one_or_none()
        if listing:
            listing.reverb_state = 'ended'
            listing.inventory_quantity = 0
            listing.has_inventory = False
            listing.updated_at = datetime.utcnow()
            self.db.add(listing)

    async def _fetch_local_live_reverb_ids(self) -> Dict[str, Dict]:
        """Fetches all Reverb listings marked as 'live' in the local DB."""
        logger.info("Fetching live Reverb listings from local DB.")
        query = text("""
            SELECT pc.external_id, pc.product_id, pc.id as platform_common_id
            FROM platform_common pc
            JOIN reverb_listings rl ON pc.id = rl.platform_id
            WHERE pc.platform_name = 'reverb' AND rl.reverb_state = 'live'
        """)
        result = await self.db.execute(query)
        return {str(row.external_id): row._asdict() for row in result.fetchall()}

    def _convert_api_timestamp_to_naive_utc(self, timestamp_str: str | None) -> datetime | None:
        """
        Parses an ISO 8601 timestamp string (which can be offset-aware)
        from an API, converts it to UTC, and returns an offset-naive 
        datetime object suitable for storing in TIMESTAMP WITHOUT TIME ZONE columns.
        """
        if not timestamp_str:
            return None
        try:
            # 1. Parse the string from Reverb. 
            #    iso8601.parse_date() will create an "offset-aware" datetime object
            #    if the string has timezone info (e.g., '2023-03-09T04:46:32-06:00').
            dt_aware = iso8601.parse_date(timestamp_str)
            
            # 2. Convert this "aware" datetime object to its equivalent in UTC.
            #    The object is still "aware" at this point, but its time and tzinfo now represent UTC.
            dt_utc_aware = dt_aware.astimezone(datetime.timezone.utc)
            
            # 3. Make it "naive" by removing the timezone information.
            #    The actual clock time is now UTC, and we remove the "UTC" label
            #    because the database column doesn't store the label.
            dt_utc_naive = dt_utc_aware.replace(tzinfo=None)
            
            return dt_utc_naive
        except Exception as e:
            return None
    
    
    @staticmethod
    def _normalize_datetime(value: Optional[Any]) -> Optional[datetime]:
        if not value:
            return None

        parsed: Optional[datetime] = None
        try:
            if isinstance(value, datetime):
                parsed = value
            elif isinstance(value, str):
                parsed = iso8601.parse_date(value)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to parse datetime value %s: %s", value, exc)
            return None

        if parsed is None:
            return None

        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
