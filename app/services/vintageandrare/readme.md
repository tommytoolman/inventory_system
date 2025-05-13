"""
Vintage & Rare Form Automation Script
-----------------------------------

This script automates the listing creation process on vintageandrare.com.

Core Functionality:
- Automates the Vintage & Rare listing form
- Handles category/subcategory selection
- Manages all basic item information (brand, model, year, price, etc.)
- Configures shipping options with fees
- Processes both remote and local image uploads

Image Handling Capabilities:
- Supports both URL-based and local file image uploads
- Uses MediaHandler for temporary file management
- Implements 20-image limit with graceful handling
- Re-fetches upload fields after each upload to avoid stale elements
- Handles Dropbox and other remote image URLs successfully

Error Handling & Validation:
- Validates required fields
- Manages category hierarchy validation
- Provides clear error messages and logging
- Gracefully handles stale elements during image uploads
- Warns when image limit is exceeded

Test Mode:
- Includes a test mode that fills form without submission
- Supports debugging with screenshot captures
- Provides detailed logging of each step

Future Integration Points:
- Ready for integration with larger automation system
- Modular design allows for easy expansion
- Clear logging helps with monitoring and debugging

Usage:
python inspect_form.py --username "user" --password "pass" [options]
See --help for full list of options
"""