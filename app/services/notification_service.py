"""Email notification helpers for platform events."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Iterable, List, Optional, Sequence

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmailNotificationService:
    """Lightweight SMTP helper for system notifications."""

    def __init__(self, settings: Settings):
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def send_sale_alert(
        self,
        *,
        product,
        platform: str,
        sale_price: Optional[float] = None,
        external_id: Optional[str] = None,
        sale_status: Optional[str] = None,
        listing_url: Optional[str] = None,
        detected_at: Optional[str] = None,
        propagated_platforms: Optional[Sequence[str]] = None,
        recipients: Optional[Sequence[str]] = None,
        additional_lines: Optional[Sequence[str]] = None,
    ) -> bool:
        """Send a sale notification email.

        Args:
            product: SQLAlchemy product model with at least ``sku``/``display_title``.
            platform: Name of the platform that reported the sale.
            sale_price: Optional price achieved on the platform.
            external_id: Order/listing identifier returned by the platform.
            recipients: Override the default notification list.
            additional_lines: Extra message lines to append to the body.
        """

        if not self._ready():
            logger.warning("SMTP configuration incomplete; sale alert skipped for %s", getattr(product, "sku", "<unknown>"))
            return False

        to_addresses = self._resolve_recipients(recipients)
        if not to_addresses:
            logger.warning("No recipients configured for sale alert; skipping email")
            return False

        subject = f"Sale: {getattr(product, 'display_title', getattr(product, 'title', 'Product'))}"  # Fallback if property missing

        sku = getattr(product, "sku", "N/A")
        base_price = getattr(product, "base_price", None)
        lines: List[str] = [
            f"Product: {getattr(product, 'display_title', getattr(product, 'title', 'Unknown Product'))}",
            f"SKU: {sku}",
            f"Platform: {platform}",
        ]

        if sale_status:
            lines.append(f"Status: {sale_status.upper()}")

        if sale_price is not None:
            lines.append(f"Sale price: £{sale_price:,.2f}")
        elif base_price is not None:
            lines.append(f"Listed price: £{base_price:,.2f}")

        if detected_at:
            lines.append(f"Detected at: {detected_at}")

        if listing_url:
            lines.append(f"Listing URL: {listing_url}")
        elif external_id:
            lines.append(f"External reference: {external_id}")

        if propagated_platforms:
            joined = ", ".join(sorted({p.upper() for p in propagated_platforms if p}))
            if joined:
                lines.append(f"Listings ended on: {joined}")

        if getattr(product, "listing_url", None):
            lines.append(f"Listing URL: {product.listing_url}")

        if getattr(product, "video_url", None):
            lines.append(f"Video URL: {product.video_url}")

        primary_image_url = getattr(product, "primary_image", None)
        if primary_image_url:
            lines.append(f"Primary image: {primary_image_url}")

        if additional_lines:
            lines.extend(additional_lines)

        lines.append("\nSent automatically by Inventory System")

        body_text = "\n".join(lines)

        body_html_lines = ["<p><strong>Product Sold</strong></p>"]
        body_html_lines.extend(f"<p>{line}</p>" for line in lines[:-1])  # Skip the footer for HTML list
        if primary_image_url:
            body_html_lines.append(
                f'<p><img src="{primary_image_url}" alt="Primary image" '
                'style="max-width: 380px; border-radius: 6px;" /></p>'
            )
        body_html_lines.append("<p><em>Sent automatically by Inventory System</em></p>")
        body_html = "".join(body_html_lines)

        message = self._build_message(subject, to_addresses, body_text, body_html)
        return await self._dispatch(message)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _ready(self) -> bool:
        settings = self._settings
        return bool(settings.SMTP_HOST and settings.SMTP_USERNAME and settings.SMTP_PASSWORD)

    def _resolve_recipients(self, override: Optional[Sequence[str]]) -> List[str]:
        recipients: Iterable[str] = override if override else self._settings.NOTIFICATION_EMAILS
        return [email.strip() for email in recipients if email]

    def _build_message(
        self,
        subject: str,
        to_addresses: Sequence[str],
        body_text: str,
        body_html: Optional[str] = None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._formatted_from_address
        message["To"] = ", ".join(sorted(set(to_addresses)))
        message.set_content(body_text)
        if body_html:
            message.add_alternative(body_html, subtype="html")
        return message

    @property
    def _formatted_from_address(self) -> str:
        from_email = self._settings.SMTP_FROM_EMAIL or self._settings.SMTP_USERNAME
        from_name = self._settings.SMTP_FROM_NAME or "Inventory Alerts"
        return formataddr((from_name, from_email))

    async def _dispatch(self, message: EmailMessage) -> bool:
        try:
            await asyncio.to_thread(self._send_sync, message)
            logger.info("Sale alert email sent to %s", message["To"])
            return True
        except Exception as exc:  # pragma: no cover - logged for observability
            logger.error("Failed to send sale alert email: %s", exc, exc_info=True)
            return False

    def _send_sync(self, message: EmailMessage) -> None:
        settings = self._settings
        host = settings.SMTP_HOST
        port = settings.SMTP_PORT or (465 if settings.SMTP_USE_SSL else 587)
        timeout = settings.SMTP_TIMEOUT

        if settings.SMTP_USE_SSL:
            smtp = smtplib.SMTP_SSL(host=host, port=port, timeout=timeout)
        else:
            smtp = smtplib.SMTP(host=host, port=port, timeout=timeout)
        try:
            if settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL:
                smtp.starttls()

            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
        finally:
            try:
                smtp.quit()
            except Exception:
                smtp.close()


async def get_email_notification_service() -> EmailNotificationService:
    """Factory for dependency injection."""

    settings = get_settings()
    return EmailNotificationService(settings)
