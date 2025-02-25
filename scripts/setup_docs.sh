#!/bin/bash

# Function to create a markdown file with basic content
create_md() {
    local file=$1
    local title=$2
    
    echo "# ${title}

## Overview

[Overview content goes here]

## Details

[Detailed content goes here]

## Additional Information

[Additional information goes here]" > "$file"
}

# Create API documentation
mkdir -p docs/api
cd docs/api
create_md "architecture.md" "System Architecture"
create_md "endpoints.md" "API Endpoints"
create_md "models.md" "Data Models"
create_md "platform_integration.md" "Platform Integration Details"

# Create deployment documentation
cd ../
mkdir -p deployment
cd deployment
create_md "setup.md" "Setup Guide"
create_md "configuration.md" "Configuration Guide"
create_md "backup.md" "Backup Procedures"
create_md "monitoring.md" "Monitoring Setup"

# Create user guide
cd ../
mkdir -p user_guide
cd user_guide
create_md "getting_started.md" "Getting Started"
create_md "inventory_management.md" "Inventory Management"
create_md "troubleshooting.md" "Troubleshooting Guide"
create_md "faq.md" "Frequently Asked Questions"

echo "Documentation structure created successfully!"