"""
Base Carrier Interface

This module defines the abstract base class that all shipping carrier
implementations must implement.

Each carrier implementation provides standard methods for:
- Getting shipping rates
- Creating labels
- Tracking shipments
- Validating addresses


The base carrier class serves an important purpose even if DHL is the default carrier. 
It defines a common interface that all carrier implementations (current and future) should follow. 
This provides several benefits:
- Consistency: Ensures all carrier implementations have the same methods with consistent signatures
- Interchangeability: Allows your code to work with any carrier without changing the calling code
- Future-proofing: Makes it easy to add additional carriers later (UPS, FedEx, TNT, etc.)

"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession


class BaseCarrier(ABC):
    """Base class for all shipping carriers"""
    
    carrier_name = "Generic Carrier"
    carrier_code = "generic"
    
    def __init__(self, db: Optional[AsyncSession] = None):
        """Initialize the carrier
        
        Args:
            db: Database session for persistence operations
        """
        self.db = db
    
    @abstractmethod
    async def create_shipment(self, shipment_details: Dict[str, Any]) -> Dict[str, Any]:
        """Create a shipment
        
        Args:
            shipment_details: Shipment details
            
        Returns:
            API response
        """
        pass
    
    @abstractmethod
    async def track_shipment(self, tracking_number: str) -> Dict[str, Any]:
        """Track a shipment
        
        Args:
            tracking_number: Shipment tracking number
            
        Returns:
            Tracking information
        """
        pass
    
    @abstractmethod
    async def get_rates(self, shipment_details: Dict[str, Any]) -> Dict[str, Any]:
        """Get shipping rates
        
        Args:
            shipment_details: Shipment details
            
        Returns:
            Rate information
        """
        pass