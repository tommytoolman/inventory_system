"""Heuristics for matching external platform listings to local products."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.platform_common import PlatformCommon


@dataclass
class MatchSuggestion:
    product: Product
    confidence: float
    reason: str
    existing_platforms: List[str]


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip()


def _similarity(a: Optional[str], b: Optional[str]) -> float:
    a_norm = _normalize(a).lower()
    b_norm = _normalize(b).lower()
    if not a_norm or not b_norm:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def _extract_first(values: Iterable[Any]) -> Optional[str]:
    for value in values:
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            for inner in value:
                inner_norm = _normalize(str(inner))
                if inner_norm:
                    return inner_norm
        else:
            value_norm = _normalize(str(value))
            if value_norm:
                return value_norm
    return None


def _gather_skus(*payloads: Dict[str, Any]) -> List[str]:
    sku_keys = {
        "sku",
        "SKU",
        "Sku",
        "product_sku",
        "variant_sku",
        "seller_sku",
        "inventory_sku",
        "custom_label",
        "legacy_sku",
        "legacySku",
        "skuId",
    }
    skus: List[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            key_lower = key.lower()
            if key_lower in sku_keys:
                candidate = _extract_first([value])
                if candidate and candidate not in skus:
                    skus.append(candidate)

        # Shopify GraphQL variants
        variants = payload.get("variants")
        if isinstance(variants, dict):
            nodes = variants.get("nodes") or []
            for node in nodes:
                candidate = _extract_first([node.get("sku"), node.get("legacyResourceId")])
                if candidate and candidate not in skus:
                    skus.append(candidate)

        # eBay item specifics may include custom label
        specifics = payload.get("ItemSpecifics") or payload.get("itemSpecifics")
        if isinstance(specifics, dict):
            name_value = specifics.get("NameValueList")
            if isinstance(name_value, Sequence):
                for entry in name_value:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("Name", "").lower() in {"custom label", "sku"}:
                        candidate = _extract_first([entry.get("Value")])
                        if candidate and candidate not in skus:
                            skus.append(candidate)

        # Shopify admin REST structure (images/variants arrays)
        variants_list = payload.get("variants") if isinstance(payload.get("variants"), list) else []
        for node in variants_list:
            candidate = _extract_first([node.get("sku")])
            if candidate and candidate not in skus:
                skus.append(candidate)

    return skus


def _extract_brand(payload: Dict[str, Any], platform: str) -> Optional[str]:
    raw = payload.get("raw_data") or payload.get("_raw") or payload.get("extended_attributes") or payload

    if platform == "vr":
        return _extract_first(
            [
                payload.get("brand"),
                raw.get("brand_name") if isinstance(raw, dict) else None,
            ]
        )

    if platform == "shopify":
        return _extract_first([
            payload.get("vendor"),
            raw.get("vendor") if isinstance(raw, dict) else None,
        ])

    if platform == "ebay":
        # Try raw['ItemSpecifics'] entries
        if isinstance(raw, dict):
            specifics = raw.get("ItemSpecifics") or raw.get("itemSpecifics")
            if isinstance(specifics, dict):
                for entry in specifics.get("NameValueList", []):
                    if entry.get("Name", "").lower() == "brand":
                        return _extract_first([entry.get("Value")])
        return _extract_first([payload.get("brand")])

    if platform == "reverb":
        return _extract_first([payload.get("brand"), raw.get("make") if isinstance(raw, dict) else None])

    return _extract_first([payload.get("brand")])


def _extract_model(payload: Dict[str, Any], platform: str) -> Optional[str]:
    raw = payload.get("raw_data") or payload.get("_raw") or payload.get("extended_attributes") or payload

    if platform == "vr":
        return _extract_first([
            payload.get("model"),
            raw.get("product_model_name") if isinstance(raw, dict) else None,
        ])

    if platform == "shopify":
        # Shopify titles often contain model; rely on manual extraction (none for now)
        return _extract_first([payload.get("model")])

    if platform == "ebay":
        if isinstance(raw, dict):
            specifics = raw.get("ItemSpecifics") or raw.get("itemSpecifics")
            if isinstance(specifics, dict):
                for entry in specifics.get("NameValueList", []):
                    if entry.get("Name", "").lower() in {"model", "model name"}:
                        return _extract_first([entry.get("Value")])
        return _extract_first([payload.get("model")])

    if platform == "reverb":
        return _extract_first([payload.get("model"), raw.get("model") if isinstance(raw, dict) else None])

    return _extract_first([payload.get("model")])


def _extract_year(payload: Dict[str, Any], platform: str) -> Optional[int]:
    raw = payload.get("raw_data") or payload.get("_raw") or payload.get("extended_attributes") or payload
    candidates = [payload.get("year"), payload.get("decade")]

    if platform == "vr" and isinstance(raw, dict):
        candidates.append(raw.get("product_year"))
    if platform == "reverb" and isinstance(raw, dict):
        candidates.append(raw.get("year"))

    for candidate in candidates:
        if not candidate:
            continue
        try:
            text_value = str(candidate)
            if len(text_value) == 4 and text_value.isdigit():
                return int(text_value)
        except (TypeError, ValueError):
            continue
    return None


def _extract_description(payload: Dict[str, Any], platform: str) -> Optional[str]:
    raw = payload.get("raw_data") or payload.get("_raw") or payload.get("extended_attributes") or payload

    potential = [payload.get("description")]

    if isinstance(raw, dict):
        potential.extend(
            [
                raw.get("product_description"),
                raw.get("body_html"),
                raw.get("descriptionHtml"),
                raw.get("description"),
            ]
        )

    return _extract_first(potential)


async def suggest_product_match(
    db: AsyncSession,
    platform: str,
    listing_payload: Dict[str, Any],
) -> Optional[MatchSuggestion]:
    raw = listing_payload.get("raw_data") or listing_payload.get("_raw") or listing_payload.get("extended_attributes")
    skus = _gather_skus(listing_payload, raw if isinstance(raw, dict) else {})

    # First, try SKU match
    for sku in skus:
        stmt = select(Product).where(func.lower(Product.sku) == sku.lower())
        result = await db.execute(stmt)
        product = result.scalar_one_or_none()
        if product:
            existing_platforms = await _fetch_existing_platforms(db, product.id)
            reason = f"SKU match ({sku})"
            return MatchSuggestion(product=product, confidence=1.0, reason=reason, existing_platforms=existing_platforms)

    brand = _extract_brand(listing_payload, platform)
    model = _extract_model(listing_payload, platform)
    year = _extract_year(listing_payload, platform)
    description = _extract_description(listing_payload, platform)
    title = listing_payload.get("title") or (raw.get("title") if isinstance(raw, dict) else None)
    price = listing_payload.get("price")

    candidates: List[Product] = []

    if brand or model:
        stmt = select(Product)
        if brand:
            stmt = stmt.where(func.lower(Product.brand) == brand.lower())
        if model:
            ilike_pattern = f"%{model.lower()}%"
            stmt = stmt.where(func.lower(Product.model).like(ilike_pattern))
        stmt = stmt.limit(20)
        products = (await db.execute(stmt)).scalars().all()
        candidates.extend(products)

    if not candidates and title:
        # fall back to fuzzy title search
        keywords = [part for part in title.split() if len(part) > 2][:3]
        if keywords:
            stmt = select(Product)
            conditions = [func.lower(Product.title).like(f"%{kw.lower()}%") for kw in keywords]
            for cond in conditions:
                stmt = stmt.where(cond)
            stmt = stmt.limit(10)
            products = (await db.execute(stmt)).scalars().all()
            candidates.extend(products)

    if not candidates:
        return None

    best: Optional[MatchSuggestion] = None
    for product in candidates:
        score = 0.0
        reasons: List[str] = []

        if brand and product.brand:
            brand_score = _similarity(brand, product.brand)
            if brand_score > 0.85:
                score += 0.35
                reasons.append("brand match")
            elif brand_score > 0.65:
                score += 0.2
                reasons.append("brand similar")

        if model and product.model:
            model_score = _similarity(model, product.model)
            if model_score > 0.85:
                score += 0.35
                reasons.append("model match")
            elif model_score > 0.65:
                score += 0.2
                reasons.append("model similar")

        if title and product.title:
            title_score = _similarity(title, product.title)
            if title_score > 0.8:
                score += 0.2
                reasons.append("title close")
            elif title_score > 0.6:
                score += 0.1
                reasons.append("title similar")

        if year and product.year:
            if abs(year - product.year) <= 1:
                score += 0.1
                reasons.append("year within 1")
            elif str(product.decade or "").startswith(str(year)[0:3]):
                score += 0.05
                reasons.append("decade similar")

        if price and product.base_price:
            try:
                price_diff = abs(float(price) - float(product.base_price))
                if float(product.base_price):
                    diff_ratio = price_diff / float(product.base_price)
                    if diff_ratio < 0.1:
                        score += 0.1
                        reasons.append("price within 10%")
                    elif diff_ratio < 0.2:
                        score += 0.05
                        reasons.append("price within 20%")
            except (TypeError, ValueError):
                pass

        if description and product.description:
            desc_score = _similarity(description[:150], product.description[:150])
            if desc_score > 0.75:
                score += 0.05
                reasons.append("description similar")

        score = min(score, 0.95)

        if score <= 0:
            continue

        existing_platforms = await _fetch_existing_platforms(db, product.id)
        reason_text = ", ".join(reasons) if reasons else "heuristic match"

        suggestion = MatchSuggestion(
            product=product,
            confidence=round(score, 2),
            reason=reason_text,
            existing_platforms=existing_platforms,
        )

        if not best or suggestion.confidence > best.confidence:
            best = suggestion

    # Only return matches above a threshold to avoid noise
    if best and best.confidence >= 0.45:
        return best
    return None


async def _fetch_existing_platforms(db: AsyncSession, product_id: int) -> List[str]:
    stmt = select(PlatformCommon.platform_name).where(PlatformCommon.product_id == product_id)
    result = await db.execute(stmt)
    return [row[0] for row in result.fetchall() if row[0]]

