# MASTER CLAUDE CODE PROMPT: WooCommerce Integration for RIFF Technology

## CONTEXT
You are implementing a bidirectional WooCommerce integration for RIFF Technology - a multi-platform inventory management system that synchronises product listings across Reverb, eBay, Shopify, Vintage & Rare marketplaces, and now WooCommerce.

## PROJECT UNDERSTANDING
First, explore the existing RIFF codebase to understand:
- Current architecture (Python backend, likely FastAPI)
- Existing marketplace integration patterns (Reverb, eBay, Shopify, Vintage & Rare)
- Database schema and models
- Authentication/configuration management
- Docker setup and deployment structure

## IMPLEMENTATION REQUIREMENTS

### 1. AUTHENTICATION & CONFIGURATION
- Implement Basic Auth over HTTPS using WooCommerce Consumer Key/Secret
- **CRITICAL**: This is SANDBOX/TESTING mode only
- Add clear warnings in code comments that OAuth 1.0a is required for production
- Store credentials securely using the same pattern as other marketplace integrations
- Support environment variables for configuration

### 2. BIDIRECTIONAL SYNCHRONISATION
Implement two-way sync between RIFF and WooCommerce:

#### RIFF → WooCommerce (Outbound):
- Product creation (title, description, SKU, price, images)
- Inventory updates (stock levels)
- Product modifications (price changes, description updates)
- Product deletion/deactivation

#### WooCommerce → RIFF (Inbound):
- Import existing WooCommerce products
- Listen for product updates via webhooks (or polling if webhooks unavailable in sandbox)
- Order notifications (when products sell on WooCommerce)
- Stock level changes from WooCommerce orders

### 3. API ENDPOINTS TO IMPLEMENT
Use WooCommerce REST API v3 (`/wp-json/wc/v3/`):

**Products:**
- `GET /products` - List all products
- `GET /products/{id}` - Get single product
- `POST /products` - Create product
- `PUT /products/{id}` - Update product
- `DELETE /products/{id}` - Delete product

**Orders:**
- `GET /orders` - List orders
- `GET /orders/{id}` - Get single order
- Listen for new orders to update RIFF inventory

**Webhooks (if available in sandbox):**
- `POST /webhooks` - Create webhook subscriptions
- Topics: `product.created`, `product.updated`, `product.deleted`, `order.created`

### 4. SANDBOX/PRODUCTION MODE TOGGLE
- Create a UI toggle button "Production Mode: ON/OFF" in the WooCommerce section
- When OFF (default): Uses sandbox credentials, shows testing banners
- When ON: Requires OAuth 1.0a credentials (to be implemented by next developer)
- Store mode preference in database/config
- Display clear visual indicators of current mode throughout the interface

### 5. CODE ORGANISATION
Place the integration in a clear, discoverable location such as:
```
src/integrations/woocommerce/
├── __init__.py
├── client.py              # WooCommerce API client wrapper
├── auth.py                # Authentication handlers (Basic + OAuth placeholder)
├── sync_manager.py        # Bidirectional sync orchestration
├── models.py              # WooCommerce-specific data models
├── webhooks.py            # Webhook receiver endpoints
├── config.py              # Configuration management
└── exceptions.py          # Custom exceptions
```

Or follow the existing pattern in the RIFF codebase if different.

### 6. ERROR HANDLING
- Implement robust error handling for API failures
- Rate limiting awareness (WooCommerce has rate limits)
- Retry logic with exponential backoff
- Clear error messages for authentication failures
- Logging of all API interactions for debugging

### 7. DATA MAPPING
Create clear mappings between RIFF's internal product model and WooCommerce:
- SKU → WooCommerce SKU
- Title → Product Name
- Description → Product Description (short & long)
- Price → Regular Price
- Images → Product Gallery
- Stock → Stock Quantity & Stock Status
- Categories/Tags (if applicable)

### 8. TESTING REQUIREMENTS
Implement three distinct testing layers:

#### Unit Tests (`tests/unit/woocommerce/`):
- Mock all WooCommerce API responses
- Test data transformation/mapping logic
- Test authentication mechanisms
- Test error handling paths
- NO actual API calls

#### Integration Tests (`tests/integration/woocommerce/`):
- Test against actual WooCommerce sandbox site
- Use sandbox credentials from environment variables
- Test full CRUD operations
- Test webhook delivery
- Verify data consistency
- Can be skipped in CI if no sandbox available

#### Mock Tests (`tests/mocks/woocommerce/`):
- Fast-running tests using recorded HTTP responses
- Test edge cases without hitting API
- Test rate limiting behaviour
- Test network failure scenarios

### 9. CONFIGURATION FILE
Create a clear configuration structure:

```python
# Example structure
WOOCOMMERCE_CONFIG = {
    'sandbox': {
        'enabled': True,  # Default for testing
        'store_url': 'https://your-store.com',
        'consumer_key': 'ck_xxxxx',  # From environment
        'consumer_secret': 'cs_xxxxx',  # From environment
        'verify_ssl': True,
        'timeout': 30,
    },
    'production': {
        'enabled': False,
        'store_url': '',  # To be configured
        'auth_method': 'oauth1',  # OAuth 1.0a required
        'consumer_key': '',
        'consumer_secret': '',
        'verify_ssl': True,
        'timeout': 30,
    },
    'sync': {
        'interval_minutes': 15,  # How often to poll for changes
        'batch_size': 50,  # Products per sync batch
        'enable_webhooks': True,  # Use webhooks when available
    }
}
```

### 10. UI COMPONENTS
Add to the RIFF admin interface:
- WooCommerce connection status indicator
- Sandbox/Production mode toggle with confirmation dialog
- Last sync timestamp display
- Sync now button (manual trigger)
- Connection test button
- Product mapping overview (which RIFF products sync to WooCommerce)
- Error log viewer for WooCommerce-specific issues

### 11. DOCUMENTATION REQUIREMENTS
Generate inline documentation:
- Docstrings for all functions/classes
- Type hints throughout
- Clear comments explaining WooCommerce-specific quirks
- README.md in the integration folder explaining setup
- Environment variable documentation

### 12. SECURITY CONSIDERATIONS
- **NEVER** commit credentials to version control
- Use environment variables or secure secret management
- Validate all incoming webhook signatures (when OAuth implemented)
- Sanitise all user input before sending to WooCommerce
- Log security events (auth failures, invalid webhooks)

## IMPLEMENTATION STRATEGY

### Phase 1: Foundation
1. Explore existing RIFF codebase structure
2. Create WooCommerce integration folder structure
3. Implement basic authentication client
4. Test connection to sandbox WooCommerce site
5. Implement simple product GET operations

### Phase 2: Outbound Sync (RIFF → WooCommerce)
1. Implement product creation in WooCommerce
2. Implement product updates
3. Implement inventory sync
4. Add sync scheduling/orchestration
5. Test with real RIFF products

### Phase 3: Inbound Sync (WooCommerce → RIFF)
1. Implement product import from WooCommerce
2. Set up webhook receivers (or polling fallback)
3. Handle order notifications
4. Update RIFF inventory from WooCommerce sales
5. Test bidirectional flow

### Phase 4: UI & Controls
1. Add WooCommerce section to admin UI
2. Implement sandbox/production toggle
3. Add connection status indicators
4. Create manual sync triggers
5. Build error log viewer

### Phase 5: Testing & Documentation
1. Write unit tests
2. Write integration tests
3. Write mock tests
4. Document setup process
5. Create handover notes for OAuth implementation

## CRITICAL REMINDERS
- **This is SANDBOX mode** - clearly mark all sandbox code
- **OAuth 1.0a is needed for production** - leave clear TODOs
- **Follow existing RIFF patterns** - maintain consistency
- **Make it obvious** - other developers need to find this easily
- **British English** in all user-facing text and documentation
- **Test thoroughly** - this handles real product data

## OUTPUT EXPECTATIONS
When complete, the integration should:
1. Successfully connect to a WooCommerce sandbox site
2. Sync products bidirectionally without data loss
3. Handle errors gracefully with clear logging
4. Have comprehensive test coverage
5. Include clear documentation for the next developer
6. Be production-ready except for OAuth implementation

## QUESTIONS TO ASK
Before implementation, verify:
- What is the exact location of the RIFF project codebase?
- Are there existing integration patterns to follow?
- What database is being used?
- Is there an existing admin UI framework?
- Are there preferred Python libraries for HTTP requests?

Begin by exploring the codebase structure and confirming the implementation approach.