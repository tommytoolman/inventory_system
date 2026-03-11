from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager
import json
import time

def scrape_reverb_categories():
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    driver.get("https://reverb.com/sell/search")  # The selling page where categories are visible
    
    try:
        # Wait for login if needed
        # If you need to log in, add code here
        
        # Navigate to the sell/listing form
        # You might need to click a button to get to the actual listing form
        
        # Wait for the root category dropdown to be visible
        root_dropdown = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "gc-item-rootuuid"))
        )
        
        # Get all root category options
        root_select = Select(root_dropdown)
        root_options = root_select.options[1:]  # Skip the "Select one" option
        
        category_tree = {}
        
        # Loop through each root category
        for root_option in root_options:
            root_uuid = root_option.get_attribute("value")
            root_name = root_option.text
            category_tree[root_uuid] = {
                "name": root_name,
                "subcategories": {}
            }
            
            # Select this root category
            root_select.select_by_value(root_uuid)
            time.sleep(1)  # Wait for subcategories to load
            
            # Check if subcategory dropdown appears
            try:
                subcategory_dropdown = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.ID, "gc-item-selectedLeaf1Uuid"))
                )
                
                # Get all subcategory options
                sub_select = Select(subcategory_dropdown)
                sub_options = sub_select.options[1:]  # Skip the "Subcategory" option
                
                for sub_option in sub_options:
                    sub_uuid = sub_option.get_attribute("value")
                    sub_name = sub_option.text
                    category_tree[root_uuid]["subcategories"][sub_uuid] = {
                        "name": sub_name,
                        "subcategories": {}
                    }
                    
                    # Select this subcategory
                    sub_select.select_by_value(sub_uuid)
                    time.sleep(1)  # Wait for level 3 to load
                    
                    # Check if level 3 dropdown appears
                    try:
                        level3_dropdown = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.ID, "gc-item-selectedLeaf2Uuid"))
                        )
                        
                        # Get all level 3 options
                        level3_select = Select(level3_dropdown)
                        level3_options = level3_select.options[1:]  # Skip the first option
                        
                        for level3_option in level3_options:
                            level3_uuid = level3_option.get_attribute("value")
                            level3_name = level3_option.text
                            category_tree[root_uuid]["subcategories"][sub_uuid]["subcategories"][level3_uuid] = {
                                "name": level3_name,
                                "subcategories": {}
                            }
                    except:
                        # No level 3 for this category
                        pass
                    
                    # Reset to just the subcategory selected
                    sub_select.select_by_value(sub_uuid)
                
            except:
                # No subcategories for this root category
                pass
            
            # Reset to no selection
            driver.refresh()
            time.sleep(2)
            root_dropdown = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "gc-item-rootuuid"))
            )
            root_select = Select(root_dropdown)
        
        return category_tree
    
    finally:
        driver.quit()

# Run the scraper and save to JSON
reverb_categories = scrape_reverb_categories()

with open('reverb_category_tree.json', 'w') as f:
    json.dump(reverb_categories, f, indent=2)

print("Category tree saved to reverb_category_tree.json")