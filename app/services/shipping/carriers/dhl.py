"""
DHL Carrier Implementation

This module implements the DHL shipping carrier API integration.

Features:
- Rate calculation
- Shipment creation
- Label generation
- Shipment tracking
- Address validation

DHL API Docs:
 - https://developer.dhl.com/api-catalog
 - https://developer.dhl.com/api-reference/dhl-express-mydhl-api#get-started-section/
 - https://developer.dhl.com/api-reference/dhl-express-mydhl-api#reference-docs-section
"""

import base64
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union

import requests
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.shipping.base import BaseCarrier
from app.models.shipping import Shipment


class DHLCarrier(BaseCarrier):
    """DHL Express carrier implementation."""
    
    carrier_name = "DHL Express"
    carrier_code = "dhl"
    
    def __init__(self, db: AsyncSession = None):
        """Initialize the DHL Express carrier.
        
        Args:
            db: Database session for persistence operations
        """
        super().__init__(db)
        settings = get_settings()
        
        # Initialize credentials from environment variables
        self.api_key = settings.DHL_API_KEY
        self.api_secret = settings.DHL_API_SECRET
        self.account_number = settings.DHL_ACCOUNT_NUMBER
        self.test_mode = settings.DHL_TEST_MODE
        
        # Base URL varies depending on test mode
        self.base_url = "https://express.api.dhl.com/mydhlapi/test" if self.test_mode else "https://express.api.dhl.com/mydhlapi"
        
        # Authentication credentials
        self.credentials = f"{self.api_key}:{self.api_secret}"
        self.encoded_credentials = base64.b64encode(self.credentials.encode()).decode()
    
    def _get_headers(self, include_message_ref: bool = False) -> Dict[str, str]:
        """Get the standard headers for API requests
        
        Args:
            include_message_ref: Whether to include a message reference (needed for some endpoints)
            
        Returns:
            Dictionary of headers
        """
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Basic {self.encoded_credentials}'
        }
        
        if include_message_ref:
            # Generate a UUID for the message reference (required length: 28-36 chars)
            headers['Message-Reference'] = str(uuid.uuid4())
            headers['Message-Reference-Date'] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S GMT+00:00")
            
        return headers
    
    async def create_shipment(self, shipment_details: Dict[str, Any]) -> Dict[str, Any]:
        """Create a shipment with DHL Express
        
        Args:
            shipment_details: Shipment details following DHL API format
            
        Returns:
            API response with tracking number, labels, etc.
        """
        shipment_url = f"{self.base_url}/shipments"
        
        # Ensure account number is set in the payload
        if 'accounts' not in shipment_details:
            shipment_details['accounts'] = [
                {
                    "number": self.account_number,
                    "typeCode": "shipper"
                }
            ]
        
        try:
            # Create shipment request
            response = requests.post(
                shipment_url, 
                headers=self._get_headers(include_message_ref=True), 
                json=shipment_details
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                self._log_success(f"Shipment created successfully! Tracking number: {result.get('shipmentTrackingNumber', 'N/A')}")
                
                # Save shipping labels if present
                self._save_shipping_documents(result)
                
                # Update shipment record in database if db session provided
                if self.db and 'shipmentTrackingNumber' in result:
                    # Implementation depends on your database model
                    # This is a placeholder - implement actual DB update
                    pass
                
                return result
            else:
                self._log_error(f"Error creating shipment: {response.status_code}", response.text)
                return {"status": "error", "details": response.text}
                
        except Exception as e:
            self._log_error("Exception during shipment creation", str(e))
            return {"status": "error", "details": str(e)}
    
    async def track_shipment(self, tracking_number: str) -> Dict[str, Any]:
        """Track a shipment by its tracking number
        
        Args:
            tracking_number: DHL shipment tracking number
            
        Returns:
            Tracking information
        """
        tracking_url = f"{self.base_url}/shipments/{tracking_number}/tracking"
        
        try:
            response = requests.get(
                tracking_url,
                headers=self._get_headers()
            )
            
            if response.status_code == 200:
                result = response.json()
                self._log_success(f"Tracking information retrieved for: {tracking_number}")
                return result
            else:
                self._log_error(f"Error tracking shipment: {response.status_code}", response.text)
                return {"status": "error", "details": response.text}
                
        except Exception as e:
            self._log_error("Exception during tracking", str(e))
            return {"status": "error", "details": str(e)}
    
    async def get_rates(self, shipment_details: Dict[str, Any]) -> Dict[str, Any]:
        """Get shipping rates for a potential shipment
        
        Args:
            shipment_details: Shipment details following DHL API format
            
        Returns:
            Rate information
        """
        rates_url = f"{self.base_url}/rates"
        
        try:
            response = requests.post(
                rates_url, 
                headers=self._get_headers(), 
                json=shipment_details
            )
            
            if response.status_code == 200:
                result = response.json()
                self._log_success(f"Rate information retrieved")
                return result
            else:
                self._log_error(f"Error getting rates: {response.status_code}", response.text)
                return {"status": "error", "details": response.text}
                
        except Exception as e:
            self._log_error("Exception during rate request", str(e))
            return {"status": "error", "details": str(e)}
    
    async def validate_address(self, address_details: Dict[str, Any]) -> Dict[str, Any]:
        """Validate an address using DHL's address validation service
        
        Args:
            address_details: Address details to validate
            
        Returns:
            Validation results
        """
        validation_url = f"{self.base_url}/address-validate"
        
        try:
            response = requests.post(
                validation_url, 
                headers=self._get_headers(), 
                json=address_details
            )
            
            if response.status_code == 200:
                result = response.json()
                self._log_success(f"Address validation completed")
                return result
            else:
                self._log_error(f"Error validating address: {response.status_code}", response.text)
                return {"status": "error", "details": response.text}
                
        except Exception as e:
            self._log_error("Exception during address validation", str(e))
            return {"status": "error", "details": str(e)}
    
    def _save_shipping_documents(self, response_data: Dict[str, Any]) -> List[str]:
        """Save shipping documents (labels, waybills, etc.) from API response
        
        Args:
            response_data: API response containing documents
            
        Returns:
            List of saved document filenames
        """
        saved_files = []
        
        if 'documents' in response_data:
            for document in response_data['documents']:
                if document['typeCode'] in ['waybillDoc', 'label', 'invoice']:
                    content = document['content']
                    filename = f"dhl_{document['typeCode']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
                    
                    # Decode base64 content
                    pdf_content = base64.b64decode(content)
                    
                    # Save to appropriate location based on your application
                    # This is a placeholder - implement actual file saving
                    with open(filename, 'wb') as f:
                        f.write(pdf_content)
                    
                    self._log_success(f"Document saved as {filename}")
                    saved_files.append(filename)
        
        return saved_files
    
    def _log_success(self, message: str) -> None:
        """Log success messages"""
        # Implement appropriate logging based on your application
        print(f"SUCCESS: {message}")
    
    def _log_error(self, message: str, details: str = None) -> None:
        """Log error messages"""
        # Implement appropriate logging based on your application
        print(f"ERROR: {message}")
        if details:
            print(details)

    # Helper methods for building common shipment types

    async def create_uk_shipment(self, 
                          shipper_details: Dict[str, Any], 
                          receiver_details: Dict[str, Any],
                          package_details: Dict[str, Any],
                          reference: str = None) -> Dict[str, Any]:
        """Create a UK domestic shipment
        
        Args:
            shipper_details: Shipper address and contact details
            receiver_details: Receiver address and contact details
            package_details: Package weight and dimensions
            reference: Optional customer reference
            
        Returns:
            API response from shipment creation
        """
        # Format the shipping date for tomorrow
        shipping_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT10:00:00 GMT+00:00")
        
        # Build the shipment payload
        shipment_payload = {
            "plannedShippingDateAndTime": shipping_date,
            "pickup": {
                "isRequested": False
            },
            "productCode": "I",  # Domestic Express for UK
            "outputImageProperties": {
                "printerDPI": 300,
                "encodingFormat": "pdf",
                "imageOptions": [
                    {
                        "typeCode": "waybillDoc",
                        "templateName": "ARCH_8x4",
                        "isRequested": True
                    },
                    {
                        "typeCode": "label",
                        "templateName": "ECOM26_84_001",
                        "isRequested": True
                    }
                ]
            },
            "customerDetails": {
                "shipperDetails": shipper_details,
                "receiverDetails": receiver_details
            },
            "content": {
                "packages": [package_details],
                "isCustomsDeclarable": False,
                "description": "Domestic shipment",
                "incoterm": "DAP",
                "unitOfMeasurement": "metric"
            },
            "estimatedDeliveryDate": {
                "isRequested": True,
                "typeCode": "QDDC"
            }
        }
        
        # Add customer reference if provided
        if reference and 'packages' in shipment_payload['content'] and shipment_payload['content']['packages']:
            shipment_payload['content']['packages'][0]['customerReferences'] = [
                {
                    "value": reference,
                    "typeCode": "CU"
                }
            ]
        
        return await self.create_shipment(shipment_payload)
    
    async def create_eu_shipment(self,
                          shipper_details: Dict[str, Any], 
                          receiver_details: Dict[str, Any],
                          package_details: Dict[str, Any],
                          customs_details: Dict[str, Any],
                          reference: str = None) -> Dict[str, Any]:
        """Create an EU international shipment
        
        Args:
            shipper_details: Shipper address and contact details
            receiver_details: Receiver address and contact details
            package_details: Package weight and dimensions
            customs_details: Customs declaration details
            reference: Optional customer reference
            
        Returns:
            API response from shipment creation
        """
        # Format the shipping date for tomorrow
        shipping_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT10:00:00 GMT+00:00")
        
        # Build the shipment payload
        shipment_payload = {
            "plannedShippingDateAndTime": shipping_date,
            "pickup": {
                "isRequested": False
            },
            "productCode": "P",  # Express Worldwide
            "outputImageProperties": {
                "printerDPI": 300,
                "encodingFormat": "pdf",
                "imageOptions": [
                    {
                        "typeCode": "waybillDoc",
                        "templateName": "ARCH_8x4",
                        "isRequested": True
                    },
                    {
                        "typeCode": "label",
                        "templateName": "ECOM26_84_001",
                        "isRequested": True
                    },
                    {
                        "typeCode": "invoice",
                        "templateName": "COMMERCIAL_INVOICE_P_10",
                        "isRequested": True,
                        "invoiceType": "commercial"
                    }
                ]
            },
            "customerDetails": {
                "shipperDetails": shipper_details,
                "receiverDetails": receiver_details
            },
            "content": {
                "packages": [package_details],
                "isCustomsDeclarable": True,
                "description": customs_details.get("description", "EU shipment"),
                "declaredValue": customs_details.get("declaredValue", 100.00),
                "declaredValueCurrency": customs_details.get("declaredValueCurrency", "EUR"),
                "incoterm": "DAP",
                "unitOfMeasurement": "metric",
                "exportDeclaration": customs_details.get("exportDeclaration", {})
            },
            "estimatedDeliveryDate": {
                "isRequested": True,
                "typeCode": "QDDC"
            }
        }
        
        # Add customer reference if provided
        if reference and 'packages' in shipment_payload['content'] and shipment_payload['content']['packages']:
            shipment_payload['content']['packages'][0]['customerReferences'] = [
                {
                    "value": reference,
                    "typeCode": "CU"
                }
            ]
        
        return await self.create_shipment(shipment_payload)
    
    async def create_row_shipment(self,
                           shipper_details: Dict[str, Any], 
                           receiver_details: Dict[str, Any],
                           package_details: Dict[str, Any],
                           customs_details: Dict[str, Any],
                           reference: str = None) -> Dict[str, Any]:
        """Create a Rest of World international shipment
        
        Args:
            shipper_details: Shipper address and contact details
            receiver_details: Receiver address and contact details
            package_details: Package weight and dimensions
            customs_details: Customs declaration details
            reference: Optional customer reference
            
        Returns:
            API response from shipment creation
        """
        # This is very similar to EU shipment but potentially with different
        # customs requirements - for now, we'll use the same implementation
        # but this can be customized further as needed
        return await self.create_eu_shipment(
            shipper_details,
            receiver_details,
            package_details,
            customs_details,
            reference
        )
