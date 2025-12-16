"""
Centralized platform pricing calculations.

Each platform has a configurable markup percentage over base price.
eBay prices are rounded to "sensible" endings: 49, 99, 499, 999.
"""

from typing import Optional

from app.core.config import get_settings


def round_to_sensible_price(target: float) -> int:
    """
    Round a price UP to the nearest sensible ending: 49, 99, 499, 999.

    Examples:
        658.9 -> 699
        1098.9 -> 1099
        540 -> 549
        4500 -> 4999
        10050 -> 10499
    """
    if target <= 0:
        return 0

    target = int(target)

    # Define sensible endings
    endings = [49, 99, 499, 999]
    candidates = []

    for ending in endings:
        if ending < 100:
            # For 49, 99 - repeat every 100
            base = (target // 100) * 100
            candidate = base + ending
            if candidate < target:
                candidate += 100
            candidates.append(candidate)
        else:
            # For 499, 999 - repeat every 1000
            base = (target // 1000) * 1000
            candidate = base + ending
            if candidate < target:
                candidate += 1000
            candidates.append(candidate)

    # Return smallest candidate >= target
    valid = [c for c in candidates if c >= target]
    return min(valid) if valid else max(candidates)


def calculate_platform_price(
    platform: str,
    base_price: float,
    markup_override: Optional[float] = None,
) -> float:
    """
    Calculate price for a platform using its configured markup.

    Args:
        platform: One of 'ebay', 'vr', 'reverb', 'shopify'
        base_price: The base price
        markup_override: Optional override for the markup percentage

    Returns:
        Calculated price (rounded for eBay, exact for others)
    """
    if not base_price or base_price <= 0:
        return 0.0

    settings = get_settings()

    # Get markup percentage
    if markup_override is not None:
        markup_percent = markup_override
    else:
        markup_map = {
            "ebay": settings.EBAY_PRICE_MARKUP_PERCENT,
            "vr": settings.VR_PRICE_MARKUP_PERCENT,
            "reverb": settings.REVERB_PRICE_MARKUP_PERCENT,
            "shopify": settings.SHOPIFY_PRICE_MARKUP_PERCENT,
        }
        markup_percent = markup_map.get(platform.lower(), 0.0)

    # Calculate target price
    target = base_price * (1 + markup_percent / 100)

    # eBay uses sensible rounding
    if platform.lower() == "ebay":
        return float(round_to_sensible_price(target))

    # Other platforms: round to 2 decimal places
    return round(target, 2)


def calculate_ebay_price(
    base_price: float,
    markup_percent: Optional[float] = None,
) -> int:
    """
    Calculate eBay price with sensible rounding.

    Args:
        base_price: The base price
        markup_percent: Override markup (default: from settings)

    Returns:
        Price rounded to nearest 49/99/499/999
    """
    return int(calculate_platform_price("ebay", base_price, markup_percent))


def calculate_vr_price(
    base_price: float,
    markup_percent: Optional[float] = None,
) -> float:
    """Calculate V&R price with markup."""
    return calculate_platform_price("vr", base_price, markup_percent)


def calculate_reverb_price(
    base_price: float,
    markup_percent: Optional[float] = None,
) -> float:
    """Calculate Reverb price with markup."""
    return calculate_platform_price("reverb", base_price, markup_percent)


def calculate_shopify_price(
    base_price: float,
    markup_percent: Optional[float] = None,
) -> float:
    """Calculate Shopify price (typically base price, 0% markup)."""
    return calculate_platform_price("shopify", base_price, markup_percent)
