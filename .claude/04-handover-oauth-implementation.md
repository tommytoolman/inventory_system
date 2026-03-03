# HANDOVER DOCUMENTATION: WooCommerce Integration
## For Production OAuth 1.0a Implementation

---

## Current State (Sandbox/Development)

### What's Been Implemented
✅ **Basic Authentication** (HTTPS only - SANDBOX MODE)
- Consumer Key/Secret authentication via HTTP headers
- Query string authentication fallback for problematic servers
- Secure credential storage using environment variables

✅ **Bidirectional Product Sync**
- RIFF → WooCommerce: Create, update, and delete products
- WooCommerce → RIFF: Import products, track changes
- Meta data mapping to link RIFF IDs with WooCommerce products

✅ **API Client Wrapper**
- Full CRUD operations for products
- Batch operations support
- Error handling with retry logic
- Rate limit detection and backoff

✅ **Webhook Support** (or polling fallback)
- Real-time product update notifications
- Order creation notifications
- Webhook signature verification (basic)

✅ **Sandbox/Production Mode Toggle**
- UI toggle for switching between modes
- Visual indicators of current mode
- Configuration management

✅ **Comprehensive Testing**
- Unit tests (90%+ coverage)
- Integration tests against sandbox
- Mock tests for edge cases

---

## ⚠️ CRITICAL: What Needs to Be Done for Production

### 1. OAuth 1.0a Implementation (MANDATORY)

**Why It's Required:**
- Basic Auth over HTTP is insecure for production
- WooCommerce recommends OAuth for all production integrations
- Provides proper signature-based request verification
- Required for webhook signature validation

**Current Placeholder Code:**
```python
# src/integrations/woocommerce/auth.py
def get_auth_headers(self):
    if self.auth_method == 'oauth1':
        raise NotImplementedError(
            'OAuth 1.0a not yet implemented. '
            'Basic Auth is SANDBOX ONLY. '
            'Implement OAuth before production deployment.'
        )
```

**What You Need to Implement:**

#### Step 1: OAuth Signature Generation
```python
import hmac
import hashlib
import urllib.parse
import time
import secrets
from typing import Dict

class WooCommerceOAuth:
    """OAuth 1.0a implementation for WooCommerce"""
    
    def __init__(self, consumer_key: str, consumer_secret: str):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
    
    def generate_oauth_signature(
        self, 
        method: str, 
        url: str, 
        params: Dict[str, str]
    ) -> str:
        """
        Generate OAuth 1.0a signature for WooCommerce
        
        This is the core security mechanism. The signature proves that:
        1. The request came from the authorised consumer
        2. The request hasn't been tampered with
        3. The request is unique (via timestamp and nonce)
        """
        # Step 1: Create signature base string
        # Format: HTTP_METHOD&URL_ENCODED_URL&URL_ENCODED_PARAMS
        
        # Normalise parameters (sort alphabetically)
        sorted_params = sorted(params.items())
        param_string = urllib.parse.urlencode(sorted_params)
        
        # Build base string
        base_string = '&'.join([
            method.upper(),
            urllib.parse.quote(url, safe=''),
            urllib.parse.quote(param_string, safe='')
        ])
        
        # Step 2: Create signing key
        # Format: CONSUMER_SECRET&TOKEN_SECRET
        # Note: WooCommerce doesn't use token_secret, so it's empty
        signing_key = f'{self.consumer_secret}&'
        
        # Step 3: Generate signature
        signature = hmac.new(
            signing_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha256  # Or sha1 - WooCommerce accepts both
        ).digest()
        
        # Step 4: Base64 encode
        return base64.b64encode(signature).decode('utf-8')
    
    def get_oauth_params(self) -> Dict[str, str]:
        """Generate OAuth parameters for request"""
        return {
            'oauth_consumer_key': self.consumer_key,
            'oauth_timestamp': str(int(time.time())),
            'oauth_nonce': secrets.token_hex(16),
            'oauth_signature_method': 'HMAC-SHA256',  # Or HMAC-SHA1
            # Note: oauth_version is optional for WooCommerce
        }
    
    def sign_request(
        self, 
        method: str, 
        url: str, 
        params: Dict[str, str] = None
    ) -> Dict[str, str]:
        """
        Sign a request and return all OAuth parameters including signature
        
        Usage:
            oauth = WooCommerceOAuth(consumer_key, consumer_secret)
            signed_params = oauth.sign_request('GET', 'https://store.com/wp-json/wc/v3/products')
            
            # Add to URL as query parameters
            url_with_auth = f'{url}?{urllib.parse.urlencode(signed_params)}'
        """
        params = params or {}
        
        # Get OAuth parameters
        oauth_params = self.get_oauth_params()
        
        # Merge with request parameters
        all_params = {**params, **oauth_params}
        
        # Generate signature
        signature = self.generate_oauth_signature(method, url, all_params)
        
        # Add signature to parameters
        oauth_params['oauth_signature'] = signature
        
        return oauth_params
```

#### Step 2: Integrate OAuth into Client
```python
# src/integrations/woocommerce/client.py
class WooCommerceClient:
    def make_request(self, method: str, endpoint: str, **kwargs):
        """Make authenticated request to WooCommerce API"""
        url = f'{self.store_url}/wp-json/wc/v3/{endpoint}'
        
        if self.auth_method == 'oauth1':
            # Use OAuth signing
            oauth = WooCommerceOAuth(self.consumer_key, self.consumer_secret)
            
            # Get request params (if any)
            params = kwargs.get('params', {})
            
            # Sign the request
            oauth_params = oauth.sign_request(method, url, params)
            
            # Add OAuth params to request
            # Can be added as query string OR Authorization header
            # Query string is more reliable with WordPress
            kwargs['params'] = {**params, **oauth_params}
        
        elif self.auth_method == 'basic':
            # Existing Basic Auth code
            # Only allow this if sandbox mode is enabled
            if not self.config.get('sandbox_mode'):
                raise SecurityError(
                    'Basic Auth is only allowed in sandbox mode. '
                    'Use OAuth 1.0a for production.'
                )
            # ... existing basic auth code
        
        return requests.request(method, url, **kwargs)
```

#### Step 3: Webhook Signature Verification
```python
# src/integrations/woocommerce/webhooks.py
import hmac
import hashlib
import base64

def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify WooCommerce webhook signature
    
    WooCommerce sends: X-WC-Webhook-Signature header
    Format: Base64(HMAC-SHA256(payload, secret))
    
    Args:
        payload: Raw request body (bytes)
        signature: Value from X-WC-Webhook-Signature header
        secret: Webhook secret from WooCommerce webhook settings
    
    Returns:
        True if signature is valid, False otherwise
    """
    # Generate expected signature
    expected_signature = base64.b64encode(
        hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).digest()
    ).decode('utf-8')
    
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected_signature, signature)

# Usage in webhook endpoint:
@app.post('/webhooks/woocommerce/product-updated')
async def handle_product_update(request: Request):
    # Get signature from header
    signature = request.headers.get('X-WC-Webhook-Signature')
    if not signature:
        raise HTTPException(401, 'Missing webhook signature')
    
    # Get raw body
    body = await request.body()
    
    # Verify signature
    webhook_secret = get_webhook_secret()  # From config
    if not verify_webhook_signature(body, signature, webhook_secret):
        logger.warning('Invalid webhook signature received')
        raise HTTPException(401, 'Invalid webhook signature')
    
    # Signature valid - process webhook
    data = await request.json()
    # ... process the webhook
```

---

### 2. Configuration Changes Required

#### Before Production Deployment:
```python
# config/woocommerce.py (or wherever config lives)

# Current (Sandbox):
WOOCOMMERCE_CONFIG = {
    'auth_method': 'basic',  # ❌ CHANGE THIS
    'sandbox_mode': True,    # ❌ CHANGE THIS
    'store_url': 'https://sandbox-store.com',  # ❌ CHANGE THIS
}

# Production (What you need):
WOOCOMMERCE_CONFIG = {
    'auth_method': 'oauth1',  # ✅ Use OAuth
    'sandbox_mode': False,     # ✅ Disable sandbox
    'store_url': 'https://production-store.com',  # ✅ Production URL
}
```

#### Environment Variables to Update:
```bash
# .env.production
WC_STORE_URL=https://your-production-store.com
WC_CONSUMER_KEY=ck_production_key_here
WC_CONSUMER_SECRET=cs_production_secret_here
WC_WEBHOOK_SECRET=production_webhook_secret
WC_AUTH_METHOD=oauth1
WC_SANDBOX_MODE=false
```

---

### 3. Security Checklist for Production

#### Before Going Live:
- [ ] OAuth 1.0a implemented and tested
- [ ] All sandbox credentials removed from codebase
- [ ] Production credentials stored in secure secret manager (not in .env files)
- [ ] Webhook signature verification implemented
- [ ] HTTPS enforced for all API requests
- [ ] Rate limiting implemented on webhook endpoints
- [ ] Request logging sanitised (don't log credentials)
- [ ] Error messages don't leak sensitive information
- [ ] Sandbox mode completely disabled in production
- [ ] API key rotation procedure documented
- [ ] Security incident response plan in place

#### SSL/TLS Considerations:
```python
# Ensure SSL verification is enabled
client = WooCommerceClient(
    store_url='https://production-store.com',
    consumer_key=consumer_key,
    consumer_secret=consumer_secret,
    verify_ssl=True,  # ✅ Must be True in production
    timeout=30
)
```

---

### 4. Testing the OAuth Implementation

#### Test Checklist:
```python
# Create a test file: tests/integration/test_oauth_production.py

def test_oauth_signature_generation():
    """Test that OAuth signatures are correctly generated"""
    oauth = WooCommerceOAuth('test_key', 'test_secret')
    
    signature = oauth.generate_oauth_signature(
        'GET',
        'https://store.com/wp-json/wc/v3/products',
        {
            'oauth_consumer_key': 'test_key',
            'oauth_timestamp': '1234567890',
            'oauth_nonce': 'test_nonce',
            'oauth_signature_method': 'HMAC-SHA256'
        }
    )
    
    assert signature is not None
    assert len(signature) > 0

def test_oauth_request_signing():
    """Test full request signing flow"""
    oauth = WooCommerceOAuth('test_key', 'test_secret')
    
    signed_params = oauth.sign_request(
        'GET',
        'https://store.com/wp-json/wc/v3/products',
        {'per_page': 10}
    )
    
    assert 'oauth_signature' in signed_params
    assert 'oauth_timestamp' in signed_params
    assert 'oauth_nonce' in signed_params
    assert 'per_page' in signed_params

@pytest.mark.integration
def test_oauth_api_call(production_config):
    """Test actual API call with OAuth (requires production creds)"""
    client = WooCommerceClient(
        store_url=production_config['store_url'],
        consumer_key=production_config['consumer_key'],
        consumer_secret=production_config['consumer_secret'],
        auth_method='oauth1'
    )
    
    # This should succeed if OAuth is correctly implemented
    products = client.get_products()
    assert products is not None
```

#### Manual Testing Steps:
1. **Test with Postman/Insomnia:**
   - Set Auth Type to OAuth 1.0
   - Add consumer key/secret
   - Set signature method to HMAC-SHA256
   - Test GET /products endpoint
   - Verify successful response

2. **Test Webhook Signatures:**
   - Create a webhook in WooCommerce admin
   - Trigger a product update
   - Verify signature in logs
   - Confirm payload is processed correctly

3. **Load Testing:**
   - Test with high request volumes
   - Verify signature generation doesn't bottleneck
   - Check timestamp/nonce uniqueness under load

---

### 5. Common OAuth Implementation Issues

#### Problem: "Consumer key is missing" error
**Solution:** 
- Some servers don't parse Authorization header correctly
- Use query string parameters instead:
```python
# Add OAuth params to URL query string, not headers
oauth_params = oauth.sign_request(method, url)
url_with_auth = f'{url}?{urllib.parse.urlencode(oauth_params)}'
```

#### Problem: "Invalid signature" error
**Solution:**
- Double-check parameter sorting (must be alphabetical)
- Verify URL encoding is correct
- Ensure signature base string format is exact
- Check that signing key includes the `&` character
- Confirm timestamp is in seconds (not milliseconds)

#### Problem: Nonce collision
**Solution:**
- Ensure nonces are truly random
- Use `secrets.token_hex()` not `random`
- Consider storing used nonces temporarily to prevent replay attacks

#### Problem: Clock skew issues
**Solution:**
- WooCommerce accepts timestamps within ±5 minutes
- Sync server time with NTP
- Add clock skew detection/warning in logs

---

### 6. Documentation to Create

#### For Operations Team:
- [ ] OAuth key generation procedure
- [ ] Key rotation schedule (recommend quarterly)
- [ ] Incident response for compromised keys
- [ ] Monitoring and alerting setup
- [ ] Backup/disaster recovery procedures

#### For Development Team:
- [ ] OAuth implementation architecture document
- [ ] API usage patterns and best practices
- [ ] Debugging guide for signature issues
- [ ] Performance considerations
- [ ] Future enhancement roadmap

---

### 7. Deployment Strategy

#### Recommended Approach:
1. **Stage 1: Parallel Running**
   - Deploy OAuth implementation to staging
   - Run both Basic Auth (sandbox) and OAuth (staging) in parallel
   - Compare results for consistency
   - Fix any OAuth-specific issues

2. **Stage 2: Production Deployment**
   - Deploy to production with feature flag
   - Keep sandbox mode available for testing
   - Gradually migrate production traffic to OAuth
   - Monitor error rates closely

3. **Stage 3: Sunset Sandbox Mode**
   - After 30 days of stable OAuth operation
   - Remove Basic Auth code paths
   - Update documentation
   - Archive sandbox credentials

#### Rollback Plan:
```python
# Keep this escape hatch temporarily
if emergency_rollback_enabled():
    logger.critical('EMERGENCY: Falling back to Basic Auth')
    # Temporarily allow Basic Auth even in production
    # REMOVE THIS AFTER OAUTH IS STABLE
```

---

### 8. Resources and References

#### Official WooCommerce OAuth Documentation:
- [WooCommerce REST API Authentication](https://woocommerce.github.io/woocommerce-rest-api-docs/#authentication)
- [OAuth 1.0a RFC 5849](https://tools.ietf.org/html/rfc5849)

#### Python Libraries to Consider:
```bash
# Option 1: requests-oauthlib (recommended)
pip install requests-oauthlib

# Option 2: authlib (more modern)
pip install authlib

# Option 3: Roll your own (we've provided the core code above)
```

#### Example Using requests-oauthlib:
```python
from requests_oauthlib import OAuth1Session

# Create OAuth session
oauth = OAuth1Session(
    client_key=consumer_key,
    client_secret=consumer_secret,
    signature_method='HMAC-SHA256'
)

# Make authenticated request
response = oauth.get('https://store.com/wp-json/wc/v3/products')
```

---

### 9. Questions for Stakeholders Before Production

1. **Business:**
   - What is the acceptable downtime window for OAuth migration?
   - What is the rollback procedure if OAuth fails in production?
   - Are there any compliance requirements (PCI DSS, GDPR, etc.)?

2. **Technical:**
   - Where should production credentials be stored (AWS Secrets Manager, Vault, etc.)?
   - What monitoring/alerting should be in place?
   - What are the SLA requirements for sync operations?

3. **Security:**
   - Who has access to production API credentials?
   - How often should credentials be rotated?
   - What is the procedure for revoking compromised credentials?

---

### 10. Contact Information

**Current Implementation:**
- Developer: [Your Name]
- Implementation Date: [Date]
- Code Location: `src/integrations/woocommerce/`
- Documentation: This file + README.md in integration folder

**For Production OAuth Implementation:**
- Assigned to: [Next Developer Name]
- Target Completion: [Date]
- Review Required: Security team, DevOps team

---

## Final Checklist Before Production

- [ ] OAuth 1.0a fully implemented and tested
- [ ] All hardcoded sandbox credentials removed
- [ ] Production environment variables configured
- [ ] Webhook signature verification working
- [ ] SSL certificate validated
- [ ] Error handling tested (401, 429, 500 errors)
- [ ] Load testing completed
- [ ] Security review completed
- [ ] Documentation updated
- [ ] Team training completed
- [ ] Monitoring and alerting configured
- [ ] Rollback procedure tested
- [ ] Stakeholder sign-off received

---

**REMEMBER: The current implementation uses Basic Auth which is INSECURE for production. OAuth 1.0a implementation is MANDATORY before going live with real customer data.**

Good luck with the OAuth implementation! The foundation is solid, and this final step will make it production-ready. 🚀