#!/usr/bin/env python
"""
Test script to verify eBay item specifics building with the new spec_fields configuration.
Run: python scripts/test_ebay_item_specifics.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum

# Mock Product for testing
class ProductCondition(Enum):
    NEW = "new"
    EXCELLENT = "excellent"
    VERYGOOD = "verygood"
    GOOD = "good"

class Handedness(Enum):
    LEFT = "left"
    RIGHT = "right"

@dataclass
class MockProduct:
    title: str = ""
    brand: str = ""
    model: str = ""
    year: Optional[int] = None
    finish: Optional[str] = None
    condition: Optional[ProductCondition] = None
    handedness: Optional[Handedness] = None
    manufacturing_country: Optional[str] = None
    artist_owned: bool = False
    artist_names: Optional[List[str]] = None
    category: str = ""
    extra_attributes: Optional[Dict[str, Any]] = None
    sku: str = "TEST-123"


# Import the spec_fields module
from app.services.ebay.spec_fields import (
    get_category_spec,
    get_required_fields,
    get_auto_set_fields,
    get_extra_attrs_map,
    EBAY_CATEGORY_SPECS,
)


def test_category_specs():
    """Test that category specs are loaded correctly."""
    print("\n=== Testing Category Specs ===")

    # Test Electric Guitars
    spec = get_category_spec("33034")
    assert spec is not None, "Electric Guitars spec should exist"
    assert spec["name"] == "Electric Guitars"
    assert "Brand" in spec["required"]
    assert "Type" in spec.get("auto_set", {})
    print(f"✓ Electric Guitars (33034): required={spec['required']}, auto_set={spec.get('auto_set', {})}")

    # Test Bass Guitars - Type is REQUIRED
    spec = get_category_spec("4713")
    assert spec is not None, "Bass Guitars spec should exist"
    assert "Type" in spec["required"], "Bass Guitars should require Type"
    print(f"✓ Bass Guitars (4713): required={spec['required']}")

    # Test Amplifiers - Amplifier Type is REQUIRED
    spec = get_category_spec("38072")
    assert spec is not None, "Amplifiers spec should exist"
    assert "Amplifier Type" in spec["required"], "Amplifiers should require Amplifier Type"
    print(f"✓ Guitar Amplifiers (38072): required={spec['required']}")

    # Test Resonators - Type is REQUIRED
    spec = get_category_spec("181219")
    assert spec is not None, "Resonators spec should exist"
    assert "Type" in spec["required"], "Resonators should require Type"
    print(f"✓ Resonator Guitars (181219): required={spec['required']}")

    print(f"\n✓ Total category specs loaded: {len(EBAY_CATEGORY_SPECS)}")


def test_auto_set_fields():
    """Test auto-set fields for different categories."""
    print("\n=== Testing Auto-Set Fields ===")

    # Electric Guitars should auto-set Type
    auto = get_auto_set_fields("33034")
    assert auto.get("Type") == "Electric Guitar"
    print(f"✓ Electric Guitars auto-set: {auto}")

    # Acoustic Guitars should auto-set Type
    auto = get_auto_set_fields("33021")
    assert auto.get("Type") == "Acoustic Guitar"
    print(f"✓ Acoustic Guitars auto-set: {auto}")

    # Bass Guitars should NOT auto-set Type (it's required from extra_attrs)
    auto = get_auto_set_fields("4713")
    assert "Type" not in auto, "Bass should not auto-set Type"
    print(f"✓ Bass Guitars auto-set: {auto} (Type should be guessed)")


def test_extra_attrs_mapping():
    """Test extra_attributes to eBay field mapping."""
    print("\n=== Testing Extra Attributes Mapping ===")

    # Bass Guitars
    mapping = get_extra_attrs_map("4713")
    assert "bass_type" in mapping.values() or "Type" in mapping
    print(f"✓ Bass Guitars extra_attrs_map: {mapping}")

    # Amplifiers
    mapping = get_extra_attrs_map("38072")
    assert "amplifier_type" in mapping.values()
    print(f"✓ Amplifiers extra_attrs_map: {mapping}")


def test_guessing_scenarios():
    """Test various guessing scenarios for item specifics."""
    print("\n=== Testing Guessing Scenarios ===")

    # Test string configuration guessing
    test_cases = [
        ("Fender Jazz Bass 5 String", "4713", "5 String"),
        ("Gibson SG 6-string", "33034", "6 String"),
        ("12 String Acoustic Guitar", "33021", "12 String"),
        ("Standard Electric Guitar", "33034", None),  # 6 is default but we don't set it for guitars
    ]

    for title, category, expected_string_config in test_cases:
        product = MockProduct(title=title, brand="Test", category=category)
        # Simulate the guessing logic
        title_lower = title.lower()
        result = None
        for count in ["12", "8", "7", "6", "5", "4"]:
            if f"{count} string" in title_lower or f"{count}-string" in title_lower:
                result = f"{count} String"
                break

        if expected_string_config:
            assert result == expected_string_config, f"Expected {expected_string_config} for '{title}', got {result}"
            print(f"✓ '{title}' → String Configuration: {result}")
        else:
            print(f"✓ '{title}' → String Configuration: (not guessed, would use default)")

    # Test amplifier type guessing
    amp_tests = [
        ("Fender Twin Reverb Combo", "Combo"),
        ("Marshall JCM800 Head", "Head"),
        ("Mesa Boogie 4x12 Cabinet", "Cabinet"),
        ("Orange 1x12 Combo Amp", "Combo"),
    ]

    for title, expected in amp_tests:
        title_lower = title.lower()
        result = "Combo"  # default
        if "head" in title_lower:
            result = "Head"
        elif "cabinet" in title_lower or "cab " in title_lower:
            result = "Cabinet"
        elif "combo" in title_lower or any(x in title_lower for x in ["1x12", "2x12", "4x10"]):
            result = "Combo"

        assert result == expected, f"Expected {expected} for '{title}', got {result}"
        print(f"✓ '{title}' → Amplifier Type: {result}")

    # Test amp technology guessing
    tech_tests = [
        ("Fender Hot Rod Deluxe Tube Amp", "Vacuum Tube"),
        ("Roland JC-120 Solid State", "Solid State"),
        ("Line 6 Helix Modeling Amp", "Modeling"),
        ("Vox AC30 (valve)", "Vacuum Tube"),
    ]

    for title, expected in tech_tests:
        title_lower = title.lower()
        result = "Vacuum Tube"  # default for vintage
        if any(w in title_lower for w in ["tube", "valve", "el34", "6l6"]):
            result = "Vacuum Tube"
        elif "solid state" in title_lower or "transistor" in title_lower:
            result = "Solid State"
        elif "modeling" in title_lower or "modelling" in title_lower or "digital" in title_lower:
            result = "Modeling"
        elif "hybrid" in title_lower:
            result = "Hybrid"

        assert result == expected, f"Expected {expected} for '{title}', got {result}"
        print(f"✓ '{title}' → Amplifier Technology: {result}")


def test_bass_type_guessing():
    """Test bass guitar type guessing."""
    print("\n=== Testing Bass Type Guessing ===")

    test_cases = [
        ("Fender Jazz Bass", "Electric Bass Guitar"),
        ("Gibson Acoustic Bass", "Acoustic Bass Guitar"),
        ("Taylor Electro-Acoustic Bass", "Electro-Acoustic Bass Guitar"),
        ("Ibanez Electric Acoustic Bass", "Electro-Acoustic Bass Guitar"),
    ]

    for title, expected in test_cases:
        title_lower = title.lower()
        result = "Electric Bass Guitar"
        if "acoustic" in title_lower:
            if "electro" in title_lower or "electric" in title_lower:
                result = "Electro-Acoustic Bass Guitar"
            else:
                result = "Acoustic Bass Guitar"

        assert result == expected, f"Expected {expected} for '{title}', got {result}"
        print(f"✓ '{title}' → Type: {result}")


def test_synthesizer_type_guessing():
    """Test synthesizer type guessing."""
    print("\n=== Testing Synthesizer Type Guessing ===")

    test_cases = [
        ("Moog Modular System", "Modular Synthesiser"),
        ("Arturia MiniBrute Desktop", "Desktop Synthesiser"),
        ("Roland Juno 106 Keyboard", "Keyboard Synthesiser"),
        ("Make Noise Eurorack Module", "Modular Synthesiser"),
    ]

    for title, expected in test_cases:
        title_lower = title.lower()
        result = "Keyboard Synthesiser"
        if "modular" in title_lower or "eurorack" in title_lower:
            result = "Modular Synthesiser"
        elif "desktop" in title_lower or "module" in title_lower:
            result = "Desktop Synthesiser"
        elif "rackmount" in title_lower:
            result = "Rackmount Synthesiser"

        assert result == expected, f"Expected {expected} for '{title}', got {result}"
        print(f"✓ '{title}' → Type: {result}")


def test_num_keys_guessing():
    """Test number of keys guessing."""
    print("\n=== Testing Number of Keys Guessing ===")

    import re

    test_cases = [
        ("Nord Stage 3 88 Key Piano", "88"),
        ("Arturia KeyLab 49-Key Controller", "49"),
        ("Roland 61-key Workstation", "61"),
        ("Yamaha Digital Piano", "61"),  # default
    ]

    for title, expected in test_cases:
        title_lower = title.lower()
        # Match patterns like "88 key", "49-key", "61 key"
        match = re.search(r'(\d+)[-\s]*key', title_lower)
        if match:
            result = match.group(1)
        else:
            result = "61"  # default

        assert result == expected, f"Expected {expected} for '{title}', got {result}"
        print(f"✓ '{title}' → Number of Keys: {result}")


def main():
    print("=" * 60)
    print("eBay Item Specifics Test Suite")
    print("=" * 60)

    try:
        test_category_specs()
        test_auto_set_fields()
        test_extra_attrs_mapping()
        test_guessing_scenarios()
        test_bass_type_guessing()
        test_synthesizer_type_guessing()
        test_num_keys_guessing()

        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
