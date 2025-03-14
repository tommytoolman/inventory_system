"""
Shipping Rate Model

Defines the ShippingRate data model for standardizing rate responses
across different carriers.

Used for:
- Presenting shipping options to users
- Storing and comparing rates
- Selecting shipping services
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class ShippingRate(BaseModel):
    """
    Standardized shipping rate model
    
    Contains all information about a shipping rate option
    from any carrier.
    """
    carrier: str
    service_code: str
    service_name: str
    total_price: float
    currency: str = "USD"
    estimated_days: Optional[int] = None
    delivery_date: Optional[datetime] = None
    rate_id: str
    metadata: Dict[str, Any] = {}
    
    @property
    def display_price(self) -> str:
        """
        Returns formatted price for display
        
        Examples:
            2.99
            £10.50
            €15.00
        """
        currency_symbols = {
            "USD": "$",
            "EUR": "€",
            "GBP": "£",
            "CAD": "C$",
            "AUD": "A$"
        }
        
        symbol = currency_symbols.get(self.currency, self.currency + " ")
        return f"{symbol}{self.total_price:.2f}"
        
    @property
    def delivery_estimate(self) -> str:
        """
        Returns a user-friendly delivery estimate
        
        Examples:
            Delivery
