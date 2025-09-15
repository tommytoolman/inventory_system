#!/usr/bin/env python3
"""
Test the shipping profiles endpoint to verify display_name is returned.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import async_session
from app.models.shipping import ShippingProfile

async def test_endpoint_logic():
    """Test the same logic as the endpoint."""
    
    async with async_session() as session:
        profiles = await session.execute(select(ShippingProfile).order_by(ShippingProfile.name))
        result = profiles.scalars().all()
        
        # Simulate the endpoint response
        response = [
            {
                "id": profile.id,
                "reverb_profile_id": profile.reverb_profile_id,
                "ebay_profile_id": profile.ebay_profile_id,
                "name": profile.name,
                "display_name": f"{profile.name} ({profile.reverb_profile_id})" if profile.reverb_profile_id else profile.name,
                "description": profile.description,
                "package_type": profile.package_type,
                "dimensions": profile.dimensions,
                "weight": profile.weight,
                "carriers": profile.carriers,
                "options": profile.options,
                "rates": profile.rates,
                "is_default": profile.is_default
            }
            for profile in result
        ]
        
        print("Sample API Response (first 3 profiles):")
        print("=" * 60)
        for profile in response[:3]:
            print(f"ID: {profile['id']}")
            print(f"Name: {profile['name']}")
            print(f"Reverb ID: {profile['reverb_profile_id']}")
            print(f"Display Name: {profile['display_name']}")
            print("-" * 40)

if __name__ == "__main__":
    asyncio.run(test_endpoint_logic())