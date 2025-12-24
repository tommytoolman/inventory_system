# eBay Category Aspects Reference

**Last Updated:** 2025-12-04
**Source:** eBay Taxonomy API (category_tree/3 - EBAY_UK)
**Data File:** `docs/ebay_category_aspects_data.json`

## Overview

This document lists all required and recommended ItemSpecifics (aspects) for each eBay category used in our inventory system. Data is fetched from eBay's Taxonomy API using the `get_item_aspects_for_category` endpoint.

## Summary Table

| Category | ID | Required Aspects | Notes |
|----------|-----|------------------|-------|
| Electric Guitars | 33034 | Brand | Type/Body Type are RECOMMENDED only |
| Acoustic Guitars | 33021 | Brand | Type/Body Type are RECOMMENDED only |
| Classical Guitars | 119544 | Brand | |
| **Bass Guitars** | 4713 | Brand, **Type** | Type: Acoustic/Electric/Electro-Acoustic |
| Lap & Pedal Steel Guitars | 181220 | Brand, Type | |
| Resonators | 181219 | Brand, Type | |
| Travel Guitars | 159948 | Brand, Type | |
| **Guitar Amplifiers** | 38072 | Brand, **Amplifier Type** | Combo/Head/Cabinet/Stack |
| Distortion & Overdrive | 41416 | Brand, Type | |
| Delay, Echo & Reverb | 41415 | Brand, Type | |
| Fuzz | 41418 | Brand | |
| Wah & Volume | 41422 | Brand, Type | |
| Multi-Effects | 41419 | Brand, Type | |
| Power Supplies | 101975 | Brand | |
| Compressors & Sustainers | 41414 | Brand, Type | |
| Chorus | 41413 | Brand | |
| Phasers & Shifters | 41420 | Brand, Type | |
| Loopers & Samplers | 101974 | Brand | |
| Flangers | 41417 | Brand | |
| Bass Effects | 41411 | Brand, Type | |
| Other Guitar Effects | 22669 | Brand, Type | |
| Electronic Keyboards | 38088 | Brand, Type | |
| **Synthesizers** | 38071 | Brand, **Type** | Keyboard/Modular/Desktop/Rackmount |
| Drum Machines | 181174 | None | No required aspects! |
| MIDI Controllers | 178896 | Brand, Type | |
| **Digital Pianos** | 85860 | Brand, **Type**, **Keys** | 3 required fields |
| **Microphones** | 29946 | Brand, **Form Factor** | Dynamic/Condenser/Ribbon/etc |
| Other Pro Audio | 3278 | Brand | |
| Drum Kits | 38097 | Brand, Type | |
| Electronic Drums | 38069 | Brand, Type | |
| Cymbals | 41441 | Brand, Type | |
| Amplifier Parts | 183389 | Brand, Type | |
| Guitar Parts | 46678 | Brand, Type | |
| Pickups | 22670 | Brand, Type | |
| Bridges | 41407 | Brand | |
| Pickguards | 41424 | Brand | |
| Bodies | 41406 | Brand | |
| Knobs, Jacks & Switches | 47076 | Brand, Type | |
| Tuning Pegs | 41434 | Brand | |
| Necks | 41423 | Brand | |
| Mandolins | 10179 | Brand | |
| Ukuleles | 16224 | Brand | |
| Banjos | 10177 | Brand | |
| **Headphones** | 14985 | Brand, **Connectivity**, **Earpiece Design**, **Form Factor**, **Features** | 5 required! |

---

## Detailed Breakdown by Category

### Guitars & Basses

#### Bass Guitars (4713)
**Required:**
- **Brand** (489 options)
- **Type** (3 options):
  - Acoustic Bass Guitar
  - Electric Bass Guitar
  - Electro-Acoustic Bass Guitar

**Recommended:** String Configuration, Body Type, Handedness, Model, Body Colour, Series, Model Year, Body Material, Fretboard Material, Number of Frets

#### Electric Guitars (33034)
**Required:**
- **Brand** (490 options)

**Recommended:** Series, Type, Model, Body Colour, Handedness, Body Type, String Configuration, Number of Frets, Model Year, Fretboard Material

*Note: Type and Body Type are NOT required for Electric Guitars - only recommended*

#### Acoustic Guitars (33021)
**Required:**
- **Brand** (490 options)

**Recommended:** Type, Body Type, Model, Handedness, Body Colour, Model Year, String Configuration, Body Material, Fretboard Material, Number of Frets

---

### Amplifiers

#### Guitar Amplifiers (38072)
**Required:**
- **Brand** (396 options)
- **Amplifier Type** (4 options):
  - Cabinet
  - Combo
  - Head
  - Stack

**Recommended:** Number of Speakers, Number of Channels, Product Line, Suitable For, Amplifier Technology, Power

---

### Synthesizers & Keyboards

#### Synthesizers (38071)
**Required:**
- **Brand** (201 options)
- **Type** (6 options):
  - Desktop Synthesizer
  - Handheld Synthesizer
  - Keyboard Synthesizer
  - Keytar Synthesizer
  - Modular Synthesizer
  - Rackmount Synthesizer

**Recommended:** Keys, Analog/Digital, MPN, Product Line, Custom Bundle, Model

#### Digital Pianos (85860)
**Required:**
- **Brand** (108 options)
- **Type** (5 options):
  - Console Digital Piano
  - Grand Digital Piano
  - Portable Digital Piano
  - Stage Piano
  - Upright Digital Piano
- **Keys** (6 options): 25, 44, 61, 76, 88, Other

**Recommended:** Colour, Custom Bundle, Model, MPN

#### Electronic Keyboards (38088)
**Required:**
- **Brand** (108 options)
- **Type** (6 options):
  - Arranger Keyboard
  - Digital Piano
  - Organ
  - Portable Keyboard
  - Synthesizer Keyboard
  - Workstation Keyboard

**Recommended:** Keys, Custom Bundle, Model

---

### Pro Audio

#### Microphones (29946)
**Required:**
- **Brand** (403 options)
- **Form Factor** (19 options):
  - Channel Strip
  - Condenser Microphone
  - Desktop Microphone
  - Direct/DI Box
  - Dynamic Microphone
  - Earset Microphone
  - Gooseneck
  - Handheld/Stand-Held
  - Hanging Microphone
  - Headset
  - Lavalier/Lapel
  - Lectern Microphone
  - Microphone Preamp
  - Microphone Receiver
  - Modular Microphone System
  - Ribbon Microphone
  - Shotgun Microphone
  - Tabletop
  - Wireless System

**Recommended:** Transducer Type, Mount Type, Polar Pattern, Connectivity, Model, Features, Phantom Power, Colour, Bundle Description

---

### Headphones (14985)
**Required:**
- **Brand** (556 options)
- **Connectivity** (4 options): Bluetooth, USB, Wired, Wireless
- **Earpiece Design** (4 options): Ear-Pad (On the Ear), Earbud (In Ear), Headband, Over-Ear
- **Form Factor** (8 options)
- **Features** (multiple)

*Note: This category has the most required fields (5)*

---

## Implementation Notes

### Categories Requiring Custom UI Fields

Based on this data, we should show additional UI fields for:

1. **Bass Guitars (4713)** - Type dropdown (already implemented)
2. **Microphones (29946)** - Form Factor dropdown (already implemented)
3. **Guitar Amplifiers (38072)** - Amplifier Type dropdown
4. **Synthesizers (38071)** - Type dropdown
5. **Digital Pianos (85860)** - Type AND Keys dropdowns
6. **Electronic Keyboards (38088)** - Type dropdown
7. **Headphones (14985)** - Multiple fields (Connectivity, Earpiece Design, Form Factor, Features)

### Categories Where Only Brand is Required

These categories don't need additional UI fields (Brand is already captured):
- Electric Guitars, Acoustic Guitars, Classical Guitars
- Fuzz, Power Supplies, Chorus, Loopers & Samplers, Flangers
- Bridges, Pickguards, Bodies, Tuning Pegs, Necks
- Mandolins, Ukuleles, Banjos

### API Integration

The eBay Taxonomy API endpoint:
```
GET https://api.ebay.com/commerce/taxonomy/v1/category_tree/3/get_item_aspects_for_category?category_id={category_id}
```

- Uses **Application token** (client credentials) - no user auth required
- Category tree ID `3` = EBAY_UK
- Returns all required and recommended aspects with valid values

### Refresh Strategy

The JSON cache should be refreshed:
1. On-demand via admin endpoint
2. Periodically (weekly/monthly)
3. When eBay API call succeeds, update the cache

---

## File Locations

- **JSON Data:** `docs/ebay_category_aspects_data.json` (complete API response)
- **Cached Config:** `app/static/data/ebay_category_aspects.json` (simplified for UI)
- **This Doc:** `docs/ebay_category_aspects.md`
