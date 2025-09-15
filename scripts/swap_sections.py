#!/usr/bin/env python3
"""
Swap Platform Settings and Shipping sections in add.html
"""

import re

# Read the file
with open('app/templates/inventory/add.html', 'r') as f:
    content = f.read()

# Find Platform Settings section (from line ~626 to ~902)
platform_pattern = r'(                <!-- Platform-Specific Section -->.*?)(                <!-- Shipping Section -->)'
platform_match = re.search(platform_pattern, content, re.DOTALL)

if not platform_match:
    print("Could not find Platform Settings section")
    exit(1)

platform_section = platform_match.group(1)

# Find Shipping section (from line ~904 to ~1129)  
shipping_pattern = r'(                <!-- Shipping Section -->.*?)(                <!-- Platform Sync -->)'
shipping_match = re.search(shipping_pattern, content, re.DOTALL)

if not shipping_match:
    print("Could not find Shipping section")
    exit(1)

shipping_section = shipping_match.group(1)

# Replace in content - put shipping before platform
# Find the position before Platform Settings
before_platform = content[:platform_match.start()]
# Find the position after Shipping section  
after_shipping = content[shipping_match.end():]

# Reconstruct with swapped order
new_content = before_platform + shipping_section + platform_section + after_shipping

# Write back
with open('app/templates/inventory/add.html', 'w') as f:
    f.write(new_content)

print("✅ Successfully swapped Platform Settings and Shipping sections!")
print("   Shipping section now comes before Platform Settings")