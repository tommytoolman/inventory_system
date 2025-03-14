"""
DHL Carrier Implementation

This module implements the DHL shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

DHL API Docs: https://developer.dhl.com/
"""

from typing import List, Dict, Any, Optional
import httpx
from .base import BaseCarrier
from ..models.package import Package
from ..models.address import Address
from ..models.rate import ShippingRate
from ..models.tracking import TrackingInfo
from ..exceptions import ShippingError

class DHLCarrier(BaseCarrier):
    """DHL carrier implementation"""
    
    BASE_URL = "https://api-mock.dhl.com/"  # Replace with actual API URL in production
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "DHL Express"
        self.carrier_code = "dhl"
        self.api_key = config.get("api_key", "")
        self.account_number = config.get("account_number", "")
        
    async def get_rates(
        self, 
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> List[ShippingRate]:
        """Get DHL shipping rates"""
        try:
            # Structure the request payload according to DHL API
            payload = {
                "customerDetails": {
                    "shipperDetails": origin.to_dict(),
                    "receiverDetails": destination.to_dict()
                },
                "accounts": [{
                    "typeCode": "shipper",
                    "number": self.account_number
                }],
                "plannedShippingDateAndTime": "2023-10-19T15:00:00GMT+01:00",
                "unitOfMeasurement": "metric",
                "packages": [{
                    "weight": package.weight,
                    "dimensions": {
                        "length": package.length,
                        "width": package.width,
                        "height": package.height
                    }
                }]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/rates", 
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                
                if response.status_code != 200:
                    raise ShippingError(
                        f"DHL API error: {response.status_code} - {response.text}"
                    )
                    
                data = response.json()
                
                # Parse response into ShippingRate objects
                rates = []
                for product in data.get("products", []):
                    rate = ShippingRate(
                        carrier=self.carrier_code,
                        service_code=product.get("productCode"),
                        service_name=product.get("productName"),
                        total_price=float(product.get("totalPrice", [{}])[0].get("price", 0)),
                        currency=product.get("totalPrice", [{}])[0].get("currency", "USD"),
                        delivery_date=product.get("deliveryCapabilities", {}).get("estimatedDeliveryDate"),
                        rate_id=f"dhl_{product.get('productCode')}",
                        metadata={
                            "delivery_type": product.get("deliveryCapabilities", {}).get("deliveryTypeCode"),
                            "delivery_time": product.get("deliveryCapabilities", {}).get("estimatedDeliveryTime")
                        }
                    )
                    rates.append(rate)
                    
                return rates
                
        except httpx.RequestError as e:
            raise ShippingError(f"DHL API request error: {str(e)}")
        except Exception as e:
            raise ShippingError(f"DHL carrier error: {str(e)}")
            
    async def create_label(
        self,
        rate_id: str,
        package: Package, 
        origin: Address, 
        destination: Address
    ) -> Dict[str, Any]:
        """Create a DHL shipping label"""
        # Implementation would be similar to get_rates but calling the label creation endpoint
        # This is a simplified placeholder
        try:
            # Extract service code from rate_id
            service_code = rate_id.replace("dhl_", "")
            
            payload = {
                "customerDetails": {
                    "shipperDetails": origin.to_dict(),
                    "receiverDetails": destination.to_dict()
                },
                "accounts": [{
                    "typeCode": "shipper",
                    "number": self.account_number
                }],
                "productCode": service_code,
                "plannedShippingDateAndTime": "2023-10-19T15:00:00GMT+01:00",
                "unitOfMeasurement": "metric",
                "packages": [{
                    "weight": package.weight,
                    "dimensions": {
                        "length": package.length,
                        "width": package.width,
                        "height": package.height
                    }
                }],
                "outputImageProperties": {
                    "printerDPI": 300,
                    "encodingFormat": "pdf",
                    "imageOptions": [{
                        "typeCode": "label",
                        "templateName": "ECOM26_A6_001"
                    }]
                }
            }
            
            # Placeholder implementation
            return {
                "tracking_number": "DHLTRACKINGNUMBER123",
                "label_url": "https://example.com/label.pdf",
                "label_data": "base64encodeddata",
                "carrier": self.carrier_code,
                "service": service_code
            }
            
        except Exception as e:
            raise ShippingError(f"DHL label creation error: {str(e)}")
            
    async def track_shipment(self, tracking_number: str) -> TrackingInfo:
        """Track a DHL shipment"""
        # Implementation for tracking API call
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/shipments/{tracking_number}/tracking",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                
                if response.status_code != 200:
                    raise ShippingError(
                        f"DHL tracking API error: {response.status_code} - {response.text}"
                    )
                
                data = response.json()
                
                # Parse the response into a TrackingInfo object
                # This is simplified - actual implementation would map DHL's response structure
                tracking_info = TrackingInfo(
                    tracking_number=tracking_number,
                    carrier=self.carrier_code,
                    status=data.get("status", "unknown"),
                    status_description=data.get("description", ""),
                    estimated_delivery=data.get("estimatedDelivery", ""),
                    events=data.get("events", []),
                )
                
                return tracking_info
                
        except httpx.RequestError as e:
            raise ShippingError(f"DHL tracking API request error: {str(e)}")
        except Exception as e:
            raise ShippingError(f"DHL tracking error: {str(e)}")
    
    async def validate_address(self, address: Address) -> Dict[str, Any]:
        """Validate an address using DHL API"""
        try:
            payload = address.to_dict()
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/address-validation",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                
                if response.status_code != 200:
                    raise ShippingError(
                        f"DHL address validation API error: {response.status_code} - {response.text}"
                    )
                
                data = response.json()
                
                # Return validation results
                return {
                    "is_valid": data.get("isValid", False),
                    "suggestions": data.get("suggestions", []),
                    "normalized_address": data.get("normalizedAddress", {}),
                    "messages": data.get("messages", [])
                }
                
        except httpx.RequestError as e:
            raise ShippingError(f"DHL address validation API request error: {str(e)}")
        except Exception as e:
            raise ShippingError(f"DHL address validation error: {str(e)}")

