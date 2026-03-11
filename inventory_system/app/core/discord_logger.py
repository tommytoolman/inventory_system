"""
app/core/discord_logger.py

A Python logging.Handler that forwards WARNING+ log records to Discord
via a webhook. Designed to be non-blocking and to never crash the app.

Key properties:
  - Subclasses logging.Handler so every logger.error() / logger.warning()
    in the codebase is automatically forwarded — no code changes elsewhere.
  - Batches records and sends them every `batch_interval` seconds via an
    asyncio background task to avoid Discord's rate limits.
  - In-memory queue (deque) with configurable max size. When full the oldest
    entry is dropped silently (Python's deque(maxlen=N) behaviour).
  - Exponential backoff retry: up to 3 attempts (1 s → 2 s → 4 s).
  - 5-second hard timeout on every HTTP request.
  - Sensitive field names (password, token, api_key …) are redacted before
    being sent to Discord.
  - Never raises an exception — all errors are written to stderr/console as
    a last-resort fallback.

Usage (see app/main.py lifespan for the real wiring):

    handler = DiscordLogHandler(webhook_url=..., service_name="RIFF")
    logging.getLogger().addHandler(handler)
    handler.start_batch_processor(asyncio.get_event_loop())
    # on shutdown:
    handler.stop_batch_processor()
    await handler.flush_now()
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

# ---------------------------------------------------------------------------
# Module-level logger (for internal diagnostics — goes to console only)
# ---------------------------------------------------------------------------
_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Discord embed constants
# ---------------------------------------------------------------------------

# Embed border colour per Python log level name
_COLOURS: Dict[str, int] = {
    "CRITICAL": 0x8B0000,  # Dark red
    "ERROR":    0xFF0000,  # Red
    "WARNING":  0xFFA500,  # Orange
    "INFO":     0x0099FF,  # Blue
    "DEBUG":    0x808080,  # Grey
}

_EMOJIS: Dict[str, str] = {
    "CRITICAL": "🔴",
    "ERROR":    "🔴",
    "WARNING":  "🟡",
    "INFO":     "🔵",
    "DEBUG":    "⚪",
}

# Discord API limits
_MAX_EMBED_DESCRIPTION = 4096
_MAX_FIELD_VALUE       = 1024
_MAX_EMBEDS_PER_MSG    = 10   # Discord hard cap
_REQUEST_TIMEOUT       = 5.0  # seconds
_MAX_RETRIES           = 3

# Substrings that mark a metadata key as sensitive (case-insensitive match)
_SENSITIVE_SUBSTRINGS = (
    "password", "secret", "token", "api_key", "apikey",
    "auth", "credential", "private", "webhook",
)

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int) -> str:
    """Return text clipped to max_len chars with a notice if clipped."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 30] + "\n… [truncated]"


def _sanitise(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of `data` with values redacted when the key contains a
    sensitive substring.  Recurses into nested dicts.  Never raises.
    """
    try:
        result: Dict[str, Any] = {}
        for key, value in data.items():
            lower = key.lower()
            if any(s in lower for s in _SENSITIVE_SUBSTRINGS):
                result[key] = "[REDACTED]"
            elif isinstance(value, dict):
                result[key] = _sanitise(value)
            else:
                result[key] = value
        return result
    except Exception:
        return {"[sanitise_error]": "Failed to sanitise data"}


# ---------------------------------------------------------------------------
# Main handler class
# ---------------------------------------------------------------------------

class DiscordLogHandler(logging.Handler):
    """
    A logging.Handler that queues Python log records and sends them to a
    Discord channel via webhook on a configurable batch interval.

    Constructor arguments all fall back to environment variables so you can
    configure it purely through Railway/your .env file:

        DISCORD_WEBHOOK_URL       — webhook URL (required)
        DISCORD_SERVICE_NAME      — label in every embed footer (default: RIFF)
        DISCORD_LOGGING_ENABLED   — set "false" to disable entirely
        DISCORD_BATCH_INTERVAL    — seconds between flushes (default: 5)
        DISCORD_QUEUE_LIMIT       — max queued records (default: 1000)
    """

    def __init__(
        self,
        webhook_url:    Optional[str] = None,
        service_name:   Optional[str] = None,
        environment:    Optional[str] = None,
        batch_interval: Optional[float] = None,
        queue_limit:    Optional[int] = None,
        min_level:      int = logging.WARNING,
    ) -> None:
        super().__init__(level=min_level)

        # Resolve config: constructor argument → environment variable → default
        self.webhook_url = (
            webhook_url
            or os.getenv("DISCORD_WEBHOOK_URL", "")
        )
        self.service_name = (
            service_name
            or os.getenv("DISCORD_SERVICE_NAME", "RIFF")
        )
        self.environment = (
            environment
            or os.getenv("ENVIRONMENT", os.getenv("NODE_ENV", "production"))
        )
        self.batch_interval = float(
            batch_interval
            if batch_interval is not None
            else os.getenv("DISCORD_BATCH_INTERVAL", "5")
        )
        self.queue_limit = int(
            queue_limit
            if queue_limit is not None
            else os.getenv("DISCORD_QUEUE_LIMIT", "1000")
        )
        self.enabled: bool = (
            os.getenv("DISCORD_LOGGING_ENABLED", "true").lower() != "false"
        )

        # deque(maxlen=N) automatically drops the oldest entry when full —
        # no manual overflow logic needed.
        self._queue: deque[Dict[str, Any]] = deque(maxlen=self.queue_limit)

        self._batch_task: Optional[asyncio.Task[None]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_batch_processor(self) -> None:
        """
        Create the asyncio background task that flushes the queue every
        `batch_interval` seconds.

        Call this from inside an async context (e.g. FastAPI lifespan)
        so that asyncio.get_event_loop() / create_task() works correctly.
        """
        try:
            loop = asyncio.get_event_loop()
            self._batch_task = loop.create_task(
                self._batch_loop(),
                name="discord-logger-batch",
            )
            _log.info(
                "[Discord Logger] Batch processor started "
                "(interval=%.0fs, queue_limit=%d, enabled=%s)",
                self.batch_interval, self.queue_limit, self.enabled,
            )
        except Exception as exc:
            # Non-fatal — log to console and continue
            print(f"[Discord Logger] Failed to start batch processor: {exc}")

    def stop_batch_processor(self) -> None:
        """
        Cancel the batch task.  The CancelledError handler inside
        _batch_loop() will attempt one final flush before exiting.

        Call this from the FastAPI lifespan shutdown block.
        """
        if self._batch_task and not self._batch_task.done():
            self._batch_task.cancel()
        _log.info("[Discord Logger] Batch processor stopped.")

    async def flush_now(self) -> None:
        """Force an immediate send of all queued records. Useful on shutdown."""
        await self._send_batch()

    # ------------------------------------------------------------------
    # logging.Handler interface
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        """
        Called by Python's logging system for every matching log record.
        Queues the record for the next batch flush.
        This method must never raise — errors are handled by handleError().
        """
        try:
            if not self.enabled or not self.webhook_url:
                return

            # Format the full message (includes exception text if present)
            try:
                full_message = self.format(record)
            except Exception:
                full_message = record.getMessage()

            # Extract a short title from the raw message (no exc info)
            title = record.getMessage()

            # Capture traceback separately for the embed Stack Trace field
            exc_text: Optional[str] = None
            if record.exc_info and record.exc_info[0] is not None:
                exc_text = "".join(traceback.format_exception(*record.exc_info))

            entry: Dict[str, Any] = {
                "level":       record.levelname,
                "title":       title[:200],
                "message":     full_message,
                "logger_name": record.name,
                "timestamp":   datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
                "exc_text":    exc_text,
            }

            self._queue.append(entry)

        except Exception:
            # Last resort — logging.Handler.handleError writes to sys.stderr
            self.handleError(record)

    # ------------------------------------------------------------------
    # Private: batch loop
    # ------------------------------------------------------------------

    async def _batch_loop(self) -> None:
        """
        Background asyncio task.  Sleeps for batch_interval then flushes.
        On CancelledError (graceful shutdown) attempts a final flush.
        """
        while True:
            try:
                await asyncio.sleep(self.batch_interval)
                await self._send_batch()
            except asyncio.CancelledError:
                # Shutdown path — best-effort final flush
                try:
                    await self._send_batch()
                except Exception as exc:
                    print(f"[Discord Logger] Final flush failed: {exc}")
                raise  # re-raise so the task actually ends
            except Exception as exc:
                # Never crash the loop — log and continue
                print(f"[Discord Logger] Batch loop error (will retry next cycle): {exc}")

    # ------------------------------------------------------------------
    # Private: build and send
    # ------------------------------------------------------------------

    async def _send_batch(self) -> None:
        """
        Atomically drain the queue, build Discord embeds, and POST them
        in chunks of up to 10 (Discord's per-message limit).
        """
        if not self._queue:
            return

        try:
            # Drain the queue atomically — records added while we're
            # sending are picked up on the next cycle.
            batch: List[Dict[str, Any]] = list(self._queue)
            self._queue.clear()

            embeds: List[Dict[str, Any]] = []
            for entry in batch:
                try:
                    embeds.append(self._build_embed(entry))
                except Exception as exc:
                    print(f"[Discord Logger] Failed to build embed for '{entry.get('title')}': {exc}")

            # Send in chunks of 10
            for i in range(0, len(embeds), _MAX_EMBEDS_PER_MSG):
                chunk = embeds[i : i + _MAX_EMBEDS_PER_MSG]
                await self._post_to_discord({
                    "username": f"{self.service_name} Logger",
                    "embeds":   chunk,
                })

        except Exception as exc:
            print(f"[Discord Logger] _send_batch failed: {exc}")

    def _build_embed(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a queued log-entry dict to a Discord embed dict."""
        level   = entry.get("level", "INFO")
        colour  = _COLOURS.get(level, 0x808080)
        emoji   = _EMOJIS.get(level, "⚪")
        title   = entry.get("title", "Log entry")
        message = entry.get("message", title)

        fields: List[Dict[str, Any]] = []

        # Logger name
        logger_name = entry.get("logger_name", "")
        if logger_name:
            fields.append({
                "name":   "Logger",
                "value":  _truncate(logger_name, 256),
                "inline": True,
            })

        # Stack trace
        exc_text = entry.get("exc_text")
        if exc_text:
            fields.append({
                "name":   "Stack Trace",
                "value":  f"```\n{_truncate(exc_text, _MAX_FIELD_VALUE - 10)}\n```",
                "inline": False,
            })

        # Description: full formatted message (may include exc repr line)
        description = _truncate(message, _MAX_EMBED_DESCRIPTION)

        return {
            "title":       f"{emoji} {level} — {_truncate(title, 200)}",
            "description": description,
            "color":       colour,
            "timestamp":   entry.get("timestamp"),
            "footer":      {"text": f"{self.service_name} | {self.environment}"},
            "fields":      fields[:25],  # Discord hard limit: 25 fields
        }

    async def _post_to_discord(self, payload: Dict[str, Any]) -> None:
        """
        POST `payload` to the Discord webhook.
        Retries up to _MAX_RETRIES times with exponential backoff.
        Handles rate-limiting (HTTP 429) using the retry-after header.
        Times out after _REQUEST_TIMEOUT seconds.
        Never raises.
        """
        if not self.webhook_url:
            return

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                    response = await client.post(
                        self.webhook_url,
                        json=payload,
                    )

                # Rate limited — wait as Discord instructs
                if response.status_code == 429:
                    retry_after = float(
                        response.headers.get("retry-after", "5")
                    )
                    print(
                        f"[Discord Logger] Rate limited — waiting {retry_after:.1f}s "
                        f"(attempt {attempt}/{_MAX_RETRIES})"
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code not in (200, 204):
                    raise httpx.HTTPStatusError(
                        f"Discord returned {response.status_code}: "
                        f"{response.text[:200]}",
                        request=response.request,
                        response=response,
                    )

                # Success
                print(
                    f"[Discord Logger] Sent {len(payload['embeds'])} embed(s) "
                    f"to #{self.service_name}"
                )
                return

            except Exception as exc:
                if attempt == _MAX_RETRIES:
                    print(
                        f"[Discord Logger] Failed after {_MAX_RETRIES} attempts — "
                        f"dropping batch. Last error: {exc}"
                    )
                    return

                # Exponential backoff: 1s, 2s, 4s
                backoff = 2 ** (attempt - 1)
                print(
                    f"[Discord Logger] Attempt {attempt}/{_MAX_RETRIES} failed "
                    f"({exc}). Retrying in {backoff}s…"
                )
                await asyncio.sleep(backoff)
