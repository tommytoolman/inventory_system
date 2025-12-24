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
from typing import Dict, List, Optional, Any, Tuple, Set
from urllib.parse import urlparse, parse_qs
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select
from sqlalchemy import update, text, func
from sqlalchemy.orm import selectinload

from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.reverb import ReverbListing
from app.models.reverb_order import ReverbOrder
from app.models.sync_event import SyncEvent
from app.services.reverb.client import ReverbClient
from app.core.config import Settings
from app.core.exceptions import ListingNotFoundError, ReverbAPIError
from app.services.match_utils import suggest_product_match
from app.core.enums import PlatformName, Handedness, ManufacturingCountry
from app.models.category_mappings import ReverbCategory
from app.services.sku_service import generate_next_riff_sku
from app.services.condition_mapping_service import ConditionMappingService

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
        self.condition_mapping_service = ConditionMappingService(db)
        
        # Use sandbox API for testing if enabled in settings
        use_sandbox = self.settings.REVERB_USE_SANDBOX
        # api_key = self.settings.REVERB_SANDBOX_API_KEY if use_sandbox else self.settings.REVERB_API_KEY
        
        self.client = ReverbClient(api_key=self.settings.REVERB_API_KEY, use_sandbox=use_sandbox)
        self.settings = settings

    async def _find_remote_listings_by_sku(self, sku: Optional[str]) -> List[Dict[str, Any]]:
        """Return Reverb listings that currently use the given SKU."""
        if not sku:
            return []

        try:
            response = await self.client.find_listing_by_sku(sku)
        except ReverbAPIError as exc:
            logger.warning("Unable to check Reverb for SKU %s: %s", sku, exc)
            return []
        except Exception as exc:
            logger.warning("Unexpected error during Reverb SKU lookup for %s: %s", sku, exc)
            return []

        listings: List[Dict[str, Any]] = []
        if isinstance(response, dict):
            if isinstance(response.get("listings"), list):
                listings = response["listings"]
            elif isinstance(response.get("_embedded", {}).get("listings"), list):
                listings = response["_embedded"]["listings"]

        total = response.get("total") if isinstance(response, dict) else None
        if total and not listings:
            logger.debug(
                "Reverb SKU lookup reported total=%s but no listings were parsed (sku=%s)",
                total,
                sku,
            )
        return listings

    @staticmethod
    def _summarize_reverb_listing(listing: Dict[str, Any]) -> Dict[str, Any]:
        """Return a lightweight summary for logging/UI messaging."""
        if not isinstance(listing, dict):
            return {}
        state = listing.get("state")
        if isinstance(state, dict):
            state_value = state.get("slug") or state.get("name")
        else:
            state_value = state
        return {
            "id": listing.get("id") or listing.get("listing_id"),
            "slug": listing.get("slug"),
            "state": state_value,
            "title": listing.get("title"),
            "price": listing.get("price", {}).get("amount") if isinstance(listing.get("price"), dict) else listing.get("price"),
        }

    async def _ensure_reverb_sku_available(self, product: Product) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Ensure the product's SKU is not already in use on Reverb.

        Returns:
            (True, adjustment_info) if it's safe to proceed. adjustment_info is populated when we auto-update the SKU.
            (False, error_payload) when we must abort (e.g., non-RIFF duplicate).
        """
        if not product.sku:
            return True, None

        listings = await self._find_remote_listings_by_sku(product.sku)
        if not listings:
            return True, None

        conflict_summary = self._summarize_reverb_listing(listings[0])
        duplicate_message = (
            f"Reverb already has a listing with SKU {product.sku}. "
            "End the existing listing or change the SKU before retrying."
        )

        if not product.sku.upper().startswith("RIFF-"):
            return False, {
                "status": "error",
                "error": duplicate_message,
                "code": "duplicate_sku",
                "conflict": conflict_summary,
            }

        for attempt in range(5):
            next_sku = await generate_next_riff_sku(self.db)
            previous_sku = product.sku
            product.sku = next_sku
            await self.db.commit()
            await self.db.refresh(product)

            logger.warning(
                "Auto-updated product %s SKU from %s to %s because Reverb already has listing %s",
                product.id,
                previous_sku,
                next_sku,
                conflict_summary.get("id"),
            )

            if not await self._find_remote_listings_by_sku(product.sku):
                return True, {
                    "old_sku": previous_sku,
                    "new_sku": next_sku,
                    "conflict": conflict_summary,
                }

        return False, {
            "status": "error",
            "error": duplicate_message + " Automatic re-assignment failed after multiple attempts.",
            "code": "duplicate_sku",
            "conflict": conflict_summary,
        }

    @staticmethod
    def _normalize_image_url(url: Optional[str]) -> Optional[str]:
        if not url:
            return url
        if "f_auto,t_supersize" in url:
            return url

        transformed = url
        if "f_auto,t_large" in transformed:
            transformed = transformed.replace("/a_0/f_auto,t_large/", "/")
            transformed = transformed.replace("f_auto,t_large/", "").replace("f_auto,t_large", "")
        if "/a_0/" in transformed:
            transformed = transformed.replace("/a_0/", "/")
        if "t_card-square" in transformed:
            transformed = transformed.replace("t_card-square/", "").replace("t_card-square", "")

        if "/image/upload/" in transformed:
            prefix, remainder = transformed.split("/image/upload/", 1)
            if remainder.startswith("s--"):
                marker, _, rest = remainder.partition("/")
                transformed = f"{prefix}/image/upload/{marker}/{rest}"
            else:
                transformed = f"{prefix}/image/upload/{remainder}"

        return transformed

    @staticmethod
    def _origin_country_code(country: Optional[Any]) -> Optional[str]:
        """Return the ISO alpha-2 country code expected by Reverb.

        Note: Reverb only accepts valid ISO country codes, not "OTHER".
        """

        if country is None:
            return None

        enum_value: Optional[ManufacturingCountry] = None

        if isinstance(country, ManufacturingCountry):
            enum_value = country
        else:
            raw = str(country or "").strip()
            if not raw:
                return None
            if raw.startswith("ManufacturingCountry."):
                raw = raw.split(".", 1)[1]
            try:
                enum_value = ManufacturingCountry(raw)
            except ValueError:
                try:
                    enum_value = ManufacturingCountry[raw.upper()]
                except KeyError:
                    normalized = raw.upper()
                    return normalized if len(normalized) == 2 else None

        # Reverb doesn't accept "OTHER" - only valid ISO country codes
        if enum_value and enum_value.value == "OTHER":
            return None

        return enum_value.value if enum_value else None

    @staticmethod
    def _handedness_value(handedness: Optional[Any]) -> Optional[str]:
        """Map our Handedness enum (or string) to Reverb's expected field."""

        if handedness is None:
            return None

        enum_value: Optional[Handedness] = None

        if isinstance(handedness, Handedness):
            enum_value = handedness
        else:
            raw = str(handedness or "").strip().upper()
            if not raw:
                return None
            raw = raw.replace("-", "_")
            if raw.startswith("HANDEDNESS."):
                raw = raw.split(".", 1)[1]
            try:
                enum_value = Handedness[raw]
            except KeyError:
                try:
                    enum_value = Handedness(raw)
                except ValueError:
                    enum_value = None

        if not enum_value or enum_value == Handedness.UNSPECIFIED:
            return None

        mapping = {
            Handedness.LEFT: "left-handed",
            Handedness.RIGHT: "right-handed",
            Handedness.AMBIDEXTROUS: "ambidextrous",
        }
        return mapping.get(enum_value)

    @staticmethod
    def _handedness_from_reverb(value: Optional[Any]) -> Optional[Handedness]:
        if value is None:
            return None
        slug = str(value).strip().lower()
        mapping = {
            "left": Handedness.LEFT,
            "left-handed": Handedness.LEFT,
            "right": Handedness.RIGHT,
            "right-handed": Handedness.RIGHT,
            "ambidextrous": Handedness.AMBIDEXTROUS,
            "ambidextrous-handed": Handedness.AMBIDEXTROUS,
        }
        return mapping.get(slug)

    @staticmethod
    def _manufacturing_country_from_code(code: Optional[str]) -> Optional[ManufacturingCountry]:
        if not code:
            return None
        try:
            return ManufacturingCountry(code.upper())
        except ValueError:
            return None

    async def _resolve_reverb_category_uuid(self, category_value: Optional[str]) -> Optional[str]:
        if not category_value:
            return None
        normalized = category_value.strip().lower()
        if not normalized:
            return None

        stmt = (
            select(ReverbCategory.uuid)
            .where(func.lower(ReverbCategory.full_path) == normalized)
            .limit(1)
        )
        result = await self.db.execute(stmt)
        uuid_value = result.scalar_one_or_none()
        if uuid_value:
            return uuid_value

        stmt = (
            select(ReverbCategory.uuid)
            .where(func.lower(ReverbCategory.name) == normalized)
            .limit(1)
        )
        result = await self.db.execute(stmt)
        uuid_value = result.scalar_one_or_none()
        if uuid_value:
            return uuid_value

        logger.warning("Unable to resolve Reverb category UUID for '%s'", category_value)
        return None

    @classmethod
    def apply_metadata_from_reverb(cls, product: Product, listing: Dict[str, Any]) -> None:
        serial_value = (listing.get("serial_number") or "").strip()
        if serial_value:
            product.serial_number = serial_value

        handedness_value = cls._handedness_from_reverb(listing.get("handedness"))
        if handedness_value:
            product.handedness = handedness_value

        origin_code = listing.get("origin_country_code") or (
            (listing.get("shipping", {}) or {}).get("origin_country_code")
        )
        country_enum = cls._manufacturing_country_from_code(origin_code)
        if country_enum:
            product.manufacturing_country = country_enum

        handmade_flag = listing.get("handmade")
        if handmade_flag is not None:
            extra = dict(product.extra_attributes or {})
            extra["handmade"] = bool(handmade_flag)
            product.extra_attributes = extra

    @staticmethod
    def _handmade_flag(product: Product) -> bool:
        extra = getattr(product, "extra_attributes", None) or {}
        return bool(extra.get("handmade"))

    @classmethod
    def _extract_image_urls(cls, listing_data: Dict[str, Any]) -> List[str]:
        urls: List[str] = []

        for photo in listing_data.get("photos") or []:
            link = (photo.get("_links") or {}).get("full", {}).get("href")
            link = cls._normalize_image_url(link)
            if link and link not in urls:
                urls.append(link)

        if not urls:
            for photo in listing_data.get("cloudinary_photos") or []:
                link = photo.get("preview_url")
                if not link and photo.get("path"):
                    link = f"https://rvb-img.reverb.com/image/upload/{photo['path']}"
                link = cls._normalize_image_url(link)
                if link and link not in urls:
                    urls.append(link)

        return urls

    async def refresh_product_images_from_listing(
        self,
        reverb_id: str,
        *,
        expected_count: Optional[int] = None,
        retry_delays: Optional[List[float]] = None,
    ) -> bool:
        """Refresh local product images using the canonical Reverb gallery.

        Args:
            reverb_id: The Reverb listing identifier to poll.
            expected_count: Optional number of images we hope to see; polling stops early
                once Reverb returns at least this many URLs.
            retry_delays: Sequence of sleep durations (in seconds) between attempts. The
                number of polling attempts equals ``len(retry_delays) + 1``. When omitted
                we fall back to the legacy behaviour (three attempts ~1.5s apart).

        Returns:
            ``True`` when at least one image was retrieved and persisted locally, ``False``
            otherwise.
        """

        delays = retry_delays or [2.0, 2.0, 2.0, 5.0, 5.0, 10.0, 10.0]
        attempts = len(delays) + 1

        collected_urls: List[str] = []
        last_error: Optional[Exception] = None

        for attempt in range(attempts):
            try:
                details = await self.client.get_listing_details(reverb_id)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "Attempt %s/%s: failed to fetch Reverb listing %s for image refresh: %s",
                    attempt + 1,
                    attempts,
                    reverb_id,
                    exc,
                )
            else:
                listing_data = details.get("listing", details) or {}
                photo_urls = self._extract_image_urls(listing_data)

                if photo_urls:
                    collected_urls = photo_urls
                    expected = expected_count or 0
                    if expected and len(photo_urls) < expected and attempt < attempts - 1:
                        logger.info(
                            "Attempt %s/%s: Reverb listing %s returned %s/%s images; continuing to poll",
                            attempt + 1,
                            attempts,
                            reverb_id,
                            len(photo_urls),
                            expected,
                        )
                    else:
                        break
                else:
                    logger.info(
                        "Attempt %s/%s: Reverb listing %s returned no photos yet",
                        attempt + 1,
                        attempts,
                        reverb_id,
                    )

            if attempt < len(delays):
                await asyncio.sleep(delays[attempt])

        if not collected_urls:
            if last_error:
                logger.warning(
                    "Giving up refreshing images for Reverb listing %s after %s attempts: %s",
                    reverb_id,
                    attempts,
                    last_error,
                )
            else:
                logger.warning(
                    "Reverb listing %s did not return any image URLs after %s attempts",
                    reverb_id,
                    attempts,
                )
            return False

        stmt = (
            select(PlatformCommon)
            .options(selectinload(PlatformCommon.product))
            .where(
                PlatformCommon.platform_name == "reverb",
                PlatformCommon.external_id == str(reverb_id),
            )
        )
        result = await self.db.execute(stmt)
        platform_common = result.scalars().first()

        if not platform_common or not platform_common.product_id:
            logger.warning("No platform_common entry found for Reverb listing %s", reverb_id)
            return False

        product = platform_common.product or await self.db.get(Product, platform_common.product_id)
        if not product:
            logger.warning(
                "PlatformCommon %s references missing product %s while refreshing images",
                platform_common.id,
                platform_common.product_id,
            )
            return False

        product.primary_image = collected_urls[0]
        product.additional_images = collected_urls[1:]
        await self.db.flush()
        logger.info(
            "Refreshed product %s images from Reverb listing %s (total %s)",
            product.id,
            reverb_id,
            len(collected_urls),
        )
        if expected_count and len(collected_urls) < expected_count:
            logger.info(
                "Reverb listing %s provided %s images but %s were expected; will retain available set",
                reverb_id,
                len(collected_urls),
                expected_count,
            )
        return True

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

    async def import_orders(self) -> Dict[str, int]:
        """
        Fetch sold orders from Reverb and upsert into reverb_orders table.

        Returns a summary dict with counts.
        """
        summary = {"fetched": 0, "inserted": 0, "updated": 0, "errors": 0}

        try:
            orders = await self.client.get_all_listings_detailed(max_concurrent=10, state="sold")
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch Reverb orders: %s", exc, exc_info=True)
            summary["errors"] += 1
            return summary

        summary["fetched"] = len(orders or [])

        for order in orders or []:
            try:
                order_uuid = str(order.get("id") or order.get("order_number") or "").strip()
                if not order_uuid:
                    summary["errors"] += 1
                    continue

                listing = order.get("listing_info") or order.get("listing") or {}
                shop = order.get("shop") or {}

                existing = (
                    await self.db.execute(
                        select(ReverbOrder).where(ReverbOrder.order_uuid == order_uuid)
                    )
                ).scalar_one_or_none()

                data = {
                    "order_uuid": order_uuid,
                    "order_number": order.get("order_number"),
                    "order_bundle_id": order.get("order_bundle_id"),
                    "reverb_listing_id": listing.get("id") if isinstance(listing, dict) else None,
                    "title": listing.get("title") if isinstance(listing, dict) else order.get("title"),
                    "shop_name": shop.get("name") if isinstance(shop, dict) else order.get("shop_name"),
                    "sku": order.get("sku") or (listing.get("sku") if isinstance(listing, dict) else None),
                    "status": order.get("status"),
                    "order_type": order.get("order_type"),
                    "order_source": order.get("order_source"),
                    "shipment_status": order.get("shipment_status"),
                    "shipping_method": order.get("shipping_method"),
                    "payment_method": order.get("payment_method"),
                    "local_pickup": order.get("local_pickup"),
                    "needs_feedback_for_buyer": order.get("needs_feedback_for_buyer"),
                    "needs_feedback_for_seller": order.get("needs_feedback_for_seller"),
                    "shipping_taxed": order.get("shipping_taxed"),
                    "tax_responsible_party": order.get("tax_responsible_party"),
                    "tax_rate": order.get("tax_rate"),
                    "quantity": order.get("quantity"),
                    "buyer_id": order.get("buyer_id"),
                    "buyer_name": order.get("buyer_name"),
                    "buyer_first_name": order.get("buyer_first_name"),
                    "buyer_last_name": order.get("buyer_last_name"),
                    "buyer_email": order.get("buyer_email"),
                    "shipping_name": order.get("shipping_name"),
                    "shipping_phone": order.get("shipping_phone"),
                    "shipping_city": order.get("shipping_city"),
                    "shipping_region": order.get("shipping_region"),
                    "shipping_postal_code": order.get("shipping_postal_code"),
                    "shipping_country_code": order.get("shipping_country_code"),
                    "created_at": order.get("created_at"),
                    "paid_at": order.get("paid_at"),
                    "updated_at": order.get("updated_at"),
                    "amount_product": order.get("amount_product"),
                    "amount_product_currency": order.get("amount_product_currency"),
                    "amount_product_subtotal": order.get("amount_product_subtotal"),
                    "amount_product_subtotal_currency": order.get("amount_product_subtotal_currency"),
                    "shipping_amount": order.get("shipping_amount"),
                    "shipping_currency": order.get("shipping_currency"),
                    "tax_amount": order.get("tax_amount"),
                    "tax_currency": order.get("tax_currency"),
                    "total_amount": order.get("total_amount"),
                    "total_currency": order.get("total_currency"),
                    "direct_checkout_fee_amount": order.get("direct_checkout_fee_amount"),
                    "direct_checkout_fee_currency": order.get("direct_checkout_fee_currency"),
                    "direct_checkout_payout_amount": order.get("direct_checkout_payout_amount"),
                    "direct_checkout_payout_currency": order.get("direct_checkout_payout_currency"),
                    "tax_on_fees_amount": order.get("tax_on_fees_amount"),
                    "tax_on_fees_currency": order.get("tax_on_fees_currency"),
                    "shipping_address": order.get("shipping_address"),
                    "order_notes": order.get("order_notes"),
                    "photos": order.get("photos"),
                    "links": order.get("links"),
                    "presentment_amounts": order.get("presentment_amounts"),
                    "raw_payload": order,
                }

                if existing:
                    for key, value in data.items():
                        setattr(existing, key, value)
                    summary["updated"] += 1
                else:
                    self.db.add(ReverbOrder(**data))
                    summary["inserted"] += 1

            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to process Reverb order: %s", exc, exc_info=True)
                summary["errors"] += 1

        await self.db.flush()
        return summary
            
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
        sku_adjustment: Optional[Dict[str, Any]] = None
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

            sku_ok, sku_context = await self._ensure_reverb_sku_available(product)
            if not sku_ok:
                return sku_context
            if sku_context:
                sku_adjustment = sku_context

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
                mapping = await self.condition_mapping_service.get_mapping(
                    PlatformName.REVERB,
                    product.condition,
                )
                if mapping:
                    condition_uuid = mapping.platform_condition_id
                else:
                    logger.warning(
                        "No Reverb condition mapping found for %s (%s)",
                        product.sku,
                        product.condition,
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
                "origin_country_code": self._origin_country_code(getattr(product, "manufacturing_country", None)),
                "publish": publish,
                "photos": valid_photos,
            }

            handedness_value = self._handedness_value(getattr(product, "handedness", None))
            if handedness_value:
                listing_payload["handedness"] = handedness_value

            # Add number_of_strings from extra_attributes
            extra_attrs = getattr(product, "extra_attributes", None) or {}
            number_of_strings = extra_attrs.get("number_of_strings")
            if number_of_strings:
                listing_payload["number_of_strings"] = number_of_strings

            listing_payload["handmade"] = self._handmade_flag(product)

            serial_value = (product.serial_number or "").strip() if product.serial_number else ""
            if serial_value:
                listing_payload["serial_number"] = serial_value

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

            # Fetch the finalised listing data (captures complete image set once Reverb finishes processing)
            if reverb_id:
                try:
                    detailed_response = await self.client.get_listing_details(reverb_id)
                    detailed_listing = detailed_response.get("listing", detailed_response)
                    if detailed_listing:
                        listing_data = detailed_listing
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Unable to fetch detailed Reverb listing data for %s: %s",
                        reverb_id,
                        exc,
                    )

            # Update product media with the CDN URLs returned from Reverb if available
            photo_urls: List[str] = []
            for photo in listing_data.get("photos") or []:
                link = (
                    (photo.get("_links") or {})
                    .get("full", {})
                    .get("href")
                )
                if link and link not in photo_urls:
                    photo_urls.append(link)

            if not photo_urls:
                # Fall back to Cloudinary entries if the main photo array is still sparse
                for photo in listing_data.get("cloudinary_photos") or []:
                    link = photo.get("preview_url")
                    if not link and photo.get("path"):
                        link = f"https://rvb-img.reverb.com/image/upload/{photo['path']}"
                    if link and link not in photo_urls:
                        photo_urls.append(link)

            if photo_urls:
                current_additional = list(product.additional_images or [])
                existing_count = int(bool(product.primary_image)) + len(current_additional)
                if existing_count == 0:
                    product.primary_image = photo_urls[0]
                    product.additional_images = photo_urls[1:]
                    logger.info(
                        "Populated product %s media from Reverb listing %s (previously empty)",
                        product.sku,
                        reverb_id,
                    )
                    await self.db.flush()

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
                "sku_adjustment": sku_adjustment,
            }

        except ReverbAPIError as api_error:
            await self.db.rollback()
            error_text = str(api_error)
            logger.error(
                "Reverb API error while creating listing for product %s: %s",
                product_id,
                error_text,
            )
            error_payload = {"status": "error", "error": error_text}
            lowered = error_text.lower()
            if "sku" in lowered and "already exists" in lowered:
                error_payload["code"] = "duplicate_sku"
            return error_payload
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
            api_listing_data = listing_data or await self._prepare_listing_data(listing, product)
            
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
        if "manufacturing_country" in changed_fields:
            country_code = self._origin_country_code(getattr(product, "manufacturing_country", None))
            payload["origin_country_code"] = country_code if country_code is not None else None
        if "handedness" in changed_fields:
            payload["handedness"] = self._handedness_value(getattr(product, "handedness", None))
        if "serial_number" in changed_fields:
            serial_value = (product.serial_number or "").strip() if product.serial_number else ""
            payload["serial_number"] = serial_value or None
        if "extra_attributes" in changed_fields:
            payload["handmade"] = self._handmade_flag(product)
            # Also update number_of_strings when extra_attributes changes
            extra_attrs = getattr(product, "extra_attributes", None) or {}
            number_of_strings = extra_attrs.get("number_of_strings")
            if number_of_strings:
                payload["number_of_strings"] = number_of_strings
        if "category" in changed_fields:
            category_uuid = await self._resolve_reverb_category_uuid(getattr(product, "category", None))
            if category_uuid:
                payload["categories"] = [{"uuid": category_uuid}]
            else:
                logger.warning(
                    "Category '%s' could not be mapped to a Reverb UUID for product %s",
                    getattr(product, "category", None),
                    product.sku,
                )

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
            if "categories" in payload and payload["categories"]:
                new_category_uuid = payload["categories"][0].get("uuid")
                if new_category_uuid:
                    listing.reverb_category_uuid = new_category_uuid
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
            listing.reverb_state = "live"
            
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
    
    async def _prepare_listing_data(self, listing: ReverbListing, product: Product) -> Dict[str, Any]:
        """
        Prepare listing data for Reverb API
        
        Args:
            listing: ReverbListing record
            product: Associated Product record
            
        Returns:
            Dict: Listing data formatted for Reverb API
        """
        condition_uuid = None
        if product.condition:
            mapping = await self.condition_mapping_service.get_mapping(
                PlatformName.REVERB,
                product.condition,
            )
            if mapping:
                condition_uuid = mapping.platform_condition_id

        if not condition_uuid:
            logger.warning(
                "Falling back to Excellent condition while preparing Reverb payload for product %s",
                product.id,
            )
            condition_uuid = "df268ad1-c462-4ba6-b6db-e007e23922ea"

        data = {
            "title": product.title or f"{product.brand} {product.model}",
            "description": product.description or "",
            "make": product.brand,
            "model": product.model,
            # Format condition as object with UUID
            "condition": {
                "uuid": condition_uuid
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

        origin_code = self._origin_country_code(getattr(product, "manufacturing_country", None))
        if origin_code:
            data["origin_country_code"] = origin_code

        handedness_value = self._handedness_value(getattr(product, "handedness", None))
        if handedness_value:
            data["handedness"] = handedness_value

        # Add number_of_strings from extra_attributes
        extra_attrs = getattr(product, "extra_attributes", None) or {}
        number_of_strings = extra_attrs.get("number_of_strings")
        if number_of_strings:
            data["number_of_strings"] = number_of_strings

        serial_value = (product.serial_number or "").strip() if product.serial_number else ""
        if serial_value:
            data["serial_number"] = serial_value

        data["handmade"] = self._handmade_flag(product)
        
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
            "link": normalized_url,
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
              AND pc.status != 'refreshed'
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

                match = await suggest_product_match(
                    self.db,
                    'reverb',
                    {
                        'title': item.get('title'),
                        'price': item.get('price'),
                        'state': item.get('state'),
                        'sku': item.get('sku'),
                        'brand': item.get('brand'),
                        'model': item.get('model'),
                        'raw_data': item.get('_raw'),
                    },
                )

                if match:
                    event_data['change_data']['match_candidate'] = {
                        'product_id': match.product.id,
                        'sku': match.product.sku,
                        'title': match.product.title,
                        'brand': match.product.brand,
                        'model': match.product.model,
                        'status': match.product.status.value if getattr(match.product.status, 'value', None) else str(match.product.status) if match.product.status else None,
                        'base_price': match.product.base_price,
                        'primary_image': match.product.primary_image,
                        'confidence': match.confidence,
                        'reason': match.reason,
                        'existing_platforms': match.existing_platforms,
                    }
                    event_data['change_data']['suggested_action'] = 'create'

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
        product = await self.db.get(Product, product_id)
        if not product:
            logger.warning("Product %s not found while applying Reverb update", product_id)
            return

        is_sold = listing.get("state", {}).get("slug") == "sold"
        new_status = ProductStatus.SOLD if is_sold else ProductStatus.ACTIVE

        price_block = listing.get("price") or {}
        try:
            price_amount = float(price_block.get("amount")) if price_block.get("amount") is not None else None
        except (TypeError, ValueError):
            price_amount = None

        if price_amount is not None:
            product.base_price = price_amount
        if listing.get("description"):
            product.description = listing.get("description")
        product.status = new_status

        self.apply_metadata_from_reverb(product, listing)
        await self.db.flush()

        platform_stmt = select(PlatformCommon).where(
            PlatformCommon.product_id == product_id,
            PlatformCommon.platform_name == "reverb",
        )
        platform_result = await self.db.execute(platform_stmt)
        platform_link = platform_result.scalar_one_or_none()
        if platform_link:
            platform_link.status = ListingStatus.SOLD.value if is_sold else ListingStatus.ACTIVE.value
            platform_link.sync_status = SyncStatus.SYNCED.value
            platform_link.last_sync = datetime.utcnow()
            platform_link.updated_at = datetime.utcnow()
            self.db.add(platform_link)

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

                    # Only log if status actually changed (avoid false positives from API lag/pagination)
                    if new_status == 'live':
                        logger.info(f"Item {reverb_id} still live on API - skipping false positive status_change")
                        continue

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
        stats = {"api_live_count": 0, "db_live_count": 0, "db_known_count": 0, "events_logged": 0, "errors": 0}
        logger.info(f"=== ReverbService: STARTING SYNC (run_id: {sync_run_id}) ===")

        try:
            # 1. Fetch all LIVE listings from the Reverb API.
            live_listings_api = await self._get_all_listings_from_api(state='live')
            api_live_ids = {str(item['id']) for item in live_listings_api}
            stats['api_live_count'] = len(api_live_ids)
            logger.info(f"Found {stats['api_live_count']} live listings on Reverb API.")

            # 2. Fetch all Reverb listings we already know about in our local DB (any status).
            local_reverb_items = await self._fetch_local_live_reverb_ids()
            local_known_ids = set(local_reverb_items.keys())

            # Determine which of the known listings we currently consider "live" locally.
            local_live_ids = {
                reverb_id
                for reverb_id, data in local_reverb_items.items()
                if str(data.get('reverb_state', '')).lower() == 'live'
                or str(data.get('platform_status', '')).lower() in {'active', 'live'}
            }

            stats['db_known_count'] = len(local_known_ids)
            stats['db_live_count'] = len(local_live_ids)
            logger.info(
                "Found %s Reverb listings in local DB (%s marked live locally).",
                stats['db_known_count'],
                stats['db_live_count'],
            )

            # 3. Compare the sets of IDs to find differences.
            new_rogue_ids = api_live_ids - local_known_ids
            missing_from_api_ids = {reverb_id for reverb_id in local_live_ids if reverb_id not in api_live_ids}

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

            # 5. For listings that exist both locally and on the API, detect status mismatches
            #    (e.g. local draft -> API live) and log them as status change events.
            for reverb_id in api_live_ids & local_known_ids:
                db_item = local_reverb_items.get(reverb_id)
                if not db_item:
                    continue

                local_status = str(
                    db_item.get('reverb_state')
                    or db_item.get('platform_status')
                    or ''
                ).lower()

                if local_status in {'live', 'active'}:
                    continue

                events_to_log.append(
                    self._prepare_sync_event(
                        sync_run_id,
                        'status_change',
                        external_id=reverb_id,
                        product_id=db_item.get('product_id'),
                        platform_common_id=db_item.get('platform_common_id'),
                        change_data={
                            'old': local_status or 'unknown',
                            'new': 'live',
                            'reverb_id': reverb_id,
                        },
                    )
                )

            # 5. For items no longer 'live' on the API, fetch their details to find out WHY.
            for reverb_id in missing_from_api_ids:
                db_item = local_reverb_items[reverb_id]
                try:
                    # This second API call is crucial to get the new status (e.g., 'sold', 'ended').
                    details = await self.client.get_listing_details(reverb_id)
                    new_status = details.get('state', {}).get('slug', 'unknown')

                    # Only log if status actually changed (avoid false positives from API lag/pagination)
                    if new_status == 'live':
                        logger.info(f"Item {reverb_id} still live on API - skipping false positive status_change")
                        continue

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
        """Update local tables so an ended listing is reflected everywhere."""
        product_id = None
        platform_row = None

        # Always start by updating platform_common using the external_id.
        platform_update = text("""
            UPDATE platform_common
            SET status = 'ended',
                sync_status = 'SYNCED',
                last_sync = timezone('utc', now()),
                updated_at = timezone('utc', now())
            WHERE platform_name = 'reverb'
              AND external_id = :external_id
            RETURNING id, product_id
        """)
        platform_result = await self.db.execute(platform_update, {"external_id": external_id})
        platform_row = platform_result.fetchone()

        if not platform_row:
            logger.warning(
                "Attempted to mark Reverb listing %s as ended locally, but no platform_common row was found.",
                external_id
            )
        else:
            product_id = platform_row.product_id

        # Update the Reverb listing using platform_id if we have it, otherwise fall back to external_id.
        listing_params = {"external_id": external_id}
        listing_update_sql = """
            UPDATE reverb_listings
            SET reverb_state = 'ended',
                inventory_quantity = 0,
                has_inventory = FALSE,
                updated_at = timezone('utc', now())
            WHERE reverb_listing_id = :external_id
        """
        if platform_row:
            listing_update_sql += " OR platform_id = :platform_id"
            listing_params["platform_id"] = platform_row.id

        await self.db.execute(text(listing_update_sql), listing_params)

        if product_id:
            await self.db.execute(
                text("""
                    UPDATE products
                    SET status = 'SOLD',
                        is_sold = TRUE,
                        updated_at = timezone('utc', now())
                    WHERE id = :product_id
                """),
                {"product_id": product_id}
            )

    async def _fetch_local_live_reverb_ids(self) -> Dict[str, Dict]:
        """Fetch all known Reverb listings from the local DB, regardless of status."""
        logger.info("Fetching Reverb listings from local DB (all statuses).")
        query = text("""
            SELECT
                pc.external_id,
                pc.product_id,
                pc.id AS platform_common_id,
                pc.status AS platform_status,
                rl.reverb_state
            FROM platform_common pc
            LEFT JOIN reverb_listings rl ON pc.id = rl.platform_id
            WHERE pc.platform_name = 'reverb' AND pc.external_id IS NOT NULL
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
