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

import os
import sys
import json
import requests
import argparse
import time
from pathlib import Path


from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


def analyze_form_elements(driver):
    print("\nAnalyzing form elements...")
    
    # Look for specific form elements we'll need
    print("\nLooking for key input fields...")
    
    # File upload fields
    file_uploads = driver.find_elements(By.XPATH, "//input[@type='file']")
    print("\nFile Upload Fields:")
    for upload in file_uploads:
        print(f"- Name: {upload.get_attribute('name')}")
        print(f"  ID: {upload.get_attribute('id')}")
        print(f"  Accept: {upload.get_attribute('accept')}")

    # Text inputs and textareas
    text_inputs = driver.find_elements(By.XPATH, "//input[@type='text'] | //textarea")
    print("\nText Input Fields:")
    for input_field in text_inputs:
        print(f"- Name: {input_field.get_attribute('name')}")
        print(f"  ID: {input_field.get_attribute('id')}")
        print(f"  Placeholder: {input_field.get_attribute('placeholder')}")

    # Select/Dropdown fields
    select_fields = driver.find_elements(By.TAG_NAME, "select")
    print("\nDropdown Fields:")
    for select in select_fields:
        print(f"- Name: {select.get_attribute('name')}")
        print(f"  ID: {select.get_attribute('id')}")
        options = select.find_elements(By.TAG_NAME, "option")
        print(f"  Options count: {len(options)}")
        if len(options) < 10:  # Only print options if there aren't too many
            print("  Available options:")
            for option in options:
                print(f"    - {option.text} (value: {option.get_attribute('value')})")

    # Submit buttons
    submit_buttons = driver.find_elements(By.XPATH, "//button[@type='submit'] | //input[@type='submit']")
    print("\nSubmit Buttons:")
    for button in submit_buttons:
        print(f"- Text: {button.text}")
        print(f"  Type: {button.get_attribute('type')}")
        print(f"  Name: {button.get_attribute('name')}")

    # Save detailed info to file
    print("\nSaving detailed form analysis to form_analysis.json...")
    form_analysis = {
        'file_uploads': [{
            'name': el.get_attribute('name'),
            'id': el.get_attribute('id'),
            'accept': el.get_attribute('accept')
        } for el in file_uploads],
        'text_inputs': [{
            'name': el.get_attribute('name'),
            'id': el.get_attribute('id'),
            'placeholder': el.get_attribute('placeholder'),
            'type': el.get_attribute('type')
        } for el in text_inputs],
        'select_fields': [{
            'name': el.get_attribute('name'),
            'id': el.get_attribute('id'),
            'options': [{
                'text': opt.text,
                'value': opt.get_attribute('value')
            } for opt in el.find_elements(By.TAG_NAME, "option")]
        } for el in select_fields],
        'submit_buttons': [{
            'text': el.text,
            'type': el.get_attribute('type'),
            'name': el.get_attribute('name')
        } for el in submit_buttons]
    }
    
    with open('form_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(form_analysis, f, indent=2)

def map_category_options(driver):
    """
    Maps all possible category and subcategory combinations including third level
    """
    wait = WebDriverWait(driver, 10)
    category_map = {}
    
    try:
        main_category = wait.until(
            EC.presence_of_element_located((By.ID, "categ_level_0"))
        )
        main_select = Select(main_category)
        main_options = main_select.options[1:]  # Skip 'choose...'
        
        print("\nMapping category hierarchy...")
        for main_opt in main_options:
            main_id = main_opt.get_attribute('value')
            main_text = main_opt.text
            print(f"\nMain Category: {main_text} (ID: {main_id})")
            
            # Select main category
            main_select.select_by_value(main_id)
            time.sleep(1)
            
            # Look for first subcategory
            try:
                sub1 = wait.until(
                    EC.presence_of_element_located((By.ID, "categ_level_1"))
                )
                sub1_select = Select(sub1)
                sub1_options = sub1_select.options[1:]
                
                category_map[main_id] = {
                    'name': main_text,
                    'subcategories': {}
                }
                
                for sub1_opt in sub1_options:
                    sub1_id = sub1_opt.get_attribute('value')
                    sub1_text = sub1_opt.text
                    print(f"  Subcategory: {sub1_text} (ID: {sub1_id})")
                    
                    # Select subcategory
                    sub1_select.select_by_value(sub1_id)
                    time.sleep(1)
                    
                    # Look for second subcategory
                    try:
                        sub2 = driver.find_element(By.ID, "categ_level_2")
                        sub2_select = Select(sub2)
                        sub2_options = sub2_select.options[1:]
                        
                        sub2_data = {}
                        for sub2_opt in sub2_options:
                            sub2_id = sub2_opt.get_attribute('value')
                            sub2_text = sub2_opt.text
                            print(f"    Sub-subcategory: {sub2_text} (ID: {sub2_id})")
                            
                            # Select sub2 category and look for level 3
                            sub2_select.select_by_value(sub2_id)
                            time.sleep(1)
                            
                            try:
                                sub3 = driver.find_element(By.ID, "categ_level_3")
                                sub3_select = Select(sub3)
                                sub3_options = sub3_select.options[1:]
                                
                                sub3_data = []
                                for sub3_opt in sub3_options:
                                    sub3_id = sub3_opt.get_attribute('value')
                                    sub3_text = sub3_opt.text
                                    print(f"      Third-level: {sub3_text} (ID: {sub3_id})")
                                    sub3_data.append({
                                        'id': sub3_id,
                                        'name': sub3_text
                                    })
                                
                                sub2_data[sub2_id] = {
                                    'name': sub2_text,
                                    'subcategories': sub3_data
                                }
                            except:
                                sub2_data[sub2_id] = {
                                    'name': sub2_text,
                                    'subcategories': []
                                }
                        
                        category_map[main_id]['subcategories'][sub1_id] = {
                            'name': sub1_text,
                            'subcategories': sub2_data
                        }
                    except:
                        category_map[main_id]['subcategories'][sub1_id] = {
                            'name': sub1_text,
                            'subcategories': {}
                        }
                        
            except:
                category_map[main_id] = {
                    'name': main_text,
                    'subcategories': {}
                }
                
        print("\nSaving category map...")
        with open('category_map.json', 'w', encoding='utf-8') as f:
            json.dump(category_map, f, indent=2)
            
        print("Category mapping complete! Saved to category_map.json")
        return category_map
        
    except Exception as e:
        print(f"Error mapping categories: {str(e)}")
        driver.save_screenshot("category_map_error.png")
        raise e

def login_and_navigate(username, password, item_data=None, test_mode=True, map_categories=False):
    # First use requests to get valid cookies
    session = requests.Session()
    
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': 'https://www.vintageandrare.com',
        'Referer': 'https://www.vintageandrare.com/',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
    }
    
    print("1. Getting main page to gather initial cookies...")
    session.get('https://www.vintageandrare.com', headers=headers)
    
    print("2. Attempting login...")
    login_data = {
        'username': username,
        'pass': password,
        'open_where': 'header'
    }
    
    response = session.post(
        'https://www.vintageandrare.com/do_login',
        data=login_data,
        headers=headers,
        allow_redirects=True
    )
    
    if 'account' in response.url:
        print("3. Login successful via requests!")
        
        # Initialize Selenium
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
        
        try:
            print("4. Setting up Selenium session...")
            # First, go to the main site to set up the domain
            driver.get('https://www.vintageandrare.com')
            time.sleep(2)
            
            print("5. Current cookies in Selenium before transfer:", driver.get_cookies())
            
            # Delete any existing cookies
            driver.delete_all_cookies()
            
            # Transfer cookies from requests session to Selenium
            print("\n6. Transferring cookies from requests to Selenium...")
            for cookie in session.cookies:
                print(f"Adding cookie: {cookie.name}")
                cookie_dict = {
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': '.vintageandrare.com',
                    'path': '/'
                }
                driver.add_cookie(cookie_dict)
            
            print("\n7. Cookies in Selenium after transfer:", driver.get_cookies())
            
            print("\n8. Refreshing page to apply cookies...")
            driver.refresh()
            time.sleep(2)
            
            print("9. Checking if login succeeded...")
            print(f"Current URL: {driver.current_url}")
            
            print("\n10. Attempting to navigate to add/edit item...")
            driver.get('https://www.vintageandrare.com/instruments/add_edit_item')
            time.sleep(2)
            
            # Handle cookie consent again if it appears
            try:
                cookie_button = driver.find_element(By.CLASS_NAME, "cc-nb-okagree")
                print("Handling cookie consent on new page...")
                cookie_button.click()
                time.sleep(1)
            except:
                print("No cookie consent needed on new page")
            
            print(f"11. Final URL: {driver.current_url}")
            driver.save_screenshot("final_page.png")
            
            if map_categories:
                print("\n12. Mapping category hierarchy...")
                category_map = map_category_options(driver)
            elif item_data:
                print("\n12. Filling form...")
                fill_item_form(driver, item_data, test_mode)
            else:
                print("\n12. Analyzing form elements...")
                analyze_form_elements(driver)
            
            input("Press Enter to close the browser...")
            
        finally:
            driver.quit()
    else:
        print("Login failed.")
        print("Response content:")
        print(response.text[:500])

def handle_year_decade(driver, year=None, decade=None):
    """
    Handle year and decade fields with auto-population logic
    """
    wait = WebDriverWait(driver, 10)
    
    if year:
        year_field = wait.until(
            EC.element_to_be_clickable((By.ID, "year"))
        )
        year_field.clear()
        year_field.send_keys(str(year))
        time.sleep(1)  # Wait for decade to auto-populate
        
        # Verify decade was auto-populated correctly
        decade_select = Select(driver.find_element(By.ID, "decade"))
        expected_decade = str(int(str(year)[:3] + '0'))
        actual_decade = decade_select.first_selected_option.get_attribute('value')
        
        if actual_decade != expected_decade:
            print(f"Warning: Decade didn't auto-populate as expected. Manual selection may be needed.")
    elif decade:
        decade_select = Select(wait.until(
            EC.element_to_be_clickable((By.ID, "decade"))
        ))
        decade_select.select_by_value(str(decade))

def handle_shipping_fees(driver, item_data):
    """
    Handle shipping fees including removal of unwanted regions
    """
    print("Setting up shipping fees...")
    wait = WebDriverWait(driver, 10)
    
    # Map of regions to look for
    regions = {
        'europe': ('Europe', 'europe_shipping'),
        'usa': ('USA', 'usa_shipping'),
        'uk': ('UK', 'uk_shipping'),
        'world': ('REST OF WORLD', 'world_shipping')
    }
    
    # Find the ships_to div
    ships_to_div = wait.until(
        EC.presence_of_element_located((By.CLASS_NAME, "ships_to"))
    )
    
    print("Available shipping fees:", item_data.get('shipping_fees', {}))
    
    # Process each region
    shipping_fees = item_data.get('shipping_fees', {})
    for region_key, (region_text, _) in regions.items():
        try:
            region_xpath = f".//div[contains(@class, 'row')][.//span[contains(text(), '{region_text}')]]"
            print(f"Processing {region_text}")
            
            region_row = ships_to_div.find_element(By.XPATH, region_xpath)
            
            if region_key in shipping_fees and shipping_fees[region_key]:
                # Update fee
                print(f"Setting {region_text} shipping fee to {shipping_fees[region_key]}")
                fee_inputs = region_row.find_elements(By.NAME, "shipping_fees_fee[]")
                if fee_inputs:
                    fee_input = fee_inputs[0]
                    driver.execute_script("arguments[0].value = arguments[1];", fee_input, shipping_fees[region_key])
            else:
                # Remove regions we don't want to keep
                print(f"Removing {region_text} shipping option (no fee provided)")
                delete_icon = region_row.find_element(By.CSS_SELECTOR, "i.fa.fa-times")
                driver.execute_script("arguments[0].click();", delete_icon)
                time.sleep(0.5)
                
        except Exception as e:
            print(f"Error handling {region_text} shipping: {str(e)}")

def validate_category_selection(driver):
    """
    System-level validation of category selection
    """
    main_select = Select(driver.find_element(By.ID, "categ_level_0"))
    main_value = main_select.first_selected_option.get_attribute('value')
    
    if not main_value:
        raise ValueError("System Error: Main category not provided")
        
    # Check if subcategory is required
    try:
        sub_element = driver.find_element(By.ID, "categ_level_1")
        if sub_element.is_displayed():
            sub_select = Select(sub_element)
            if not sub_select.first_selected_option.get_attribute('value'):
                raise ValueError("System Error: Required subcategory not provided for main category {main_value}. Please check category mapping configuration.")
    except:
        pass  # No subcategory element found

def get_category_path(category_map, target_id, path=None):
    """
    Find the full path to a category ID in the category map
    Returns a list of IDs to select [main_id, sub1_id, sub2_id, sub3_id]
    """
    if path is None:
        path = []
    
    # Check main categories
    for main_id, main_data in category_map.items():
        if main_id == target_id:
            return [main_id]
        
        # Check first level subcategories
        if 'subcategories' in main_data:
            for sub1_id, sub1_data in main_data['subcategories'].items():
                if sub1_id == target_id:
                    return [main_id, sub1_id]
                
                # Check second level
                if 'subcategories' in sub1_data:
                    for sub2_id, sub2_data in sub1_data['subcategories'].items():
                        if sub2_id == target_id:
                            return [main_id, sub1_id, sub2_id]
                        
                        # Check third level
                        if 'subcategories' in sub2_data:
                            for sub3 in sub2_data['subcategories']:
                                if sub3['id'] == target_id:
                                    return [main_id, sub1_id, sub2_id, sub3['id']]
    
    return None

def fill_categories(driver, main_id, sub1_id=None, sub2_id=None, sub3_id=None):
    """
    Fill category dropdowns with system-level validation
    """
    wait = WebDriverWait(driver, 10)
    
    print(f"Selecting main category: {main_id}")
    main_select = Select(wait.until(
        EC.element_to_be_clickable((By.ID, "categ_level_0"))
    ))
    main_select.select_by_value(str(main_id))
    time.sleep(1)
    
    # Check for subcategory
    try:
        sub1_element = wait.until(
            EC.presence_of_element_located((By.ID, "categ_level_1"))
        )
        if sub1_element.is_displayed():
            if not sub1_id:
                raise ValueError(f"System Error: Subcategory required but not provided for main category {main_id}")
            print(f"Selecting subcategory: {sub1_id}")
            sub1_select = Select(sub1_element)
            sub1_select.select_by_value(str(sub1_id))
            time.sleep(1)
            
            # Check for second subcategory
            try:
                sub2_element = wait.until(
                    EC.presence_of_element_located((By.ID, "categ_level_2"))
                )
                if sub2_element.is_displayed():
                    if not sub2_id:
                        raise ValueError(f"System Error: Second subcategory required but not provided for subcategory {sub1_id}")
                    print(f"Selecting second subcategory: {sub2_id}")
                    sub2_select = Select(sub2_element)
                    sub2_select.select_by_value(str(sub2_id))
                    time.sleep(1)
                    
                    # Check for third subcategory
                    try:
                        sub3_element = wait.until(
                            EC.presence_of_element_located((By.ID, "categ_level_3"))
                        )
                        if sub3_element.is_displayed():
                            if not sub3_id:
                                raise ValueError(f"System Error: Third subcategory required but not provided for subcategory {sub2_id}")
                            print(f"Selecting third subcategory: {sub3_id}")
                            sub3_select = Select(sub3_element)
                            sub3_select.select_by_value(str(sub3_id))
                    except Exception as e:
                        if "System Error" in str(e):
                            raise
                        if sub3_id:
                            print(f"Warning: Third subcategory {sub3_id} provided but not required or not found")
                            
            except Exception as e:
                if "System Error" in str(e):
                    raise
                if sub2_id:
                    print(f"Warning: Second subcategory {sub2_id} provided but not required or not found")
                    
    except Exception as e:
        if "System Error" in str(e):
            raise
        if sub1_id:
            print(f"Warning: Subcategory {sub1_id} provided but not required or not found")

# Modify the fill_item_form function to accept a test parameter
def fill_item_form(driver, item_data, test_mode=True):
    """
    Fill in the add/edit item form with the provided data
    """
    try:
        print("Starting to fill form...")
        project_root = Path(__file__).resolve().parent.parent.parent.parent / 'inventory_system'
        wait = WebDriverWait(driver, 10)
        
        # Handle categories (keeping existing category logic)
        if 'category_id' in item_data:
            print("Handling category selection by ID...")
            with open('category_map.json', 'r') as f:
                category_map = json.load(f)
            category_path = get_category_path(category_map, item_data['category_id'])
            if not category_path:
                raise ValueError(f"Category ID {item_data['category_id']} not found in category map")
            fill_categories(driver, *category_path)
        elif 'category' in item_data:
            print("Handling simple category selection...")
            fill_categories(driver, item_data['category'], item_data.get('subcategory'))

    # Basic Information
        
        # For Brand/Make
        if 'brand' in item_data:
            print("Filling brand/make...")
            try:
                brand_field = wait.until(
                    EC.element_to_be_clickable((By.ID, "recipient_name"))
                )
                brand_field.clear()
                brand_field.send_keys(item_data['brand'])
                print("Brand/make filled")
            except Exception as e:
                print(f"Error filling brand/make: {str(e)}")
                driver.save_screenshot("brand_error.png")
                raise

        if 'model_name' in item_data:
            print("Filling model name...")
            model_field = wait.until(
                EC.element_to_be_clickable((By.ID, "model_name"))
            )
            model_field.send_keys(item_data['model_name'])

        # Handle year (which auto-populates decade)
        handle_year_decade(driver, 
                         year=item_data.get('year'),
                         decade=item_data.get('decade'))

        if 'finish_color' in item_data:
            print("Filling color...")
            color_field = wait.until(
                EC.element_to_be_clickable((By.ID, "finish_color"))
            )
            color_field.send_keys(item_data['finish_color'])

        if 'external_url' in item_data:
            print("Filling external URL...")
            url_field = wait.until(
                EC.element_to_be_clickable((By.ID, "external_url"))
            )
            url_field.send_keys(item_data['external_url'])

        # For Description (TinyMCE)
        if 'description' in item_data:
            print("Filling description...")
            try:
                # First switch to TinyMCE iframe
                iframe = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#item_desc_ifr"))
                )
                driver.switch_to.frame(iframe)
                
                # Now we can interact with the TinyMCE body
                tinymce_body = wait.until(
                    EC.presence_of_element_located((By.ID, "tinymce"))
                )
                tinymce_body.clear()
                tinymce_body.send_keys(item_data['description'])
                
                # Switch back to main content
                driver.switch_to.default_content()
                print("Description filled")
            except Exception as e:
                print(f"Error filling description: {str(e)}")
                driver.save_screenshot("desc_error.png")
                driver.switch_to.default_content()  # Always switch back
                raise   

        # Basic Pricing
        if 'price' in item_data:
            print("Filling price...")
            price_field = wait.until(
                EC.element_to_be_clickable((By.ID, "price"))
            )
            price_field.send_keys(item_data['price'])

        # Handle checkboxes
        if 'show_vat' in item_data and item_data['show_vat']:
            print("Setting show VAT checkbox...")
            try:
                show_vat_checkbox = wait.until(
                    EC.presence_of_element_located((By.ID, "show_vat"))  # We need to verify this ID
                )
                if not show_vat_checkbox.is_selected():
                    show_vat_checkbox.click()
            except Exception as e:
                print(f"Error with show VAT checkbox: {str(e)}")

        if 'call_for_price' in item_data and item_data['call_for_price']:
            print("Setting call for price checkbox...")
            try:
                call_price_checkbox = wait.until(
                    EC.presence_of_element_located((By.ID, "call_price"))  # Verify ID
                )
                if not call_price_checkbox.is_selected():
                    call_price_checkbox.click()
            except Exception as e:
                print(f"Error with call for price checkbox: {str(e)}")

        if 'discounted_price' in item_data:
            print("Filling discounted price...")
            disc_field = wait.until(
                EC.element_to_be_clickable((By.ID, "discounted_price"))
            )
            disc_field.send_keys(item_data['discounted_price'])

        # Processing Time
        if 'processing_time' in item_data:
            print("Filling processing time...")
            time_field = wait.until(
                EC.element_to_be_clickable((By.ID, "processing_time"))
            )
            time_field.clear()  # Clear existing value first otherwise get 3 in front
            time_field.send_keys(item_data['processing_time'])

            if 'time_unit' in item_data:
                time_unit_select = Select(wait.until(
                    EC.element_to_be_clickable((By.ID, "hours_days_sel"))
                ))
                time_unit_select.select_by_value(item_data['time_unit'])

        # Handle shipping method and fees
        if 'shipping' in item_data and item_data['shipping']:
            print("Enabling shipping...")
            try:
                shipping_checkbox = wait.until(
                    EC.presence_of_element_located((By.NAME, "available_for_shipment"))
                )
                if not shipping_checkbox.is_selected():
                    shipping_checkbox.click()
                    time.sleep(1)  # Wait for shipping options to appear
                
                # Handle shipping fees
                handle_shipping_fees(driver, item_data)
            except Exception as e:
                print(f"Error setting up shipping: {str(e)}")

        # Before starting image upload, handle the brand dropdown issue
        try:
            # Find processing time field to defocus brand dropdown
            time_field = wait.until(
                EC.element_to_be_clickable((By.ID, "processing_time"))
            )
            time_field.click()
        except Exception as e:
            print(f"Error defocusing brand dropdown: {str(e)}")
        
        # Small pause
        time.sleep(1)

        # Handle image uploads
        if 'images' in item_data:
            print("Starting image upload process...")
            
            # Scroll to top of page before image uploads
            try:
                driver.execute_script("window.scrollTo(0, 0);")
                print("Scrolled to top of page")
                time.sleep(2)  # Small pause to ensure visibility
            except Exception as e:
                print(f"Error scrolling to top: {str(e)}")
            
            if len(item_data['images']) > 20:
                print(f"Warning: Received {len(item_data['images'])} images but maximum allowed is 20.")
                print("Only the first 20 images will be processed.")
                item_data['images'] = item_data['images'][:20]
            
            
            if len(item_data['images']) > 20:
                print(f"Warning: Received {len(item_data['images'])} images but maximum allowed is 20.")
                print("Only the first 20 images will be processed.")
                item_data['images'] = item_data['images'][:20]
            
            print(f"Processing {len(item_data['images'])} images...")
            import os, sys
            project_root = os.path.expanduser('~/Documents/GitHub/PROJECTS/HANKS/inventory_system')
            sys.path.append(project_root)
            
            from app.services.vintageandrare.media_handler import MediaHandler
            
            with MediaHandler() as handler:
                for image_url in item_data['images']:
                    print(f"Processing image: {image_url}")
                    
                    # Download image if it's a URL
                    if image_url.startswith(('http://', 'https://')):
                        temp_file = handler.download_image(image_url)
                        if temp_file:
                            image_path = str(temp_file)
                            print(f"Downloaded to temp file: {image_path}")
                        else:
                            print(f"Failed to download image from {image_url}")
                            continue
                    else:
                        # Handle local file
                        import os
                        base_path = Path(__file__).resolve().parent.parent.parent.parent
                        abs_path = os.path.join(str(base_path), "Wxke_YkD.jpeg")
                        print(f"Checking local file at: {abs_path}")
                        if not os.path.exists(abs_path):
                            print(f"Warning: File does not exist at {abs_path}")
                            continue
                        image_path = abs_path

                    # Re-fetch upload fields for each image
                    try:
                        wait = WebDriverWait(driver, 10)
                        # Wait for any upload processing to complete
                        time.sleep(2)
                        # Find all upload fields again
                        upload_fields = wait.until(
                            EC.presence_of_all_elements_located((By.XPATH, "//input[@type='file']"))
                        )

                        # Find an empty field
                        empty_field_found = False
                        for upload_field in upload_fields:
                            try:
                                # Use JavaScript to check if field is empty
                                is_empty = driver.execute_script(
                                    "return arguments[0].value === '';", 
                                    upload_field
                                )
                                if is_empty:
                                    print(f"Found empty upload field")
                                    upload_field.send_keys(image_path)
                                    print(f"Uploaded {image_path}")
                                    time.sleep(3)  # Wait longer for upload to complete
                                    empty_field_found = True
                                    break
                            except Exception as e:
                                print(f"Error checking field: {str(e)}")
                                continue
                        
                        if not empty_field_found:
                            print("No empty upload fields available")
                            break
                            
                    except Exception as e:
                        print(f"Error during image upload: {str(e)}")
                        driver.save_screenshot("upload_error.png")
                        continue

        
        # YouTube URL
        if 'youtube_url' in item_data:
            print("Filling YouTube URL...")
            youtube_field = wait.until(
                EC.element_to_be_clickable((By.ID, "youtube_upload"))
            )
            youtube_field.send_keys(item_data['youtube_url'])

        print("Form filled successfully!")
        
        if test_mode:
            print("Test mode: Form will not be submitted")
            time.sleep(5)
            print("Test complete - closing in 5 seconds...")
        else:
            input("Review the form and press Enter to submit, or Ctrl+C to cancel...")
            submit_button = wait.until(
                EC.element_to_be_clickable((By.NAME, "submit_form"))
            )
            submit_button.click()
            time.sleep(3)
            print(f"Form submitted. Current URL: {driver.current_url}")
        
    except Exception as e:
        print(f"Error filling form: {str(e)}")
        driver.save_screenshot("form_error.png")
        raise e

# Modify the main section to accept all parameters
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Login and fill form')
    parser.add_argument('--username', required=True, help='Login username')
    parser.add_argument('--password', required=True, help='Login password')
    parser.add_argument('--map-categories', action='store_true', help='Map all category options')
    parser.add_argument('--test', type=bool, default=True, help='Test mode (default: True)')

    # Item Information - in form order
    parser.add_argument('--category', default='51', help='Category ID (default: 51 for Guitars)')
    parser.add_argument('--subcategory', help='Subcategory ID')
    parser.add_argument('--sub_subcategory', help='Sub-subcategory ID (if applicable)')
    parser.add_argument('--brand', help='Brand/Make (required)', required=True)
    parser.add_argument('--model', help='Model name (required)', required=True)
    parser.add_argument('--year', help='Year')
    parser.add_argument('--decade', help='Decade (auto-populated from year if provided)')
    parser.add_argument('--color', help='Finish color')
    parser.add_argument('--external_url', help='External/Webshop URL for the item')
    parser.add_argument('--webshop_url', help='Webshop URL (optional)')
    parser.add_argument('--description', help='Item description')

    # Pricing
    parser.add_argument('--price', help='Price (required unless call_for_price is True)')
    parser.add_argument('--call_for_price', action='store_true', help='Enable Call for Price')
    parser.add_argument('--show_vat', action='store_true', help='Show VAT')
    parser.add_argument('--discounted_price', help='Discounted price')
    parser.add_argument('--discount_percentage', help='Discount percentage')
    parser.add_argument('--partner_collective', action='store_true', help='Enable Partner Collective Price')
    parser.add_argument('--partner_price', help='Partner Collective absolute price')
    parser.add_argument('--partner_discount', help='Partner Collective discount')
    parser.add_argument('--buy_it_now', action='store_true', help='Enable Buy it Now')

    # Shipping
    parser.add_argument('--local_pickup', action='store_true', help='Available for local pickup')
    parser.add_argument('--shipping', action='store_true', help='Available for shipment')
    parser.add_argument('--processing_time', help='Processing time value')
    parser.add_argument('--time_unit', choices=['Days', 'Weeks', 'Months'], help='Processing time unit')
    
    # Shipping fees (when shipping is True)
    parser.add_argument('--europe_shipping', help='Shipping fee to Europe in GBP')
    parser.add_argument('--usa_shipping', help='Shipping fee to USA in GBP')
    parser.add_argument('--uk_shipping', help='Shipping fee to UK in GBP')
    parser.add_argument('--world_shipping', help='Shipping fee to Rest of World in GBP')
    # For additional locations, we might need a JSON structure or multiple arguments
    parser.add_argument('--additional_shipping', nargs='+', help='Additional shipping locations and fees in format "location:fee"')

    # Media
    parser.add_argument('--youtube', help='YouTube URL')
    parser.add_argument('--images', nargs='+', help='Path to image files')

    args = parser.parse_args()

    # Validation
    if not args.call_for_price and not args.price:
        parser.error("Either --price or --call_for_price is required")
    
    if not args.local_pickup and not args.shipping:
        parser.error("At least one shipping method (--local_pickup or --shipping) is required")
        
    if args.shipping and not any([args.europe_shipping, args.usa_shipping, 
                                 args.uk_shipping, args.world_shipping, 
                                 args.additional_shipping]):
        parser.error("When --shipping is enabled, at least one shipping fee must be provided")
    

    # Create item_data dictionary if any form fields are provided
    if any([args.model, args.category, args.subcategory, args.sub_subcategory,
            args.brand, args.year, args.decade, args.color, args.webshop_url, args.external_url,
            args.description, args.price, args.call_for_price, args.show_vat,
            args.discounted_price, args.discount_percentage,
            args.partner_collective, args.partner_price, args.partner_discount,
            args.buy_it_now, args.local_pickup, args.shipping,
            args.processing_time, args.time_unit,
            args.europe_shipping, args.usa_shipping, args.uk_shipping, 
            args.world_shipping, args.additional_shipping,
            args.youtube, args.images]):
        item_data = {
            # Item Information
            'category': args.category,
            'subcategory': args.subcategory,
            'sub_subcategory': args.sub_subcategory,
            'brand': args.brand,
            'model_name': args.model,
            'year': args.year,
            'decade': args.decade,
            'finish_color': args.color,
            'webshop_url': args.webshop_url,
            'external_url': args.external_url,
            'description': args.description,
            
            # Pricing
            'price': args.price,
            'call_for_price': args.call_for_price,
            'show_vat': args.show_vat,
            'discounted_price': args.discounted_price,
            'discount_percentage': args.discount_percentage,
            'partner_collective': args.partner_collective,
            'partner_price': args.partner_price,
            'partner_discount': args.partner_discount,
            'buy_it_now': args.buy_it_now,

            # Shipping
            'local_pickup': args.local_pickup,
            'shipping': args.shipping,
            'processing_time': args.processing_time,
            'time_unit': args.time_unit,
            'shipping_fees': {
                'europe': args.europe_shipping,
                'usa': args.usa_shipping,
                'uk': args.uk_shipping,
                'world': args.world_shipping,
                'additional': args.additional_shipping
            } if args.shipping else None,
            
            # Media
            'youtube_url': args.youtube,
            'images': args.images
        }
        # Remove None values
        item_data = {k: v for k, v in item_data.items() if v is not None}

    login_and_navigate(args.username, args.password, item_data, args.test, args.map_categories)