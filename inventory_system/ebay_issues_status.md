# eBay Integration Issues - Status Report
*Date: 2025-09-08*

## Summary
Working on creating a unified, flexible eBay listing creation process that supports both sandbox testing and production, with configurable shipping options (profiles vs hardcoded).

## What We've Accomplished

### 1. ✅ Fixed Shopify Extended Attributes
- **Problem**: `extended_attributes` in shopify_listings table were empty
- **Root Cause**: Bug in `process_sync_event.py` line 611 - was checking `'product' in full_product` but API returns product directly
- **Solution**: Store `full_product` directly as extended_attrs
- **Result**: Now properly stores URLs, categories, SEO fields from Shopify API

### 2. ✅ Enhanced eBay Service for Flexibility
- **File**: `app/services/ebay_service.py`
- **Enhancement**: `create_listing_from_product()` now supports:
  - `sandbox` parameter for testing
  - `use_shipping_profile` flag to toggle between profiles and inline shipping
  - `shipping_profile_id`, `payment_profile_id`, `return_profile_id` for business policies
  - `shipping_details` for hardcoded shipping costs
  - `dry_run` parameter for testing without creating listings

### 3. ✅ Updated Process Sync Event Script
- **File**: `scripts/process_sync_event.py`
- **Changes**:
  - Added `--sandbox` flag support
  - Protection against updating sync_events status in sandbox mode
  - Passes sandbox parameter through to ebay_service

### 4. ✅ Generated New Sandbox Tokens
- **Problem**: Sandbox refresh token showing 514 days valid but returning "invalid_grant"
- **Solution**: Generated completely new sandbox tokens
- **Result**: 
  - Refresh Token: Valid for 547 days
  - Access Token: Valid for 119 minutes
  - Tokens saved to: `ebay_sandbox_tokens.json`

### 5. ✅ Organized Token Management
- Created `/scripts/ebay/auth_token/` directory
- Added comprehensive `README.md` explaining eBay's 3-token system
- Created `exchange_sandbox_code.py` for secure token generation
- Uses `getpass` for secure URL input (no command history exposure)

## Current Issues

### 1. 🔴 Sync Event Processing for eBay
- **Problem**: Sync events with status 'partial' are being skipped
- **Event ID**: 12292 (test case)
- **Need**: Process partial sync_events for eBay platform specifically
- **Note**: The `--retry-errors` flag should handle this but needs verification

### 2. 🟡 eBay Listings Table Entry
- **Issue**: Need to ensure ebay_listings table entry is created when listing succeeds
- **Location**: TODO comment in the code
- **Status**: Not yet implemented

### 3. 🟡 Configuration Management
- **Need**: Centralized configuration for:
  - Shipping profile IDs (production vs sandbox)
  - Payment profile IDs
  - Return profile IDs
- **Current**: These would need to be passed as parameters

## Key Design Decisions Made

1. **Single Creation Process**: Unified approach instead of multiple code paths
2. **Highly Configurable**: Support both shipping profiles AND hardcoded shipping
3. **Sandbox Safety**: Never update sync_events status when in sandbox mode
4. **Token Security**: Use secure prompts instead of command-line arguments for sensitive data
5. **NOT Reinventing**: Use existing ebay_service.py and trading.py capabilities

## File Structure
```
scripts/ebay/
├── auth_token/
│   ├── README.md                    # Complete token system documentation
│   ├── exchange_sandbox_code.py     # Secure token exchange script
│   └── get_sandbox_token.py         # Initial token generation
├── check_token_status.py           # (existing, hardcoded to production)
├── exchange_code_for_refresh_token.py  # (existing, hardcoded to sandbox)
├── generate_token.py                # (existing, hardcoded to production)
└── renew_ebay_sandbox_token.py     # (existing, sandbox only)
```

## Token Files
- Production: `app/services/ebay/tokens/ebay_tokens.json`
- Sandbox: `app/services/ebay/tokens/ebay_sandbox_tokens.json`

## Testing Commands

### Check Token Status
```bash
python scripts/ebay/auth_token/exchange_sandbox_code.py  # Prompts for URL securely
```

### Process Sync Event (Sandbox)
```bash
python scripts/process_sync_event.py --event-id 12292 --platforms ebay --sandbox --retry-errors
```

## Next Steps When Returning

1. **Fix Partial Status Processing**
   - Ensure --retry-errors flag works for 'partial' status
   - OR add specific handling for partial eBay events

2. **Test Full eBay Creation Flow**
   - Use event 12292 as test case
   - Verify listing appears in sandbox
   - Confirm NO database updates in sandbox mode

3. **Implement eBay Listings Table Entry**
   - Add code to create ebay_listings record after successful API call
   - Link to product and store eBay item ID

4. **Add Configuration Management**
   - Consider adding to CLAUDE.md or config file:
     - Sandbox shipping/payment/return profile IDs
     - Production shipping/payment/return profile IDs
   - OR create a mapping in the database

5. **Clean Up Old Token Scripts**
   - Consider deprecating the individual scripts
   - Move to unified token management approach

## Important Notes

- **Sandbox URL**: https://sandbox.ebay.com
- **Sandbox Tokens**: Now valid and working (547 days remaining)
- **Database Connection**: Use `postgresql+asyncpg://postgres:postgres@localhost/inventory_system`
- **Key Principle**: Don't reinvent the wheel - use existing services

## Error Patterns Encountered

1. **"invalid_grant"**: Token for wrong environment or expired
2. **"relation sync_events does not exist"**: Table name is `sync_event` (singular)
3. **Database connection issues**: Need correct connection string
4. **EOF errors in scripts**: Can't use interactive input in non-TTY environment

---

*This document captures the current state of eBay integration work. Pick up from "Next Steps" section when returning to this task.*