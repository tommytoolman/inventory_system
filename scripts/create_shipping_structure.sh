#!/bin/bash

# Set colors for better output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Creating Shipping Service and Test Structure ===${NC}"

# Base directories
APP_DIR="app"
TEST_DIR="tests"

# Function to create directory if it doesn't exist
create_dir() {
    if [ ! -d "$1" ]; then
        mkdir -p "$1"
        echo -e "${GREEN}Created directory: $1${NC}"
    else
        echo -e "${YELLOW}Directory already exists: $1${NC}"
    fi
}

# Function to create file with content if it doesn't exist
create_file() {
    local file_path="$1"
    local content="$2"
    
    if [ ! -f "$file_path" ]; then
        echo -e "$content" > "$file_path"
        echo -e "${GREEN}Created file: $file_path${NC}"
    else
        echo -e "${YELLOW}File already exists (not modified): $file_path${NC}"
    fi
}

# Create necessary directories
echo -e "${GREEN}Creating directory structure...${NC}"
create_dir "$APP_DIR/services/shipping"
create_dir "$APP_DIR/services/shipping/carriers"
create_dir "$APP_DIR/services/shipping/models"
create_dir "$APP_DIR/services/shipping/config"
create_dir "$APP_DIR/services/shipping/utils"

create_dir "$TEST_DIR/unit/services/shipping"
create_dir "$TEST_DIR/unit/services/shipping/carriers"
create_dir "$TEST_DIR/unit/models/shipping"
create_dir "$TEST_DIR/integration/shipping"
create_dir "$TEST_DIR/mocks"
create_dir "$TEST_DIR/fixtures"

# Create shipping service files
echo -e "${GREEN}Creating shipping service files...${NC}"

# Service main file
create_file "$APP_DIR/services/shipping/__init__.py" "# Shipping service package init file"

create_file "$APP_DIR/services/shipping/service.py" "\"\"\"
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
\"\"\"

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
    \"\"\"Main shipping service facade that orchestrates carrier operations\"\"\"
    
    def __init__(self, settings: Optional[ShippingSettings] = None):
        \"\"\"Initialize the shipping service with available carriers\"\"\"
        self.settings = settings or ShippingSettings()
        self.carriers = {}
        self._initialize_carriers()
        
    def _initialize_carriers(self) -> None:
        \"\"\"Initialize available shipping carriers based on configuration\"\"\"
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
        \"\"\"
        Get shipping rates from all enabled carriers or specified carriers
        
        Args:
            package: Package details (dimensions, weight)
            origin: Shipping origin address
            destination: Shipping destination address
            carrier_filter: Optional list of carrier codes to use (e.g., ['dhl', 'ups'])
            
        Returns:
            List of available shipping rates across carriers
        \"\"\"
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
                print(f\"Error getting rates from {carrier_code}: {str(e)}\")
        
        return sorted(rates, key=lambda x: x.total_price)
    
    # Additional methods would be implemented here
"

# Base carrier class
create_file "$APP_DIR/services/shipping/carriers/__init__.py" "# Carriers package init file"

create_file "$APP_DIR/services/shipping/carriers/base.py" "\"\"\"
Base Carrier Interface

This module defines the abstract base class that all shipping carrier
integrations must implement.

Each carrier implementation provides standard methods for:
- Getting shipping rates
- Creating labels
- Tracking shipments
- Validating addresses

This ensures consistency across different carrier implementations.
\"\"\"

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo

class BaseCarrier(ABC):
    \"\"\"
    Abstract base class for shipping carrier implementations.
    All carrier implementations must extend this class.
    \"\"\"
    
    def __init__(self, config: Dict[str, Any]):
        \"\"\"Initialize the carrier with configuration settings\"\"\"
        self.config = config
        self.name = \"BaseCarrier\"
        self.carrier_code = \"base\"
        
    @abstractmethod
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        \"\"\"
        Get available shipping rates for this carrier
        
        Args:
            package: Package details (dimensions, weight)
            origin: Shipping origin address
            destination: Shipping destination address
        
        Returns:
            List of available shipping rates
        \"\"\"
        pass
        
    @abstractmethod
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        \"\"\"
        Create a shipping label
        
        Args:
            rate_id: ID of the rate selected for shipping
            package: Package details (dimensions, weight)
            origin: Shipping origin address
            destination: Shipping destination address
            
        Returns:
            Dictionary containing label information and URL
        \"\"\"
        pass
        
    @abstractmethod
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        \"\"\"
        Track a shipment by tracking number
        
        Args:
            tracking_number: The carrier's tracking number
            
        Returns:
            Tracking information for the shipment
        \"\"\"
        pass
        
    @abstractmethod
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        \"\"\"
        Validate a shipping address
        
        Args:
            address: Address to validate
            
        Returns:
            Dictionary with validation results
        \"\"\"
        pass
"

# DHL carrier implementation
create_file "$APP_DIR/services/shipping/carriers/dhl.py" "\"\"\"
DHL Carrier Implementation

This module implements the DHL shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

DHL API Docs: https://developer.dhl.com/
\"\"\"

from typing import List, Dict, Any, Optional
import httpx
from .base import BaseCarrier
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo
from ..exceptions import ShippingError

class DHLCarrier(BaseCarrier):
    \"\"\"DHL carrier implementation\"\"\"
    
    BASE_URL = \"https://api-mock.dhl.com/\"  # Replace with actual API URL in production
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = \"DHL Express\"
        self.carrier_code = \"dhl\"
        self.api_key = config.get(\"api_key\", \"\")
        self.account_number = config.get(\"account_number\", \"\")
        
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        \"\"\"Get DHL shipping rates\"\"\"
        try:
            # Structure the request payload according to DHL API
            payload = {
                \"customerDetails\": {
                    \"shipperDetails\": origin.to_dict(),
                    \"receiverDetails\": destination.to_dict()
                },
                \"accounts\": [{
                    \"typeCode\": \"shipper\",
                    \"number\": self.account_number
                }],
                \"plannedShippingDateAndTime\": \"2023-10-19T15:00:00GMT+01:00\",
                \"unitOfMeasurement\": \"metric\",
                \"packages\": [{
                    \"weight\": package.weight,
                    \"dimensions\": {
                        \"length\": package.length,
                        \"width\": package.width,
                        \"height\": package.height
                    }
                }]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f\"{self.BASE_URL}/rates\", 
                    json=payload,
                    headers={
                        \"Authorization\": f\"Bearer {self.api_key}\",
                        \"Content-Type\": \"application/json\"
                    }
                )
                
                if response.status_code != 200:
                    raise ShippingError(
                        f\"DHL API error: {response.status_code} - {response.text}\"
                    )
                    
                data = response.json()
                
                # Parse response into ShippingRate objects
                rates = []
                for product in data.get(\"products\", []):
                    rate = ShippingRate(
                        carrier=self.carrier_code,
                        service_code=product.get(\"productCode\"),
                        service_name=product.get(\"productName\"),
                        total_price=float(product.get(\"totalPrice\", [{}])[0].get(\"price\", 0)),
                        currency=product.get(\"totalPrice\", [{}])[0].get(\"currency\", \"USD\"),
                        delivery_date=product.get(\"deliveryCapabilities\", {}).get(\"estimatedDeliveryDate\"),
                        rate_id=f\"dhl_{product.get('productCode')}\",
                        metadata={
                            \"delivery_type\": product.get(\"deliveryCapabilities\", {}).get(\"deliveryTypeCode\"),
                            \"delivery_time\": product.get(\"deliveryCapabilities\", {}).get(\"estimatedDeliveryTime\")
                        }
                    )
                    rates.append(rate)
                    
                return rates
                
        except httpx.RequestError as e:
            raise ShippingError(f\"DHL API request error: {str(e)}\")
        except Exception as e:
            raise ShippingError(f\"DHL carrier error: {str(e)}\")
            
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        \"\"\"Create a DHL shipping label\"\"\"
        # Implementation would be similar to get_rates but calling the label creation endpoint
        # This is a simplified placeholder
        try:
            # Extract service code from rate_id
            service_code = rate_id.replace(\"dhl_\", \"\")
            
            payload = {
                \"customerDetails\": {
                    \"shipperDetails\": origin.to_dict(),
                    \"receiverDetails\": destination.to_dict()
                },
                \"accounts\": [{
                    \"typeCode\": \"shipper\",
                    \"number\": self.account_number
                }],
                \"productCode\": service_code,
                \"plannedShippingDateAndTime\": \"2023-10-19T15:00:00GMT+01:00\",
                \"unitOfMeasurement\": \"metric\",
                \"packages\": [{
                    \"weight\": package.weight,
                    \"dimensions\": {
                        \"length\": package.length,
                        \"width\": package.width,
                        \"height\": package.height
                    }
                }],
                \"outputImageProperties\": {
                    \"printerDPI\": 300,
                    \"encodingFormat\": \"pdf\",
                    \"imageOptions\": [{
                        \"typeCode\": \"label\",
                        \"templateName\": \"ECOM26_A6_001\"
                    }]
                }
            }
            
            # Placeholder implementation
            return {
                \"tracking_number\": \"DHLTRACKINGNUMBER123\",
                \"label_url\": \"https://example.com/label.pdf\",
                \"label_data\": \"base64encodeddata\",
                \"carrier\": self.carrier_code,
                \"service\": service_code
            }
            
        except Exception as e:
            raise ShippingError(f\"DHL label creation error: {str(e)}\")
            
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        \"\"\"Track a DHL shipment\"\"\"
        # Implementation for tracking API call
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f\"{self.BASE_URL}/shipments/{tracking_number}/tracking\",
                    headers={\"Authorization\": f\"Bearer {self.api_key}\"}
                )
                
                if response.status_code != 200:
                    raise ShippingError(
                        f\"DHL tracking API error: {response.status_code} - {response.text}\"
                    )
                
                data = response.json()
                
                # Parse the response into a TrackingInfo object
                # This is simplified - actual implementation would map DHL's response structure
                tracking_info = TrackingInfo(
                    tracking_number=tracking_number,
                    carrier=self.carrier_code,
                    status=data.get(\"status\", \"unknown\"),
                    status_description=data.get(\"description\", \"\"),
                    estimated_delivery=data.get(\"estimatedDelivery\", \"\"),
                    events=data.get(\"events\", []),
                )
                
                return tracking_info
                
        except httpx.RequestError as e:
            raise ShippingError(f\"DHL tracking API request error: {str(e)}\")
        except Exception as e:
            raise ShippingError(f\"DHL tracking error: {str(e)}\")
    
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        \"\"\"Validate an address using DHL API\"\"\"
        try:
            payload = address.to_dict()
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f\"{self.BASE_URL}/address-validation\",
                    json=payload,
                    headers={\"Authorization\": f\"Bearer {self.api_key}\"}
                )
                
                if response.status_code != 200:
                    raise ShippingError(
                        f\"DHL address validation API error: {response.status_code} - {response.text}\"
                    )
                
                data = response.json()
                
                # Return validation results
                return {
                    \"is_valid\": data.get(\"isValid\", False),
                    \"suggestions\": data.get(\"suggestions\", []),
                    \"normalized_address\": data.get(\"normalizedAddress\", {}),
                    \"messages\": data.get(\"messages\", [])
                }
                
        except httpx.RequestError as e:
            raise ShippingError(f\"DHL address validation API request error: {str(e)}\")
        except Exception as e:
            raise ShippingError(f\"DHL address validation error: {str(e)}\")
"

# Create placeholder carrier files
create_file "$APP_DIR/services/shipping/carriers/ups.py" "\"\"\"
UPS Carrier Implementation

This module implements the UPS shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

UPS API Docs: https://developer.ups.com/
\"\"\"

from typing import List, Dict, Any, Optional
from .base import BaseCarrier
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo

class UPSCarrier(BaseCarrier):
    \"\"\"UPS carrier implementation\"\"\"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = \"UPS\"
        self.carrier_code = \"ups\"
        # Initialize UPS specific configuration
        
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        \"\"\"Get UPS shipping rates\"\"\"
        # Implementation for UPS rate API call
        pass
            
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        \"\"\"Create a UPS shipping label\"\"\"
        # Implementation for UPS label creation
        pass
            
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        \"\"\"Track a UPS shipment\"\"\"
        # Implementation for UPS tracking API call
        pass
    
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        \"\"\"Validate an address using UPS API\"\"\"
        # Implementation for UPS address validation
        pass
"

create_file "$APP_DIR/services/shipping/carriers/fedex.py" "\"\"\"
FedEx Carrier Implementation

This module implements the FedEx shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

FedEx API Docs: https://developer.fedex.com/
\"\"\"

from typing import List, Dict, Any, Optional
from .base import BaseCarrier
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo

class FedExCarrier(BaseCarrier):
    \"\"\"FedEx carrier implementation\"\"\"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = \"FedEx\"
        self.carrier_code = \"fedex\"
        # Initialize FedEx specific configuration
        
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        \"\"\"Get FedEx shipping rates\"\"\"
        # Implementation for FedEx rate API call
        pass
            
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        \"\"\"Create a FedEx shipping label\"\"\"
        # Implementation for FedEx label creation
        pass
            
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        \"\"\"Track a FedEx shipment\"\"\"
        # Implementation for FedEx tracking API call
        pass
    
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        \"\"\"Validate an address using FedEx API\"\"\"
        # Implementation for FedEx address validation
        pass
"

# Create model files
create_file "$APP_DIR/services/shipping/models/__init__.py" "# Shipping models package init file"

create_file "$APP_DIR/services/shipping/models/address.py" "\"\"\"
Address Model

This module defines the Address data model used for shipping operations.
Includes validation and conversion functionality.

The Address model handles:
- Shipping origin and destination addresses
- Address validation formatting
- Conversion to carrier-specific formats
\"\"\"

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class Address(BaseModel):
    \"\"\"
    Standard address model for shipping operations
    
    Used for both origin and destination addresses
    \"\"\"
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
        \"\"\"Convert to dictionary format for API requests\"\"\"
        return {
            \"companyName\": self.company_name,
            \"name\": self.name,
            \"street1\": self.street1,
            \"street2\": self.street2,
            \"street3\": self.street3,
            \"city\": self.city,
            \"state\": self.state,
            \"postalCode\": self.postal_code,
            \"country\": self.country,
            \"phone\": self.phone,
            \"email\": self.email,
            \"isResidential\": self.is_residential
        }
        
    def to_dhl_format(self) -> Dict[str, Any]:
        \"\"\"Convert to DHL-specific address format\"\"\"
        return {
            \"postalAddress\": {
                \"postalCode\": self.postal_code,
                \"cityName\": self.city,
                \"countryCode\": self.country,
                \"provinceCode\": self.state,
                \"addressLine1\": self.street1,
                \"addressLine2\": self.street2,
                \"addressLine3\": self.street3,
                \"companyName\": self.company_name,
                \"countyName\": \"\"  # Not in our model but required by DHL
            },
            \"contactInformation\": {
                \"phone\": self.phone,
                \"emailAddress\": self.email,
                \"personName\": self.name,
                \"companyName\": self.company_name
            },
            \"typeCode\": \"business\" if not self.is_residential else \"residential\"
        }
        
    def to_ups_format(self) -> Dict[str, Any]:
        \"\"\"Convert to UPS-specific address format\"\"\"
        # UPS-specific conversion implementation
        return {}
        
    def to_fedex_format(self) -> Dict[str, Any]:
        \"\"\"Convert to FedEx-specific address format\"\"\"
        # FedEx-specific conversion implementation
        return {}
"

create_file "$APP_DIR/services/shipping/models/package.py" "\"\"\"
Package Model

Defines the Package data model for shipping operations, 
including dimensions, weight, and package characteristics.

Used for:
- Rate calculation
- Label generation
- Package type specification
\"\"\"

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, validator
from enum import Enum

class PackageType(str, Enum):
    \"\"\"Standard package types across carriers\"\"\"
    CUSTOM = \"custom\"
    ENVELOPE = \"envelope\"
    SMALL_BOX = \"small_box\"
    MEDIUM_BOX = \"medium_box\"
    LARGE_BOX = \"large_box\"
    PALLET = \"pallet\"

class WeightUnit(str, Enum):
    \"\"\"Weight measurement units\"\"\"
    KG = \"kg\"
    LB = \"lb\"
    OZ = \"oz\"
    G = \"g\"

class DimensionUnit(str, Enum):
    \"\"\"Dimension measurement units\"\"\"
    CM = \"cm\"
    IN = \"in\"
    MM = \"mm\"
    M = \"m\"

class Package(BaseModel):
    \"\"\"Package model for shipping\"\"\"
    length: float
    width: float
    height: float
    weight: float
    dimension_unit: DimensionUnit = DimensionUnit.CM
    weight_unit: WeightUnit = WeightUnit.KG
    package_type: PackageType = PackageType.CUSTOM
    is_fragile: bool = False
    reference: Optional[str] = None
    items: Optional[List[Dict[str, Any]]] = None
    
    @validator('weight')
    def weight_must_be_positive(cls, v):
        \"\"\"Validate weight is positive\"\"\"
        if v <= 0:
            raise ValueError('Weight must be positive')
        return v
    
    @validator('length', 'width', 'height')
    def dimensions_must_be_positive(cls, v):
        \"\"\"Validate dimensions are positive\"\"\"
        if v <= 0:
            raise ValueError('Dimensions must be positive')
        return v
    
    def to_dict(self) -> Dict[str, Any]:
        \"\"\"Convert to dictionary format for API requests\"\"\"
        return {
            \"length\": self.length,
            \"width\": self.width,
            \"height\": self.height,
            \"weight\": self.weight,
            \"dimensionUnit\": self.dimension_unit,
            \"weightUnit\": self.weight_unit,
            \"packageType\": self.package_type,
            \"isFragile\": self.is_fragile,
            \"reference\": self.reference,
            \"items\": self.items
        }
        
    def get_volume(self) -> float:
        \"\"\"Calculate package volume\"\"\"
        return self.length * self.width * self.height
        
    def convert_weight_to(self, unit: WeightUnit) -> float:
        \"\"\"Convert weight to specified unit\"\"\"
        if self.weight_unit == unit:
            return self.weight
            
        # Conversion logic
        if self.weight_unit == WeightUnit.KG and unit == WeightUnit.LB:
            return self.weight * 2.20462
        elif self.weight_unit == WeightUnit.LB and unit == WeightUnit.KG:
            return self.weight * 0.453592
        
        # Add more conversion logic as needed
        return self.weight
        
    def convert_dimensions_to(self, unit: DimensionUnit) -> Dict[str, float]:
        \"\"\"Convert dimensions to specified unit\"\"\"
        if self.dimension_unit == unit:
            return {\"length\": self.length, \"width\": self.width, \"height\": self.height}
            
        # Conversion logic
        conversion_factor = 1.0
        if self.dimension_unit == DimensionUnit.CM and unit == DimensionUnit.IN:
            conversion_factor = 0.393701
        elif self.dimension_unit == DimensionUnit.IN and unit == DimensionUnit.CM:
            conversion_factor = 2.54
        
        # Add more conversion logic as needed
        
        return {
            \"length\": self.length * conversion_factor,
            \"width\": self.width * conversion_factor,
            \"height\": self.height * conversion_factor
        }
"

create_file "$APP_DIR/services/shipping/models/rate.py" "\"\"\"
Shipping Rate Model

Defines the ShippingRate data model for standardizing rate responses
across different carriers.

Used for:
- Presenting shipping options to users
- Storing and comparing rates
- Selecting shipping services
\"\"\"

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class ShippingRate(BaseModel):
    \"\"\"
    Standardized shipping rate model
    
    Contains all information about a shipping rate option
    from any carrier.
    \"\"\"
    carrier: str
    service_code: str
    service_name: str
    total_price: float
    currency: str = \"USD\"
    estimated_days: Optional[int] = None
    delivery_date: Optional[datetime] = None
    rate_id: str
    metadata: Dict[str, Any] = {}
    
    @property
    def display_price(self) -> str:
        \"\"\"
        Returns formatted price for display
        
        Examples:
            $12.99
            £10.50
            €15.00
        \"\"\"
        currency_symbols = {
            \"USD\": \"$\",
            \"EUR\": \"€\",
            \"GBP\": \"£\",
            \"CAD\": \"C$\",
            \"AUD\": \"A$\"
        }
        
        symbol = currency_symbols.get(self.currency, self.currency + \" \")
        return f\"{symbol}{self.total_price:.2f}\"
        
    @property
    def delivery_estimate(self) -> str:
        \"\"\"
        Returns a user-friendly delivery estimate
        
        Examples:
            "Delivery by Oct 15, 2023"
            "Delivery in 3-5 days"
        \"\"\"
        if self.delivery_date:
            return f\"Delivery by {self.delivery_date.strftime('%b %d, %Y')}\"
        elif self.estimated_days:
            return f\"Delivery in {self.estimated_days} days\"
        else:
            return \"Delivery date unknown\"
            
    def to_dict(self) -> Dict[str, Any]:
        \"\"\"Convert to dictionary for API responses\"\"\"
        result = {
            \"carrier\": self.carrier,
            \"service_code\": self.service_code,
            \"service_name\": self.service_name,
            \"total_price\": self.total_price,
            \"currency\": self.currency,
            \"display_price\": self.display_price,
            \"delivery_estimate\": self.delivery_estimate,
            \"rate_id\": self.rate_id,
        }
        
        if self.estimated_days is not None:
            result[\"estimated_days\"] = self.estimated_days
            
        if self.delivery_date is not None:
            result[\"delivery_date\"] = self.delivery_date.isoformat()
            
        if self.metadata:
            result[\"metadata\"] = self.metadata
            
        return result
"

create_file "$APP_DIR/services/shipping/models/tracking.py" "\"\"\"
Tracking Model

Defines the TrackingInfo data model for standardizing tracking information
across different carriers.

Used for:
- Tracking package status
- Providing delivery estimates
- Logging shipping events
\"\"\"

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Fiel#!/bin/bash

# Set colors for better output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Creating Shipping Service and Test Structure ===${NC}"

# Base directories
APP_DIR="app"
TEST_DIR="tests"

# Function to create directory if it doesn't exist
create_dir() {
    if [ ! -d "$1" ]; then
        mkdir -p "$1"
        echo -e "${GREEN}Created directory: $1${NC}"
    else
        echo -e "${YELLOW}Directory already exists: $1${NC}"
    fi
}

# Function to create file with content if it doesn't exist
create_file() {
    local file_path="$1"
    local content="$2"
    
    if [ ! -f "$file_path" ]; then
        echo -e "$content" > "$file_path"
        echo -e "${GREEN}Created file: $file_path${NC}"
    else
        echo -e "${YELLOW}File already exists (not modified): $file_path${NC}"
    fi
}

# Create necessary directories
echo -e "${GREEN}Creating directory structure...${NC}"
create_dir "$APP_DIR/services/shipping"
create_dir "$APP_DIR/services/shipping/carriers"
create_dir "$APP_DIR/services/shipping/models"
create_dir "$APP_DIR/services/shipping/config"
create_dir "$APP_DIR/services/shipping/utils"

create_dir "$TEST_DIR/unit/services/shipping"
create_dir "$TEST_DIR/unit/services/shipping/carriers"
create_dir "$TEST_DIR/unit/models/shipping"
create_dir "$TEST_DIR/integration/shipping"
create_dir "$TEST_DIR/mocks"
create_dir "$TEST_DIR/fixtures"

# Create shipping service files
echo -e "${GREEN}Creating shipping service files...${NC}"

# Service main file
create_file "$APP_DIR/services/shipping/__init__.py" "# Shipping service package init file"

create_file "$APP_DIR/services/shipping/service.py" "\"\"\"
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
\"\"\"

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
    \"\"\"Main shipping service facade that orchestrates carrier operations\"\"\"
    
    def __init__(self, settings: Optional[ShippingSettings] = None):
        \"\"\"Initialize the shipping service with available carriers\"\"\"
        self.settings = settings or ShippingSettings()
        self.carriers = {}
        self._initialize_carriers()
        
    def _initialize_carriers(self) -> None:
        \"\"\"Initialize available shipping carriers based on configuration\"\"\"
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
        \"\"\"
        Get shipping rates from all enabled carriers or specified carriers
        
        Args:
            package: Package details (dimensions, weight)
            origin: Shipping origin address
            destination: Shipping destination address
            carrier_filter: Optional list of carrier codes to use (e.g., ['dhl', 'ups'])
            
        Returns:
            List of available shipping rates across carriers
        \"\"\"
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
                print(f\"Error getting rates from {carrier_code}: {str(e)}\")
        
        return sorted(rates, key=lambda x: x.total_price)
    
    # Additional methods would be implemented here
"

# Base carrier class
create_file "$APP_DIR/services/shipping/carriers/__init__.py" "# Carriers package init file"

create_file "$APP_DIR/services/shipping/carriers/base.py" "\"\"\"
Base Carrier Interface

This module defines the abstract base class that all shipping carrier
integrations must implement.

Each carrier implementation provides standard methods for:
- Getting shipping rates
- Creating labels
- Tracking shipments
- Validating addresses

This ensures consistency across different carrier implementations.
\"\"\"

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo

class BaseCarrier(ABC):
    \"\"\"
    Abstract base class for shipping carrier implementations.
    All carrier implementations must extend this class.
    \"\"\"
    
    def __init__(self, config: Dict[str, Any]):
        \"\"\"Initialize the carrier with configuration settings\"\"\"
        self.config = config
        self.name = \"BaseCarrier\"
        self.carrier_code = \"base\"
        
    @abstractmethod
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        \"\"\"
        Get available shipping rates for this carrier
        
        Args:
            package: Package details (dimensions, weight)
            origin: Shipping origin address
            destination: Shipping destination address
        
        Returns:
            List of available shipping rates
        \"\"\"
        pass
        
    @abstractmethod
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        \"\"\"
        Create a shipping label
        
        Args:
            rate_id: ID of the rate selected for shipping
            package: Package details (dimensions, weight)
            origin: Shipping origin address
            destination: Shipping destination address
            
        Returns:
            Dictionary containing label information and URL
        \"\"\"
        pass
        
    @abstractmethod
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        \"\"\"
        Track a shipment by tracking number
        
        Args:
            tracking_number: The carrier's tracking number
            
        Returns:
            Tracking information for the shipment
        \"\"\"
        pass
        
    @abstractmethod
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        \"\"\"
        Validate a shipping address
        
        Args:
            address: Address to validate
            
        Returns:
            Dictionary with validation results
        \"\"\"
        pass
"

# DHL carrier implementation
create_file "$APP_DIR/services/shipping/carriers/dhl.py" "\"\"\"
DHL Carrier Implementation

This module implements the DHL shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

DHL API Docs: https://developer.dhl.com/
\"\"\"

from typing import List, Dict, Any, Optional
import httpx
from .base import BaseCarrier
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo
from ..exceptions import ShippingError

class DHLCarrier(BaseCarrier):
    \"\"\"DHL carrier implementation\"\"\"
    
    BASE_URL = \"https://api-mock.dhl.com/\"  # Replace with actual API URL in production
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = \"DHL Express\"
        self.carrier_code = \"dhl\"
        self.api_key = config.get(\"api_key\", \"\")
        self.account_number = config.get(\"account_number\", \"\")
        
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        \"\"\"Get DHL shipping rates\"\"\"
        try:
            # Structure the request payload according to DHL API
            payload = {
                \"customerDetails\": {
                    \"shipperDetails\": origin.to_dict(),
                    \"receiverDetails\": destination.to_dict()
                },
                \"accounts\": [{
                    \"typeCode\": \"shipper\",
                    \"number\": self.account_number
                }],
                \"plannedShippingDateAndTime\": \"2023-10-19T15:00:00GMT+01:00\",
                \"unitOfMeasurement\": \"metric\",
                \"packages\": [{
                    \"weight\": package.weight,
                    \"dimensions\": {
                        \"length\": package.length,
                        \"width\": package.width,
                        \"height\": package.height
                    }
                }]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f\"{self.BASE_URL}/rates\", 
                    json=payload,
                    headers={
                        \"Authorization\": f\"Bearer {self.api_key}\",
                        \"Content-Type\": \"application/json\"
                    }
                )
                
                if response.status_code != 200:
                    raise ShippingError(
                        f\"DHL API error: {response.status_code} - {response.text}\"
                    )
                    
                data = response.json()
                
                # Parse response into ShippingRate objects
                rates = []
                for product in data.get(\"products\", []):
                    rate = ShippingRate(
                        carrier=self.carrier_code,
                        service_code=product.get(\"productCode\"),
                        service_name=product.get(\"productName\"),
                        total_price=float(product.get(\"totalPrice\", [{}])[0].get(\"price\", 0)),
                        currency=product.get(\"totalPrice\", [{}])[0].get(\"currency\", \"USD\"),
                        delivery_date=product.get(\"deliveryCapabilities\", {}).get(\"estimatedDeliveryDate\"),
                        rate_id=f\"dhl_{product.get('productCode')}\",
                        metadata={
                            \"delivery_type\": product.get(\"deliveryCapabilities\", {}).get(\"deliveryTypeCode\"),
                            \"delivery_time\": product.get(\"deliveryCapabilities\", {}).get(\"estimatedDeliveryTime\")
                        }
                    )
                    rates.append(rate)
                    
                return rates
                
        except httpx.RequestError as e:
            raise ShippingError(f\"DHL API request error: {str(e)}\")
        except Exception as e:
            raise ShippingError(f\"DHL carrier error: {str(e)}\")
            
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        \"\"\"Create a DHL shipping label\"\"\"
        # Implementation would be similar to get_rates but calling the label creation endpoint
        # This is a simplified placeholder
        try:
            # Extract service code from rate_id
            service_code = rate_id.replace(\"dhl_\", \"\")
            
            payload = {
                \"customerDetails\": {
                    \"shipperDetails\": origin.to_dict(),
                    \"receiverDetails\": destination.to_dict()
                },
                \"accounts\": [{
                    \"typeCode\": \"shipper\",
                    \"number\": self.account_number
                }],
                \"productCode\": service_code,
                \"plannedShippingDateAndTime\": \"2023-10-19T15:00:00GMT+01:00\",
                \"unitOfMeasurement\": \"metric\",
                \"packages\": [{
                    \"weight\": package.weight,
                    \"dimensions\": {
                        \"length\": package.length,
                        \"width\": package.width,
                        \"height\": package.height
                    }
                }],
                \"outputImageProperties\": {
                    \"printerDPI\": 300,
                    \"encodingFormat\": \"pdf\",
                    \"imageOptions\": [{
                        \"typeCode\": \"label\",
                        \"templateName\": \"ECOM26_A6_001\"
                    }]
                }
            }
            
            # Placeholder implementation
            return {
                \"tracking_number\": \"DHLTRACKINGNUMBER123\",
                \"label_url\": \"https://example.com/label.pdf\",
                \"label_data\": \"base64encodeddata\",
                \"carrier\": self.carrier_code,
                \"service\": service_code
            }
            
        except Exception as e:
            raise ShippingError(f\"DHL label creation error: {str(e)}\")
            
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        \"\"\"Track a DHL shipment\"\"\"
        # Implementation for tracking API call
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f\"{self.BASE_URL}/shipments/{tracking_number}/tracking\",
                    headers={\"Authorization\": f\"Bearer {self.api_key}\"}
                )
                
                if response.status_code != 200:
                    raise ShippingError(
                        f\"DHL tracking API error: {response.status_code} - {response.text}\"
                    )
                
                data = response.json()
                
                # Parse the response into a TrackingInfo object
                # This is simplified - actual implementation would map DHL's response structure
                tracking_info = TrackingInfo(
                    tracking_number=tracking_number,
                    carrier=self.carrier_code,
                    status=data.get(\"status\", \"unknown\"),
                    status_description=data.get(\"description\", \"\"),
                    estimated_delivery=data.get(\"estimatedDelivery\", \"\"),
                    events=data.get(\"events\", []),
                )
                
                return tracking_info
                
        except httpx.RequestError as e:
            raise ShippingError(f\"DHL tracking API request error: {str(e)}\")
        except Exception as e:
            raise ShippingError(f\"DHL tracking error: {str(e)}\")
    
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        \"\"\"Validate an address using DHL API\"\"\"
        try:
            payload = address.to_dict()
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f\"{self.BASE_URL}/address-validation\",
                    json=payload,
                    headers={\"Authorization\": f\"Bearer {self.api_key}\"}
                )
                
                if response.status_code != 200:
                    raise ShippingError(
                        f\"DHL address validation API error: {response.status_code} - {response.text}\"
                    )
                
                data = response.json()
                
                # Return validation results
                return {
                    \"is_valid\": data.get(\"isValid\", False),
                    \"suggestions\": data.get(\"suggestions\", []),
                    \"normalized_address\": data.get(\"normalizedAddress\", {}),
                    \"messages\": data.get(\"messages\", [])
                }
                
        except httpx.RequestError as e:
            raise ShippingError(f\"DHL address validation API request error: {str(e)}\")
        except Exception as e:
            raise ShippingError(f\"DHL address validation error: {str(e)}\")
"

# Create placeholder carrier files
create_file "$APP_DIR/services/shipping/carriers/ups.py" "\"\"\"
UPS Carrier Implementation

This module implements the UPS shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

UPS API Docs: https://developer.ups.com/
\"\"\"

from typing import List, Dict, Any, Optional
from .base import BaseCarrier
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo

class UPSCarrier(BaseCarrier):
    \"\"\"UPS carrier implementation\"\"\"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = \"UPS\"
        self.carrier_code = \"ups\"
        # Initialize UPS specific configuration
        
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        \"\"\"Get UPS shipping rates\"\"\"
        # Implementation for UPS rate API call
        pass
            
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        \"\"\"Create a UPS shipping label\"\"\"
        # Implementation for UPS label creation
        pass
            
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        \"\"\"Track a UPS shipment\"\"\"
        # Implementation for UPS tracking API call
        pass
    
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        \"\"\"Validate an address using UPS API\"\"\"
        # Implementation for UPS address validation
        pass
"

create_file "$APP_DIR/services/shipping/carriers/fedex.py" "\"\"\"
FedEx Carrier Implementation

This module implements the FedEx shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

FedEx API Docs: https://developer.fedex.com/
\"\"\"

from typing import List, Dict, Any, Optional
from .base import BaseCarrier
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo

class FedExCarrier(BaseCarrier):
    \"\"\"FedEx carrier implementation\"\"\"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = \"FedEx\"
        self.carrier_code = \"fedex\"
        # Initialize FedEx specific configuration
        
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        \"\"\"Get FedEx shipping rates\"\"\"
        # Implementation for FedEx rate API call
        pass
            
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        \"\"\"Create a FedEx shipping label\"\"\"
        # Implementation for FedEx label creation
        pass
            
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        \"\"\"Track a FedEx shipment\"\"\"
        # Implementation for FedEx tracking API call
        pass
    
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        \"\"\"Validate an address using FedEx API\"\"\"
        # Implementation for FedEx address validation
        pass
"

# Create model files
create_file "$APP_DIR/services/shipping/models/__init__.py" "# Shipping models package init file"

create_file "$APP_DIR/services/shipping/models/address.py" "\"\"\"
Address Model

This module defines the Address data model used for shipping operations.
Includes validation and conversion functionality.

The Address model handles:
- Shipping origin and destination addresses
- Address validation formatting
- Conversion to carrier-specific formats
\"\"\"

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class Address(BaseModel):
    \"\"\"
    Standard address model for shipping operations
    
    Used for both origin and destination addresses
    \"\"\"
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
        \"\"\"Convert to dictionary format for API requests\"\"\"
        return {
            \"companyName\": self.company_name,
            \"name\": self.name,
            \"street1\": self.street1,
            \"street2\": self.street2,
            \"street3\": self.street3,
            \"city\": self.city,
            \"state\": self.state,
            \"postalCode\": self.postal_code,
            \"country\": self.country,
            \"phone\": self.phone,
            \"email\": self.email,
            \"isResidential\": self.is_residential
        }
        
    def to_dhl_format(self) -> Dict[str, Any]:
        \"\"\"Convert to DHL-specific address format\"\"\"
        return {
            \"postalAddress\": {
                \"postalCode\": self.postal_code,
                \"cityName\": self.city,
                \"countryCode\": self.country,
                \"provinceCode\": self.state,
                \"addressLine1\": self.street1,
                \"addressLine2\": self.street2,
                \"addressLine3\": self.street3,
                \"companyName\": self.company_name,
                \"countyName\": \"\"  # Not in our model but required by DHL
            },
            \"contactInformation\": {
                \"phone\": self.phone,
                \"emailAddress\": self.email,
                \"personName\": self.name,
                \"companyName\": self.company_name
            },
            \"typeCode\": \"business\" if not self.is_residential else \"residential\"
        }
        
    def to_ups_format(self) -> Dict[str, Any]:
        \"\"\"Convert to UPS-specific address format\"\"\"
        # UPS-specific conversion implementation
        return {}
        
    def to_fedex_format(self) -> Dict[str, Any]:
        \"\"\"Convert to FedEx-specific address format\"\"\"
        # FedEx-specific conversion implementation
        return {}
"

create_file "$APP_DIR/services/shipping/models/package.py" "\"\"\"
Package Model

Defines the Package data model for shipping operations, 
including dimensions, weight, and package characteristics.

Used for:
- Rate calculation
- Label generation
- Package type specification
\"\"\"

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, validator
from enum import Enum

class PackageType(str, Enum):
    \"\"\"Standard package types across carriers\"\"\"
    CUSTOM = \"custom\"
    ENVELOPE = \"envelope\"
    SMALL_BOX = \"small_box\"
    MEDIUM_BOX = \"medium_box\"
    LARGE_BOX = \"large_box\"
    PALLET = \"pallet\"

class WeightUnit(str, Enum):
    \"\"\"Weight measurement units\"\"\"
    KG = \"kg\"
    LB = \"lb\"
    OZ = \"oz\"
    G = \"g\"

class DimensionUnit(str, Enum):
    \"\"\"Dimension measurement units\"\"\"
    CM = \"cm\"
    IN = \"in\"
    MM = \"mm\"
    M = \"m\"

class Package(BaseModel):
    \"\"\"Package model for shipping\"\"\"
    length: float
    width: float
    height: float
    weight: float
    dimension_unit: DimensionUnit = DimensionUnit.CM
    weight_unit: WeightUnit = WeightUnit.KG
    package_type: PackageType = PackageType.CUSTOM
    is_fragile: bool = False
    reference: Optional[str] = None
    items: Optional[List[Dict[str, Any]]] = None
    
    @validator('weight')
    def weight_must_be_positive(cls, v):
        \"\"\"Validate weight is positive\"\"\"
        if v <= 0:
            raise ValueError('Weight must be positive')
        return v
    
    @validator('length', 'width', 'height')
    def dimensions_must_be_positive(cls, v):
        \"\"\"Validate dimensions are positive\"\"\"
        if v <= 0:
            raise ValueError('Dimensions must be positive')
        return v
    
    def to_dict(self) -> Dict[str, Any]:
        \"\"\"Convert to dictionary format for API requests\"\"\"
        return {
            \"length\": self.length,
            \"width\": self.width,
            \"height\": self.height,
            \"weight\": self.weight,
            \"dimensionUnit\": self.dimension_unit,
            \"weightUnit\": self.weight_unit,
            \"packageType\": self.package_type,
            \"isFragile\": self.is_fragile,
            \"reference\": self.reference,
            \"items\": self.items
        }
        
    def get_volume(self) -> float:
        \"\"\"Calculate package volume\"\"\"
        return self.length * self.width * self.height
        
    def convert_weight_to(self, unit: WeightUnit) -> float:
        \"\"\"Convert weight to specified unit\"\"\"
        if self.weight_unit == unit:
            return self.weight
            
        # Conversion logic
        if self.weight_unit == WeightUnit.KG and unit == WeightUnit.LB:
            return self.weight * 2.20462
        elif self.weight_unit == WeightUnit.LB and unit == WeightUnit.KG:
            return self.weight * 0.453592
        
        # Add more conversion logic as needed
        return self.weight
        
    def convert_dimensions_to(self, unit: DimensionUnit) -> Dict[str, float]:
        \"\"\"Convert dimensions to specified unit\"\"\"
        if self.dimension_unit == unit:
            return {\"length\": self.length, \"width\": self.width, \"height\": self.height}
            
        # Conversion logic
        conversion_factor = 1.0
        if self.dimension_unit == DimensionUnit.CM and unit == DimensionUnit.IN:
            conversion_factor = 0.393701
        elif self.dimension_unit == DimensionUnit.IN and unit == DimensionUnit.CM:
            conversion_factor = 2.54
        
        # Add more conversion logic as needed
        
        return {
            \"length\": self.length * conversion_factor,
            \"width\": self.width * conversion_factor,
            \"height\": self.height * conversion_factor
        }
"

create_file "$APP_DIR/services/shipping/models/rate.py" "\"\"\"
Shipping Rate Model

Defines the ShippingRate data model for standardizing rate responses
across different carriers.

Used for:
- Presenting shipping options to users
- Storing and comparing rates
- Selecting shipping services
\"\"\"

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class ShippingRate(BaseModel):
    \"\"\"
    Standardized shipping rate model
    
    Contains all information about a shipping rate option
    from any carrier.
    \"\"\"
    carrier: str
    service_code: str
    service_name: str
    total_price: float
    currency: str = \"USD\"
    estimated_days: Optional[int] = None
    delivery_date: Optional[datetime] = None
    rate_id: str
    metadata: Dict[str, Any] = {}
    
    @property
    def display_price(self) -> str:
        \"\"\"
        Returns formatted price for display
        
        Examples:
            $12.99
            £10.50
            €15.00
        \"\"\"
        currency_symbols = {
            \"USD\": \"$\",
            \"EUR\": \"€\",
            \"GBP\": \"£\",
            \"CAD\": \"C$\",
            \"AUD\": \"A$\"
        }
        
        symbol = currency_symbols.get(self.currency, self.currency + \" \")
        return f\"{symbol}{self.total_price:.2f}\"
        
    @property
    def delivery_estimate(self) -> str:
        \"\"\"
        Returns a user-friendly delivery estimate
        
        Examples:
            "Delivery by Oct 15, 2023"
            "Delivery in 3-5 days"
        \"\"\"
        if self.delivery_date:
            return f\"Delivery by {self.delivery_date.strftime('%b %d, %Y')}\"
        elif self.estimated_days:
            return f\"Delivery in {self.estimated_days} days\"
        else:
            return \"Delivery date unknown\"
            
    def to_dict(self) -> Dict[str, Any]:
        \"\"\"Convert to dictionary for API responses\"\"\"
        result = {
            \"carrier\": self.carrier,
            \"service_code\": self.service_code,
            \"service_name\": self.service_name,
            \"total_price\": self.total_price,
            \"currency\": self.currency,
            \"display_price\": self.display_price,
            \"delivery_estimate\": self.delivery_estimate,
            \"rate_id\": self.rate_id,
        }
        
        if self.estimated_days is not None:
            result[\"estimated_days\"] = self.estimated_days
            
        if self.delivery_date is not None:
            result[\"delivery_date\"] = self.delivery_date.isoformat()
            
        if self.metadata:
            result[\"metadata\"] = self.metadata
            
        return result
"

create_file "$APP_DIR/services/shipping/models/tracking.py" "\"\"\"
Tracking Model

Defines the TrackingInfo data model for standardizing tracking information
across different carriers.

Used for:
- Tracking package status
- Providing delivery estimates
- Logging shipping events
\"\"\"

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class TrackingStatus(str, Enum):
    \"\"\"Standardized tracking status codes across carriers\"\"\"
    UNKNOWN = \"unknown\"
    LABEL_CREATED = \"label_created\"
    PICKED_UP = \"picked_up\"
    IN_TRANSIT = \"in_transit\"
    OUT_FOR_DELIVERY = \"out_for_delivery\"
    DELIVERED = \"delivered\"
    EXCEPTION = \"exception\"
    DELAYED = \"delayed\"
    RETURN_TO_SENDER = \"return_to_sender\"

class TrackingEvent(BaseModel):
    \"\"\"Individual event in the tracking history\"\"\"
    timestamp: datetime
    status: str
    description: str
    location: Optional[str] = None
    metadata: Dict[str, Any] = {}

class TrackingInfo(BaseModel):
    \"\"\"
    Standardized tracking information model
    
    Contains all tracking details for a shipment regardless
    of the carrier used.
    \"\"\"
    tracking_number: str
    carrier: str
    status: TrackingStatus
    status_description: str
    estimated_delivery: Optional[datetime] = None
    actual_delivery: Optional[datetime] = None
    events: List[TrackingEvent] = []
    metadata: Dict[str, Any] = {}
    
    @property
    def is_delivered(self) -> bool:
        \"\"\"Check if package has been delivered\"\"\"
        return self.status == TrackingStatus.DELIVERED
        
    @property
    def days_in_transit(self) -> Optional[int]:
        \"\"\"Calculate days in transit if applicable\"\"\"
        if not self.events:
            return None
            
        # Find the first event (usually label creation)
        first_event = min(self.events, key=lambda e: e.timestamp)
        
        # Calculate days since first event
        if self.is_delivered and self.actual_delivery:
            delta = self.actual_delivery - first_event.timestamp
        else:
            delta = datetime.now() - first_event.timestamp
            
        return delta.days
        
    def get_latest_event(self) -> Optional[TrackingEvent]:
        \"\"\"Get the most recent tracking event\"\"\"
        if not self.events:
            return None
            
        return max(self.events, key=lambda e: e.timestamp)
        
    def to_dict(self) -> Dict[str, Any]:
        \"\"\"Convert to dictionary for API responses\"\"\"
        result = {
            \"tracking_number\": self.tracking_number,
            \"carrier\": self.carrier,
            \"status\": self.status,
            \"status_description\": self.status_description,
            \"is_delivered\": self.is_delivered,
            \"events\": [event.dict() for event in self.events],
        }
        
        if self.estimated_delivery:
            result[\"estimated_delivery\"] = self.estimated_delivery.isoformat()
            
        if self.actual_delivery:
            result[\"actual_delivery\"] = self.actual_delivery.isoformat()
            
        if self.days_in_transit is not None:
            result[\"days_in_transit\"] = self.days_in_transit
            
        if self.metadata:
            result[\"metadata\"] = self.metadata
            
        return result
"
