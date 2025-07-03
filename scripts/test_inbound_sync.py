# scripts/test_inbound_sync.py
import asyncio
from app.database import get_session
from app.services.sync_services import InboundSyncScheduler

async def test_sync():
    async with get_session() as db:
        scheduler = InboundSyncScheduler(db, report_only=True)
        
        # Test single platform
        report = await scheduler.run_platform_sync("reverb")
        scheduler.print_sync_report(report)
        
        # Test all platforms
        # reports = await scheduler.run_all_platforms_sync()
        # for platform, report in reports.items():
        #     scheduler.print_sync_report(report)

if __name__ == "__main__":
    asyncio.run(test_sync())