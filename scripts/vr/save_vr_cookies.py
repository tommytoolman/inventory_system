#!/usr/bin/env python3
"""
Manual cookie harvesting for V&R
Run this script with headless=false to manually solve Cloudflare and save cookies
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc
import time

async def harvest_vr_cookies():
    """Manually authenticate and save cookies for V&R"""

    # Get credentials from environment
    username = os.environ.get("VINTAGE_AND_RARE_USERNAME", "")
    password = os.environ.get("VINTAGE_AND_RARE_PASSWORD", "")

    if not username or not password:
        print("❌ Please set VINTAGE_AND_RARE_USERNAME and VINTAGE_AND_RARE_PASSWORD environment variables")
        return False

    print("🚀 Starting V&R cookie harvesting...")
    print("This will open a browser window. Please:")
    print("1. Complete any Cloudflare challenges")
    print("2. Log in if needed")
    print("3. The script will save cookies when done")
    print("-" * 60)

    # Use UDC in visible mode
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1280,1024")

    driver = None
    try:
        driver = uc.Chrome(headless=False, options=options)

        # Navigate to V&R
        print("📍 Navigating to V&R...")
        driver.get("https://www.vintageandrare.com")

        # Wait for user to complete Cloudflare if needed
        print("⏳ Waiting for page to load...")
        time.sleep(5)

        # Check if we need to log in
        if "Sign out" not in driver.page_source:
            print("🔐 Need to log in...")

            # Navigate to login page
            driver.get("https://www.vintageandrare.com/do_login")
            time.sleep(2)

            try:
                # Try to find and fill login form
                username_field = driver.find_element(By.NAME, "username")
                password_field = driver.find_element(By.NAME, "pass")

                username_field.clear()
                username_field.send_keys(username)
                password_field.clear()
                password_field.send_keys(password)

                print("📝 Filled login form, please complete login if needed...")

                # Wait for user to complete login
                input("Press Enter after you've successfully logged in...")

            except Exception as e:
                print(f"⚠️  Could not auto-fill login: {e}")
                input("Please log in manually and press Enter when done...")

        # Verify we're logged in
        if "Sign out" in driver.page_source or "/account" in driver.current_url:
            print("✅ Successfully authenticated!")

            # Get all cookies
            cookies = driver.get_cookies()
            print(f"🍪 Got {len(cookies)} cookies")

            # Save cookies to file
            output_dir = Path("scripts/vr/output")
            output_dir.mkdir(parents=True, exist_ok=True)

            cookie_file = output_dir / "vr_cookies.json"
            with open(cookie_file, "w") as f:
                json.dump(cookies, f, indent=2)

            print(f"💾 Saved cookies to {cookie_file}")

            # Also save a session info file
            session_info = {
                "harvested_at": datetime.now().isoformat(),
                "user_agent": driver.execute_script("return navigator.userAgent"),
                "cookies_count": len(cookies),
                "cookie_names": [c["name"] for c in cookies]
            }

            info_file = output_dir / "vr_session_info.json"
            with open(info_file, "w") as f:
                json.dump(session_info, f, indent=2)

            print(f"📊 Saved session info to {info_file}")

            return True
        else:
            print("❌ Authentication failed - not logged in")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if driver:
            driver.quit()
            print("🔒 Browser closed")

if __name__ == "__main__":
    # Load .env file
    from dotenv import load_dotenv
    load_dotenv()

    result = asyncio.run(harvest_vr_cookies())
    if result:
        print("\n✅ Cookie harvesting completed successfully!")
        print("These cookies will be used for API requests.")
    else:
        print("\n❌ Cookie harvesting failed!")