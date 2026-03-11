"""
Inventory inspection routes for testing payload generation.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any
import json

from app.database import get_session as get_db
from app.models.shipping import ShippingProfile
from sqlalchemy import select

router = APIRouter(prefix="/inventory", tags=["inventory-inspection"])

def generate_reverb_payload(form_data: Dict[str, Any], shipping_profile: ShippingProfile) -> Dict:
    """Generate Reverb API payload from form data."""
    payload = {
        "title": form_data.get("title", ""),
        "sku": form_data.get("sku", ""),
        "description": form_data.get("description", ""),
        "condition": {
            "uuid": form_data.get("reverb_condition", "")
        },
        "price": {
            "amount": form_data.get("base_price", ""),
            "currency": "GBP"
        },
        "shipping_profile_id": shipping_profile.reverb_profile_id if shipping_profile else None,
        "categories": [{
            "uuid": form_data.get("reverb_category", "")
        }],
        "photos": [],
        "has_inventory": True,
        "inventory": form_data.get("quantity", 1),
        "publish": form_data.get("reverb_publish", False),
        "videos": [form_data.get("video_url")] if form_data.get("video_url") else []
    }
    
    # Add images
    if form_data.get("primary_image_url"):
        payload["photos"].append(form_data["primary_image_url"])
    if form_data.get("additional_images_urls"):
        for img in form_data.get("additional_images_urls", []):
            if img:
                payload["photos"].append(img)
    
    return payload

def generate_ebay_payload(form_data: Dict[str, Any], shipping_profile: ShippingProfile) -> Dict:
    """Generate eBay API payload from form data."""
    payload = {
        "sku": form_data.get("sku", ""),
        "product": {
            "title": form_data.get("title", ""),
            "description": form_data.get("description", ""),
            "brand": form_data.get("brand", ""),
            "mpn": form_data.get("model", ""),
            "imageUrls": []
        },
        "condition": form_data.get("ebay_condition", "USED"),
        "conditionDescription": form_data.get("condition_description", ""),
        "availability": {
            "shipToLocationAvailability": {
                "quantity": form_data.get("quantity", 1)
            }
        },
        "listingPolicies": {
            "fulfillmentPolicyId": shipping_profile.ebay_profile_id if shipping_profile and shipping_profile.ebay_profile_id else None,
            "paymentPolicyId": form_data.get("ebay_payment_policy", ""),
            "returnPolicyId": form_data.get("ebay_return_policy", "")
        },
        "pricingSummary": {
            "price": {
                "value": str(form_data.get("base_price", "")),
                "currency": "GBP"
            }
        },
        "categoryId": form_data.get("ebay_category", ""),
        "listingDuration": form_data.get("ebay_duration", "GTC")
    }
    
    # Add images
    if form_data.get("primary_image_url"):
        payload["product"]["imageUrls"].append(form_data["primary_image_url"])
    if form_data.get("additional_images_urls"):
        for img in form_data.get("additional_images_urls", []):
            if img:
                payload["product"]["imageUrls"].append(img)
    
    return payload

def generate_vr_payload(form_data: Dict[str, Any], shipping_profile: ShippingProfile) -> Dict:
    """Generate Vintage & Rare payload from form data."""
    payload = {
        "ProductTitle": form_data.get("title", ""),
        "ProductSKU": form_data.get("sku", ""),
        "ProductDescription": form_data.get("description", ""),
        "ProductPrice": form_data.get("base_price", ""),
        "ProductCategoryID": form_data.get("vr_category", ""),
        "ProductBrand": form_data.get("vr_brand_fallback") == "true" and "Justin" or form_data.get("brand", ""),
        "ProductModel": form_data.get("model", ""),
        "ProductYear": form_data.get("year", ""),
        "ProductCondition": form_data.get("condition", ""),
        "ProductFinish": form_data.get("finish", ""),
        "ProductImages": [],
        "ShippingAvailableForShipment": form_data.get("available_for_shipment", True),
        "ShippingAvailableForLocalPickup": form_data.get("local_pickup", False),
        "FeaturedProduct": form_data.get("vr_featured", False)
    }
    
    # Add shipping rates from profile
    if shipping_profile and shipping_profile.rates:
        payload["shipping_uk_fee"] = shipping_profile.rates.get("uk", 0)
        payload["shipping_europe_fee"] = shipping_profile.rates.get("europe", 0)
        payload["shipping_usa_fee"] = shipping_profile.rates.get("usa", 0)
        payload["shipping_world_fee"] = shipping_profile.rates.get("row", 0)
    
    # Add images
    if form_data.get("primary_image_url"):
        payload["ProductImages"].append(form_data["primary_image_url"])
    if form_data.get("additional_images_urls"):
        for img in form_data.get("additional_images_urls", []):
            if img:
                payload["ProductImages"].append(img)
    
    return payload

def generate_shopify_payload(form_data: Dict[str, Any], shipping_profile: ShippingProfile) -> Dict:
    """Generate Shopify API payload from form data."""

    description_html = ensure_description_has_standard_footer(form_data.get("description", ""))
    keywords = generate_shopify_keywords(
        brand=form_data.get("brand"),
        model=form_data.get("model"),
        finish=form_data.get("finish"),
        year=form_data.get("year"),
        decade=form_data.get("decade"),
        category=form_data.get("shopify_category"),
        condition=form_data.get("condition"),
        description_html=description_html,
    )

    fallback_title = (form_data.get("title") or f"{form_data.get('brand', '')} {form_data.get('model', '')}").strip()
    short_description = generate_shopify_short_description(description_html, fallback=fallback_title)

    payload = {
        "product": {
            "title": form_data.get("title", ""),
            "body_html": description_html,
            "vendor": form_data.get("brand", ""),
            "product_type": form_data.get("shopify_category", ""),
            "tags": keywords,
            "status": "draft" if not form_data.get("shopify_publish") else "active",
            "variants": [{
                "price": str(form_data.get("base_price", "")),
                "sku": form_data.get("sku", ""),
                "inventory_quantity": form_data.get("quantity", 1),
                "inventory_management": "shopify",
                "weight": shipping_profile.weight if shipping_profile else None,
                "weight_unit": "kg",
                "requires_shipping": True
            }],
            "images": [],
            "metafields": [
                {
                    "namespace": "custom",
                    "key": "year",
                    "value": str(form_data.get("year", "")),
                    "type": "single_line_text_field"
                },
                {
                    "namespace": "custom", 
                    "key": "condition",
                    "value": form_data.get("condition", ""),
                    "type": "single_line_text_field"
                },
                {
                    "namespace": "custom",
                    "key": "model",
                    "value": form_data.get("model", ""),
                    "type": "single_line_text_field"
                },
                {
                    "namespace": "custom",
                    "key": "short_description",
                    "value": short_description,
                    "type": "multi_line_text_field",
                },
            ],
        }
    }

    seo_block = {}
    if fallback_title:
        seo_block["title"] = fallback_title[:255]
    if short_description:
        seo_block["description"] = short_description
    if seo_block:
        payload["product"]["seo"] = seo_block

    # Add images
    if form_data.get("primary_image_url"):
        payload["product"]["images"].append({"src": form_data["primary_image_url"]})
    if form_data.get("additional_images_urls"):
        for img in form_data.get("additional_images_urls", []):
            if img:
                payload["product"]["images"].append({"src": img})

    return payload

@router.post("/inspect-payload")
async def inspect_payload(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Generate and return inspection payloads for all platforms.
    This does NOT create any products - it just shows what would be sent.
    """
    form_data = await request.form()
    form_dict = dict(form_data)
    
    # Get shipping profile if selected
    shipping_profile = None
    if form_dict.get("shipping_profile"):
        result = await db.execute(
            select(ShippingProfile).where(ShippingProfile.id == int(form_dict["shipping_profile"]))
        )
        shipping_profile = result.scalar_one_or_none()
    
    # Parse additional images if they exist
    if form_dict.get("additional_images_urls"):
        # Handle if it's a string with comma-separated URLs
        if isinstance(form_dict["additional_images_urls"], str):
            form_dict["additional_images_urls"] = [
                url.strip() for url in form_dict["additional_images_urls"].split(",") if url.strip()
            ]
    
    # Generate payloads for each platform
    payloads = {
        "reverb": generate_reverb_payload(form_dict, shipping_profile),
        "ebay": generate_ebay_payload(form_dict, shipping_profile),
        "vr": generate_vr_payload(form_dict, shipping_profile),
        "shopify": generate_shopify_payload(form_dict, shipping_profile)
    }
    
    # Add metadata
    response = {
        "status": "inspection",
        "message": "Payload inspection - NO products created",
        "form_data": form_dict,
        "shipping_profile": {
            "id": shipping_profile.id,
            "name": shipping_profile.name,
            "reverb_id": shipping_profile.reverb_profile_id,
            "ebay_id": shipping_profile.ebay_profile_id,
            "rates": shipping_profile.rates
        } if shipping_profile else None,
        "payloads": payloads
    }
    
    return response
