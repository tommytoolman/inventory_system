# app/services/shipping/payload_builder.py
"""
DHL Payload Builder

Converts Reverb and eBay order data into DHL API payloads.
Handles UK domestic, EU, and Rest of World shipments with appropriate
customs declarations.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Literal
from dataclasses import dataclass
from enum import Enum

from app.core.config import get_settings


class DestinationType(str, Enum):
    """Shipping destination classification"""
    UK_DOMESTIC = "uk"
    EU = "eu"
    ROW = "row"  # Rest of World


# EU member states (post-Brexit)
EU_COUNTRY_CODES = {
    'AT',  # Austria
    'BE',  # Belgium
    'BG',  # Bulgaria
    'HR',  # Croatia
    'CY',  # Cyprus
    'CZ',  # Czech Republic
    'DK',  # Denmark
    'EE',  # Estonia
    'FI',  # Finland
    'FR',  # France
    'DE',  # Germany
    'GR',  # Greece
    'HU',  # Hungary
    'IE',  # Ireland
    'IT',  # Italy
    'LV',  # Latvia
    'LT',  # Lithuania
    'LU',  # Luxembourg
    'MT',  # Malta
    'NL',  # Netherlands
    'PL',  # Poland
    'PT',  # Portugal
    'RO',  # Romania
    'SK',  # Slovakia
    'SI',  # Slovenia
    'ES',  # Spain
    'SE',  # Sweden
}

# HS Codes for musical instruments
HS_CODES = {
    'electric_guitar': '9202900030',
    'acoustic_guitar': '9202900030',
    'bass_guitar': '9202900030',
    'amplifier': '8518400000',
    'effects_pedal': '8543709099',
    'keyboard': '9201100000',
    'drums': '9206000000',
    'other': '9209999000',
}

# DHL Express Product Codes
# See: https://developer.dhl.com/api-reference/dhl-express-mydhl-api
DHL_PRODUCT_CODES = {
    # Domestic
    'N': 'DOM - Domestic Express',
    # International
    'P': 'WPX - Express Worldwide (products/goods)',
    'D': 'DOX - Express Worldwide (documents only)',
    'U': 'ECX - Express Worldwide EU',
    # Time-definite
    'K': 'TDK - Express 9:00',
    'T': 'TDT - Express 12:00',
    'E': 'TDE - Express 9:00 (nondoc)',
    # Economy
    'H': 'ESI - Economy Select',
    'W': 'ESU - Economy Select EU',
}


@dataclass
class ShipperConfig:
    """Shipper (sender) configuration"""
    company_name: str
    contact_name: str
    email: str
    phone: str
    address_line1: str
    address_line2: Optional[str]
    city: str
    postal_code: str
    country_code: str = "GB"
    country_name: str = "UNITED KINGDOM"
    vat_number: Optional[str] = None
    eori_number: Optional[str] = None


def get_default_shipper() -> ShipperConfig:
    """Get shipper config from environment settings."""
    settings = get_settings()
    return ShipperConfig(
        company_name=settings.DHL_SHIPPER_COMPANY or "London Vintage Guitars",
        contact_name=settings.DHL_SHIPPER_CONTACT or "London Vintage Guitars",
        email=settings.DHL_SHIPPER_EMAIL or settings.DHL_EMAIL or "",
        phone=settings.DHL_SHIPPER_PHONE or "",
        address_line1=settings.DHL_SHIPPER_ADDRESS1 or "",
        address_line2=settings.DHL_SHIPPER_ADDRESS2 or None,
        city=settings.DHL_SHIPPER_CITY or "London",
        postal_code=settings.DHL_SHIPPER_POSTCODE or "",
        country_code="GB",
        country_name="UNITED KINGDOM",
        vat_number=settings.DHL_SHIPPER_VAT or None,
        eori_number=settings.DHL_SHIPPER_EORI or None,
    )


class DHLPayloadBuilder:
    """
    Builds DHL Express API payloads from marketplace order data.

    Supports:
    - Reverb orders
    - eBay orders
    - UK domestic, EU, and international shipments
    """

    def __init__(self, shipper: Optional[ShipperConfig] = None):
        """
        Initialize the payload builder.

        Args:
            shipper: Shipper configuration. Defaults to config from environment.
        """
        self.shipper = shipper or get_default_shipper()
        self.settings = get_settings()

    def classify_destination(self, country_code: str) -> DestinationType:
        """
        Classify destination as UK, EU, or Rest of World.

        Args:
            country_code: ISO 2-letter country code

        Returns:
            DestinationType enum value
        """
        country_code = country_code.upper()

        if country_code == 'GB':
            return DestinationType.UK_DOMESTIC
        elif country_code in EU_COUNTRY_CODES:
            return DestinationType.EU
        else:
            return DestinationType.ROW

    def _build_shipper_details(self) -> Dict[str, Any]:
        """Build DHL shipper details from config."""
        details = {
            "postalAddress": {
                "postalCode": self.shipper.postal_code,
                "cityName": self.shipper.city,
                "countryCode": self.shipper.country_code,
                "addressLine1": self.shipper.address_line1,
                "countryName": self.shipper.country_name,
            },
            "contactInformation": {
                "email": self.shipper.email,
                "phone": self.shipper.phone,
                "companyName": self.shipper.company_name,
                "fullName": self.shipper.contact_name,
            },
            "typeCode": "business"
        }

        # Add address line 2 if present
        if self.shipper.address_line2:
            details["postalAddress"]["addressLine2"] = self.shipper.address_line2

        # Add registration numbers for international shipments
        registration_numbers = []
        if self.shipper.vat_number:
            registration_numbers.append({
                "typeCode": "VAT",
                "number": self.shipper.vat_number,
                "issuerCountryCode": "GB"
            })
        if self.shipper.eori_number:
            registration_numbers.append({
                "typeCode": "EOR",
                "number": self.shipper.eori_number,
                "issuerCountryCode": "GB"
            })

        if registration_numbers:
            details["registrationNumbers"] = registration_numbers

        return details

    def _build_receiver_from_reverb(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build DHL receiver details from Reverb order.

        Args:
            order: Reverb order dict (from reverb_orders table)

        Returns:
            DHL receiver details dict
        """
        # shipping_address is a JSONB field with full address details
        addr = order.get('shipping_address', {}) or {}

        # Build postal address
        postal_address = {
            "postalCode": addr.get('postal_code') or order.get('shipping_postal_code', ''),
            "cityName": addr.get('locality') or order.get('shipping_city', ''),
            "countryCode": addr.get('country_code') or order.get('shipping_country_code', ''),
            "addressLine1": addr.get('street_address', ''),
        }

        # Add extended address if present
        if addr.get('extended_address'):
            postal_address["addressLine2"] = addr.get('extended_address')

        # Add region/state if present
        region = addr.get('region') or order.get('shipping_region')
        if region:
            postal_address["provinceCode"] = region

        # Get country name
        country_code = postal_address["countryCode"]
        postal_address["countryName"] = self._get_country_name(country_code)

        # Build contact information
        contact_info = {
            "fullName": addr.get('name') or order.get('shipping_name') or order.get('buyer_name', ''),
            "phone": addr.get('phone') or addr.get('unformatted_phone') or order.get('shipping_phone', ''),
        }

        # Add email if available (from buyer info)
        if order.get('buyer_email'):
            contact_info["email"] = order.get('buyer_email')

        return {
            "postalAddress": postal_address,
            "contactInformation": contact_info,
            "typeCode": "private"  # Most buyers are individuals
        }

    def _build_receiver_from_ebay(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build DHL receiver details from eBay order.

        Args:
            order: eBay order dict (from ebay_orders table)

        Returns:
            DHL receiver details dict
        """
        # shipping_address is a JSONB field
        addr = order.get('shipping_address', {}) or {}

        # Build postal address
        postal_address = {
            "postalCode": addr.get('PostalCode') or order.get('shipping_postal_code', ''),
            "cityName": addr.get('CityName') or order.get('shipping_city', ''),
            "countryCode": addr.get('Country') or order.get('shipping_country', ''),
            "addressLine1": addr.get('Street1', ''),
        }

        # Add Street2 if present
        if addr.get('Street2'):
            postal_address["addressLine2"] = addr.get('Street2')

        # Add state/province if present
        state = addr.get('StateOrProvince') or order.get('shipping_state')
        if state:
            postal_address["provinceCode"] = state

        # Get country name
        country_code = postal_address["countryCode"]
        postal_address["countryName"] = addr.get('CountryName') or self._get_country_name(country_code)

        # Build contact information
        contact_info = {
            "fullName": addr.get('Name') or order.get('shipping_name', ''),
            "phone": addr.get('Phone', ''),
        }

        return {
            "postalAddress": postal_address,
            "contactInformation": contact_info,
            "typeCode": "private"
        }

    def _build_package_details(
        self,
        weight_kg: float = 5.0,
        length_cm: float = 120,
        width_cm: float = 50,
        height_cm: float = 15,
        reference: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build DHL package details.

        Args:
            weight_kg: Package weight in kg
            length_cm: Package length in cm
            width_cm: Package width in cm
            height_cm: Package height in cm
            reference: Customer reference (e.g., order number, SKU)

        Returns:
            DHL package details dict
        """
        package = {
            "typeCode": "2BP",  # Customer-provided packaging
            "weight": weight_kg,
            "dimensions": {
                "length": int(length_cm),
                "width": int(width_cm),
                "height": int(height_cm)
            }
        }

        if reference:
            package["customerReferences"] = [{
                "value": reference[:35],  # DHL limit
                "typeCode": "CU"
            }]

        return package

    def _build_customs_declaration(
        self,
        description: str,
        value: float,
        currency: str = "GBP",
        quantity: int = 1,
        weight_kg: float = 5.0,
        hs_code: Optional[str] = None,
        invoice_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build customs declaration for international shipments.

        Args:
            description: Item description
            value: Declared value
            currency: Currency code (GBP, EUR, USD, etc.)
            quantity: Number of items
            weight_kg: Net weight in kg
            hs_code: Harmonized System code
            invoice_number: Invoice reference

        Returns:
            DHL export declaration dict
        """
        # Default HS code for musical instruments
        if not hs_code:
            hs_code = HS_CODES.get('electric_guitar', HS_CODES['other'])

        # Generate invoice number if not provided
        if not invoice_number:
            invoice_number = f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        return {
            "lineItems": [
                {
                    "number": 1,
                    "description": description[:75],  # DHL limit
                    "price": value,
                    "quantity": {
                        "value": quantity,
                        "unitOfMeasurement": "PCS"
                    },
                    "commodityCodes": [
                        {
                            "typeCode": "outbound",
                            "value": hs_code
                        }
                    ],
                    "exportReasonType": "permanent",
                    "manufacturerCountry": "GB",
                    "weight": {
                        "netValue": weight_kg,
                        "grossValue": weight_kg + 0.5  # Add packaging weight
                    },
                    "isTaxesPaid": False
                }
            ],
            "invoice": {
                "number": invoice_number,
                "date": datetime.now().strftime("%Y-%m-%d")
            },
            "exportReason": "sale",
            "exportReasonType": "permanent"
        }

    def _get_country_name(self, country_code: str) -> str:
        """Get full country name from code."""
        # Common countries - expand as needed
        countries = {
            'GB': 'UNITED KINGDOM',
            'US': 'UNITED STATES',
            'DE': 'GERMANY',
            'FR': 'FRANCE',
            'IT': 'ITALY',
            'ES': 'SPAIN',
            'NL': 'NETHERLANDS',
            'BE': 'BELGIUM',
            'AT': 'AUSTRIA',
            'CH': 'SWITZERLAND',
            'SE': 'SWEDEN',
            'NO': 'NORWAY',
            'DK': 'DENMARK',
            'FI': 'FINLAND',
            'IE': 'IRELAND',
            'PT': 'PORTUGAL',
            'PL': 'POLAND',
            'CZ': 'CZECH REPUBLIC',
            'AU': 'AUSTRALIA',
            'NZ': 'NEW ZEALAND',
            'CA': 'CANADA',
            'JP': 'JAPAN',
            'KR': 'SOUTH KOREA',
            'CN': 'CHINA',
            'HK': 'HONG KONG',
            'SG': 'SINGAPORE',
            'MX': 'MEXICO',
            'BR': 'BRAZIL',
            'AR': 'ARGENTINA',
            'ZA': 'SOUTH AFRICA',
            'AE': 'UNITED ARAB EMIRATES',
            'SA': 'SAUDI ARABIA',
            'IL': 'ISRAEL',
            'IN': 'INDIA',
            'TH': 'THAILAND',
            'MY': 'MALAYSIA',
            'ID': 'INDONESIA',
            'PH': 'PHILIPPINES',
            'VN': 'VIETNAM',
            'TW': 'TAIWAN',
            'RU': 'RUSSIA',
            'TR': 'TURKEY',
            'GR': 'GREECE',
            'HU': 'HUNGARY',
            'RO': 'ROMANIA',
            'BG': 'BULGARIA',
            'HR': 'CROATIA',
            'SK': 'SLOVAKIA',
            'SI': 'SLOVENIA',
            'LT': 'LITHUANIA',
            'LV': 'LATVIA',
            'EE': 'ESTONIA',
            'LU': 'LUXEMBOURG',
            'MT': 'MALTA',
            'CY': 'CYPRUS',
        }
        return countries.get(country_code.upper(), country_code.upper())

    def _get_shipping_date(self, days_ahead: int = 1) -> str:
        """Get formatted shipping date for DHL API."""
        ship_date = datetime.now() + timedelta(days=days_ahead)
        # Skip weekends
        while ship_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
            ship_date += timedelta(days=1)
        return ship_date.strftime("%Y-%m-%dT10:00:00 GMT+00:00")

    def build_from_reverb_order(
        self,
        order: Dict[str, Any],
        weight_kg: float = 5.0,
        length_cm: float = 120,
        width_cm: float = 50,
        height_cm: float = 15,
        request_pickup: bool = False
    ) -> Dict[str, Any]:
        """
        Build complete DHL shipment payload from Reverb order.

        Args:
            order: Reverb order dict (from reverb_orders table or API)
            weight_kg: Package weight
            length_cm: Package length
            width_cm: Package width
            height_cm: Package height
            request_pickup: Whether to request DHL pickup

        Returns:
            Complete DHL shipment payload ready for API
        """
        # Get destination country and classify
        country_code = (
            order.get('shipping_country_code') or
            (order.get('shipping_address', {}) or {}).get('country_code', 'GB')
        )
        dest_type = self.classify_destination(country_code)

        # Build receiver details
        receiver = self._build_receiver_from_reverb(order)

        # Build reference from order
        reference = order.get('order_number') or order.get('sku') or str(order.get('id', ''))

        # Build package
        package = self._build_package_details(
            weight_kg=weight_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            reference=reference
        )

        # Build base payload
        payload = self._build_base_payload(
            receiver=receiver,
            package=package,
            dest_type=dest_type,
            request_pickup=request_pickup
        )

        # Add customs for international
        if dest_type != DestinationType.UK_DOMESTIC:
            # Get item details for customs
            title = order.get('title', 'Musical Instrument')
            value = float(order.get('amount_product') or order.get('total_amount') or 0)
            currency = order.get('amount_product_currency') or order.get('total_currency') or 'GBP'

            payload["content"]["isCustomsDeclarable"] = True
            payload["content"]["declaredValue"] = value
            payload["content"]["declaredValueCurrency"] = currency
            payload["content"]["exportDeclaration"] = self._build_customs_declaration(
                description=title,
                value=value,
                currency=currency,
                weight_kg=weight_kg,
                invoice_number=f"REV-{order.get('order_number', datetime.now().strftime('%Y%m%d'))}"
            )

        return payload

    def build_from_ebay_order(
        self,
        order: Dict[str, Any],
        weight_kg: float = 5.0,
        length_cm: float = 120,
        width_cm: float = 50,
        height_cm: float = 15,
        request_pickup: bool = False
    ) -> Dict[str, Any]:
        """
        Build complete DHL shipment payload from eBay order.

        Args:
            order: eBay order dict (from ebay_orders table or API)
            weight_kg: Package weight
            length_cm: Package length
            width_cm: Package width
            height_cm: Package height
            request_pickup: Whether to request DHL pickup

        Returns:
            Complete DHL shipment payload ready for API
        """
        # Get destination country and classify
        country_code = (
            order.get('shipping_country') or
            (order.get('shipping_address', {}) or {}).get('Country', 'GB')
        )
        dest_type = self.classify_destination(country_code)

        # Build receiver details
        receiver = self._build_receiver_from_ebay(order)

        # Build reference from order
        reference = order.get('order_id') or order.get('primary_sku') or str(order.get('id', ''))

        # Build package
        package = self._build_package_details(
            weight_kg=weight_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            reference=reference
        )

        # Build base payload
        payload = self._build_base_payload(
            receiver=receiver,
            package=package,
            dest_type=dest_type,
            request_pickup=request_pickup
        )

        # Add customs for international
        if dest_type != DestinationType.UK_DOMESTIC:
            # Get item details for customs - eBay stores transaction info differently
            # Try to get from transactions JSONB or use order total
            value = float(order.get('total_amount') or order.get('amount_paid') or 0)
            currency = order.get('total_currency') or order.get('amount_paid_currency') or 'GBP'

            # For item description, we'd ideally get from product, but use generic for now
            description = "Vintage Musical Instrument"

            payload["content"]["isCustomsDeclarable"] = True
            payload["content"]["declaredValue"] = value
            payload["content"]["declaredValueCurrency"] = currency
            payload["content"]["exportDeclaration"] = self._build_customs_declaration(
                description=description,
                value=value,
                currency=currency,
                weight_kg=weight_kg,
                invoice_number=f"EBAY-{order.get('order_id', datetime.now().strftime('%Y%m%d'))}"
            )

        return payload

    def _build_base_payload(
        self,
        receiver: Dict[str, Any],
        package: Dict[str, Any],
        dest_type: DestinationType,
        request_pickup: bool = False,
        use_eu_product: bool = False
    ) -> Dict[str, Any]:
        """
        Build base DHL shipment payload structure.

        Args:
            receiver: Receiver details dict
            package: Package details dict
            dest_type: Destination classification
            request_pickup: Whether to request pickup
            use_eu_product: Use EU-specific product code (U) for EU destinations

        Returns:
            Base payload dict
        """
        settings = get_settings()

        # Select product code based on destination
        # N = DOM (Domestic Express)
        # P = WPX (Express Worldwide - products/goods)
        # U = ECX (Express Worldwide EU)
        if dest_type == DestinationType.UK_DOMESTIC:
            product_code = "N"  # DHL Domestic Express
        elif dest_type == DestinationType.EU and use_eu_product:
            product_code = "U"  # DHL Express Worldwide EU
        else:
            product_code = "P"  # DHL Express Worldwide (non-doc)

        # Build image options based on destination
        image_options = [
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

        # Add invoice for international shipments
        if dest_type != DestinationType.UK_DOMESTIC:
            image_options.append({
                "typeCode": "invoice",
                "templateName": "COMMERCIAL_INVOICE_P_10",
                "isRequested": True,
                "invoiceType": "commercial"
            })

        # Build content section
        content = {
            "packages": [package],
            "isCustomsDeclarable": dest_type != DestinationType.UK_DOMESTIC,
            "description": "Musical Instrument",
            "incoterm": "DAP",  # Delivered at Place - buyer pays duties
            "unitOfMeasurement": "metric"
        }

        return {
            "plannedShippingDateAndTime": self._get_shipping_date(),
            "pickup": {
                "isRequested": request_pickup
            },
            "productCode": product_code,
            "accounts": [
                {
                    "number": settings.DHL_ACCOUNT_NUMBER,
                    "typeCode": "shipper"
                }
            ],
            "outputImageProperties": {
                "printerDPI": 300,
                "encodingFormat": "pdf",
                "imageOptions": image_options
            },
            "customerDetails": {
                "shipperDetails": self._build_shipper_details(),
                "receiverDetails": receiver
            },
            "content": content,
            "estimatedDeliveryDate": {
                "isRequested": True,
                "typeCode": "QDDC"
            }
        }

    def validate_payload(self, payload: Dict[str, Any]) -> List[str]:
        """
        Validate a DHL payload for required fields.

        Args:
            payload: DHL shipment payload

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check receiver details
        receiver = payload.get("customerDetails", {}).get("receiverDetails", {})
        postal = receiver.get("postalAddress", {})
        contact = receiver.get("contactInformation", {})

        if not postal.get("postalCode"):
            errors.append("Missing receiver postal code")
        if not postal.get("cityName"):
            errors.append("Missing receiver city")
        if not postal.get("countryCode"):
            errors.append("Missing receiver country code")
        if not postal.get("addressLine1"):
            errors.append("Missing receiver address")
        if not contact.get("fullName"):
            errors.append("Missing receiver name")
        if not contact.get("phone"):
            errors.append("Missing receiver phone number")

        # Check package details
        packages = payload.get("content", {}).get("packages", [])
        if not packages:
            errors.append("Missing package details")
        else:
            pkg = packages[0]
            if not pkg.get("weight"):
                errors.append("Missing package weight")

        # Check customs for international
        if payload.get("content", {}).get("isCustomsDeclarable"):
            if not payload.get("content", {}).get("declaredValue"):
                errors.append("Missing declared value for international shipment")
            if not payload.get("content", {}).get("exportDeclaration"):
                errors.append("Missing export declaration for international shipment")

        return errors
