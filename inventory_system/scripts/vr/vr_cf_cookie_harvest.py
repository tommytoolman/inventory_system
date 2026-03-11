#!/usr/bin/env python3
"""
Use seleniumbase (undetected Chrome) to clear Cloudflare, log in to V&R, and dump cookies.

Requires:
  pip install seleniumbase

Usage:
  python scripts/vr/vr_cf_cookie_harvest.py

Environment:
  VINTAGE_AND_RARE_USERNAME / VINTAGE_AND_RARE_PASSWORD must be set.
"""

import json
import os
import time
from pathlib import Path
from seleniumbase import SB
from dotenv import load_dotenv


def main():
    # Load .env from repo root if present
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    with SB(uc=True, headed=True) as sb:
        print("Opening V&R to clear Cloudflare... solve any checkbox if shown.")
        sb.uc_open("https://www.vintageandrare.com")
        time.sleep(10)
        print("\nIf you see a GDPR/cookie banner, accept it. Then click Login and sign in manually in the browser window.")
        input("After you are logged in (or ready to dump cookies), press Enter here to continue...")
        cookies = sb.driver.get_cookies()
        # Save to file for convenience
        output_dir = Path(__file__).resolve().parent / "output"
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / "vr_cookies.json"
        with output_file.open("w") as f:
            json.dump(cookies, f, indent=2)
        print(f"\nSaved {len(cookies)} cookies to {output_file}")
        print("\n=== Cookies (stdout) ===")
        print(json.dumps(cookies, indent=2))
        print("\nSet VINTAGE_AND_RARE_COOKIES_FILE to this path to seed the client.")


if __name__ == "__main__":
    main()
