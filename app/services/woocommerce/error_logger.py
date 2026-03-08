# app/services/woocommerce/error_logger.py
"""
WooCommerce Error Logger

Dedicated file-based logging for the WooCommerce integration.
Writes to ``logs/woocommerce/`` with rotating file handlers so logs
never fill the disk.

Files
-----
errors.log   All WC errors -- formatted blocks with context, HTTP details,
             and tracebacks.  Easy to scan for a technical user.
sync.log     Sync operation progress and summaries.  One line per event.
debug.log    Verbose debug output (only created when LOG_LEVEL=DEBUG).

Usage
-----
    from app.services.woocommerce.error_logger import wc_logger

    wc_logger.log_error(some_exception)
    wc_logger.log_warning("Price fallback", operation="import", wc_product_id="123")

    wc_logger.sync_start("run-abc-123")
    wc_logger.sync_progress("Processing 50/150 products")
    wc_logger.sync_complete("run-abc-123", stats_dict, error_summary)
"""

import logging
import os
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, Any

LOG_DIR = Path("logs/woocommerce")


# ===================================================================
# Custom formatters
# ===================================================================

class _ErrorFormatter(logging.Formatter):
    """
    Produces clean, readable error blocks for errors.log.

    Each error is a visual block separated by ═══ lines with key
    context fields, the error message, optional response body, and
    traceback.  Designed to be scanned quickly by a developer.
    """

    SEP = "=" * 72
    THIN = "-" * 72

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        ctx: dict = getattr(record, "error_context", {})
        error_type = ctx.get("error_type", level)

        lines = [
            "",
            self.SEP,
            f"  {level}  {ts}  {error_type}",
            self.THIN,
        ]

        # -- Key fields --------------------------------------------------
        if ctx.get("operation"):
            lines.append(f"  Operation : {ctx['operation']}")

        product_parts = []
        if ctx.get("sku"):
            product_parts.append(ctx["sku"])
        if ctx.get("product_id"):
            product_parts.append(f"ID: {ctx['product_id']}")
        if ctx.get("wc_product_id"):
            product_parts.append(f"WC#{ctx['wc_product_id']}")
        if product_parts:
            lines.append(f"  Product   : {' | '.join(product_parts)}")

        http_parts = []
        if ctx.get("http_status"):
            http_parts.append(str(ctx["http_status"]))
        if ctx.get("request_method"):
            http_parts.append(ctx["request_method"])
        if ctx.get("request_url"):
            http_parts.append(ctx["request_url"])
        if http_parts:
            lines.append(f"  HTTP      : {' '.join(http_parts)}")

        if ctx.get("retry_count"):
            lines.append(f"  Retries   : {ctx['retry_count']}")

        lines.append("")

        # -- Error message ------------------------------------------------
        lines.append(f"  {record.getMessage()}")

        # -- Response body ------------------------------------------------
        if ctx.get("response_body"):
            lines.append("")
            lines.append("  Response:")
            body = ctx["response_body"][:1500]
            for body_line in body.split("\n"):
                lines.append(f"    {body_line}")

        # -- Traceback ----------------------------------------------------
        if record.exc_info and record.exc_info[1]:
            lines.append("")
            lines.append("  Traceback:")
            tb_text = "".join(traceback.format_exception(*record.exc_info))
            for tb_line in tb_text.strip().split("\n"):
                lines.append(f"    {tb_line}")

        lines.append(self.SEP)
        return "\n".join(lines)


class _SyncFormatter(logging.Formatter):
    """Timestamped single-line entries for sync.log."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        return f"[{ts}] {record.getMessage()}"


# ===================================================================
# WCErrorLogger  (singleton)
# ===================================================================

class WCErrorLogger:
    """
    Singleton file-based logger for WooCommerce integration.

    Manages rotating log files under ``logs/woocommerce/``.
    Thread-safe via Python's logging module.
    """

    _instance: Optional["WCErrorLogger"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._setup()

    def _setup(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        # -- errors.log ---------------------------------------------------
        self._error_log = logging.getLogger("wc.errors")
        self._error_log.setLevel(logging.WARNING)
        self._error_log.propagate = False
        if not self._error_log.handlers:
            h = RotatingFileHandler(
                LOG_DIR / "errors.log",
                maxBytes=10 * 1024 * 1024,   # 10 MB
                backupCount=5,
                encoding="utf-8",
            )
            h.setFormatter(_ErrorFormatter())
            self._error_log.addHandler(h)

        # -- sync.log -----------------------------------------------------
        self._sync_log = logging.getLogger("wc.sync")
        self._sync_log.setLevel(logging.INFO)
        self._sync_log.propagate = False
        if not self._sync_log.handlers:
            h = RotatingFileHandler(
                LOG_DIR / "sync.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            h.setFormatter(_SyncFormatter())
            self._sync_log.addHandler(h)

        # -- debug.log  (only when LOG_LEVEL=DEBUG) -----------------------
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        self._debug_log = None
        if log_level == "DEBUG":
            self._debug_log = logging.getLogger("wc.debug")
            self._debug_log.setLevel(logging.DEBUG)
            self._debug_log.propagate = False
            if not self._debug_log.handlers:
                h = RotatingFileHandler(
                    LOG_DIR / "debug.log",
                    maxBytes=10 * 1024 * 1024,
                    backupCount=3,
                    encoding="utf-8",
                )
                h.setFormatter(logging.Formatter(
                    "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
                ))
                self._debug_log.addHandler(h)

    # =================================================================
    # Error logging
    # =================================================================

    def log_error(self, error: Exception, **extra_context):
        """
        Log a WooCommerce error with full context to errors.log.

        If the error has a ``to_dict()`` method (WCErrorMixin), its
        structured context is included automatically.  Extra keyword
        args are merged in and can override/supplement the context.
        """
        ctx = {}
        if hasattr(error, "to_dict"):
            ctx = error.to_dict()
        ctx.update(extra_context)

        ei = None
        if error.__traceback__:
            ei = (type(error), error, error.__traceback__)

        self._error_log.error(
            str(error),
            exc_info=ei,
            extra={"error_context": ctx},
        )

        if self._debug_log:
            self._debug_log.error(
                f"[{ctx.get('error_type', 'Error')}] {error}",
                exc_info=ei,
            )

    def log_warning(self, message: str, **context):
        """Log a non-critical warning to errors.log (data fallbacks, etc.)."""
        ctx = {"error_type": "Warning", **context}
        self._error_log.warning(
            message,
            extra={"error_context": ctx},
        )
        if self._debug_log:
            self._debug_log.warning(message)

    # =================================================================
    # Sync lifecycle
    # =================================================================

    def sync_start(self, sync_run_id: str, operation: str = "Product Import"):
        """Log the start of a sync operation to sync.log."""
        self._sync_log.info(
            f"== SYNC STARTED ==  {operation}  |  Run: {sync_run_id}"
        )

    def sync_progress(self, message: str):
        """Log a progress update during sync."""
        self._sync_log.info(message)

    def sync_warning(self, message: str):
        """Log a non-fatal issue during sync (shown with WARNING marker)."""
        self._sync_log.info(f"WARNING  {message}")

    def sync_complete(self, sync_run_id: str, stats: Dict[str, Any],
                      error_summary: Optional[Dict[str, Any]] = None,
                      duration_seconds: float = 0):
        """Log sync completion with full statistics."""
        dur = f"{duration_seconds:.1f}s" if duration_seconds else "N/A"
        self._sync_log.info(
            f"== SYNC COMPLETED ==  Duration: {dur}  |  Run: {sync_run_id}"
        )

        # Stats line
        parts = []
        for key in ("total", "created", "updated", "sku_matched", "errors", "skipped"):
            if key in stats:
                label = key.replace("_", " ").title()
                parts.append(f"{label}: {stats[key]}")
        if parts:
            self._sync_log.info(f"  {' | '.join(parts)}")

        # Error breakdown
        if error_summary and error_summary.get("by_type"):
            type_parts = [f"{k}({v})" for k, v in error_summary["by_type"].items()]
            self._sync_log.info(f"  Error types: {', '.join(type_parts)}")

        if error_summary and error_summary.get("action_required"):
            for action in error_summary["action_required"]:
                self._sync_log.info(f"  -> Action: {action}")

        self._sync_log.info("")  # blank line between runs

    def sync_error(self, sync_run_id: str, error: Exception):
        """Log a sync that failed entirely (critical / unrecoverable error)."""
        self._sync_log.info(f"== SYNC FAILED ==  Run: {sync_run_id}")
        self._sync_log.info(f"  {type(error).__name__}: {error}")
        self._sync_log.info("")

    # =================================================================
    # Debug
    # =================================================================

    def debug(self, message: str):
        """Write to debug.log only (no-op if LOG_LEVEL != DEBUG)."""
        if self._debug_log:
            self._debug_log.debug(message)


# Module-level singleton -- import this directly
wc_logger = WCErrorLogger()
