"""
Base Carrier Interface

This module defines the abstract base class that all shipping carrier
integrations must implement.

Each carrier implementation provides standard methods for:
- Getting shipping rates
- Creating labels
- Tracking shipments
- Validating addresses

This ensures consistency across different carrier implementations.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo

class BaseCarrier(ABC):
    """
    Abstract base class for shipping carrier implementations.
    All carrier implementations must extend this class.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the carrier with configuration settings"""
        self.config = config
        self.name = "BaseCarrier"
        self.carrier_code = "base"
        
    @abstractmethod
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        """
        Get available shipping rates for this carrier
        
        Args:
            package: Package details (dimensions, weight)
            origin: Shipping origin address
            destination: Shipping destination address
        
        Returns:
            List of available shipping rates
        """
        pass
        
    @abstractmethod
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        """
        Create a shipping label
        
        Args:
            rate_id: ID of the rate selected for shipping
            package: Package details (dimensions, weight)
            origin: Shipping origin address
            destination: Shipping destination address
            
        Returns:
            Dictionary containing label information and URL
        """
        pass
        
    @abstractmethod
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        """
        Track a shipment by tracking number
        
        Args:
            tracking_number: The carrier's tracking number
            
        Returns:
            Tracking information for the shipment
        """
        pass
        
    @abstractmethod
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        """
        Validate a shipping address
        
        Args:
            address: Address to validate
            
        Returns:
            Dictionary with validation results
        """
        pass

