# Field Mapping: RIFF → Platform Sync

*Last updated: 2026-01-07*

This document describes how product fields in RIFF sync to Shopify and eBay.

## Field Mapping Table

| RIFF Field | Shopify | eBay |
|------------|---------|------|
| `title` | Product title | Item title |
| `description` | `descriptionHtml` | Item description |
| `base_price` | Variant price | StartPrice |
| `quantity` | Inventory level | Quantity |
| `finish` | `custom.colour_finish` metafield + tag | Body Colour + Colour item specifics |
| `year` | `custom.year` metafield + tag | Year item specific |
| `condition` | `custom.condition` metafield + tag (formatted) | ConditionID (separate system) |
| `handedness` | `custom.handedness` metafield + "Left-Handed" tag | Handedness item specific |
| `artist_owned` | `guitar_specs.artist_owned` metafield | Artist Owned item specific ("Yes") |
| `artist_names` | `custom.artist_names` metafield | Artist Names item specific |
| `manufacturing_country` | Country of Origin (inventory item) | Country of Origin + Country/Region of Manufacture |

## Shopify Details

### Metafields

All product metafields use namespace `custom` unless noted:

| Key | Type | Notes |
|-----|------|-------|
| `colour_finish` | `single_line_text_field` | Product's finish/colour |
| `year` | `single_line_text_field` | Year of manufacture (can be decade e.g. "1960s") |
| `condition` | `single_line_text_field` | Formatted: "verygood" → "Very Good" |
| `handedness` | `single_line_text_field` | "Left" or "Right" |
| `artist_names` | `multi_line_text_field` | Newline-separated list |
| `artist_owned` | `boolean` | Namespace: `guitar_specs` |

### Tags

Tags are added for:
- Year (e.g., "1965", "1970s")
- Finish (e.g., "Sunburst", "Natural")
- Condition (e.g., "Excellent", "Very Good")
- "Left-Handed" when handedness is LEFT

### Clearing Values

When artist_owned is unchecked or artist_names cleared, the metafields are **deleted** from Shopify using the `metafieldsDelete` mutation (not just set to empty).

## eBay Details

### Item Specifics

| Field | Notes |
|-------|-------|
| Year | From `year` (as string) |
| Body Colour | From `finish` |
| Colour | From `finish` (duplicate for eBay UK compatibility) |
| Handedness | "Left Handed" or "Right Handed" |
| Country of Origin | From `manufacturing_country` |
| Country/Region of Manufacture | From `manufacturing_country` (duplicate) |
| Artist Owned | "Yes" when true, omitted when false |
| Artist Names | Comma-separated, max 65 chars |

### Condition

eBay condition is handled separately via `ConditionID` (numeric) based on eBay category requirements, not via item specifics.

## Change Detection

Changes are detected by comparing current values to `original_values` captured at edit start. Fields tracked:
- title, brand, model, description
- quantity, base_price, category, serial_number
- handedness, manufacturing_country
- artist_owned, artist_names
- condition, year, finish
- extra_attributes

## Files

- **Shopify sync**: `app/services/shopify_service.py`
  - `apply_product_update()` - handles edit propagation
  - `_sync_colour_finish()`, `_sync_year()`, `_sync_condition()`, `_sync_artist_info()`, etc.
- **eBay sync**: `app/services/ebay_service.py`
  - `_build_item_specifics()` - builds item specifics dict
  - `apply_product_update()` - handles edit propagation
- **Change detection**: `app/routes/inventory.py`
  - `original_values` dict in edit route
