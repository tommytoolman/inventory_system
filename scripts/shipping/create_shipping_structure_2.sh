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
        echo "$content" > "$file_path"
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

create_file "$APP_DIR/services/shipping/service.py" """
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

# Config files
create_file "$APP_DIR/services/shipping/config/__init__.py" "# Shipping configuration package init file"

create_file "$APP_DIR/services/shipping/config/settings.py" """
Shipping Settings

Configuration settings for shipping service.
Defines carrier-specific settings and global shipping parameters.
"""

# Exceptions
create_file "$APP_DIR/services/shipping/exceptions.py" """
Shipping Exceptions

Custom exceptions for the shipping service.
Provides specific error types for different failure scenarios.
"""

# Utils
create_file "$APP_DIR/services/shipping/utils/__init__.py" "# Shipping utilities package init file"

create_file "$APP_DIR/services/shipping/utils/validator.py" """
Shipping Validation Utilities

Helper functions for validating shipping data.
"""

# Carriers
create_file "$APP_DIR/services/shipping/carriers/__init__.py" "# Carriers package init file"

create_file "$APP_DIR/services/shipping/carriers/base.py" """
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

create_file "$APP_DIR/services/shipping/carriers/dhl.py" """
DHL Carrier Implementation

This module implements the DHL shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

DHL API Docs: https://developer.dhl.com/
"""

create_file "$APP_DIR/services/shipping/carriers/ups.py" """
UPS Carrier Implementation

This module implements the UPS shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

UPS API Docs: https://developer.ups.com/
"""

create_file "$APP_DIR/services/shipping/carriers/fedex.py" """
FedEx Carrier Implementation

This module implements the FedEx shipping carrier API integration.

Features:
- Rate calculation
- Label generation
- Shipment tracking
- Address validation

FedEx API Docs: https://developer.fedex.com/
"""

# Models
create_file "$APP_DIR/services/shipping/models/__init__.py" "# Shipping models package init file"

create_file "$APP_DIR/services/shipping/models/address.py" """
Address Model

This module defines the Address data model used for shipping operations.
Includes validation and conversion functionality.

The Address model handles:
- Shipping origin and destination addresses
- Address validation formatting
- Conversion to carrier-specific formats
"""

create_file "$APP_DIR/services/shipping/models/package.py" """
Package Model

Defines the Package data model for shipping operations, 
including dimensions, weight, and package characteristics.

Used for:
- Rate calculation
- Label generation
- Package type specification
"""

create_file "$APP_DIR/services/shipping/models/rate.py" """
Shipping Rate Model

Defines the ShippingRate data model for standardizing rate responses
across different carriers.

Used for:
- Presenting shipping options to users
- Storing and comparing rates
- Selecting shipping services
"""

create_file "$APP_DIR/services/shipping/models/tracking.py" """
Tracking Model

Defines the TrackingInfo data model for standardizing tracking information
across different carriers.

Used for:
- Tracking package status
- Providing delivery estimates
- Logging shipping events
"""

# Create test files
echo -e "${GREEN}Creating test files...${NC}"

# Test fixtures
create_file "$TEST_DIR/fixtures/shipping_fixtures.py" """
Shipping Test Fixtures

Test fixtures for shipping-related tests.
Provides sample data for addresses, packages, rates, etc.
"""

create_file "$TEST_DIR/mocks/mock_carriers.py" """
Mock Carrier Implementations

Mock implementations of carrier APIs for testing.
"""

# Unit tests
create_file "$TEST_DIR/unit/services/shipping/test_service.py" """
Shipping Service Tests

Unit tests for the main shipping service.
"""

create_file "$TEST_DIR/unit/services/shipping/carriers/test_dhl.py" """
DHL Carrier Tests

Unit tests for the DHL carrier implementation.
"""

create_file "$TEST_DIR/unit/services/shipping/carriers/test_ups.py" """
UPS Carrier Tests

Unit tests for the UPS carrier implementation.
"""

create_file "$TEST_DIR/unit/services/shipping/carriers/test_fedex.py" """
FedEx Carrier Tests

Unit tests for the FedEx carrier implementation.
"""

create_file "$TEST_DIR/unit/models/shipping/test_address.py" """
Address Model Tests

Unit tests for the Address model.
"""

create_file "$TEST_DIR/unit/models/shipping/test_package.py" """
Package Model Tests

Unit tests for the Package model.
"""

create_file "$TEST_DIR/unit/models/shipping/test_rate.py" """
Rate Model Tests

Unit tests for the ShippingRate model.
"""

# Integration tests
create_file "$TEST_DIR/integration/shipping/test_shipping_service.py" """
Shipping Service Integration Tests

Integration tests for the shipping service with actual API calls.
"""

create_file "$TEST_DIR/integration/shipping/test_dhl_api.py" """
DHL API Integration Tests

Integration tests for the DHL API endpoints.
"""

echo -e "${GREEN}=== Shipping service and test structure created successfully ===${NC}"

