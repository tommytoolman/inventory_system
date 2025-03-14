"""
Address Model

This module defines the Address data model used for shipping operations.
Includes validation and conversion functionality.

The Address model handles:
- Shipping origin and destination addresses
- Address validation formatting
- Conversion to carrier-specific formats
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class Address(BaseModel):
    """
    Standard address model for shipping operations
    
    Used for both origin and destination addresses
    """
    company_name: Optional[str] = None
    name: str
    street1: str
    street2: Optional[str] = None
    street3: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str
    phone: Optional[str] = None
    email: Optional[str] = None
    is_residential: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for API requests"""
        return {
            "companyName": self.company_name,
            "name": self.name,
            "street1": self.street1,
            "street2": self.street2,
            "street3": self.street3,
            "city": self.city,
            "state": self.state,
            "postalCode": self.postal_code,
            "country": self.country,
            "phone": self.phone,
            "email": self.email,
            "isResidential": self.is_residential
        }
        
    def to_dhl_format(self) -> Dict[str, Any]:
        """Convert to DHL-specific address format"""
        return {
            "postalAddress": {
                "postalCode": self.postal_code,
                "cityName": self.city,
                "countryCode": self.country,
                "provinceCode": self.state,
                "addressLine1": self.street1,
                "addressLine2": self.street2,
                "addressLine3": self.street3,
                "companyName": self.company_name,
                "countyName": ""  # Not in our model but required by DHL
            },
            "contactInformation": {
                "phone": self.phone,
                "emailAddress": self.email,
                "personName": self.name,
                "companyName": self.company_name
            },
            "typeCode": "business" if not self.is_residential else "residential"
        }
        
    def to_ups_format(self) -> Dict[str, Any]:
        """Convert to UPS-specific address format"""
        # UPS-specific conversion implementation
        return {}
        
    def to_fedex_format(self) -> Dict[str, Any]:
        """Convert to FedEx-specific address format"""
        # FedEx-specific conversion implementation
        return {}

