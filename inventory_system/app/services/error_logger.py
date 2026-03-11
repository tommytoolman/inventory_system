"""
app/services/error_logger.py

Captures sync/upload errors to the database and forwards them to Discord
via the existing DiscordLogHandler (which picks up all WARNING+ log records
automatically — no separate notification call needed).
"""
import logging
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync_error import SyncErrorRecord

logger = logging.getLogger(__name__)


class SyncErrorLogger:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log_upload_error(
        self,
        product_id: Optional[int],
        platform: str,
        operation: str,
        error: Exception,
        user_id: Optional[int] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> SyncErrorRecord:
        """
        Persist a sync error to the database and emit an ERROR log record
        (which the DiscordLogHandler picks up and forwards to Discord).

        Returns the SyncErrorRecord so callers can include the error ID in
        their HTTP response (e.g. "Sync failed. Error ID: A3F9B12C").
        """
        error_id = str(uuid.uuid4())[:8].upper()
        error_type = type(error).__name__
        error_message = str(error)[:2000]
        stack = traceback.format_exc()

        record = SyncErrorRecord(
            id=error_id,
            product_id=product_id,
            platform=platform,
            operation=operation,
            error_message=error_message,
            error_type=error_type,
            stack_trace=stack,
            user_id=user_id,
            extra_context=extra_context,
            created_at=datetime.utcnow(),
        )
        self.db.add(record)
        try:
            await self.db.flush()
        except Exception as db_exc:
            # Never let error logging crash the caller
            logger.warning("SyncErrorLogger: failed to persist error record: %s", db_exc)

        # This goes to Discord automatically via DiscordLogHandler
        logger.error(
            "[%s] %s failed for product_id=%s — Error ID: %s | %s: %s",
            platform.upper(),
            operation,
            product_id,
            error_id,
            error_type,
            error_message,
            exc_info=error,
        )

        return record
