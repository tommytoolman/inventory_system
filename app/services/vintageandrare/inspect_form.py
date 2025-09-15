"""
This is a script to look at the webform for V&R to inspect elements we need to interact with to automate listings.
"""

import os
import re
import sys
import json
import requests
import argparse
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
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

def login_and_navigate(username, password, item_data=None, test_mode=True, map_categories=False, db_session=None, edit_mode=False, edit_item_id=None):
    """
    Unified function for both create and edit operations ed. 31/07/2025
    """
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
        
        # Initialize Selenium with network logging enabled
        options = webdriver.ChromeOptions()
        options.add_experimental_option('useAutomationExtension', False)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--headless=new")  # Add this line
        options.add_argument("--window-size=1920,1080")  # Add this line
        
        # Enable performance logging to capture network events
        options.add_experimental_option('perfLoggingPrefs', {
            'enableNetwork': True,
            'enablePage': False
        })
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        
        # Enable DevTools for response body access
        options.add_argument("--remote-debugging-port=9222")
        
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        
        # Enable Network domain for CDP
        driver.execute_cdp_cmd('Network.enable', {})
        
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
            driver.save_screenshot("data/final_page.png")
            
            if map_categories:
                print("\n12. Mapping category hierarchy...")
                category_map = map_category_options(driver)
            elif item_data:
                print("\n12. Filling form...")
                result = fill_item_form(driver, item_data, test_mode, db_session)  # Pass db_session
                return result
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

    if edit_mode and edit_item_id:
        print(f"\n12. Editing item {edit_item_id}...")
        result = edit_item_form(driver, edit_item_id, item_data, test_mode, db_session)
        return result
    elif item_data:
        print("\n12. Filling create form...")
        result = fill_item_form(driver, item_data, test_mode, db_session)
        return result
    else:
        print("\n12. Analyzing form elements...")
        analyze_form_elements(driver)

def handle_year_decade(driver, year=None, decade=None):
    """
    Handle year and decade fields with auto-population logic
    """
    wait = WebDriverWait(driver, 10)
    
    if year:
        print(f"Filling year: {year}")
        year_field = wait.until(EC.element_to_be_clickable((By.ID, "year")))
        year_field.clear()
        year_field.send_keys(str(year))
        
        # ✅ CRUCIAL: Trigger blur event to activate V&R's decade calculation
        print("Triggering blur event to calculate decade...")
        year_field.send_keys(Keys.TAB)  # Tab to trigger blur
        time.sleep(2)  # Wait for V&R's JavaScript to calculate decade
        
        # Verify decade was auto-populated correctly
        try:
            decade_select = Select(driver.find_element(By.ID, "decade"))
            selected_value = decade_select.first_selected_option.get_attribute('value')
            selected_text = decade_select.first_selected_option.text
            
            print(f"✅ Decade auto-populated: {selected_text} (value: {selected_value})")
            
        except Exception as e:
            print(f"❌ Error verifying decade auto-population: {str(e)}")
            
    elif decade:
        print(f"Manually setting decade: {decade}")
        decade_select = Select(wait.until(EC.element_to_be_clickable((By.ID, "decade"))))
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

def wait_for_manual_submission_and_capture_result(driver, db_session=None):
    """
    Wait for user to manually submit the form, then capture V&R's response
    V&R reloads the same page after submission, so we detect page reload + success message
    """
    print("Form filled successfully!")
    print("Please manually click the 'Publish' button when ready...")
    print("After clicking, wait 3-5 seconds then press ENTER to capture result...")
    
    # Store page source before submission to detect changes
    initial_page_source = driver.page_source
    
    # Simple manual trigger - more reliable than automatic detection
    input("Press ENTER after you've submitted the form and seen V&R's response...")
    
    try:
        print("Capturing current page response...")
        
        # Give V&R time to process and reload
        time.sleep(2)
        
        # Check if page content changed (indicating submission happened)
        current_page_source = driver.page_source
        if current_page_source == initial_page_source:
            print("⚠️ Warning: Page content hasn't changed - submission may not have occurred")
        else:
            print("✅ Page content changed - submission detected")
        
        # Analyze the current page for success/failure
        result = analyze_vr_response(driver, db_session)
        
        # Save screenshot for debugging
        screenshot_path = save_response_screenshot(driver)
        if screenshot_path:
            result["screenshot_path"] = screenshot_path
            
        return result
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error capturing response: {str(e)}"
        }

def extract_vr_product_id(driver):
    """Try to extract V&R product ID from URL or page content"""
    try:
        # Check URL for ID pattern first
        url = driver.current_url
        print(f"Checking URL for product ID: {url}")
        
        # Look for patterns like /add_edit_item/12345
        id_match = re.search(r'/add_edit_item/(\d+)', url)
        if id_match:
            product_id = id_match.group(1)
            print(f"Found product ID in URL: {product_id}")
            return product_id
            
        # Check page content for ID in hidden inputs - BE MORE SELECTIVE
        try:
            # Look for specific V&R hidden inputs with meaningful names
            priority_selectors = [
                "input[name='item_id']",
                "input[name='instrument_id']", 
                "input[name='product_id']"
            ]
            
            for selector in priority_selectors:
                inputs = driver.find_elements(By.CSS_SELECTOR, selector)
                for input_elem in inputs:
                    value = input_elem.get_attribute('value')
                    name = input_elem.get_attribute('name')
                    if value and value.isdigit() and int(value) > 0:
                        print(f"Found product ID in priority input '{name}': {value}")
                        return value
            
            # Check all hidden inputs but be more selective about values
            all_hidden_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='hidden']")
            for input_elem in all_hidden_inputs:
                name = input_elem.get_attribute('name') or ''
                value = input_elem.get_attribute('value') or ''
                
                # Look for names that might contain ID
                if any(keyword in name.lower() for keyword in ['id', 'item', 'product', 'instrument']):
                    if value and value.isdigit() and int(value) > 0:
                        print(f"Found potential product ID in hidden input '{name}': {value}")
                        return value
                        
            # Check for the unique_id which might be related
            unique_id_inputs = driver.find_elements(By.CSS_SELECTOR, "input[name='unique_id']")
            for input_elem in unique_id_inputs:
                value = input_elem.get_attribute('value')
                if value and len(value) > 10:  # Unique IDs are usually long
                    print(f"Found unique_id (might be useful): {value}")
                    # Don't return this as product_id, but log it for reference
                    
        except Exception as e:
            print(f"Error checking hidden inputs: {str(e)}")
        
        # After the existing hidden input checks, add this:
        # Look for success message elements that might contain ID
        try:
            success_elements = driver.find_elements(By.CSS_SELECTOR, "[class*='success'], [class*='message']")
            for element in success_elements:
                text = element.text
                if "published" in text.lower():
                    print(f"Success element text: {text}")
                    # Look for any numbers in the success message
                    numbers = re.findall(r'\d+', text)
                    for num in numbers:
                        if len(num) > 3:  # Likely an ID
                            print(f"Found potential ID in success message: {num}")
                            return num
        except Exception as e:
            print(f"Error checking success elements: {str(e)}")
        
        # Look for V&R item ID in page source with more specific patterns
        try:
            page_source = driver.page_source
            
            # Look for JavaScript variables that might contain the ID
            js_patterns = [
                r'item_id["\s]*[:=]["\s]*(\d+)',
                r'instrument_id["\s]*[:=]["\s]*(\d+)',
                r'product_id["\s]*[:=]["\s]*(\d+)',
                r'"id"["\s]*:["\s]*(\d+)',
                # Look for specific V&R patterns
                r'vintageandrare\.com/instruments/(\d+)',
                r'/instruments/edit/(\d+)',
                r'item-(\d+)',
                # Look for form action URLs that might contain ID
                r'action="[^"]*add_edit_item/(\d+)',
                r'href="[^"]*add_edit_item/(\d+)'
            ]
            
            for pattern in js_patterns:
                matches = re.findall(pattern, page_source)
                for match in matches:
                    if int(match) > 0:  # Any positive integer
                        print(f"Found product ID in page source (pattern: {pattern}): {match}")
                        return match
                        
        except Exception as e:
            print(f"Error searching page source: {str(e)}")
            
        print("No valid product ID found")
        return None
        
    except Exception as e:
        print(f"Error extracting product ID: {str(e)}")
        return None

def analyze_vr_response_with_network(driver):
    """Analyze V&R's response focusing on actual form submission responses"""
    try:
        print("Analyzing network logs for ACTUAL form submission responses...")
        logs = driver.get_log('performance')
        
        # Sort logs by timestamp to get the most recent ones first
        sorted_logs = sorted(logs, key=lambda x: x.get('timestamp', 0), reverse=True)
        
        # Track the specific form submission we care about
        form_submission_request_id = None
        
        for log in sorted_logs:
            try:
                message = json.loads(log['message'])
                
                # First, find the actual form submission request
                if message['message']['method'] == 'Network.requestWillBeSent':
                    request = message['message']['params']['request']
                    url = request.get('url', '')
                    method = request.get('method', '')
                    
                    # This is THE form submission we care about
                    if (method == 'POST' and 
                        url == 'https://www.vintageandrare.com/instruments/add_edit_item' and
                        'multipart/form-data' in str(request.get('headers', {}))):
                        
                        form_submission_request_id = message['message']['params']['requestId']
                        print(f"✅ Found THE form submission request ID: {form_submission_request_id}")
                        
                        post_data = request.get('postData', '')
                        if post_data:
                            print(f"Form POST Data preview: {post_data[:300]}...")
                        break
                        
            except (json.JSONDecodeError, KeyError) as e:
                continue
        
        # Now find the response to that specific request
        if form_submission_request_id:
            for log in sorted_logs:
                try:
                    message = json.loads(log['message'])
                    
                    if message['message']['method'] == 'Network.responseReceived':
                        response = message['message']['params']['response']
                        request_id = message['message']['params']['requestId']
                        
                        # This is the response to our form submission
                        if request_id == form_submission_request_id:
                            print(f"✅ Found THE form submission response: {response.get('status')} - {response.get('url')}")
                            
                            # Check for redirect with item ID
                            if response.get('status') == 302:
                                headers = response.get('headers', {})
                                location = headers.get('location') or headers.get('Location')
                                if location:
                                    print(f"Form submission redirect location: {location}")
                                    id_match = re.search(r'/add_edit_item/(\d+)', location)
                                    if id_match:
                                        product_id = id_match.group(1)
                                        print(f"✅ Found product ID in form redirect: {product_id}")
                                        return product_id
                            
                            # Try to get the response body
                            try:
                                response_body = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})
                                body_content = response_body.get('body', '')
                                
                                if body_content:
                                    print(f"✅ FORM RESPONSE BODY: {body_content[:1000]}...")
                                    
                                    # Look for item ID in the actual form response
                                    id_patterns = [
                                        r'"item_id"[:\s]*"?(\d{5,7})"?',
                                        r'"id"[:\s]*"?(\d{5,7})"?',
                                        r'item_id[=:](\d{5,7})',
                                        r'product_id[=:](\d{5,7})',
                                        r'new_item[:\s]*(\d{5,7})',
                                        r'created[:\s]*(\d{5,7})',
                                        r'/add_edit_item/(\d{5,7})',
                                        r'item[_\s]*id[_\s]*[:=][_\s]*(\d{5,7})'
                                    ]
                                    
                                    for pattern in id_patterns:
                                        matches = re.findall(pattern, body_content, re.IGNORECASE)
                                        for match in matches:
                                            if 100000 <= int(match) <= 999999:  # Reasonable range
                                                print(f"✅ Found product ID in form response body: {match}")
                                                return match
                                                
                                    # Also check for any 6-digit numbers in reasonable range
                                    all_numbers = re.findall(r'\b(\d{6})\b', body_content)
                                    for num in all_numbers:
                                        if 120000 <= int(num) <= 130000:  # Your observed range
                                            print(f"✅ Found likely product ID in response: {num}")
                                            return num
                                            
                            except Exception as e:
                                print(f"Error getting form response body: {str(e)}")
                                
                except (json.JSONDecodeError, KeyError) as e:
                    continue
        
        print("No product ID found in THE form submission response")
        
    except Exception as e:
        print(f"Error analyzing THE form submission: {str(e)}")
    
    # Fall back to standard extraction
    print("Trying alternative ID extraction methods...")
    return extract_vr_product_id_enhanced(driver)

def extract_vr_product_id_enhanced(driver):
    """Enhanced product ID extraction with multiple strategies"""
    try:
        print("Enhanced product ID extraction...")
        
        # Strategy 1: Check for success message with ID
        try:
            success_elements = driver.find_elements(By.CSS_SELECTOR, 
                "[class*='success'], [class*='message'], [class*='alert']")
            for element in success_elements:
                text = element.text
                if "published" in text.lower() or "live" in text.lower():
                    print(f"Success message: {text}")
                    # Look for any 6-digit numbers in success message
                    numbers = re.findall(r'\b(\d{6,7})\b', text)
                    for num in numbers:
                        if 120000 <= int(num) <= 130000:
                            print(f"✅ Found ID in success message: {num}")
                            return num
        except Exception as e:
            print(f"Error checking success messages: {str(e)}")
        
        # Strategy 2: Check current URL after submission
        url = driver.current_url
        print(f"Current URL after submission: {url}")
        id_match = re.search(r'/add_edit_item/(\d+)', url)
        if id_match:
            product_id = id_match.group(1)
            if int(product_id) > 0:
                print(f"✅ Found product ID in URL: {product_id}")
                return product_id
        
        # Strategy 3: Check all hidden inputs for recent ID
        try:
            hidden_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='hidden']")
            for input_elem in hidden_inputs:
                name = input_elem.get_attribute('name') or ''
                value = input_elem.get_attribute('value') or ''
                
                if ('id' in name.lower() and value.isdigit() and 
                    120000 <= int(value) <= 130000):
                    print(f"✅ Found product ID in hidden input '{name}': {value}")
                    return value
        except Exception as e:
            print(f"Error checking hidden inputs: {str(e)}")
        
        # Strategy 4: Execute JavaScript to find any V&R item variables
        try:
            js_result = driver.execute_script("""
                // Look for common V&R JavaScript variables
                var possibleIds = [];
                
                // Check window object for item-related variables
                for (var key in window) {
                    if (key.toLowerCase().includes('item') || key.toLowerCase().includes('id')) {
                        var value = window[key];
                        if (typeof value === 'number' && value >= 120000 && value <= 130000) {
                            possibleIds.push({key: key, value: value});
                        }
                    }
                }
                
                return possibleIds;
            """)
            
            if js_result:
                print(f"JavaScript variables with potential IDs: {js_result}")
                for item in js_result:
                    return str(item['value'])
                    
        except Exception as e:
            print(f"Error executing JavaScript ID search: {str(e)}")
        
        print("No product ID found with enhanced extraction")
        return None
        
    except Exception as e:
        print(f"Error in enhanced product ID extraction: {str(e)}")
        return None

def extract_ids_from_json(json_data, path=""):
    """Recursively extract potential product IDs from JSON data"""
    potential_ids = []
    
    if isinstance(json_data, dict):
        for key, value in json_data.items():
            if any(id_key in key.lower() for id_key in ['id', 'item', 'product', 'instrument']):
                if isinstance(value, (int, str)) and str(value).isdigit() and int(value) > 0:
                    potential_ids.append(str(value))
                    print(f"Found ID in JSON path '{path}.{key}': {value}")
            
            # Recurse into nested objects
            if isinstance(value, (dict, list)):
                potential_ids.extend(extract_ids_from_json(value, f"{path}.{key}"))
    
    elif isinstance(json_data, list):
        for i, item in enumerate(json_data):
            if isinstance(item, (dict, list)):
                potential_ids.extend(extract_ids_from_json(item, f"{path}[{i}]"))
    
    return potential_ids

def fill_item_form(driver, item_data, test_mode=True, db_session=None):
    """
    Fill in the add/edit item form with the provided data
    """
    
    import time
    form_start_time = time.time()  # ✅ ADD TIMING HERE
    
    try:
        print(f"🕐 Starting form fill at {time.strftime('%H:%M:%S')}")
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
            print("Handling category selection with multiple levels...")
            fill_categories(driver, 
                        item_data.get('category'),
                        item_data.get('subcategory'), 
                        item_data.get('sub_subcategory'),
                        item_data.get('sub_sub_subcategory'))

    # --- Basic Information ---
        
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
        
        # Year and decade handling - CORRECTED VERSION BASED ON ACTUAL HTML
        if 'year' in item_data and item_data['year'] is not None:
            print(f"Processing year: {item_data['year']}")
            year_field = wait.until(EC.element_to_be_clickable((By.ID, "year")))
            year_field.clear()
            year_field.send_keys(str(item_data['year']))
            
            # ✅ CORRECTED: Call the exact JavaScript function from the onBlur attribute
            print("Triggering V&R's check_decade() function...")
            
            # Method 1: Execute the exact onBlur JavaScript function
            driver.execute_script("check_decade();")
            
            # Method 2: Trigger the actual blur event (as backup)
            driver.execute_script("arguments[0].onblur();", year_field)
            
            # Method 3: Traditional blur trigger (as backup)
            year_field.send_keys(Keys.TAB)
            
            time.sleep(2)  # Wait for JavaScript to execute
            
            # Enhanced verification
            try:
                decade_dropdown = driver.find_element(By.ID, "decade")
                decade_select = Select(decade_dropdown)
                
                selected_value = decade_select.first_selected_option.get_attribute('value')
                selected_text = decade_select.first_selected_option.text
                
                print(f"Decade dropdown state after JavaScript:")
                print(f"  Selected value: '{selected_value}'")
                print(f"  Selected text: '{selected_text}'")
                
                if selected_value and selected_value != "":
                    print(f"✅ Decade auto-populated: {selected_text} (value: {selected_value})")
                    
                    # Validate the decade calculation
                    try:
                        year_int = int(str(item_data['year']))
                        expected_decade = str((year_int // 10) * 10)  # e.g., 1965 -> "1960"
                        if selected_value == expected_decade:
                            print(f"✅ Decade correctly calculated: {expected_decade}s")
                        else:
                            print(f"⚠️  Warning: Expected decade {expected_decade} but got {selected_value}")
                    except ValueError:
                        print(f"⚠️  Could not validate decade for year: {item_data['year']}")
                else:
                    print("❌ Decade not auto-populated (empty value)")
                    
                # Debug all dropdown options
                all_options = decade_dropdown.find_elements(By.TAG_NAME, "option")
                print(f"🔍 DEBUG: All decade options:")
                for i, option in enumerate(all_options):
                    is_selected = option.is_selected()
                    value = option.get_attribute('value')
                    text = option.text
                    print(f"   {i}: '{text}' (value='{value}') - Selected: {is_selected}")
                
                # Force visual selection if needed
                if selected_value == "2000":
                    driver.execute_script("document.getElementById('decade').value = '2000';")
                    print("✅ Forced decade selection via JavaScript")
                    
            except Exception as e:
                print(f"⚠️  Error verifying decade: {str(e)}")

        elif 'decade' in item_data and item_data['decade'] is not None:
            print(f"Manually setting decade: {item_data['decade']}")
            try:
                decade_select = Select(wait.until(EC.element_to_be_clickable((By.ID, "decade"))))
                decade_select.select_by_value(str(item_data['decade']))
                print(f"✅ Manually set decade to: {item_data['decade']}")
            except Exception as e:
                print(f"❌ Error manually setting decade: {str(e)}")
        else:
            print("No year or decade data provided")
        

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

        # For Description (TinyMCE) - UPDATED VERSION with proper processing
        if 'description' in item_data:
            print("Filling description...")
            try:
                description_html = item_data['description']
                
                # ✅ Process line breaks: AFTER first header, BEFORE+AFTER subsequent headers
                processed_description = description_html

                # Find all headers in the content
                header_pattern = r'<p><strong><strong>([^<]+)</strong></strong></p>'
                headers = re.findall(header_pattern, processed_description)

                if headers:
                    # The first header is the title - don't add space before it
                    title_header = headers[0]
                    
                    # Add empty paragraph before all OTHER headers (not the title)
                    for header_text in headers[1:]:  # Skip first header (title)
                        # Don't add space before standard footer headers
                        if header_text not in ['ALL EU PURCHASES ARE DELIVERED WITH TAXES AND DUTIES PAID']:
                            old_pattern = f'<p><strong><strong>{re.escape(header_text)}</strong></strong></p>'
                            new_pattern = f'<p></p><p><strong><strong>{header_text}</strong></strong></p>'
                            processed_description = processed_description.replace(old_pattern, new_pattern)
                    
                    # ✅ ADD: Empty paragraphs AFTER all headers (including the first one)
                    for header_text in headers:
                        old_pattern = f'<p><strong><strong>{re.escape(header_text)}</strong></strong></p>'
                        new_pattern = f'<p><strong><strong>{header_text}</strong></strong></p><p></p>'
                        processed_description = processed_description.replace(old_pattern, new_pattern)

                print("✅ Added empty paragraphs before and after bold headers")
                
                print(f"Setting TinyMCE content: {processed_description[:100]}...")
                
                # Method 1: Use TinyMCE API to set HTML content
                try:
                    driver.execute_script(f"""
                        var editor = tinymce.get('item_desc');
                        if (editor) {{
                            editor.setContent(`{processed_description.replace('`', '\\`')}`);
                            console.log('TinyMCE content set via API');
                        }} else {{
                            console.log('TinyMCE editor not found, trying iframe method');
                            throw new Error('Editor not found');
                        }}
                    """)
                    print("✅ Description set via TinyMCE API with line breaks")
                    
                except Exception as api_error:
                    print(f"TinyMCE API method failed: {api_error}, trying iframe method...")
                    
                    # Fallback to iframe method
                    iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#item_desc_ifr")))
                    driver.switch_to.frame(iframe)
                    
                    driver.execute_script(f"""
                        document.getElementById('tinymce').innerHTML = `{processed_description.replace('`', '\\`')}`;
                    """)
                    
                    driver.switch_to.default_content()
                    print("✅ Description set via iframe innerHTML method with line breaks")
                    
                # ADD THIS DEBUG BLOCK RIGHT HERE (after line 1089)
                # After setting TinyMCE content, verify what was actually set:
                try:
                    # Get the actual content from TinyMCE
                    actual_content = driver.execute_script("return tinymce.get('item_desc').getContent();")
                    print(f"🔍 DEBUG: Actual TinyMCE content after setting:")
                    print(f"   First 200 chars: {actual_content[:200]}...")
                    
                    # Check if our <br> tags are present
                    br_count = actual_content.count('<br>')
                    print(f"   Number of <br> tags found: {br_count}")
                    
                    # Check for our specific patterns (updated for TinyMCE's HTML conversion)
                    if '</strong></strong></p><p>&nbsp;</p>' in actual_content:
                        print("   ✅ Found line breaks AFTER headers")
                    else:
                        print("   ❌ Missing line breaks AFTER headers")

                    if '<p>&nbsp;</p><p><strong><strong>' in actual_content:
                        print("   ✅ Found line breaks BEFORE headers")  
                    else:
                        print("   ❌ Missing line breaks BEFORE headers")
                        
                except Exception as e:
                    print(f"TinyMCE debug error: {str(e)}")
                    
            except Exception as e:
                print(f"❌ Error filling description: {str(e)}")
                driver.save_screenshot("desc_error.png")
                driver.switch_to.default_content()
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
        
        if 'discounted_price' in item_data and item_data['discounted_price'] is not None and str(item_data['discounted_price']).strip():
            print(f"Filling discounted price: {item_data['discounted_price']}")
            disc_field = wait.until(
                EC.element_to_be_clickable((By.ID, "discounted_price"))
            )
            disc_field.clear()
            disc_field.send_keys(str(item_data['discounted_price']))
        else:
            print("No discounted price provided - skipping discount field")
        
        # --- Processing Time ---
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
        
        # ✅ ADD TIMING SUMMARY HERE (still inside the try block)
        form_end_time = time.time()
        form_duration = form_end_time - form_start_time
        
        print(f"\n⏱️  **FORM FILL TIMING**")
        print(f"Form fill duration: {form_duration:.1f} seconds")
        print(f"🎯 Estimated time for 400 items: {form_duration * 400:.1f} seconds ({(form_duration * 400)/60:.1f} minutes)")
        
        if test_mode:
            print("TEST MODE: Form filled. You can manually submit or wait for timeout.")
            result = wait_for_manual_submission_and_capture_result(driver, db_session)
        else:
            print("LIVE MODE: Auto-submitting form and capturing response...")
            result = submit_form_and_capture_response(driver, db_session)
        
        # ✅ ADD TIMING TO RESULT
        if isinstance(result, dict):
            result["form_timing"] = {
                "form_fill_duration": form_duration,
                "estimated_400_items_seconds": form_duration * 400,
                "estimated_400_items_minutes": (form_duration * 400) / 60
            }
        
        return result
        
    except Exception as e:
        # ✅ ADD TIMING TO ERROR CASE TOO
        form_end_time = time.time()
        form_duration = form_end_time - form_start_time
        print(f"❌ Form fill failed after {form_duration:.1f} seconds")
        
        print(f"Error filling form: {str(e)}")
        driver.save_screenshot("form_error.png")
        print("ERROR: Keeping browser open for debugging...")
        input("Press Enter to close the browser after reviewing the form...")
        raise e

def edit_item_form(driver, item_id, item_data, test_mode=True, db_session=None):
    """
    Edit an existing V&R listing using an already authenticated Selenium driver
    
    Args:
        driver: Authenticated Selenium WebDriver instance
        item_id: V&R item ID to edit
        item_data: Dictionary containing updated item details
        test_mode: If True, form is filled but not submitted
        db_session: Optional database session
    """
    wait = WebDriverWait(driver, 10)
    
    try:
        print(f"🔧 **EDITING V&R ITEM {item_id}**")
        
        # Step 1: Navigate to EDIT page (key difference from create)
        edit_url = f'https://www.vintageandrare.com/instruments/add_edit_item/{item_id}'
        print(f"1. Navigating to edit page: {edit_url}")
        driver.get(edit_url)
        time.sleep(3)
        
        # Handle cookie consent if it appears
        try:
            cookie_button = driver.find_element(By.CSS_SELECTOR, ".cc-nb-okagree")
            cookie_button.click()
            time.sleep(1)
        except:
            pass
        
        print(f"2. Current URL after navigation: {driver.current_url}")
        
        # Step 2: Extract the existing unique_id from the form (more reliable than generating)
        try:
            unique_id_field = driver.find_element(By.NAME, "unique_id")
            existing_unique_id = unique_id_field.get_attribute('value')
            print(f"3. Found existing unique_id: {existing_unique_id}")
            
            # Update item_data with the real unique_id and edit-specific fields
            item_data_copy = item_data.copy()  # Don't modify the original
            item_data_copy['unique_id'] = existing_unique_id
            item_data_copy['product_id'] = item_id
            item_data_copy['added_completed'] = 'yes'  # Edit flag
            item_data_copy['version'] = 'v4'
            
        except Exception as e:
            print(f"⚠️ Could not extract unique_id: {str(e)}")
            item_data_copy = item_data.copy()
            item_data_copy['product_id'] = item_id
            item_data_copy['added_completed'] = 'yes'
            item_data_copy['version'] = 'v4'
        
        # Step 3: Fill the form (reuse existing fill_item_form logic)
        print("4. Filling edit form...")
        result = fill_item_form(driver, item_data_copy, test_mode, db_session)
        
        print(f"✅ Edit form completed for item {item_id}")
        return result
        
    except Exception as e:
        print(f"❌ Error during edit form processing: {str(e)}")
        driver.save_screenshot(f"edit_error_{item_id}.png")
        raise e

def submit_form_and_capture_response(driver, db_session=None):
    """Submit the V&R form automatically and capture response - V&R optimized version"""
    try:
        print("\n" + "="*60)
        print("🚀 STARTING V&R AUTOMATIC FORM SUBMISSION")
        print("="*60)
        
        # Step 1: Save pre-submission state
        print("\n📸 Step 1: Saving pre-submission state...")
        driver.save_screenshot("01_before_vr_submit_search.png")
        initial_url = driver.current_url
        print(f"   Current URL: {initial_url}")
        
        # Step 2: V&R-specific submit button detection
        print("\n🎯 Step 2: Looking for V&R 'Publish item' button...")
        
        submit_button = None
        found_method = None
        
        # Method 1: Try the known V&R publish button by ID
        try:
            submit_button = driver.find_element(By.CSS_SELECTOR, "a#submit_step_1")
            found_method = "ID: a#submit_step_1"
            print(f"✅ Found V&R publish button by ID: '{submit_button.text}'")
        except Exception as e:
            print(f"   Method 1 (ID) failed: {str(e)}")
            
            # Method 2: Try by class
            try:
                submit_button = driver.find_element(By.CSS_SELECTOR, "a.save_changes")
                found_method = "CLASS: a.save_changes"
                print(f"✅ Found V&R publish button by class: '{submit_button.text}'")
            except Exception as e:
                print(f"   Method 2 (class) failed: {str(e)}")
                
                # Method 3: Try by text content using XPath
                try:
                    submit_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Publish item')]")
                    found_method = "XPATH: text='Publish item'"
                    print(f"✅ Found V&R publish button by text: '{submit_button.text}'")
                except Exception as e:
                    print(f"   Method 3 (text) failed: {str(e)}")
                    
                    # Method 4: Try more flexible text search
                    try:
                        submit_button = driver.find_element(By.XPATH, "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'publish')]")
                        found_method = "XPATH: case-insensitive text search"
                        print(f"✅ Found V&R publish button by flexible text: '{submit_button.text}'")
                    except Exception as e:
                        print(f"   Method 4 (flexible) failed: {str(e)}")
                        submit_button = None
        
        # Step 3: If V&R button found, validate and click it
        if submit_button:
            print(f"\n🎯 Step 3: V&R publish button found!")
            print(f"   Method: {found_method}")
            print(f"   Text: '{submit_button.text}'")
            print(f"   Tag: {submit_button.tag_name}")
            print(f"   Class: {submit_button.get_attribute('class')}")
            print(f"   ID: {submit_button.get_attribute('id')}")
            print(f"   Href: {submit_button.get_attribute('href')}")
            
            # Validate the button is clickable
            try:
                is_displayed = submit_button.is_displayed()
                is_enabled = submit_button.is_enabled()
                print(f"   Displayed: {is_displayed}")
                print(f"   Enabled: {is_enabled}")
                
                if not is_displayed:
                    print("❌ V&R publish button is not visible")
                    driver.save_screenshot("02_vr_button_not_visible.png")
                    return {
                        "status": "error",
                        "message": "V&R publish button found but not visible",
                        "vr_product_id": None
                    }
                
                if not is_enabled:
                    print("❌ V&R publish button is not enabled")
                    driver.save_screenshot("02_vr_button_not_enabled.png")
                    return {
                        "status": "error", 
                        "message": "V&R publish button found but not enabled",
                        "vr_product_id": None
                    }
                
                # Button is good to click
                print("✅ V&R publish button is clickable")
                
                # Scroll to button to ensure it's in view
                print("📍 Scrolling to V&R publish button...")
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", submit_button)
                time.sleep(2)  # Wait for scroll to complete
                
                # Take screenshot before clicking
                driver.save_screenshot("03_before_vr_publish_click.png")
                print("📸 Screenshot saved: before V&R publish click")
                
                # Click the V&R publish button
                print("🖱️  Clicking V&R 'Publish item' button...")
                submit_button.click()
                print("✅ V&R Publish button clicked successfully!")
                
                # Wait for V&R to process the submission
                print("⏱️  Waiting for V&R response...")
                time.sleep(5)  # Give V&R time to process
                
                # Check if URL changed
                new_url = driver.current_url
                print(f"📍 URL after click: {new_url}")
                
                if new_url != initial_url:
                    print("✅ URL changed - submission likely successful")
                else:
                    print("⚠️  URL unchanged - checking page content for changes...")
                
                # Take screenshot after submission
                driver.save_screenshot("04_after_vr_publish_click.png")
                print("📸 Screenshot saved: after V&R publish click")
                
                # Analyze V&R's response
                print("\n📊 Step 4: Analyzing V&R response...")
                result = analyze_vr_response(driver, db_session)
                result["submission_method"] = found_method
                result["url_changed"] = new_url != initial_url
                return result
                
            except Exception as click_error:
                print(f"❌ Error during V&R button interaction: {str(click_error)}")
                driver.save_screenshot("02_vr_button_click_error.png")
                return {
                    "status": "error",
                    "message": f"Error clicking V&R publish button: {str(click_error)}",
                    "vr_product_id": None,
                    "exception": str(click_error)
                }
        
        # Step 4: Fallback - if V&R button not found, try generic submit detection
        print(f"\n⚠️  Step 4: V&R button not found, falling back to generic submit detection...")
        
        # Find all potential submit elements as fallback
        all_buttons = driver.find_elements(By.TAG_NAME, "button")
        all_inputs = driver.find_elements(By.TAG_NAME, "input")
        all_links = driver.find_elements(By.TAG_NAME, "a")
        
        print(f"   Found: {len(all_buttons)} buttons, {len(all_inputs)} inputs, {len(all_links)} links")
        
        # Generic submit candidates
        submit_candidates = []
        
        # Check all links for submit-like behavior
        for i, link in enumerate(all_links):
            try:
                text = (link.text or "").strip().lower()
                class_attr = (link.get_attribute('class') or "").lower()
                id_attr = (link.get_attribute('id') or "").lower()
                
                score = 0
                if any(keyword in text for keyword in ['publish', 'submit', 'save', 'create']):
                    score += 10
                if any(keyword in class_attr for keyword in ['submit', 'save', 'publish']):
                    score += 8
                if any(keyword in id_attr for keyword in ['submit', 'save', 'publish']):
                    score += 8
                
                if score > 0:
                    submit_candidates.append({
                        'element': link,
                        'type': 'link',
                        'score': score,
                        'text': text,
                        'class': class_attr,
                        'id': id_attr
                    })
                    print(f"   Link candidate {i}: score={score}, text='{text}', class='{class_attr}'")
                    
            except Exception as e:
                continue
        
        # Check submit inputs
        for i, input_elem in enumerate(all_inputs):
            try:
                type_attr = (input_elem.get_attribute('type') or "").lower()
                if type_attr == 'submit':
                    value_attr = (input_elem.get_attribute('value') or "").lower()
                    name_attr = (input_elem.get_attribute('name') or "").lower()
                    
                    score = 15  # Base score for submit inputs
                    if any(keyword in value_attr for keyword in ['publish', 'submit', 'save']):
                        score += 10
                    
                    submit_candidates.append({
                        'element': input_elem,
                        'type': 'input',
                        'score': score,
                        'text': value_attr,
                        'name': name_attr,
                        'type_attr': type_attr
                    })
                    print(f"   Input candidate {i}: score={score}, value='{value_attr}', name='{name_attr}'")
                    
            except Exception as e:
                continue
        
        # Try fallback candidates
        if submit_candidates:
            submit_candidates.sort(key=lambda x: x['score'], reverse=True)
            print(f"\n🎯 Trying {len(submit_candidates)} fallback candidates...")
            
            for i, candidate in enumerate(submit_candidates[:3]):  # Try top 3
                try:
                    element = candidate['element']
                    print(f"   Trying candidate {i+1}: {candidate['type']} (score: {candidate['score']})")
                    
                    if element.is_displayed() and element.is_enabled():
                        driver.execute_script("arguments[0].scrollIntoView(true);", element)
                        time.sleep(1)
                        
                        driver.save_screenshot(f"05_fallback_candidate_{i+1}_before.png")
                        element.click()
                        time.sleep(3)
                        
                        new_url = driver.current_url
                        if new_url != initial_url:
                            print(f"✅ Fallback candidate {i+1} worked!")
                            driver.save_screenshot(f"05_fallback_candidate_{i+1}_success.png")
                            result = analyze_vr_response(driver, db_session)
                            result["submission_method"] = f"Fallback {candidate['type']}"
                            return result
                            
                except Exception as e:
                    print(f"   Candidate {i+1} failed: {str(e)}")
                    continue
        
        # If we get here, nothing worked
        print("\n❌ ALL SUBMISSION METHODS FAILED")
        driver.save_screenshot("06_all_methods_failed.png")
        
        return {
            "status": "error",
            "message": "Could not find or click any submit button (V&R or generic)",
            "vr_product_id": None,
            "debug_info": {
                "vr_button_found": submit_button is not None,
                "fallback_candidates": len(submit_candidates) if 'submit_candidates' in locals() else 0,
                "final_url": driver.current_url
            }
        }
        
    except Exception as e:
        print(f"\n💥 CRITICAL ERROR in V&R form submission: {str(e)}")
        driver.save_screenshot("07_critical_submission_error.png")
        
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        
        return {
            "status": "error",
            "message": f"Critical error during V&R form submission: {str(e)}",
            "vr_product_id": None,
            "exception": str(e),
            "traceback": traceback.format_exc()
        }

def analyze_vr_response(driver, db_session=None):
    """Analyze V&R's response page for success/failure"""
    try:
        current_url = driver.current_url
        page_title = driver.title
        page_text = driver.page_source.lower()
        
        print(f"Response URL: {current_url}")
        print(f"Response Title: {page_title}")
        
        # V&R-specific success patterns
        success_patterns = [
            "your item is now published and live on vintageandrare.com",
            "your item is now published and live",
            "published and live",
            "successfully created",
            "item has been created",
            "listing created successfully"
        ]
        
        # Check for success messages first
        for pattern in success_patterns:
            if pattern in page_text:
                print(f"✅ SUCCESS: Found pattern '{pattern}'")
                
                # Use your existing VRExportService for ID extraction
                vr_id = None
                if db_session:
                    vr_id = analyze_vr_response_with_export_fallback(driver, db_session)
                
                return {
                    "status": "success",
                    "message": f"V&R listing created successfully: {pattern}",
                    "vr_product_id": vr_id,
                    "page_url": current_url,
                    "page_title": page_title,
                    "detected_pattern": pattern
                }
        
        # Check for error patterns
        error_patterns = [
            "error",
            "failed",
            "invalid",
            "required field",
            "please try again",
            "something went wrong"
        ]
        
        for pattern in error_patterns:
            if pattern in page_text:
                print(f"❌ ERROR: Found error pattern '{pattern}'")
                return {
                    "status": "error",
                    "message": f"V&R listing failed: {pattern}",
                    "vr_product_id": None,
                    "page_url": current_url,
                    "page_title": page_title,
                    "detected_pattern": pattern
                }
        
        # If no clear success or error pattern found
        print("⚠️ WARNING: No clear success or error pattern detected")
        
        # Try to extract any product ID anyway
        vr_id = None
        if db_session:
            vr_id = analyze_vr_response_with_export_fallback(driver, db_session)
        
        return {
            "status": "unknown",
            "message": "Response analysis inconclusive - manual verification recommended",
            "vr_product_id": vr_id,
            "page_url": current_url,
            "page_title": page_title,
            "detected_pattern": None
        }
        
    except Exception as e:
        print(f"Exception in analyze_vr_response: {str(e)}")
        return {
            "status": "error",
            "message": f"Error analyzing V&R response: {str(e)}",
            "vr_product_id": None,
            "page_url": driver.current_url if driver else None,
            "page_title": driver.title if driver else None,
            "exception": str(e)
        }

def save_response_screenshot(driver):
    """Save screenshot of V&R response page for debugging"""
    try:
        from pathlib import Path
        import datetime
        
        # Save to app/services/vintageandrare/ folder based on your structure
        project_root = Path(__file__).resolve().parent  # This should be app/services/vintageandrare/
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = project_root / f"vr_response_{timestamp}.png"
        
        driver.save_screenshot(str(screenshot_path))
        print(f"Response screenshot saved: {screenshot_path}")
        return str(screenshot_path)
        
    except Exception as e:
        print(f"Error saving screenshot: {str(e)}")
        return None

def analyze_vr_response_with_export_fallback(driver, db_session):
    """
    Enhanced response analysis using your existing VRExportService as fallback
    """
    try:
        # First try network analysis (in case V&R changes and starts returning IDs)
        vr_id = analyze_vr_response_with_network(driver)
        
        if vr_id:
            print(f"✅ Found ID via network analysis: {vr_id}")
            return vr_id
            
        # Fallback to your existing export service
        print("Network analysis failed, using VRExportService fallback...")
        
        # Run the async function
        # import asyncio
        # vr_id = asyncio.run(get_newly_created_item_id_via_export_service(db_session))
        vr_id = None
        
        if vr_id:
            print(f"✅ Found ID via VRExportService: {vr_id}")
            return vr_id
            
        print("❌ Could not determine V&R item ID")
        return None
        
    except Exception as e:
        print(f"Error in export fallback analysis: {str(e)}")
        return None


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