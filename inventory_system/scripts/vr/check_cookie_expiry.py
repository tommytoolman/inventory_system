#!/usr/bin/env python3
"""Check V&R cookie expiration dates"""
import json
from datetime import datetime
from pathlib import Path
import os

def check_cookie_expiry():
    """Analyze V&R cookies and their expiration"""
    cookie_file = os.environ.get("VINTAGE_AND_RARE_COOKIES_FILE",
                                 "scripts/vr/output/vr_cookies.json")

    if not Path(cookie_file).exists():
        print(f"❌ Cookie file not found: {cookie_file}")
        return

    with open(cookie_file, "r") as f:
        cookies = json.load(f)

    print(f"🍪 Analyzing {len(cookies)} cookies from V&R")
    print("=" * 60)

    session_cookies = []
    persistent_cookies = []

    for cookie in cookies:
        name = cookie.get("name", "unknown")
        expiry = cookie.get("expiry", cookie.get("expirationDate"))

        if expiry:
            # Convert to datetime
            if isinstance(expiry, (int, float)):
                expiry_date = datetime.fromtimestamp(expiry)
                days_left = (expiry_date - datetime.now()).days

                cookie_info = {
                    "name": name,
                    "expiry_date": expiry_date,
                    "days_left": days_left,
                    "domain": cookie.get("domain", ""),
                    "httpOnly": cookie.get("httpOnly", False),
                    "secure": cookie.get("secure", False)
                }
                persistent_cookies.append(cookie_info)
            else:
                print(f"⚠️  Unknown expiry format for {name}: {expiry}")
        else:
            session_cookies.append(name)

    # Sort by expiration
    persistent_cookies.sort(key=lambda x: x["days_left"])

    print("\n📅 PERSISTENT COOKIES (with expiration):")
    for cookie in persistent_cookies:
        status = "✅" if cookie["days_left"] > 0 else "❌"
        print(f"{status} {cookie['name']:<20} expires {cookie['expiry_date'].strftime('%Y-%m-%d %H:%M')} ({cookie['days_left']} days)")
        if cookie["name"] == "cf_clearance":
            print(f"   ⚡ Cloudflare cookie - critical for bypassing challenges")

    print(f"\n🔄 SESSION COOKIES (expire on browser close): {len(session_cookies)}")
    for name in session_cookies:
        print(f"   • {name}")
        if name in ["PHPSESSID", "session", "auth"]:
            print(f"     ⚡ Likely auth cookie - critical for login state")

    # Find the soonest expiring critical cookie
    critical_cookies = ["cf_clearance", "PHPSESSID", "session", "auth"]
    soonest_expiry = None

    for cookie in persistent_cookies:
        if cookie["name"] in critical_cookies and cookie["days_left"] > 0:
            if not soonest_expiry or cookie["days_left"] < soonest_expiry["days_left"]:
                soonest_expiry = cookie

    print("\n📊 SUMMARY:")
    print(f"Total cookies: {len(cookies)}")
    print(f"Session cookies: {len(session_cookies)}")
    print(f"Persistent cookies: {len(persistent_cookies)}")

    if soonest_expiry:
        print(f"\n⏰ Next critical cookie expires in {soonest_expiry['days_left']} days: {soonest_expiry['name']}")

    if session_cookies:
        print(f"\n⚠️  You have {len(session_cookies)} session cookies that will expire when browser closes")
        print("These will need re-harvesting for each deployment")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    check_cookie_expiry()