# app/services/woocommerce/error_tracker.py
"""
WooCommerce Error Tracker

In-memory error collector for a single WooCommerce operation (sync, import,
publish).  Records errors as they happen, then produces a clean summary at
the end for activity logging and WebSocket broadcasts.

Usage
-----
    tracker = WCErrorTracker(sync_run_id="abc-123")

    # During operation:
    try:
        process_product(data)
    except SomeWCError as e:
        tracker.record(e)

    # After operation:
    if tracker.has_critical_errors():
        abort_and_alert()

    summary = tracker.get_summary()
    # {"total_errors": 3, "by_type": {"WCDataTransformError": 2, ...}, ...}
"""

from datetime import datetime, timezone
from typing import Dict, List, Any, Optional


class WCErrorTracker:
    """
    Collects errors during a single WooCommerce operation.

    Not a singleton -- create one per sync run / import / publish.
    """

    # Error types that should halt the entire operation
    CRITICAL_TYPES = frozenset({
        "WCAuthenticationError",
        "WCConnectionError",
    })

    def __init__(self, sync_run_id: str = None):
        self.sync_run_id = sync_run_id
        self._errors: List[Dict[str, Any]] = []
        self._started_at = datetime.now(timezone.utc)

    def record(self, error: Exception, **extra_context):
        """
        Record an error that occurred during the operation.

        Args:
            error:            The exception that was caught.
            **extra_context:  Additional context (product_id, sku, etc.)
                              merged into the error entry.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": type(error).__name__,
            "message": str(error),
        }
        if hasattr(error, "to_dict"):
            entry.update(error.to_dict())
        entry.update(extra_context)
        self._errors.append(entry)

    # =================================================================
    # Queries
    # =================================================================

    @property
    def error_count(self) -> int:
        return len(self._errors)

    @property
    def errors(self) -> List[Dict[str, Any]]:
        """All recorded errors (copy)."""
        return self._errors.copy()

    def has_critical_errors(self) -> bool:
        """True if any errors should halt the entire operation."""
        return any(
            e["error_type"] in self.CRITICAL_TYPES for e in self._errors
        )

    def get_errors_by_type(self) -> Dict[str, int]:
        """Count of errors grouped by exception class name."""
        counts: Dict[str, int] = {}
        for e in self._errors:
            t = e["error_type"]
            counts[t] = counts.get(t, 0) + 1
        return counts

    # =================================================================
    # Summary  (for dashboard / activity log / WebSocket broadcast)
    # =================================================================

    def get_summary(self) -> Dict[str, Any]:
        """
        Clean summary suitable for activity logging and dashboard display.

        Returns
        -------
        dict with keys:
            total_errors    -- int
            has_critical    -- bool
            by_type         -- dict of error_type -> count
            sample_errors   -- list of first error message per type (max 5)
            action_required -- list of human-readable fix suggestions
            sync_run_id     -- str or None
        """
        by_type = self.get_errors_by_type()

        # First error message per type (deduplicated samples)
        samples: List[str] = []
        seen_types: set = set()
        for e in self._errors:
            t = e["error_type"]
            if t not in seen_types:
                seen_types.add(t)
                msg = e["message"]
                if len(msg) > 150:
                    msg = msg[:147] + "..."
                product_hint = ""
                if e.get("wc_product_id"):
                    product_hint = f"WC#{e['wc_product_id']}: "
                elif e.get("sku"):
                    product_hint = f"{e['sku']}: "
                samples.append(f"{product_hint}{msg}")
            if len(samples) >= 5:
                break

        # Actionable suggestions
        actions = _build_action_list(by_type)

        return {
            "total_errors": len(self._errors),
            "has_critical": self.has_critical_errors(),
            "by_type": by_type,
            "sample_errors": samples,
            "action_required": actions,
            "sync_run_id": self.sync_run_id,
        }


def _build_action_list(by_type: Dict[str, int]) -> List[str]:
    """Map error types to human-readable fix suggestions."""
    actions: List[str] = []
    _ACTION_MAP = {
        "WCAuthenticationError": (
            "Authentication failed -- check WC_CONSUMER_KEY and "
            "WC_CONSUMER_SECRET in .env"
        ),
        "WCConnectionError": (
            "Store unreachable -- verify WC_STORE_URL in .env and "
            "check the site is online"
        ),
        "WCRateLimitError": (
            "Rate limited by WooCommerce -- wait a few minutes and retry"
        ),
        "WCValidationError": (
            "Some products have invalid data -- check logs/woocommerce/errors.log"
        ),
        "WCImageUploadError": (
            "Broken image URLs detected -- check logs/woocommerce/errors.log"
        ),
        "WCDataTransformError": (
            "Data parsing issues -- check logs/woocommerce/errors.log for details"
        ),
        "WCOrderImportError": (
            "Order import failures -- check logs/woocommerce/errors.log"
        ),
        "WCInventoryUpdateError": (
            "Inventory update failures -- check logs/woocommerce/errors.log"
        ),
    }
    for error_type, suggestion in _ACTION_MAP.items():
        if error_type in by_type:
            actions.append(suggestion)
    return actions
