# TESTING STRATEGY: WooCommerce Integration

## Three-Layer Testing Approach

### Layer 1: Unit Tests (Fast, No External Deps)
**Location**: `tests/unit/woocommerce/`
**Purpose**: Test business logic in isolation
**Run Frequency**: On every commit, in CI/CD

#### Files to Create:
```
tests/unit/woocommerce/
├── test_auth.py
├── test_client.py
├── test_data_mapping.py
├── test_sync_manager.py
├── test_webhooks.py
└── test_exceptions.py
```

#### Example: test_data_mapping.py
```python
import pytest
from src.integrations.woocommerce.models import RiffProductMapper

class TestRiffProductMapper:
    """Test RIFF to WooCommerce data transformation"""
    
    def test_basic_product_mapping(self):
        """Test mapping a simple RIFF product to WooCommerce format"""
        riff_product = {
            'id': 'riff-12345',
            'title': 'Fender Stratocaster 1965',
            'sku': 'STRAT-1965-001',
            'price': 2499.99,
            'description': 'Vintage Fender Stratocaster',
            'quantity': 1
        }
        
        mapper = RiffProductMapper()
        wc_product = mapper.to_woocommerce(riff_product)
        
        assert wc_product['name'] == 'Fender Stratocaster 1965'
        assert wc_product['sku'] == 'STRAT-1965-001'
        assert wc_product['regular_price'] == '2499.99'
        assert wc_product['stock_quantity'] == 1
        
        # Check meta_data includes RIFF ID
        meta_keys = [m['key'] for m in wc_product['meta_data']]
        assert '_riff_id' in meta_keys
    
    def test_product_with_images(self):
        """Test mapping product with multiple images"""
        riff_product = {
            'id': 'riff-67890',
            'title': 'Gibson Les Paul',
            'sku': 'LP-1959-001',
            'price': 8999.99,
            'images': [
                'https://cdn.riff.com/guitar1.jpg',
                'https://cdn.riff.com/guitar2.jpg'
            ],
            'quantity': 1
        }
        
        mapper = RiffProductMapper()
        wc_product = mapper.to_woocommerce(riff_product)
        
        assert len(wc_product['images']) == 2
        assert wc_product['images'][0]['src'] == 'https://cdn.riff.com/guitar1.jpg'
    
    def test_out_of_stock_mapping(self):
        """Test that zero quantity maps to out of stock"""
        riff_product = {
            'id': 'riff-11111',
            'title': 'Test Guitar',
            'sku': 'TEST-001',
            'price': 999.99,
            'quantity': 0
        }
        
        mapper = RiffProductMapper()
        wc_product = mapper.to_woocommerce(riff_product)
        
        assert wc_product['stock_quantity'] == 0
        assert wc_product['stock_status'] == 'outofstock'
    
    def test_reverse_mapping_woocommerce_to_riff(self):
        """Test mapping WooCommerce product back to RIFF format"""
        wc_product = {
            'id': 123,
            'name': 'Fender Telecaster',
            'sku': 'TELE-1952-001',
            'price': '3499.99',
            'stock_quantity': 1,
            'meta_data': [
                {'key': '_riff_id', 'value': 'riff-99999'}
            ]
        }
        
        mapper = RiffProductMapper()
        riff_product = mapper.from_woocommerce(wc_product)
        
        assert riff_product['id'] == 'riff-99999'
        assert riff_product['title'] == 'Fender Telecaster'
        assert riff_product['sku'] == 'TELE-1952-001'
        assert riff_product['price'] == 3499.99
```

#### Example: test_auth.py
```python
import pytest
from unittest.mock import Mock, patch
from src.integrations.woocommerce.auth import WooCommerceAuth, AuthenticationError

class TestWooCommerceAuth:
    """Test authentication mechanisms"""
    
    def test_basic_auth_header_generation(self):
        """Test Basic Auth header is correctly formatted"""
        auth = WooCommerceAuth(
            consumer_key='ck_test123',
            consumer_secret='cs_test456',
            auth_method='basic'
        )
        
        headers = auth.get_auth_headers()
        
        assert 'Authorization' in headers
        assert headers['Authorization'].startswith('Basic ')
    
    def test_query_string_auth(self):
        """Test query string authentication for problematic servers"""
        auth = WooCommerceAuth(
            consumer_key='ck_test123',
            consumer_secret='cs_test456',
            auth_method='basic',
            use_query_string=True
        )
        
        params = auth.get_auth_params()
        
        assert params['consumer_key'] == 'ck_test123'
        assert params['consumer_secret'] == 'cs_test456'
    
    def test_oauth_placeholder_raises_not_implemented(self):
        """OAuth should raise NotImplementedError in sandbox mode"""
        auth = WooCommerceAuth(
            consumer_key='ck_test123',
            consumer_secret='cs_test456',
            auth_method='oauth1'
        )
        
        with pytest.raises(NotImplementedError, match='OAuth 1.0a not yet implemented'):
            auth.get_auth_headers()
    
    def test_missing_credentials_raises_error(self):
        """Test that missing credentials raise appropriate error"""
        with pytest.raises(AuthenticationError, match='Consumer key required'):
            WooCommerceAuth(consumer_key=None, consumer_secret='cs_test')
        
        with pytest.raises(AuthenticationError, match='Consumer secret required'):
            WooCommerceAuth(consumer_key='ck_test', consumer_secret=None)
```

#### Example: test_client.py
```python
import pytest
from unittest.mock import Mock, patch, MagicMock
from src.integrations.woocommerce.client import WooCommerceClient
from src.integrations.woocommerce.exceptions import WooCommerceAPIError, RateLimitError

class TestWooCommerceClient:
    """Test API client functionality with mocked responses"""
    
    @pytest.fixture
    def mock_response(self):
        """Fixture for mocked HTTP responses"""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {'id': 123, 'name': 'Test Product'}
        response.headers = {}
        return response
    
    @patch('requests.request')
    def test_get_products_success(self, mock_request, mock_response):
        """Test successful product retrieval"""
        mock_request.return_value = mock_response
        
        client = WooCommerceClient(
            store_url='https://test-store.com',
            consumer_key='ck_test',
            consumer_secret='cs_test'
        )
        
        products = client.get_products()
        
        assert products['id'] == 123
        assert products['name'] == 'Test Product'
        mock_request.assert_called_once()
    
    @patch('requests.request')
    def test_rate_limit_handling(self, mock_request):
        """Test rate limit error handling"""
        rate_limit_response = Mock()
        rate_limit_response.status_code = 429
        rate_limit_response.headers = {'Retry-After': '60'}
        rate_limit_response.raise_for_status.side_effect = Exception('Rate limited')
        
        mock_request.return_value = rate_limit_response
        
        client = WooCommerceClient(
            store_url='https://test-store.com',
            consumer_key='ck_test',
            consumer_secret='cs_test'
        )
        
        with pytest.raises(RateLimitError) as exc_info:
            client.get_products()
        
        assert exc_info.value.retry_after == 60
    
    @patch('requests.request')
    def test_authentication_error(self, mock_request):
        """Test 401 authentication error handling"""
        auth_error_response = Mock()
        auth_error_response.status_code = 401
        auth_error_response.json.return_value = {
            'code': 'woocommerce_rest_cannot_view',
            'message': 'Invalid credentials'
        }
        auth_error_response.raise_for_status.side_effect = Exception('Unauthorized')
        
        mock_request.return_value = auth_error_response
        
        client = WooCommerceClient(
            store_url='https://test-store.com',
            consumer_key='ck_wrong',
            consumer_secret='cs_wrong'
        )
        
        with pytest.raises(WooCommerceAPIError, match='Invalid credentials'):
            client.get_products()
```

---

### Layer 2: Integration Tests (Sandbox API Required)
**Location**: `tests/integration/woocommerce/`
**Purpose**: Test actual API interactions with WooCommerce sandbox
**Run Frequency**: Before deployment, manually, or in nightly builds

#### Prerequisites:
- Active WooCommerce sandbox site
- Valid sandbox API credentials in environment variables
- Network connectivity

#### Files to Create:
```
tests/integration/woocommerce/
├── conftest.py           # Pytest fixtures and setup
├── test_product_crud.py  # Create, read, update, delete operations
├── test_sync_flow.py     # Full bidirectional sync
├── test_webhooks.py      # Webhook delivery and handling
└── test_error_scenarios.py
```

#### Example: conftest.py
```python
import pytest
import os
from src.integrations.woocommerce.client import WooCommerceClient

@pytest.fixture(scope='session')
def wc_client():
    """Create WooCommerce client for integration tests"""
    store_url = os.getenv('WC_SANDBOX_URL')
    consumer_key = os.getenv('WC_SANDBOX_CONSUMER_KEY')
    consumer_secret = os.getenv('WC_SANDBOX_CONSUMER_SECRET')
    
    if not all([store_url, consumer_key, consumer_secret]):
        pytest.skip('WooCommerce sandbox credentials not configured')
    
    return WooCommerceClient(
        store_url=store_url,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret
    )

@pytest.fixture
def test_product_data():
    """Sample product data for testing"""
    import uuid
    return {
        'name': f'Integration Test Product {uuid.uuid4().hex[:8]}',
        'sku': f'TEST-{uuid.uuid4().hex[:8].upper()}',
        'regular_price': '999.99',
        'description': 'This is a test product created by integration tests',
        'stock_quantity': 5,
        'manage_stock': True,
        'meta_data': [
            {'key': '_test_product', 'value': 'true'}
        ]
    }

@pytest.fixture
def cleanup_test_products(wc_client):
    """Cleanup fixture to remove test products after tests"""
    created_product_ids = []
    
    yield created_product_ids
    
    # Cleanup
    if created_product_ids:
        for product_id in created_product_ids:
            try:
                wc_client.delete_product(product_id, force=True)
            except Exception as e:
                print(f'Failed to cleanup product {product_id}: {e}')
```

#### Example: test_product_crud.py
```python
import pytest

class TestProductCRUD:
    """Test full CRUD operations against sandbox"""
    
    def test_create_product(self, wc_client, test_product_data, cleanup_test_products):
        """Test creating a product in WooCommerce"""
        product = wc_client.create_product(test_product_data)
        cleanup_test_products.append(product['id'])
        
        assert product['id'] > 0
        assert product['name'] == test_product_data['name']
        assert product['sku'] == test_product_data['sku']
        assert product['status'] == 'publish'
    
    def test_get_product(self, wc_client, test_product_data, cleanup_test_products):
        """Test retrieving a product"""
        # Create product first
        created = wc_client.create_product(test_product_data)
        cleanup_test_products.append(created['id'])
        
        # Retrieve it
        retrieved = wc_client.get_product(created['id'])
        
        assert retrieved['id'] == created['id']
        assert retrieved['name'] == test_product_data['name']
    
    def test_update_product(self, wc_client, test_product_data, cleanup_test_products):
        """Test updating a product"""
        # Create product
        product = wc_client.create_product(test_product_data)
        cleanup_test_products.append(product['id'])
        
        # Update it
        updated = wc_client.update_product(product['id'], {
            'regular_price': '1299.99',
            'stock_quantity': 3
        })
        
        assert updated['regular_price'] == '1299.99'
        assert updated['stock_quantity'] == 3
    
    def test_delete_product(self, wc_client, test_product_data):
        """Test deleting a product"""
        # Create product
        product = wc_client.create_product(test_product_data)
        
        # Delete it
        deleted = wc_client.delete_product(product['id'], force=True)
        
        assert deleted['id'] == product['id']
        
        # Verify it's gone
        with pytest.raises(Exception):
            wc_client.get_product(product['id'])
    
    def test_batch_create_products(self, wc_client, cleanup_test_products):
        """Test batch product creation"""
        products_to_create = [
            {
                'name': f'Batch Test Product {i}',
                'sku': f'BATCH-TEST-{i}',
                'regular_price': '100.00',
                'meta_data': [{'key': '_test_product', 'value': 'true'}]
            }
            for i in range(5)
        ]
        
        result = wc_client.batch_products(create=products_to_create)
        
        assert len(result['create']) == 5
        for product in result['create']:
            cleanup_test_products.append(product['id'])
```

#### Example: test_sync_flow.py
```python
import pytest
from src.integrations.woocommerce.sync_manager import WooCommerceSyncManager

class TestBidirectionalSync:
    """Test full sync flows"""
    
    @pytest.fixture
    def sync_manager(self, wc_client):
        """Create sync manager instance"""
        return WooCommerceSyncManager(wc_client)
    
    def test_riff_to_woocommerce_sync(self, sync_manager, cleanup_test_products):
        """Test syncing a RIFF product to WooCommerce"""
        riff_product = {
            'id': 'riff-test-12345',
            'title': 'Test Sync Guitar',
            'sku': 'SYNC-TEST-001',
            'price': 1499.99,
            'quantity': 2,
            'description': 'Testing bidirectional sync'
        }
        
        wc_product_id = sync_manager.sync_to_woocommerce(riff_product)
        cleanup_test_products.append(wc_product_id)
        
        # Verify product was created in WooCommerce
        wc_product = sync_manager.wc_client.get_product(wc_product_id)
        
        assert wc_product['name'] == 'Test Sync Guitar'
        assert wc_product['sku'] == 'SYNC-TEST-001'
        
        # Verify RIFF ID is stored in meta_data
        riff_id_meta = next(
            (m for m in wc_product['meta_data'] if m['key'] == '_riff_id'),
            None
        )
        assert riff_id_meta['value'] == 'riff-test-12345'
    
    def test_woocommerce_to_riff_sync(self, sync_manager, wc_client, cleanup_test_products):
        """Test importing a WooCommerce product to RIFF"""
        # Create product in WooCommerce
        wc_product = wc_client.create_product({
            'name': 'WC Origin Product',
            'sku': 'WC-ORIGIN-001',
            'regular_price': '799.99',
            'stock_quantity': 1
        })
        cleanup_test_products.append(wc_product['id'])
        
        # Import to RIFF
        riff_product = sync_manager.sync_from_woocommerce(wc_product['id'])
        
        assert riff_product['title'] == 'WC Origin Product'
        assert riff_product['sku'] == 'WC-ORIGIN-001'
        assert riff_product['price'] == 799.99
    
    def test_update_sync(self, sync_manager, wc_client, cleanup_test_products):
        """Test syncing updates bidirectionally"""
        # Create product from RIFF
        riff_product = {
            'id': 'riff-update-test',
            'title': 'Original Title',
            'sku': 'UPDATE-TEST-001',
            'price': 500.00,
            'quantity': 5
        }
        
        wc_id = sync_manager.sync_to_woocommerce(riff_product)
        cleanup_test_products.append(wc_id)
        
        # Update in RIFF
        riff_product['price'] = 550.00
        riff_product['quantity'] = 3
        
        # Sync update
        sync_manager.sync_to_woocommerce(riff_product)
        
        # Verify update in WooCommerce
        wc_product = wc_client.get_product(wc_id)
        assert wc_product['regular_price'] == '550.00'
        assert wc_product['stock_quantity'] == 3
```

---

### Layer 3: Mock Tests (Recorded Responses)
**Location**: `tests/mocks/woocommerce/`
**Purpose**: Fast tests using recorded HTTP responses for edge cases
**Run Frequency**: On every commit, in CI/CD

#### Setup VCR.py for Recording Responses
```python
# conftest.py
import pytest
import vcr

@pytest.fixture(scope='module')
def vcr_config():
    return {
        'filter_headers': ['authorization'],
        'record_mode': 'once',  # Record once, then replay
    }

@pytest.fixture
def vcr_cassette(vcr_config):
    """VCR cassette for recording/replaying HTTP interactions"""
    return vcr.VCR(**vcr_config)
```

#### Example: test_edge_cases.py
```python
import pytest
import vcr

class TestEdgeCases:
    """Test edge cases using recorded responses"""
    
    @vcr.use_cassette('tests/mocks/woocommerce/fixtures/duplicate_sku.yaml')
    def test_duplicate_sku_error(self, wc_client):
        """Test handling of duplicate SKU error"""
        from src.integrations.woocommerce.exceptions import DuplicateSKUError
        
        with pytest.raises(DuplicateSKUError):
            wc_client.create_product({
                'name': 'Test Product',
                'sku': 'DUPLICATE-SKU-001',
                'regular_price': '100.00'
            })
    
    @vcr.use_cassette('tests/mocks/woocommerce/fixtures/rate_limit.yaml')
    def test_rate_limit_retry(self, wc_client):
        """Test automatic retry on rate limit"""
        # This cassette contains a 429 response followed by success
        product = wc_client.get_products()
        assert product is not None
```

---

## Running the Tests

### Environment Variables
```bash
# .env.test
WC_SANDBOX_URL=https://your-sandbox-store.com
WC_SANDBOX_CONSUMER_KEY=ck_xxxxxxxxxxxxx
WC_SANDBOX_CONSUMER_SECRET=cs_xxxxxxxxxxxxx
WC_WEBHOOK_SECRET=test_webhook_secret_123
```

### Command Examples
```bash
# Run only unit tests (fast)
pytest tests/unit/woocommerce/ -v

# Run integration tests (requires sandbox)
pytest tests/integration/woocommerce/ -v --tb=short

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src/integrations/woocommerce --cov-report=html

# Run specific test file
pytest tests/unit/woocommerce/test_data_mapping.py -v

# Run tests matching pattern
pytest -k "test_product" -v
```

### CI/CD Pipeline Configuration
```yaml
# .github/workflows/test-woocommerce.yml
name: WooCommerce Integration Tests

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      - name: Run unit tests
        run: pytest tests/unit/woocommerce/ -v --cov
  
  integration-tests:
    runs-on: ubuntu-latest
    # Only run if sandbox credentials are available
    if: ${{ secrets.WC_SANDBOX_URL != '' }}
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
      - name: Run integration tests
        env:
          WC_SANDBOX_URL: ${{ secrets.WC_SANDBOX_URL }}
          WC_SANDBOX_CONSUMER_KEY: ${{ secrets.WC_SANDBOX_CONSUMER_KEY }}
          WC_SANDBOX_CONSUMER_SECRET: ${{ secrets.WC_SANDBOX_CONSUMER_SECRET }}
        run: pytest tests/integration/woocommerce/ -v
```

## Coverage Goals

- **Unit Tests**: Aim for 90%+ code coverage
- **Integration Tests**: Cover all critical user flows
- **Mock Tests**: Cover edge cases and error scenarios

## Test Data Management

### Creating Test Fixtures
```python
# tests/fixtures/products.py
SAMPLE_RIFF_PRODUCT = {
    'id': 'riff-fixture-001',
    'title': 'Fender Stratocaster 1960',
    'sku': 'FIXTURE-STRAT-001',
    'price': 3299.99,
    'quantity': 1,
    'description': 'Beautiful vintage Stratocaster',
    'images': [
        'https://example.com/strat1.jpg',
        'https://example.com/strat2.jpg'
    ]
}

SAMPLE_WC_PRODUCT_RESPONSE = {
    'id': 999,
    'name': 'Fender Stratocaster 1960',
    'sku': 'FIXTURE-STRAT-001',
    'price': '3299.99',
    'stock_quantity': 1,
    'meta_data': [
        {'key': '_riff_id', 'value': 'riff-fixture-001'}
    ]
}
```

### Cleanup Strategy
```python
# Always use cleanup fixtures to remove test data
@pytest.fixture(autouse=True)
def cleanup_after_test(wc_client):
    """Auto-cleanup fixture"""
    yield
    # Delete all products with _test_product meta
    test_products = wc_client.get_products(params={
        'meta_key': '_test_product',
        'meta_value': 'true'
    })
    for product in test_products:
        wc_client.delete_product(product['id'], force=True)
```

## Debugging Failed Tests

### Enable Verbose Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# In your client
logger = logging.getLogger('woocommerce.client')
logger.debug(f'Request: {method} {url}')
logger.debug(f'Response: {response.text}')
```

### Pytest Debugging Flags
```bash
# Show print statements
pytest -s

# Drop into debugger on failure
pytest --pdb

# Show local variables in tracebacks
pytest -l

# Stop on first failure
pytest -x
```

This comprehensive testing strategy ensures the WooCommerce integration is robust, reliable, and ready for production (after OAuth implementation).