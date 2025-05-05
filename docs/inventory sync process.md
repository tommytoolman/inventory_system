Inventory Sync Process: Part 1

When inventory synchronization is triggered (manually or via cron), the following sequence occurs:

1. Triggering Event: Either a scheduled cron job runs or a user clicks a "Sync Now" button in the UI.

2. Initial Request Handling: The system identifies which products need synchronization based on:
   - Products with pending status changes
   - Products with stock quantity changes
   - Products that haven't been synced recently

3. SyncService Activation: The SyncService is instantiated with:
   - Database session for data access
   - Reference to the StockManager for cross-platform updates

4. Product Retrieval: The service queries the database for products needing sync, including their current platform status from PlatformCommon records.

5. Platform-Specific Processing: For each product and each enabled platform (eBay, Reverb, VintageAndRare):
   - The appropriate platform service is instantiated (EbayService, ReverbService, etc.)
   - Product data is transformed to match platform requirements
  
After establishing local and remote state baselines, the synchronization process continues:

6. Difference Analysis: The system compares the two snapshots to determine what actions are needed:
   - Products on platforms that need updates (price, description, images)
   - Products in local DB not on platforms (need creation)
   - Products on platforms not in local DB (possible deletion)
   - Products with stock discrepancies (quantity updates needed)

7. Action Planning: Each difference generates a planned action:
   - Create: New listings for products not on platforms
   - Update: Modify existing listings with changed data
   - Delete: Remove listings no longer in inventory
   - Stock Update: Synchronize quantities across platforms

8. Execution: The SyncService executes these actions:
   - Platform-specific services handle the actual API calls
   - Changes are batched where possible for efficiency
   - Each action is logged for auditing

9. Status Recording: As actions complete:
   - platform_common records are updated with new statuses
   - Success/failure is logged
   - Error handling processes failures

10. Result Reporting: The system generates a summary report of all sync actions and their outcomes.

Inventory Sync Process: Part 1 Answers
The inventory synchronization process begins with establishing a baseline of "what's where" across all platforms. This process requires two key perspectives:

1. Local System State

The process queries platform_common table to identify all products with platform integrations
For platform-specific details, it checks ebay_listings, reverb_listings, and vr_listings tables
Product master data comes from the products table (stock quantities, prices, descriptions)
This represents "what we think is on each platform"
2. Remote Platform State

For accurate platforms with APIs (eBay, Reverb):
Fetch current listing data via API calls
Retrieve status, quantity, price, and other platform-specific attributes
For VintageAndRare (web-based):
Either rely on the last known state or
Perform a web scraping operation to get current data
For the website:
Query the website's API or database directly
The SyncService starts by building these two snapshots - what our system believes exists on each platform versus what actually exists - before calculating the required synchronization actions.