"""
Common shipping data structures for use across the application
"""

# UK Shipper Details
uk_shipper = {
    "postalAddress": {
        "postalCode": "EC1A 1BB",
        "cityName": "London",
        "countryCode": "GB",
        "addressLine1": "123 Sample Street",
        "countryName": "UNITED KINGDOM"
    },
    "contactInformation": {
        "email": "shipper@example.com",
        "phone": "4420712345678",
        "companyName": "UK Sender Ltd",
        "fullName": "John Sender"
    },
    "registrationNumbers": [
        {
            "typeCode": "VAT",
            "number": "GB123456789",
            "issuerCountryCode": "GB"
        }
    ],
    "typeCode": "business"
}

# UK Receiver Details
uk_receiver = {
    "postalAddress": {
        "postalCode": "M1 1AA",
        "cityName": "Manchester",
        "countryCode": "GB",
        "addressLine1": "456 Receiver Road",
        "countryName": "UNITED KINGDOM"
    },
    "contactInformation": {
        "email": "receiver@example.com",
        "phone": "4416123456789",
        "companyName": "UK Receiver Ltd",
        "fullName": "Jane Receiver"
    },
    "typeCode": "business"
}

# EU Receiver Details
eu_receiver = {
    "postalAddress": {
        "postalCode": "75001",
        "cityName": "Paris",
        "countryCode": "FR",
        "addressLine1": "1 Rue de Rivoli",
        "countryName": "FRANCE"
    },
    "contactInformation": {
        "email": "receiver@example.com",
        "phone": "33123456789",
        "companyName": "French Receiver SARL",
        "fullName": "Pierre Receiver"
    },
    "registrationNumbers": [
        {
            "typeCode": "VAT",
            "number": "FR12345678900",
            "issuerCountryCode": "FR"
        }
    ],
    "typeCode": "business"
}

# ROW Receiver Details
row_receiver = {
    "postalAddress": {
        "postalCode": "2000",
        "cityName": "Sydney",
        "countryCode": "AU",
        "addressLine1": "42 George Street",
        "countryName": "AUSTRALIA"
    },
    "contactInformation": {
        "email": "receiver@example.com",
        "phone": "61298765432",
        "companyName": "Australian Receiver Pty Ltd",
        "fullName": "James Receiver"
    },
    "registrationNumbers": [
        {
            "typeCode": "ABN",  # Australian Business Number
            "number": "12345678901",
            "issuerCountryCode": "AU"
        }
    ],
    "typeCode": "business"
}

# Standard Package Details
standard_package = {
    "typeCode": "2BP",
    "weight": 1.0,
    "dimensions": {
        "length": 20,
        "width": 15,
        "height": 10
    }
}

# EU Customs Details for international shipment
eu_customs = {
    "description": "Electronics",
    "declaredValue": 200.00,
    "declaredValueCurrency": "EUR",
    "exportDeclaration": {
        "lineItems": [
            {
                "number": 1,
                "description": "Tablet computer",
                "price": 200.00,
                "quantity": {
                    "value": 1,
                    "unitOfMeasurement": "PCS"
                },
                "commodityCodes": [
                    {
                        "typeCode": "outbound",
                        "value": "851712"
                    }
                ],
                "exportReasonType": "permanent",
                "manufacturerCountry": "GB",
                "weight": {
                    "netValue": 1.2,
                    "grossValue": 1.5
                },
                "isTaxesPaid": False
            }
        ],
        "invoice": {
            "number": "EU-INV-12345",
            "date": "2023-08-10"
        },
        "exportReason": "sale",
        "exportReasonType": "permanent"
    }
}

# ROW Customs Details
row_customs = {
    "description": "Clothing",
    "declaredValue": 150.00,
    "declaredValueCurrency": "AUD",
    "exportDeclaration": {
        "lineItems": [
            {
                "number": 1,
                "description": "Men's cotton t-shirts",
                "price": 150.00,
                "quantity": {
                    "value": 5,
                    "unitOfMeasurement": "PCS"
                },
                "commodityCodes": [
                    {
                        "typeCode": "outbound",
                        "value": "6109100010"
                    }
                ],
                "exportReasonType": "permanent",
                "manufacturerCountry": "GB",
                "weight": {
                    "netValue": 1.8,
                    "grossValue": 2.0
                },
                "isTaxesPaid": False
            }
        ],
        "invoice": {
            "number": "ROW-INV-12345",
            "date": "2023-08-10"
        },
        "exportReason": "sale",
        "exportReasonType": "permanent"
    }
}