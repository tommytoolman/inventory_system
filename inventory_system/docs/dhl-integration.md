# DHL Express Integration

*Status: In Progress (paused pending DHL password reset)*
*Last updated: 2026-01-02*

## Overview

DHL Express shipping label integration allowing label generation directly from the orders page for Reverb, eBay, and Shopify orders.

## Completed Work

### 1. DHLPayloadBuilder Service
**File:** `app/services/shipping/payload_builder.py`

Converts marketplace orders to DHL API payloads with:
- Destination classification (UK Domestic / EU / International)
- Receiver details extraction from Reverb, eBay, Shopify orders
- Package dimensions and weight
- Customs declarations for international shipments
- HS codes for musical instruments (default: `9202900030`)

**Product Codes:**
| Code | Service | Use Case |
|------|---------|----------|
| `N` | DOM - Domestic Express | UK to UK |
| `P` | WPX - Express Worldwide | International (products) |
| `U` | ECX - Express Worldwide EU | EU destinations (optional) |
| `D` | DOX - Express Worldwide | Documents only |

### 2. Configuration Settings
**File:** `app/core/config.py`

Added shipper configuration variables:
```
DHL_SHIPPER_COMPANY      # Company name
DHL_SHIPPER_CONTACT      # Contact person
DHL_SHIPPER_EMAIL        # Email
DHL_SHIPPER_PHONE        # Phone (format: 442071234567)
DHL_SHIPPER_ADDRESS1     # Street address
DHL_SHIPPER_ADDRESS2     # Address line 2 (optional)
DHL_SHIPPER_CITY         # City
DHL_SHIPPER_POSTCODE     # Postal code
DHL_SHIPPER_VAT          # GB VAT number (for EU customs)
DHL_SHIPPER_EORI         # EORI number (for international customs)
```

### 3. Orders List UI Enhancement
**File:** `app/templates/orders/list.html`

- Added shipping truck icon in Actions column
- Amber icon = Ready to ship (links to shipping page)
- Grey icon = Already shipped or cancelled
- Removed SKU column, expanded item description
- Product link shows grey strikethrough for deposit/payment orders

### 4. Shipping Label Page
**Files:**
- `app/routes/orders.py` - Added `/{platform}/{order_id}/ship` route
- `app/templates/orders/ship.html` - Shipping form template

Features:
- Destination type banner (UK/EU/International with colour coding)
- Sender details display (from config)
- Receiver details display (from order)
- Package dimensions form (weight, L×W×H)
- Customs declaration section (for international)
- Sandbox mode checkbox
- Request pickup option

## Remaining Work

### Blocked On
- [ ] DHL account password reset (user action required)

### To Complete
1. **Add shipper details to `.env`:**
   ```bash
   DHL_SHIPPER_PHONE=44XXXXXXXXXX
   DHL_SHIPPER_ADDRESS1=Your actual street address
   DHL_SHIPPER_POSTCODE=Your postcode
   DHL_SHIPPER_VAT=GB123456789
   DHL_SHIPPER_EORI=GB123456789000
   ```

2. **POST route for label creation** (`/orders/{platform}/{order_id}/ship/create`)
   - Call DHL API with built payload
   - Store shipment in `shipments` table
   - Return label PDF for download/print
   - Update order with tracking number

3. **Railway environment variables**
   - Add all `DHL_SHIPPER_*` variables
   - Set `DHL_TEST_MODE=false` for production

## API Reference

### DHL Express MyDHL API
- **Sandbox:** `https://express.api.dhl.com/mydhlapi/test`
- **Production:** `https://express.api.dhl.com/mydhlapi`
- **Docs:** https://developer.dhl.com/api-reference/dhl-express-mydhl-api

Same credentials work for both environments - the URL determines sandbox vs production.

### Payload Structure
```json
{
  "plannedShippingDateAndTime": "2026-01-05T10:00:00 GMT+00:00",
  "pickup": {"isRequested": false},
  "productCode": "P",
  "accounts": [{"number": "427879232", "typeCode": "shipper"}],
  "outputImageProperties": {
    "printerDPI": 300,
    "encodingFormat": "pdf",
    "imageOptions": [
      {"typeCode": "waybillDoc", "templateName": "ARCH_8x4", "isRequested": true},
      {"typeCode": "label", "templateName": "ECOM26_84_001", "isRequested": true},
      {"typeCode": "invoice", "templateName": "COMMERCIAL_INVOICE_P_10", "isRequested": true}
    ]
  },
  "customerDetails": {
    "shipperDetails": {...},
    "receiverDetails": {...}
  },
  "content": {
    "packages": [{...}],
    "isCustomsDeclarable": true,
    "declaredValue": 17500.0,
    "declaredValueCurrency": "GBP",
    "exportDeclaration": {...}
  }
}
```

## Files Modified/Created

| File | Change |
|------|--------|
| `app/services/shipping/payload_builder.py` | NEW - DHL payload builder |
| `app/core/config.py` | Added DHL_SHIPPER_* settings |
| `app/routes/orders.py` | Added /ship route |
| `app/templates/orders/ship.html` | NEW - Shipping form |
| `app/templates/orders/list.html` | Added shipping icon, removed SKU |
