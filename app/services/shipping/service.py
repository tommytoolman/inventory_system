"""
Shipping Service - Main Facade

This module provides the main entry point to the shipping service functionality,
abstracting away the specific carrier implementations.

Core Capabilities:
- Get shipping rates across multiple carriers
- Generate shipping labels
- Track shipments
- Validate addresses
- Manage shipping profiles

Usage:
    shipping_service = ShippingService()
    rates = await shipping_service.get_rates(package, origin, destination)
    label = await shipping_service.create_label(rate_id, package, origin, destination)
"""

from typing import List, Dict, Any, Optional
from .models.package import Package
from .models.address import Address
from .models.rate import ShippingRate
from .carriers.base import BaseCarrier
from .carriers.dhl import DHLCarrier
from .carriers.ups import UPSCarrier
from .carriers.fedex import FedExCarrier
from .config.settings import ShippingSettings
from .exceptions import ShippingError

class ShippingService:
    """Main shipping service facade that orchestrates carrier operations"""
    
    def __init__(self, settings: Optional[ShippingSettings] = None):
        """Initialize the shipping service with available carriers"""
        self.settings = settings or ShippingSettings()
        self.carriers = {}
        self._initialize_carriers()
        
    def _initialize_carriers(self) -> None:
        """Initialize available shipping carriers based on configuration"""
        # Initialize carriers based on configuration
        if self.settings.dhl_enabled:
            self.carriers['dhl'] = DHLCarrier(self.settings.dhl_config)
            
        if self.settings.ups_enabled:
            self.carriers['ups'] = UPSCarrier(self.settings.ups_config)
            
        if self.settings.fedex_enabled:
            self.carriers['fedex'] = FedExCarrier(self.settings.fedex_config)
    
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address,
        carrier_filter: List[str] = None
    ) -> List[ShippingRate]:
        """
        Get shipping rates from all enabled carriers or specified carriers
        
        Args:
            package: Package details (dimensions, weight)
            origin: Shipping origin address
            destination: Shipping destination address
            carrier_filter: Optional list of carrier codes to use (e.g., ['dhl', 'ups'])
            
        Returns:
            List of available shipping rates across carriers
        """
        rates = []
        carriers_to_check = carrier_filter or self.carriers.keys()
        
        for carrier_code in carriers_to_check:
            if carrier_code not in self.carriers:
                continue
                
            carrier = self.carriers[carrier_code]
            try:
                carrier_rates = await carrier.get_rates(package, origin, destination)
                rates.extend(carrier_rates)
            except Exception as e:
                # Log the error but continue with other carriers
                print(f"Error getting rates from {carrier_code}: {str(e)}")
        
        return sorted(rates, key=lambda x: x.total_price)
    
    # Additional methods would be implemented here

