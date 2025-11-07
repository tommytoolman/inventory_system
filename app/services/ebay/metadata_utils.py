# app/services/ebay/metadata_utils.py
"""
Shared helpers for working with detailed eBay listing metadata.

These utilities are used by both the metadata refresh service workflow and
any standalone scripts that need to flatten GetItem payloads.
"""

from typing import Dict, List


def extract_item_specifics(item_details: Dict) -> Dict[str, str]:
    """Extract item specifics as a flat dictionary."""
    specifics: Dict[str, str] = {}

    item_specifics = item_details.get("ItemSpecifics", {})
    if "NameValueList" not in item_specifics:
        return specifics

    name_value_lists = item_specifics["NameValueList"]
    if not isinstance(name_value_lists, list):
        name_value_lists = [name_value_lists]

    for nvl in name_value_lists:
        name = nvl.get("Name", "")
        value = nvl.get("Value", "")
        if not name or not value:
            continue

        if isinstance(value, list):
            specifics[name] = ", ".join(str(v) for v in value)
        else:
            specifics[name] = str(value)

    return specifics


def extract_specific_field(item_specifics: Dict[str, str], field_names: List[str]) -> str:
    """Extract a specific field from item specifics, trying multiple names."""
    for field_name in field_names:
        if field_name in item_specifics:
            return item_specifics[field_name]
    return ""


def extract_picture_urls(item_details: Dict) -> List[str]:
    """Extract picture URLs from a GetItem response."""
    picture_details = item_details.get("PictureDetails", {})
    picture_urls = picture_details.get("PictureURL", [])

    if isinstance(picture_urls, str):
        return [picture_urls]
    if isinstance(picture_urls, list):
        return picture_urls
    return []


def extract_shipping_cost(item_details: Dict) -> str:
    """Extract primary shipping cost as a string value."""
    shipping_details = item_details.get("ShippingDetails", {})
    service_options = shipping_details.get("ShippingServiceOptions", [])

    if not isinstance(service_options, list):
        service_options = [service_options]

    if not service_options:
        return "0.00"

    first_option = service_options[0]
    cost = first_option.get("ShippingServiceCost", {})
    if isinstance(cost, dict):
        return cost.get("#text", "0.00")
    return str(cost) if cost else "0.00"


def extract_free_shipping(item_details: Dict) -> bool:
    """Determine whether the listing offers free shipping."""
    try:
        return float(extract_shipping_cost(item_details)) == 0.0
    except (ValueError, TypeError):
        return False


def extract_buy_it_now_price(item_details: Dict) -> str:
    """Extract the Buy-It-Now price."""
    bin_price = item_details.get("BuyItNowPrice", {})
    if isinstance(bin_price, dict):
        return bin_price.get("#text", "")
    return str(bin_price) if bin_price else ""
