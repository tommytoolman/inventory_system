import pytest
import asyncio
from datetime import datetime, timezone
from app.integrations.stock_manager import StockManager
from app.integrations.events import StockUpdateEvent
from app.integrations.base import SyncStatus

@pytest.fixture
async def mock_system():
    from tests.mocks.mock_platform import MockPlatform
    
    # Create manager with two mock platforms
    manager = StockManager()
    platform1 = MockPlatform({"test": "credentials"})
    platform2 = MockPlatform({"test": "credentials"})
    
    manager.register_platform("platform1", platform1)
    manager.register_platform("platform2", platform2)
    
    return manager, platform1, platform2

@pytest.mark.asyncio
async def test_stock_update_propagation(mock_system):
    manager, platform1, platform2 = mock_system
    
    event = StockUpdateEvent(
        product_id=123,
        platform="platform1",
        new_quantity=10,
        timestamp=datetime.now()
    )
    
    await manager.process_stock_update(event)
    
    assert platform2.stock_levels[123] == 10
    assert len(platform2.update_calls) == 1
    assert len(platform1.update_calls) == 0

@pytest.mark.asyncio
async def test_error_handling(mock_system):
    manager, platform1, platform2 = mock_system
    
    platform2.should_fail = True
    
    event = StockUpdateEvent(
        product_id=123,
        platform="platform1",
        new_quantity=10,
        timestamp=datetime.now()
    )
    
    await manager.process_stock_update(event)
    status = await platform2.sync_status(123)
    assert status == SyncStatus.ERROR

@pytest.mark.asyncio
async def test_queue_processing(mock_system):
    manager, platform1, platform2 = mock_system
    
    # Create multiple updates
    events = [
        StockUpdateEvent(
            product_id=123,
            platform="platform1",
            new_quantity=i,
            timestamp=datetime.now()
        )
        for i in range(5)
    ]
    
    # Start monitoring task first
    monitor_task = asyncio.create_task(manager.start_sync_monitor())
    
    # Then add events to queue
    for event in events:
        await manager.update_queue.put(event)
    
    try:
        # Wait for all events to be processed
        await asyncio.wait_for(manager.update_queue.join(), timeout=5.0)
        
        # Give a small delay to ensure all updates are reflected
        await asyncio.sleep(0.1)
        
        # Verify final state
        assert platform2.stock_levels[123] == 4  # Last update was quantity=4
        assert len(platform2.update_calls) == 5  # All updates processed
        
    except asyncio.TimeoutError:
        pytest.fail("Queue processing timed out")
    finally:
        # Cleanup
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass