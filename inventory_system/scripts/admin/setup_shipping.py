#!/usr/bin/env python3
"""
Standalone script to setup shipping profiles.
Migrated from app/cli/shipping functionality.
"""

import sys
from pathlib import Path
import asyncio

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.shipping.shipping import populate_shipping_profiles

def main():
    """Setup shipping profiles."""
    print("🚛 Setting up shipping profiles...")
    asyncio.run(populate_shipping_profiles(reset=False))
    print("✅ Shipping profiles setup complete!")

if __name__ == "__main__":
    main()