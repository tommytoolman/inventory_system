#!/usr/bin/env python
"""Manually create order_sale sync_events for stocked items."""
import asyncio
import uuid
from app.database import async_session
from app.services.reverb_service import ReverbService
from app.core.config import get_settings

async def main():
    settings = get_settings()
    async with async_session() as db:
        service = ReverbService(db, settings)
        result = await service.create_sync_events_for_stocked_orders(uuid.uuid4())
        await db.commit()
        print(result)

if __name__ == "__main__":
    asyncio.run(main())
