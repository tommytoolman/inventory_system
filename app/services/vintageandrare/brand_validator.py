# app/services/vintageandrare/brand_validator.py

import logging
import os
import time
from typing import Dict, Any, Optional

import requests
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)

# Shared UA + headers aligned with the main V&R client (Chrome 142 by default)
DEFAULT_VR_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)
BASE_URL = "https://www.vintageandrare.com"
BRAND_CHECK_URL = "https://www.vintageandrare.com/ajax/check_brand_exists"
BRAND_CHECK_TIMEOUT = float(os.environ.get("VR_BRAND_TIMEOUT", "3.0"))
_shared_session: Optional[requests.Session] = None

# Simple in-memory cache: {brand_lower: (timestamp, result_dict)}
_cache: dict[str, tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL = float(os.environ.get("VR_BRAND_CACHE_TTL", "300"))
_CACHE_MAX = int(os.environ.get("VR_BRAND_CACHE_MAX", "200"))


def _build_headers() -> Dict[str, str]:
    ua = os.environ.get("VR_USER_AGENT", DEFAULT_VR_UA)
    return {
        "User-Agent": ua,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.vintageandrare.com",
        "Referer": "https://www.vintageandrare.com/",
    }


def _seed_cookies(session: requests.Session) -> int:
    """Seed cookies from file if provided. Returns count seeded."""
    cookie_file = os.environ.get("VINTAGE_AND_RARE_COOKIES_FILE")
    if not cookie_file:
        return 0
    try:
        import json

        with open(cookie_file, "r") as f:
            cookies = json.load(f)
        loaded = 0
        for cookie in cookies:
            if "name" in cookie and "value" in cookie:
                session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain") or "www.vintageandrare.com",
                )
                loaded += 1
        if loaded:
            logger.info("Seeded %s V&R cookies from %s", loaded, cookie_file)
        return loaded
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load V&R cookies from %s: %s", cookie_file, exc)
        return 0


def _get_session() -> requests.Session:
    global _shared_session  # noqa: PLW0603
    if _shared_session is None:
        sess = requests.Session()
        sess.headers.update(_build_headers())
        _seed_cookies(sess)
        _shared_session = sess
    return _shared_session


def _refresh_cookies_with_selenium(session: requests.Session) -> bool:
    """Use Selenium grid to refresh cookies when CF blocks brand checks."""
    grid_url = (os.environ.get("SELENIUM_GRID_URL") or "").strip()
    if not grid_url:
        return False

    ua = os.environ.get("VR_USER_AGENT", DEFAULT_VR_UA)
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument(f"--user-agent={ua}")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,1024")

    driver = None
    try:
        driver = webdriver.Remote(command_executor=grid_url, options=options)
        driver.get(BASE_URL)

        def cleared():
            try:
                title = driver.title or ""
                url = driver.current_url or ""
                if "Just a moment" not in title and "/cdn-cgi/" not in url:
                    return True
                WebDriverWait(driver, 5).until(
                    EC.frame_to_be_available_and_switch_to_it(
                        (By.CSS_SELECTOR, "iframe[title*='Cloudflare security challenge']")
                    )
                )
                try:
                    WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "label.ctp-checkbox-label"))
                    ).click()
                finally:
                    driver.switch_to.default_content()
                return False
            except Exception:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
                return False

        # wait up to ~15s for CF to clear
        for _ in range(15):
            if cleared():
                break
            time.sleep(1)

        # copy cookies into requests session
        for cookie in driver.get_cookies():
            if "name" in cookie and "value" in cookie:
                session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Selenium cookie refresh failed: %s", exc)
        return False
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _from_cache(brand: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    entry = _cache.get(brand.lower())
    if not entry:
        return None
    ts, result = entry
    if now - ts > _CACHE_TTL:
        _cache.pop(brand.lower(), None)
        return None
    return result


def _to_cache(brand: str, result: Dict[str, Any]) -> None:
    if len(_cache) >= _CACHE_MAX:
        # drop oldest entry
        oldest = min(_cache.items(), key=lambda kv: kv[1][0])
        _cache.pop(oldest[0], None)
    _cache[brand.lower()] = (time.time(), result)


class VRBrandValidator:
    """Fast brand validation using V&R's check_brand_exists endpoint."""

    # TEMPORARY: Set to True to bypass V&R API and use local DB check instead
    # TODO: Set back to False when V&R Cloudflare issues are resolved
    USE_LOCAL_DB_CHECK = True

    @classmethod
    def _check_brand_in_db(cls, brand_name: str) -> Dict[str, Any]:
        """Check if brand exists in local products table (sync, for temporary CF bypass)."""
        from sqlalchemy import create_engine, text
        from app.core.config import get_settings

        settings = get_settings()
        # Convert async postgres URL to sync if needed
        db_url = settings.DATABASE_URL
        if db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(db_url)

        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT COUNT(*) FROM products WHERE LOWER(brand) = LOWER(:brand)"),
                {"brand": brand_name}
            )
            count = result.scalar()

        if count and count > 0:
            return {
                "is_valid": True,
                "brand_id": None,
                "message": f"Brand '{brand_name}' found in inventory",
                "original_brand": brand_name,
                "error_code": None,
            }
        else:
            return {
                "is_valid": False,
                "brand_id": None,
                "message": f"Brand '{brand_name}' not found - will use 'Justin' for V&R",
                "original_brand": brand_name,
                "error_code": "not_found",
            }

    @classmethod
    def validate_brand(cls, brand_name: str) -> Dict[str, Any]:
        """
        Fast brand validation - NO LOGIN REQUIRED
        Uses seeded CF cookies + shared UA to avoid 403s, and a short timeout.
        """
        # TEMPORARY: Use local DB check instead of V&R API
        if cls.USE_LOCAL_DB_CHECK:
            cached = _from_cache(brand_name)
            if cached is not None:
                return cached
            result = cls._check_brand_in_db(brand_name)
            _to_cache(brand_name, result)
            return result

        cached = _from_cache(brand_name)
        if cached is not None:
            return cached

        session = _get_session()
        payload = {"brand_name": brand_name}

        try:
            response = session.post(
                BRAND_CHECK_URL,
                data=payload,
                timeout=BRAND_CHECK_TIMEOUT,
            )
            if response.status_code == 403:
                logger.warning(
                    "V&R brand check returned 403 (brand=%s). Trying Selenium cookie refresh...",
                    brand_name,
                )
                if _refresh_cookies_with_selenium(session):
                    try:
                        response = session.post(
                            BRAND_CHECK_URL,
                            data=payload,
                            timeout=BRAND_CHECK_TIMEOUT,
                        )
                    except requests.exceptions.RequestException as exc2:
                        logger.error("Retry after Selenium failed for '%s': %s", brand_name, exc2)
                        return cls._error_result(
                            brand_name,
                            "Vintage & Rare is not responding right now",
                            error_code="network",
                        )
                if response.status_code == 403:
                    logger.warning(
                        "V&R brand check still 403 after Selenium refresh (brand=%s). "
                        "Re-harvest cookies via scripts/vr/vr_cf_cookie_harvest.py and set VINTAGE_AND_RARE_COOKIES_FILE.",
                        brand_name,
                    )
                    return cls._error_result(
                        brand_name,
                        "Vintage & Rare blocked the request (403). Refresh cookies.",
                        error_code="forbidden",
                    )

            response.raise_for_status()

            try:
                brand_id = int(response.text.strip())
            except ValueError:
                logger.error("Unexpected V&R response format: '%s'", response.text)
                return cls._error_result(
                    brand_name,
                    "Unexpected response format from V&R",
                    error_code="unexpected_response",
                )

            if brand_id == 0:
                result = {
                    "is_valid": False,
                    "brand_id": None,
                    "message": f"❌ Brand '{brand_name}' is not accepted by Vintage & Rare",
                    "original_brand": brand_name,
                    "error_code": "not_found",
                }
            else:
                result = {
                    "is_valid": True,
                    "brand_id": brand_id,
                    "message": f"✅ Brand '{brand_name}' is accepted by Vintage & Rare",
                    "original_brand": brand_name,
                    "error_code": None,
                }

            _to_cache(brand_name, result)
            return result

        except requests.exceptions.RequestException as exc:
            logger.error("Network error validating brand '%s': %s", brand_name, exc)
            return cls._error_result(
                brand_name,
                "Vintage & Rare is not responding right now",
                error_code="network",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error validating brand '%s': %s", brand_name, exc)
            return cls._error_result(
                brand_name,
                f"Validation failed: {str(exc)}",
                error_code="unexpected",
            )

    @classmethod
    def _error_result(cls, brand_name: str, error_message: str, error_code: str | None = None) -> Dict[str, Any]:
        """Standard error response format."""
        return {
            "is_valid": None if error_code in {"network", "forbidden"} else False,
            "brand_id": None,
            "message": f"⚠️ Could not validate brand '{brand_name}': {error_message}",
            "original_brand": brand_name,
            "error_code": error_code,
        }

    @classmethod
    def validate_multiple_brands(cls, brand_names: list) -> Dict[str, Dict[str, Any]]:
        """Validate multiple brands at once."""
        results = {}
        for brand in brand_names:
            results[brand] = cls.validate_brand(brand)
        return results


# Convenience functions
def is_brand_valid(brand_name: str) -> bool:
    """Simple boolean check for brand validity."""
    result = VRBrandValidator.validate_brand(brand_name)
    return bool(result["is_valid"])


def get_brand_id(brand_name: str) -> int | None:
    """Get V&R brand ID for a valid brand."""
    result = VRBrandValidator.validate_brand(brand_name)
    return result["brand_id"] if result["is_valid"] else None
