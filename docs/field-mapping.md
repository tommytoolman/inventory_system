# Field Mapping: RIFF → Platform Sync

*Last updated: 2026-01-08*

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
| `extra_attributes.*` | `custom.*` metafields | Category-specific item specifics |

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

### Category-Specific Item Specifics

eBay requires different item specifics for different categories. These are configured in `app/services/ebay/spec_fields.py` and populated from `extra_attributes` or guessed from product data.

| Category | ID | Required Fields | Auto-Guessed |
|----------|-----|-----------------|--------------|
| Electric Guitars | 33034 | Brand | Type (auto: "Electric Guitar"), Body Type |
| Acoustic Guitars | 33021 | Brand | Type (auto: "Acoustic Guitar"), Body Type |
| Bass Guitars | 4713 | Brand, **Type** | Type, String Configuration |
| Classical Guitars | 119544 | Brand | Type (auto: "Classical Guitar") |
| Guitar Amplifiers | 38072 | Brand, **Amplifier Type** | Amplifier Type, Amplifier Technology |
| Resonator Guitars | 181219 | Brand, **Type** | Type |
| Travel Guitars | 159948 | **Type**, Brand | Type |
| Lap & Pedal Steel | 181220 | **Type**, Brand | Type |
| Synthesizers | 38071 | Brand, **Type** | Type |
| Electronic Keyboards | 38088 | Brand, **Number of Keys** | Number of Keys |
| Digital Pianos | 85860 | Brand, **Number of Keys** | Type, Number of Keys |
| Effects Pedals | Various | Brand, Type (varies) | Analogue/Digital |

**Bold** indicates fields that are **required** by eBay (in addition to Brand).

### extra_attributes Keys

Category-specific values are stored in `product.extra_attributes`:

| Key | Used For | eBay Field |
|-----|----------|------------|
| `body_type` | Guitars | Body Type |
| `string_configuration` | Guitars, Bass | String Configuration |
| `amplifier_type` | Amps | Amplifier Type |
| `amp_technology` | Amps | Amplifier Technology |
| `amp_power` | Amps | Power |
| `num_speakers` | Amps | Number of Speakers |
| `bass_type` | Bass Guitars | Type |
| `synth_type` | Synthesizers | Type |
| `pedal_type` | Effects | Type |
| `analog_digital` | Effects | Analogue/Digital |
| `num_keys` | Keyboards/Pianos | Number of Keys |

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
  - `_sync_category_specific_fields()` - syncs extra_attributes to Shopify metafields
- **eBay sync**: `app/services/ebay_service.py`
  - `_build_item_specifics()` - builds item specifics dict (uses spec_fields config)
  - `_apply_category_guessers()` - guesses required fields from product data
  - `apply_product_update()` - handles edit propagation
- **eBay category config**: `app/services/ebay/spec_fields.py`
  - `EBAY_CATEGORY_SPECS` - defines required/recommended fields per category
  - `get_category_spec()`, `get_auto_set_fields()`, `get_extra_attrs_map()` - helpers
- **Change detection**: `app/routes/inventory.py`
  - `original_values` dict in edit route
- **Test script**: `scripts/test_ebay_item_specifics.py`
  - Validates category specs and guessing logic
