"""
Shipping carrier factory to make carrier selection easy
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.shipping.base import BaseCarrier
from app.services.shipping.carriers.dhl import DHLCarrier
# Import your other carrier classes here


def get_carrier(carrier_code: str, db: Optional[AsyncSession] = None) -> BaseCarrier:
    """
    Factory function to get the appropriate carrier by code
    
    Args:
        carrier_code: The code of the carrier to use
        db: Optional database session
        
    Returns:
        An instance of the appropriate carrier class
        
    Raises:
        ValueError: If the carrier code is not supported
    """
    carriers = {
        "dhl": DHLCarrier,
        # Add your other carriers here
    }
    
    if carrier_code not in carriers:
        raise ValueError(f"Carrier '{carrier_code}' is not supported")
    
    return carriers[carrier_code](db)