#!/usr/bin/env python3
"""
Export V&R cookies as base64 for Railway deployment.

This script reads the harvested cookies and outputs a base64 string
that can be set as VR_COOKIES_BASE64 environment variable in Railway.

Usage:
    python scripts/vr/export_cookies_for_railway.py

The output can be copied directly into Railway's environment variables.
"""
import json
import base64
import os
from pathlib import Path
from datetime import datetime


def export_cookies_base64():
    """Export cookies as base64 string for Railway."""

    # Find cookie file
    cookie_file = Path("scripts/vr/output/vr_cookies.json")
    if not cookie_file.exists():
        print(f"Cookie file not found: {cookie_file}")
        print("Run save_vr_cookies.py first to harvest cookies.")
        return None

    # Load cookies
    with open(cookie_file, "r") as f:
        cookies = json.load(f)

    print(f"Loaded {len(cookies)} cookies from {cookie_file}")

    # Analyze cookies
    cf_clearance = None
    phpsessid = None
    critical_cookies = []

    for cookie in cookies:
        name = cookie.get("name", "")
        expiry = cookie.get("expiry")

        if name == "cf_clearance":
            cf_clearance = cookie
            if expiry:
                expiry_date = datetime.fromtimestamp(expiry)
                print(f"  cf_clearance: expires {expiry_date.strftime('%Y-%m-%d')} (CRITICAL)")
            critical_cookies.append(cookie)
        elif name == "PHPSESSID":
            phpsessid = cookie
            print(f"  PHPSESSID: session cookie (will need fresh login)")
        elif name in ["vr_currency", "cookie_consent_user_accepted"]:
            critical_cookies.append(cookie)

    if not cf_clearance:
        print("\nWARNING: No cf_clearance cookie found!")
        print("This cookie is essential for Cloudflare bypass.")
        print("Re-run save_vr_cookies.py to harvest fresh cookies.")
        return None

    # For Railway, we only need cf_clearance and a few others
    # PHPSESSID will be obtained via fresh login
    minimal_cookies = []
    for cookie in cookies:
        name = cookie.get("name", "")
        # Include cf_clearance and helpful cookies, skip analytics
        if name in ["cf_clearance", "vr_currency", "cookie_consent_user_accepted",
                    "cookie_consent_level", "cookie_consent_user_consent_token"]:
            minimal_cookies.append(cookie)

    print(f"\nMinimal cookie set for Railway: {len(minimal_cookies)} cookies")
    for c in minimal_cookies:
        print(f"  - {c['name']}")

    # Encode as base64
    cookies_json = json.dumps(minimal_cookies)
    cookies_b64 = base64.b64encode(cookies_json.encode('utf-8')).decode('utf-8')

    print("\n" + "=" * 60)
    print("BASE64 ENCODED COOKIES FOR RAILWAY")
    print("=" * 60)
    print("\nSet this as VR_COOKIES_BASE64 in Railway:")
    print("-" * 60)
    print(cookies_b64)
    print("-" * 60)

    # Also save to file for easy copy
    output_file = Path("scripts/vr/output/vr_cookies_base64.txt")
    with open(output_file, "w") as f:
        f.write(cookies_b64)
    print(f"\nAlso saved to: {output_file}")

    # Provide full cookies option too
    full_b64 = base64.b64encode(json.dumps(cookies).encode('utf-8')).decode('utf-8')
    full_output = Path("scripts/vr/output/vr_cookies_full_base64.txt")
    with open(full_output, "w") as f:
        f.write(full_b64)
    print(f"Full cookies (all {len(cookies)}): {full_output}")

    return cookies_b64


def verify_base64(b64_string: str):
    """Verify the base64 string can be decoded back."""
    try:
        decoded = base64.b64decode(b64_string).decode('utf-8')
        cookies = json.loads(decoded)
        print(f"\nVerification: Successfully decoded {len(cookies)} cookies")
        return True
    except Exception as e:
        print(f"\nVerification FAILED: {e}")
        return False


if __name__ == "__main__":
    result = export_cookies_base64()
    if result:
        verify_base64(result)
        print("\nNext steps:")
        print("1. Copy the base64 string above")
        print("2. Go to Railway dashboard -> Your service -> Variables")
        print("3. Add: VR_COOKIES_BASE64 = <paste the string>")
        print("4. Redeploy the service")
