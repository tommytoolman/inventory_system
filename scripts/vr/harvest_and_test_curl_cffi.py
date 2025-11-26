#!/usr/bin/env python3
"""
Harvest fresh V&R cookies with UDC and immediately test with curl_cffi.

This script will:
1. Open a visible Chrome browser with UDC
2. Navigate to V&R and wait for Cloudflare to clear
3. Auto-login (or wait for manual login)
4. Save the cookies
5. Immediately test if curl_cffi can use those cookies

NON-INTERACTIVE VERSION - uses timeouts instead of input() prompts
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()


async def harvest_and_test():
    """Harvest cookies with UDC and test with curl_cffi."""

    print("=" * 60)
    print("V&R Cookie Harvest + curl_cffi Test")
    print("=" * 60)

    # Get credentials
    username = os.environ.get("VINTAGE_AND_RARE_USERNAME")
    password = os.environ.get("VINTAGE_AND_RARE_PASSWORD")

    if not username or not password:
        print("ERROR: Set VINTAGE_AND_RARE_USERNAME and PASSWORD")
        return False

    # Import UDC
    try:
        import undetected_chromedriver as uc
    except ImportError:
        print("ERROR: undetected-chromedriver not installed")
        return False

    print("\nOpening browser (visible mode)...")
    print("Will auto-login or wait 60s for manual intervention")
    print("-" * 60)

    # Use UDC in visible mode
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1280,1024")

    driver = None
    try:
        driver = uc.Chrome(headless=False, options=options)

        # Navigate to V&R
        print("Navigating to V&R...")
        driver.get("https://www.vintageandrare.com")

        # Wait for Cloudflare - check periodically
        print("Waiting for Cloudflare to clear...")
        for i in range(30):  # 30 seconds max
            time.sleep(1)
            title = driver.title or ""
            if "Just a moment" not in title and "Cloudflare" not in title:
                print(f"Cloudflare cleared after {i+1} seconds")
                break
            if i % 5 == 0:
                print(f"  Still waiting... ({i}s)")
        else:
            print("WARNING: Cloudflare may not have cleared after 30s")

        # Check if already logged in
        time.sleep(2)  # Let page render
        if "Sign out" in driver.page_source:
            print("Already logged in!")
        else:
            # Navigate to login
            print("\nNot logged in, navigating to login...")
            driver.get("https://www.vintageandrare.com/do_login")
            time.sleep(3)

            # Try to auto-fill login
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            try:
                print("Waiting for login form...")
                username_field = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.NAME, "username"))
                )
                password_field = driver.find_element(By.NAME, "pass")

                print(f"Filling login: {username}")
                username_field.clear()
                time.sleep(0.5)
                username_field.send_keys(username)
                time.sleep(0.5)
                password_field.clear()
                time.sleep(0.5)
                password_field.send_keys(password)
                time.sleep(0.5)

                print("Submitting...")
                password_field.submit()
                time.sleep(5)  # Wait for login to complete

            except Exception as e:
                print(f"Auto-fill failed: {e}")
                print("Waiting 45 seconds for manual login...")
                time.sleep(45)

        # Verify login status
        time.sleep(2)
        page_source = driver.page_source
        current_url = driver.current_url

        if "Sign out" in page_source or "/account" in current_url:
            print("\nSUCCESS: Logged in!")
        else:
            print("\nWARNING: May not be logged in")
            print(f"Current URL: {current_url}")
            # Continue anyway to harvest whatever cookies we have

        # Get cookies
        cookies = driver.get_cookies()
        print(f"\nHarvested {len(cookies)} cookies")

        # Check for key cookies
        cf_cookie = next((c for c in cookies if c["name"] == "cf_clearance"), None)
        phpsessid = next((c for c in cookies if c["name"] == "PHPSESSID"), None)

        if cf_cookie:
            print(f"cf_clearance: {cf_cookie['value'][:50]}...")
        else:
            print("WARNING: No cf_clearance cookie!")

        if phpsessid:
            print(f"PHPSESSID: {phpsessid['value']}")
        else:
            print("WARNING: No PHPSESSID cookie!")

        # Save cookies
        output_dir = Path("scripts/vr/output")
        output_dir.mkdir(parents=True, exist_ok=True)

        cookie_file = output_dir / "vr_cookies.json"
        with open(cookie_file, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"Saved cookies to {cookie_file}")

        # Save session info
        session_info = {
            "harvested_at": datetime.now().isoformat(),
            "user_agent": driver.execute_script("return navigator.userAgent"),
            "cookies_count": len(cookies),
            "cookie_names": [c["name"] for c in cookies],
            "cf_clearance_present": cf_cookie is not None,
            "phpsessid_present": phpsessid is not None,
        }
        info_file = output_dir / "vr_session_info.json"
        with open(info_file, "w") as f:
            json.dump(session_info, f, indent=2)
        print(f"Saved session info to {info_file}")

        # Now test with curl_cffi IMMEDIATELY
        print("\n" + "=" * 60)
        print("Testing with curl_cffi (immediately after harvest)")
        print("=" * 60)

        try:
            from curl_cffi import requests as cf_requests

            # Build cookie string
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

            # Use the same User-Agent from the browser
            user_agent = session_info["user_agent"]
            headers = {
                "Cookie": cookie_str,
                "User-Agent": user_agent,
            }

            # Test basic page load
            print("\nTest 1: Basic page load with curl_cffi...")
            response = cf_requests.get(
                "https://www.vintageandrare.com",
                impersonate="chrome",
                headers=headers
            )

            print(f"Status: {response.status_code}")
            print(f"cf-mitigated header: {response.headers.get('cf-mitigated', 'not present')}")

            if response.status_code == 200:
                if "Just a moment" not in response.text:
                    print("SUCCESS: curl_cffi bypassed Cloudflare!")

                    # Test authenticated page
                    print("\nTest 2: Account page access...")
                    response2 = cf_requests.get(
                        "https://www.vintageandrare.com/account",
                        impersonate="chrome",
                        headers=headers
                    )
                    print(f"Status: {response2.status_code}")

                    if response2.status_code == 200 and "Sign out" in response2.text:
                        print("SUCCESS: Authenticated access works with curl_cffi!")
                        return True
                    else:
                        print("Partial success: Page loads but auth may not transfer")
                        return True  # Still a partial success
                else:
                    print("BLOCKED: Still getting Cloudflare challenge")
            else:
                print(f"BLOCKED: Status {response.status_code}")

            # If curl_cffi failed, test with regular requests for comparison
            print("\nTest 3: Comparison with regular requests...")
            import requests
            session = requests.Session()
            for c in cookies:
                session.cookies.set(c["name"], c["value"], domain=c.get("domain", "www.vintageandrare.com"))

            response3 = session.get("https://www.vintageandrare.com", headers={"User-Agent": user_agent})
            print(f"requests status: {response3.status_code}")

        except ImportError:
            print("curl_cffi not installed!")
            print("Install with: pip install curl_cffi")

        return False

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if driver:
            print("\nClosing browser...")
            driver.quit()


if __name__ == "__main__":
    result = asyncio.run(harvest_and_test())

    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)

    if result:
        print("SUCCESS! Cookies harvested and curl_cffi works.")
        print("\nNext steps:")
        print("1. Run: python scripts/vr/export_cookies_for_railway.py")
        print("2. Set VR_COOKIES_BASE64 in Railway")
    else:
        print("Cookies harvested but curl_cffi may not work.")
        print("\nThe cookies were still saved and may work for other purposes.")
        print("Consider using Selenium Grid for V&R operations instead.")
