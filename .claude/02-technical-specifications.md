# TECHNICAL SPECIFICATIONS: WooCommerce API Integration

## WooCommerce REST API v3 Reference

### Base URL Structure
```
https://your-store.com/wp-json/wc/v3/{endpoint}
```

### Authentication Headers (Basic Auth - SANDBOX ONLY)
```
Authorization: Basic base64(consumer_key:consumer_secret)
```

Or as query parameters (for servers with header parsing issues):
```
?consumer_key=ck_xxxxx&consumer_secret=cs_xxxxx
```

## CRITICAL API ENDPOINTS

### Products API

#### List All Products
```http
GET /wp-json/wc/v3/products
```

Query Parameters:
- `page` (int): Page number
- `per_page` (int): Products per page (max 100)
- `search` (string): Search by product name/SKU
- `status` (string): Filter by status (publish, draft, pending, private)
- `sku` (string): Filter by SKU
- `orderby` (string): Sort by (date, id, title, slug)
- `order` (string): asc or desc

#### Get Single Product
```http
GET /wp-json/wc/v3/products/{id}
```

#### Create Product
```http
POST /wp-json/wc/v3/products
Content-Type: application/json

{
  "name": "Guitar Model Name",
  "type": "simple",
  "regular_price": "599.99",
  "description": "Full product description",
  "short_description": "Brief description",
  "sku": "RIFF-GUITAR-001",
  "manage_stock": true,
  "stock_quantity": 1,
  "stock_status": "instock",
  "images": [
    {
      "src": "https://example.com/image.jpg"
    }
  ],
  "categories": [
    {
      "id": 12
    }
  ],
  "tags": [
    {
      "id": 34
    }
  ]
}
```

#### Update Product
```http
PUT /wp-json/wc/v3/products/{id}
Content-Type: application/json

{
  "regular_price": "549.99",
  "stock_quantity": 0,
  "stock_status": "outofstock"
}
```

#### Delete Product
```http
DELETE /wp-json/wc/v3/products/{id}?force=true
```

Note: `force=true` permanently deletes, otherwise moves to trash

#### Batch Update Products
```http
POST /wp-json/wc/v3/products/batch
Content-Type: application/json

{
  "create": [...],
  "update": [...],
  "delete": [...]
}
```

### Orders API

#### List Orders
```http
GET /wp-json/wc/v3/orders
```

Query Parameters:
- `status` (string): Filter by status (pending, processing, completed, etc.)
- `after` (ISO8601): Orders created after date
- `before` (ISO8601): Orders created before date

#### Get Single Order
```http
GET /wp-json/wc/v3/orders/{id}
```

Order Response includes:
- `line_items`: Products in the order
- `status`: Order status
- `total`: Order total
- `date_created`: When order was placed

### Webhooks API (for real-time sync)

#### Create Webhook
```http
POST /wp-json/wc/v3/webhooks
Content-Type: application/json

{
  "name": "RIFF Product Created",
  "topic": "product.created",
  "delivery_url": "https://riff-api.com/webhooks/woocommerce/product-created",
  "secret": "your-webhook-secret"
}
```

Available Topics:
- `product.created`
- `product.updated`
- `product.deleted`
- `product.restored`
- `order.created`
- `order.updated`
- `order.deleted`

#### Webhook Payload Structure
WooCommerce sends:
```http
POST https://your-riff-api.com/webhooks/woocommerce/product-created
X-WC-Webhook-Source: https://store.com
X-WC-Webhook-Topic: product.created
X-WC-Webhook-Resource: product
X-WC-Webhook-Event: created
X-WC-Webhook-Signature: base64_encoded_signature
X-WC-Webhook-ID: 123
X-WC-Webhook-Delivery-ID: 456

{product_data}
```

Verify signature:
```python
import hmac
import hashlib
import base64

def verify_webhook(payload, signature, secret):
    expected = base64.b64encode(
        hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).digest()
    ).decode('utf-8')
    return hmac.compare_digest(expected, signature)
```

## DATA MODELS

### WooCommerce Product Schema (relevant fields)
```json
{
  "id": 123,
  "name": "Product Name",
  "slug": "product-name",
  "permalink": "https://store.com/product/product-name",
  "type": "simple",
  "status": "publish",
  "description": "Full HTML description",
  "short_description": "Brief HTML description",
  "sku": "UNIQUE-SKU",
  "price": "99.99",
  "regular_price": "99.99",
  "sale_price": "",
  "manage_stock": true,
  "stock_quantity": 5,
  "stock_status": "instock",
  "images": [
    {
      "id": 456,
      "src": "https://store.com/image.jpg",
      "name": "image.jpg",
      "alt": "Alt text"
    }
  ],
  "categories": [
    {
      "id": 12,
      "name": "Guitars",
      "slug": "guitars"
    }
  ],
  "tags": [
    {
      "id": 34,
      "name": "Vintage",
      "slug": "vintage"
    }
  ],
  "meta_data": [
    {
      "key": "riff_product_id",
      "value": "riff-12345"
    }
  ]
}
```

### RIFF → WooCommerce Mapping Strategy

Use `meta_data` to store RIFF identifiers:
```python
# When creating WooCommerce product from RIFF
wc_product = {
    "name": riff_product.title,
    "sku": riff_product.sku,
    "regular_price": str(riff_product.price),
    "description": riff_product.description,
    "stock_quantity": riff_product.quantity,
    "meta_data": [
        {"key": "_riff_id", "value": str(riff_product.id)},
        {"key": "_riff_last_sync", "value": datetime.utcnow().isoformat()},
        {"key": "_synced_from_riff", "value": "true"}
    ]
}
```

This allows you to:
1. Find WooCommerce products by RIFF ID
2. Track sync timestamps
3. Identify which products came from RIFF

## ERROR HANDLING

### Common WooCommerce API Errors

#### 401 Unauthorized
```json
{
  "code": "woocommerce_rest_cannot_view",
  "message": "Sorry, you cannot list resources.",
  "data": {"status": 401}
}
```
**Action**: Check credentials, verify user permissions

#### 400 Bad Request
```json
{
  "code": "woocommerce_rest_product_invalid_sku",
  "message": "Invalid or duplicated SKU.",
  "data": {"status": 400}
}
```
**Action**: Validate SKU uniqueness, check data format

#### 404 Not Found
```json
{
  "code": "woocommerce_rest_product_invalid_id",
  "message": "Invalid ID.",
  "data": {"status": 404}
}
```
**Action**: Verify product exists, check mapping data

#### 429 Too Many Requests (Rate Limiting)
```
HTTP/1.1 429 Too Many Requests
Retry-After: 60
```
**Action**: Implement exponential backoff, respect Retry-After header

### Python Error Handling Example
```python
import requests
from time import sleep

def make_wc_request(url, method='GET', **kwargs):
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, **kwargs)
            
            if response.status_code == 429:
                # Rate limited
                retry_after = int(response.headers.get('Retry-After', 60))
                logger.warning(f"Rate limited. Waiting {retry_after}s")
                sleep(retry_after)
                continue
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                logger.error("Authentication failed - check credentials")
                raise AuthenticationError("Invalid WooCommerce credentials")
            elif e.response.status_code == 404:
                logger.warning(f"Resource not found: {url}")
                return None
            elif e.response.status_code >= 500:
                # Server error - retry with backoff
                if attempt < max_retries - 1:
                    sleep(retry_delay * (2 ** attempt))
                    continue
                raise
            else:
                logger.error(f"WooCommerce API error: {e.response.text}")
                raise
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error: {str(e)}")
            if attempt < max_retries - 1:
                sleep(retry_delay * (2 ** attempt))
                continue
            raise
    
    raise Exception("Max retries exceeded")
```

## RATE LIMITING

WooCommerce doesn't officially document rate limits, but:
- Respect `Retry-After` headers
- Implement request throttling (suggested: max 10 requests/second)
- Use batch endpoints when updating multiple products
- Cache product data to reduce API calls

## SYNC STRATEGY RECOMMENDATIONS

### Polling-Based Sync (Fallback)
```python
async def poll_for_changes():
    """Poll WooCommerce for changes every N minutes"""
    last_sync = get_last_sync_timestamp()
    
    # Get products modified since last sync
    products = wc_client.get_products(
        modified_after=last_sync,
        per_page=100
    )
    
    for product in products:
        sync_product_to_riff(product)
    
    update_last_sync_timestamp()
```

### Webhook-Based Sync (Preferred)
```python
@app.post("/webhooks/woocommerce/product-updated")
async def handle_product_update(request: Request):
    """Real-time webhook handler"""
    
    # Verify webhook signature
    signature = request.headers.get('X-WC-Webhook-Signature')
    payload = await request.body()
    
    if not verify_webhook(payload, signature, WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid webhook signature")
    
    # Process the update
    product_data = await request.json()
    sync_product_to_riff(product_data)
    
    return {"status": "success"}
```

### Hybrid Approach (Recommended)
- Use webhooks for real-time updates
- Fallback to polling if webhook fails
- Run scheduled full sync daily to catch any missed updates

## TESTING ENDPOINTS

### Sandbox Test Card Numbers
WooCommerce sandbox doesn't process real payments, but for testing payment gateway integrations:
- Test Card: 4242 4242 4242 4242
- Any future expiry date
- Any 3-digit CVC

### Test Data Generation
Create test products via API:
```python
test_products = [
    {
        "name": "Test Stratocaster",
        "sku": f"TEST-STRAT-{i}",
        "regular_price": "799.99",
        "stock_quantity": 1,
        "meta_data": [{"key": "_test_product", "value": "true"}]
    }
    for i in range(10)
]

# Batch create
wc_client.post('products/batch', json={'create': test_products})
```

### Cleanup Test Data
```python
# Get all test products
test_products = wc_client.get('products', params={
    'meta_key': '_test_product',
    'meta_value': 'true',
    'per_page': 100
})

# Batch delete
wc_client.post('products/batch', json={
    'delete': [p['id'] for p in test_products]
})
```

## PERFORMANCE OPTIMISATIONS

1. **Batch Operations**: Use `/batch` endpoints for bulk updates
2. **Pagination**: Always paginate large result sets
3. **Field Filtering**: Request only needed fields (not yet supported in v3)
4. **Conditional Requests**: Use `If-Modified-Since` headers
5. **Connection Pooling**: Reuse HTTP connections
6. **Async Operations**: Use async/await for concurrent requests

## MONITORING & LOGGING

Log these events:
- All authentication attempts (success/failure)
- API errors (with request/response details)
- Rate limit hits
- Webhook deliveries (received/processed/failed)
- Sync operations (started/completed/failed)
- Data inconsistencies found

Example log entry:
```json
{
  "timestamp": "2026-03-03T10:30:00Z",
  "level": "INFO",
  "event": "woocommerce_sync_completed",
  "direction": "riff_to_wc",
  "products_synced": 42,
  "duration_seconds": 12.5,
  "errors": 0
}
```