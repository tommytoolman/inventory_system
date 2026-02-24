"""
Daily log review service.

Captures WARNING+ log records in a bounded ring buffer and lightweight
counters for INFO-level events.  A scheduler sends a daily HTML email
report via the existing EmailNotificationService.
"""

from __future__ import annotations

import asyncio
import logging
import re
import traceback
from collections import deque
from datetime import datetime, timedelta, time, timezone
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern matchers for INFO-level counters
# ---------------------------------------------------------------------------
_RE_404 = re.compile(r'"[A-Z]+ .+ HTTP/\d\.\d" 404')
_RE_SALE = re.compile(r"(?i)\bsale\b.*\balert\b|\bsold\b|Sale:")
_RE_PLATFORM_SYNC = re.compile(
    r"(?i)\b(ebay|reverb|shopify|vr|vintage.?rare)\b.*\bsync",
)
_RE_VR_AUTH_FAIL = re.compile(r"(?i)vr.*auth.*fail|vintage.*rare.*login.*fail|vr.*cookie.*expired")


class LogAggregatorHandler(logging.Handler):
    """Logging handler that stores WARNING+ records and counts key events."""

    def __init__(self, maxlen: int = 5000):
        super().__init__(level=logging.DEBUG)
        self._records: deque[Dict[str, Any]] = deque(maxlen=maxlen)
        # Lightweight counters (reset each time get_summary drains them)
        self._total_requests = 0
        self._status_404 = 0
        self._sales_detected = 0
        self._vr_auth_failures = 0
        self._platform_syncs: Dict[str, int] = {
            "ebay": 0, "reverb": 0, "shopify": 0, "vr": 0,
        }

    # ------------------------------------------------------------------
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record) if self.formatter else record.getMessage()
            self._count_info_events(msg)

            if record.levelno >= logging.WARNING:
                entry: Dict[str, Any] = {
                    "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": msg[:2000],
                }
                if record.exc_info and record.exc_info[1]:
                    entry["traceback"] = "".join(
                        traceback.format_exception(*record.exc_info)
                    )[:4000]
                self._records.append(entry)
        except Exception:
            self.handleError(record)

    # ------------------------------------------------------------------
    def _count_info_events(self, msg: str) -> None:
        if "HTTP/" in msg:
            self._total_requests += 1
        if _RE_404.search(msg):
            self._status_404 += 1
        if _RE_SALE.search(msg):
            self._sales_detected += 1
        if _RE_VR_AUTH_FAIL.search(msg):
            self._vr_auth_failures += 1
        m = _RE_PLATFORM_SYNC.search(msg)
        if m:
            platform = m.group(1).lower()
            if "vintage" in platform or platform == "vr":
                platform = "vr"
            if platform in self._platform_syncs:
                self._platform_syncs[platform] += 1

    # ------------------------------------------------------------------
    def get_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Return a structured summary of recent log activity."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
        cutoff_iso = cutoff.isoformat()

        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        for entry in self._records:
            if entry["time"] < cutoff_iso:
                continue
            if entry["level"] == "ERROR" or entry["level"] == "CRITICAL":
                errors.append(entry)
            elif entry["level"] == "WARNING":
                warnings.append(entry)

        summary = {
            "period_start": cutoff.isoformat(),
            "period_end": datetime.now(tz=timezone.utc).isoformat(),
            "errors": errors,
            "warnings": warnings,
            "stats": {
                "total_requests": self._total_requests,
                "status_404_count": self._status_404,
                "platform_syncs": dict(self._platform_syncs),
                "vr_auth_failures": self._vr_auth_failures,
                "sales_detected": self._sales_detected,
            },
        }

        # Reset counters after draining
        self._total_requests = 0
        self._status_404 = 0
        self._sales_detected = 0
        self._vr_auth_failures = 0
        self._platform_syncs = {k: 0 for k in self._platform_syncs}

        return summary


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class DailyLogReviewScheduler:
    """Sends a daily log-review email at the configured time."""

    def __init__(self, log_handler: LogAggregatorHandler):
        self._handler = log_handler
        settings = get_settings()
        h, m = (settings.LOG_REVIEW_TIME or "07:00").split(":")
        self._review_time = time(int(h), int(m), tzinfo=timezone.utc)

    async def run(self) -> None:
        logger.info("Log review scheduler started (daily at %s UTC)", self._review_time.strftime("%H:%M"))

        while True:
            try:
                now = datetime.now(tz=timezone.utc)
                next_run = datetime.combine(now.date(), self._review_time, tzinfo=timezone.utc)
                if next_run <= now:
                    next_run += timedelta(days=1)

                wait_secs = (next_run - now).total_seconds()
                logger.info("Next log review at %s (%.1f hours)", next_run.isoformat(), wait_secs / 3600)
                await asyncio.sleep(wait_secs)

                await self._send_report()

                # Avoid double-run at the boundary
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.info("Log review scheduler cancelled")
                break
            except Exception:
                logger.exception("Error in log review scheduler loop")
                await asyncio.sleep(300)

    async def _send_report(self) -> None:
        summary = self._handler.get_summary(hours=24)

        from app.services.notification_service import EmailNotificationService
        settings = get_settings()
        email_svc = EmailNotificationService(settings)
        ok = await email_svc.send_log_report(summary)
        if ok:
            logger.info("Daily log report sent successfully")
        else:
            logger.warning("Daily log report could not be sent")
