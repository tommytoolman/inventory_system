#!/usr/bin/env python3
"""Generate platform listing payloads without calling external APIs."""

import argparse
import asyncio
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.database import async_session
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.services.ebay_service import EbayService
from app.services.reverb_service import ReverbService
from app.services.shopify_service import ShopifyService
from app.services.vr_service import VRService


@contextmanager
def patched(module, attr: str, replacement):
    original = getattr(module, attr)
    setattr(module, attr, replacement)
    try:
        yield original
    finally:
        setattr(module, attr, original)


class DummyReverbClient:
    def __init__(self, *args, **kwargs):
        self.payloads: List[Dict[str, Any]] = []

    async def create_listing(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.payloads.append(payload)
        return {
            "listing": {
                "id": "DUMMY-REVERB-ID",
                "state": {"slug": "live"},
                "_links": {"web": {"href": "https://example.com/reverb/DUMMY-REVERB-ID"}},
            }
        }

    async def publish_listing(self, listing_id: str) -> Dict[str, Any]:
        return {"status": "ok"}

    async def get_listing(self, listing_id: str) -> Dict[str, Any]:
        return {
            "listing": {
                "id": listing_id,
                "state": {"slug": "live"},
                "_links": {"web": {"href": f"https://example.com/reverb/{listing_id}"}},
            }
        }

    async def get_listing_assets(self, listing_id: str) -> Dict[str, Any]:
        return {"listing": {"state": {"slug": "live"}}}


class DummyShopifyClient:
    def __init__(self, *args, **kwargs):
        self.created_product: Optional[Dict[str, Any]] = None
        self.variant_updates: List[Dict[str, Any]] = []
        self.images_payload: Optional[List[Dict[str, Any]]] = None
        self.category_payloads: List[Dict[str, Any]] = []

    def create_product(self, product_input: Dict[str, Any]) -> Dict[str, Any]:
        self.created_product = product_input
        return {
            "product": {
                "id": "gid://shopify/Product/1234567890",
                "legacyResourceId": "1234567890",
                "variants": {
                    "edges": [
                        {"node": {"id": "gid://shopify/ProductVariant/0987654321"}}
                    ]
                },
            }
        }

    def update_variant_rest(self, variant_gid: str, variant_update: Dict[str, Any]) -> None:
        self.variant_updates.append({"variant_gid": variant_gid, "payload": variant_update})

    def create_product_images(self, product_gid: str, media_input: Sequence[Dict[str, Any]]) -> None:
        self.images_payload = list(media_input)

    def set_product_category(self, product_gid: str, category_gid: str) -> bool:
        self.category_payloads.append({"product_gid": product_gid, "category_gid": category_gid})
        return True

    def get_online_store_publication_id(self) -> str:
        return "gid://shopify/Publication/ONLINE"

    def publish_product_to_sales_channel(self, product_gid: str, publication_gid: str) -> bool:
        return True

    def get_product_snapshot_by_id(
        self,
        product_gid: str,
        num_variants: int = 10,
        num_images: int = 20,
        num_metafields: int = 0,
    ) -> Dict[str, Any]:
        return {
            "id": product_gid,
            "variants": {"edges": []},
            "images": {"edges": []},
        }


class DummyVRClient:
    def __init__(self, *args, **kwargs):
        self.payloads: List[Dict[str, Any]] = []

    async def authenticate(self) -> bool:
        return True

    async def create_listing_selenium(
        self,
        product_data: Dict[str, Any],
        test_mode: bool = False,
        from_scratch: bool = False,
        db_session: Any = None,
    ) -> Dict[str, Any]:
        self.payloads.append(product_data)
        return {
            "status": "success",
            "vr_listing_id": "DUMMY-VR-ID",
            "payload": product_data,
        }


@dataclass
class CaptureResult:
    status: str
    payload: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)


async def load_product(product_id: int, session) -> Optional[Product]:
    stmt = (
        select(Product)
        .options(
            selectinload(Product.shipping_profile),
            selectinload(Product.platform_listings),
        )
        .where(Product.id == product_id)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


def extract_platform_data(product: Product, platform: str) -> Optional[Dict[str, Any]]:
    for link in getattr(product, "platform_listings", []) or []:
        if (link.platform_name or "").lower() == platform.lower():
            return link.platform_specific_data
    return None


async def capture_ebay(product_id: int, settings) -> CaptureResult:
    async with async_session() as session:
        product = await load_product(product_id, session)
        if not product:
            raise RuntimeError(f"Product {product_id} not found for eBay capture")

        service = EbayService(session, settings)

        shipping_profile_id = None
        if getattr(product, "shipping_profile", None):
            shipping_profile_id = product.shipping_profile.ebay_profile_id

        platform_data = extract_platform_data(product, "ebay") or {}
        payment_profile_id = platform_data.get("payment_policy")
        return_profile_id = platform_data.get("return_policy")

        result = await service.create_listing_from_product(
            product=product,
            reverb_api_data=extract_platform_data(product, "reverb"),
            use_shipping_profile=bool(shipping_profile_id),
            shipping_profile_id=shipping_profile_id,
            payment_profile_id=payment_profile_id,
            return_profile_id=return_profile_id,
            dry_run=True,
        )
        await session.rollback()

    return CaptureResult(status=result.get("status", "unknown"), payload=result.get("item_data"), extra=result)


async def capture_reverb(product_id: int, settings) -> CaptureResult:
    import app.services.reverb_service as reverb_module

    dummy_client = DummyReverbClient()

    async with async_session() as session:
        product = await load_product(product_id, session)
        if not product:
            raise RuntimeError(f"Product {product_id} not found for Reverb capture")

        with patched(reverb_module, "ReverbClient", lambda *args, **kwargs: dummy_client):
            service = ReverbService(session, settings)
            result = await service.create_listing_from_product(
                product_id=product.id,
                platform_options={"reverb": extract_platform_data(product, "reverb") or {}},
            )
        await session.rollback()

    payload = dummy_client.payloads[-1] if dummy_client.payloads else None
    return CaptureResult(status=result.get("status", "unknown"), payload=payload, extra=result)


async def capture_shopify(product_id: int, settings) -> CaptureResult:
    import app.services.shopify_service as shopify_module

    dummy_client = DummyShopifyClient()

    async with async_session() as session:
        product = await load_product(product_id, session)
        if not product:
            raise RuntimeError(f"Product {product_id} not found for Shopify capture")

        with patched(shopify_module, "ShopifyGraphQLClient", lambda *args, **kwargs: dummy_client):
            service = ShopifyService(session, settings)
            result = await service.create_listing_from_product(
                product=product,
                reverb_data=extract_platform_data(product, "reverb"),
                platform_options=extract_platform_data(product, "shopify"),
            )
        await session.rollback()

    payload = {
        "product_input": dummy_client.created_product,
        "variant_updates": dummy_client.variant_updates,
        "images": dummy_client.images_payload,
        "categories": dummy_client.category_payloads,
    }
    return CaptureResult(status=result.get("status", "unknown"), payload=payload, extra=result)


async def capture_vr(product_id: int, settings) -> CaptureResult:
    import app.services.vr_service as vr_module

    dummy_client = DummyVRClient()

    async with async_session() as session:
        product = await load_product(product_id, session)
        if not product:
            raise RuntimeError(f"Product {product_id} not found for VR capture")

        with patched(vr_module, "VintageAndRareClient", lambda *args, **kwargs: dummy_client):
            service = VRService(session)
            result = await service.create_listing_from_product(
                product=product,
                reverb_data=extract_platform_data(product, "reverb"),
                platform_options=extract_platform_data(product, "vr"),
            )
        await session.rollback()

    payload = dummy_client.payloads[-1] if dummy_client.payloads else None
    return CaptureResult(status=result.get("status", "unknown"), payload=payload, extra=result)


async def run(args: argparse.Namespace) -> Dict[str, Any]:
    settings = get_settings()
    async with async_session() as session:
        product = await load_product(args.product_id, session)
        if not product:
            raise RuntimeError(f"Product {args.product_id} not found")
        product_sku = product.sku

    captures: Dict[str, CaptureResult] = {}

    if "ebay" in args.platforms:
        captures["ebay"] = await capture_ebay(args.product_id, settings)
    if "reverb" in args.platforms:
        captures["reverb"] = await capture_reverb(args.product_id, settings)
    if "shopify" in args.platforms:
        captures["shopify"] = await capture_shopify(args.product_id, settings)
    if "vr" in args.platforms:
        captures["vr"] = await capture_vr(args.product_id, settings)

    return {
        "product_id": args.product_id,
        "sku": product_sku,
        "captures": {
            platform: {
                "status": result.status,
                "payload": result.payload,
                "details": result.extra,
            }
            for platform, result in captures.items()
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-id", type=int, required=True, help="Product ID to inspect")
    parser.add_argument(
        "--platforms",
        nargs="*",
        default=["reverb", "ebay", "shopify", "vr"],
        choices=["reverb", "ebay", "shopify", "vr"],
        help="Platforms to capture (default: all)",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = asyncio.run(run(args))
    if args.pretty:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
