Overall Purpose & Structure:

These files establish a dedicated layer (app/integrations/) focused purely on the mechanics of outbound stock synchronization.

- Uses a clear interface (PlatformInterface) to define how to interact with platforms regarding stock.
- Uses an event-driven model (StockUpdateEvent, asyncio.Queue) to decouple the detection of a stock change from the process of updating other platforms.
- Includes robust monitoring (MetricsCollector).
- Has a central orchestrator (StockManager) running as a background task.
- Provides setup logic (setup.py) to initialize the system, likely at application startup.

Relationship to Services (app/services/):

This integrations layer seems designed to receive notifications (likely as StockUpdateEvents put onto the queue) from the services layer. For example:
A webhook route (app/routes/webhooks.py) receives a notification from Reverb about a sale.
The route calls a corresponding service (app/services/reverb_service.py or a webhook processor service).
The service updates the local database (e.g., marks Product as SOLD, updates PlatformCommon status).
The service then creates a StockUpdateEvent (product_id=X, platform='reverb', new_quantity=0) and puts it onto the StockManager's update_queue.
The StockManager's start_sync_monitor picks up the event and calls _process_update.
_process_update calls ebay_platform.update_stock(X, 0), website_platform.update_stock(X, 0), etc., via the registered PlatformInterface implementations.
This separation allows services to focus on handling platform-specific incoming data, business logic, and local DB state, while integrations focuses solely on the mechanics of pushing state changes out consistently and reliably across platforms.