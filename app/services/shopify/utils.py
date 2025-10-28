"""Utility helpers for generating Shopify-specific metadata."""

from __future__ import annotations

import re
from html import unescape
from typing import Iterable, List, Optional

# Canonical footer appended to long-form product descriptions
STANDARD_DESCRIPTION_FOOTER = (
    "<br/><br/>\n"
    "<p><strong>ALL EU PURCHASES ARE DELIVERED WITH TAXES AND DUTIES PAID</strong></p>\n"
    "<p>All purchases include EU Taxes / Duties paid, i.e., nothing further is due on receipt of goods to any EU State.</p>\n"
    "<br/>\n"
    "<p><strong>WHY BUY FROM US</strong></p>\n"
    "<p>We are one of the world's leading specialists in used and vintage gear with over 30 years of experience. Prior to shipping, each item will be fully serviced and professionally packed.</p>\n"
    "<br/>\n"
    "<p><strong>SELL - TRADE - CONSIGN</strong></p>\n"
    "<p>If you are looking to sell, trade, or consign any of your classic gear, please contact us by message.</p>\n"
    "<br/>\n"
    "<p><strong>WORLDWIDE COLLECTION - DELIVERY</strong></p>\n"
    "<p>We offer personal delivery and collection services worldwide with offices/locations in London, Amsterdam, and Chicago.</p>\n"
    "<br/>\n"
    "<p><strong>VALUATION SERVICE</strong></p>\n"
    "<p>If you require a valuation of any of your classic gear, please forward a brief description and pictures, and we will come back to you ASAP.</p>"
)

_FOOTER_MARKER = "ALL EU PURCHASES ARE DELIVERED WITH TAXES AND DUTIES PAID"

_WORD_PATTERN = re.compile(r"[A-Za-z0-9&'\-/]+")
_PARAGRAPH_PATTERN = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")

_STOPWORDS = {
    "and",
    "the",
    "with",
    "for",
    "are",
    "this",
    "that",
    "from",
    "your",
    "our",
    "will",
    "have",
    "has",
    "into",
    "onto",
    "each",
    "over",
    "nbsp",
}


def ensure_description_has_standard_footer(description: Optional[str]) -> str:
    """Append the standard footer to a description exactly once."""

    if not description or not description.strip():
        return description or ""

    if _FOOTER_MARKER in description:
        return description

    return f"{description.rstrip()}{STANDARD_DESCRIPTION_FOOTER}"


def _strip_tags(html: Optional[str]) -> str:
    if not html:
        return ""
    text = _TAG_PATTERN.sub(" ", html)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _first_paragraph_text(html: Optional[str]) -> str:
    if not html:
        return ""

    match = _PARAGRAPH_PATTERN.search(html)
    if match:
        return _strip_tags(match.group(1))

    # Fallback: take the first sentence worth of plain text
    plain = _strip_tags(html)
    if not plain:
        return ""

    # Split on common sentence delimiters but keep it concise
    for delimiter in [". ", "! ", "? "]:
        if delimiter in plain:
            return plain.split(delimiter, 1)[0].strip()

    return plain


def _base_keyword_values(values: Iterable[Optional[str]]) -> List[str]:
    keywords: List[str] = []
    seen = set()
    for value in values:
        if not value:
            continue
        cleaned = value.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        keywords.append(cleaned)
    return keywords


def generate_shopify_keywords(
    *,
    brand: Optional[str],
    model: Optional[str],
    finish: Optional[str],
    year: Optional[int],
    decade: Optional[int],
    category: Optional[str],
    condition: Optional[str],
    description_html: Optional[str],
    max_length: int = 250,
) -> List[str]:
    """Produce a deduplicated list of SEO keywords for Shopify tags."""

    base_values = [brand, model, finish]
    if year:
        base_values.append(str(year))
    elif decade:
        base_values.append(f"{decade}s")

    base_values.extend([category, condition])
    keywords = _base_keyword_values(base_values)

    description_text = _strip_tags(description_html)
    if description_text:
        for word in _WORD_PATTERN.findall(description_text.lower()):
            if len(word) < 3 or word in _STOPWORDS:
                continue
            if word not in keywords:
                keywords.append(word)

    # Enforce Shopify's 250-character soft limit
    trimmed: List[str] = []
    current_length = 0
    for keyword in keywords:
        projected = current_length + len(keyword) + (1 if trimmed else 0)
        if projected > max_length:
            break
        trimmed.append(keyword)
        current_length = projected

    return trimmed


def generate_shopify_short_description(
    description_html: Optional[str],
    *,
    fallback: Optional[str] = None,
    max_length: int = 320,
) -> str:
    """Return the first paragraph (or fallback) trimmed to Shopify's limit."""

    excerpt = _first_paragraph_text(description_html)
    if not excerpt:
        excerpt = fallback or ""

    excerpt = excerpt.strip()
    if len(excerpt) > max_length:
        return excerpt[: max_length - 1].rstrip() + "…"
    return excerpt


__all__ = [
    "STANDARD_DESCRIPTION_FOOTER",
    "ensure_description_has_standard_footer",
    "generate_shopify_keywords",
    "generate_shopify_short_description",
]
