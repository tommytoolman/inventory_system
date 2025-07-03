# Project: Multi-Platform Inventory Sync System
## Phase: Hybrid Sandbox/Production Testing Plan & Considerations

**Date:** May 16, 2025

**Overall Goal of this Testing Phase:**
To validate the end-to-end inventory synchronization process across multiple platforms (eBay, Reverb, Vintage & Rare, Shopify). This phase emphasizes using a combination of live production data (for reads) and sandbox/simulated environments (for writes) to ensure system stability and accuracy before a full production launch.

---

### Core Testing Steps:

1.  **Live Production Reads:**
    * Configure the system to read live inventory data from existing production sites (eBay, Reverb, V&R, Shopify).
    * Focus: Test the system's ability to correctly fetch and interpret data from diverse live environments.

2.  **Parallel Sandbox Listings:**
    * Use existing/new scripts to create parallel (clone) listings of production items onto Reverb and eBay Sandbox environments.
    * Focus: Establish a safe environment for testing write operations.

3.  **Vintage & Rare (V&R) Sandbox Simulation:**
    * Due to the lack of a formal V&R sandbox, simulate one. This could be:
        * A dedicated spreadsheet.
        * A simple custom-built mock API/database.
    * Focus: Ensure V&R integration can be tested for both read and write operations in a controlled manner.

4.  **Central System Updates (RIFF):**
    * The central inventory system (RIFF) will process data read from production (and simulated V&R).
    * Focus: Verify that the central database correctly reflects the state of items as per the live reads.

5.  **Push Updates to Sandboxes:**
    * Inventory changes (e.g., simulated sales, price updates) processed by the central system should be pushed out to the corresponding Reverb and eBay sandbox listings (and the V&R simulated sandbox).
    * Focus: Test the system's ability to accurately propagate changes to other platforms.

6.  **"To Do" List for Verification:**
    * Implement or utilize a system (manual or automated) to generate a "to do" list based on sales or detected discrepancies.
    * Focus: Provide a mechanism for manual verification of critical sync actions during the testing phase.

7.  **Centralized Listing Creation (RIFF to Sandbox):**
    * Test the functionality of creating new product listings directly from the central RIFF system and pushing these listings to the sandbox environments (eBay, Reverb, simulated V&R).
    * Focus: Validate the product creation and initial push-to-platform workflow.

8.  **Sales Simulation:**
    * Actively simulate sales of items within the sandbox/simulated environments or by flagging items in the central system.
    * Scenarios: Test single sales, sales of last items, sales reducing quantity, and attempted sales of out-of-stock items.
    * Focus: Ensure the system correctly handles sales events, updates quantities, and propagates "sold" statuses.

9.  **Shopify Integration (Later in this phase):**
    * Once the core sync logic for existing platforms is stable, integrate Shopify.
    * This will involve connecting to a Shopify development/sandbox store and incorporating it into the full read/update/propagate cycle.
    * Focus: Extend the system's capabilities to the Shopify platform.

10. **Qualification & Launch Planning:**
    * Define clear criteria for qualifying the system as "ready for launch" (e.g., X successful end-to-end sync cycles, Y simulated sales processed correctly).
    * Develop a detailed cutover plan for transitioning from hybrid testing to full production, including how "fresh inventory" will be established.

---

### Key Considerations & Recommendations:

* **Data Mapping & SKU Consistency:**
    * Ensure a robust strategy for mapping production items to their sandbox/simulated counterparts. Consistent SKUs or a clear mapping table in the central system is crucial.
    * Verify how the `product_matcher.py` tool handles these relationships.
* **V&R Sandbox Implementation Details:**
    * If using a spreadsheet, define the process for "pushing" updates from the central system. A mock API might offer more robust testing for V&R write operations.
* **"To Do" List Purpose & Granularity:**
    * Clearly define what triggers items on this list and the expected actions/verifications.
* **Caution for Listing Creation to Production:**
    * **Strongly advise against** pushing new listings from the central RIFF system directly to *production* platforms during this hybrid phase. Reserve this for the final launch or extremely limited, controlled tests. Stick to sandboxes for new listing pushes.
* **Realistic Sales Simulation Scenarios:**
    * Cover various sale types (single, last item, out-of-stock attempts, multiple platform sales if simulatable) to test system logic and error handling.
* **Shopify Integration Strategy:**
    * Integrate Shopify methodically after other platforms are stable. Utilize a Shopify development store.
* **"Fresh Inventory" & Cutover Plan:**
    * Detail the process for the final launch: Will the database be wiped and re-imported from production, or will existing records be updated? Plan for a smooth transition, potentially with a maintenance window.
* **Idempotency & Error Recovery:**
    * Observe and test how the system handles API failures, network issues, and retries. Ensure operations are idempotent (safe to re-run).
* **Monitoring & Logging:**
    * Leverage and enhance existing logging (like the "Recent Activity" UI and backend logs) to provide clear traceability for all sync operations and data changes.
* **Rollback Considerations:**
    * Have a conceptual plan for disconnecting or rolling back parts of the system if major issues arise during hybrid testing.

---

### Next Immediate Internal Verification Step (Before full hybrid testing):

* **Confirm Local System Activity:**
    * Thoroughly verify that inventory sync operations (e.g., "Sync eBay") are correctly triggering the intended changes within the local database (e.g., `Product` table, platform-specific tables like `EbayListing`, and `ActivityLog`).
    * Trace a product through a change on an external platform (sandbox), sync, and verify database updates and activity logging.