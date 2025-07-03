# app/services/vintageandrare/brand_validator.py

import requests
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class VRBrandValidator:
    """Fast brand validation using V&R's check_brand_exists endpoint"""
    
    BRAND_CHECK_URL = "https://www.vintageandrare.com/ajax/check_brand_exists"
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest'
    }
    
    @classmethod
    def validate_brand(cls, brand_name: str) -> Dict[str, Any]:
        """
        Fast brand validation - NO LOGIN REQUIRED
        
        Args:
            brand_name: Brand name to validate
            
        Returns:
            {
                "is_valid": bool,
                "brand_id": int|None,  # V&R's internal brand ID
                "message": str,        # User-friendly message
                "original_brand": str, # Brand name that was tested
            }
        """
        try:
            logger.info(f"Validating brand '{brand_name}' with V&R...")
            
            payload = {'brand_name': brand_name}
            response = requests.post(
                cls.BRAND_CHECK_URL, 
                data=payload, 
                headers=cls.HEADERS, 
                timeout=5
            )
            response.raise_for_status()
            
            # Parse response - should be a number
            try:
                brand_id = int(response.text.strip())
            except ValueError:
                logger.error(f"Unexpected V&R response format: '{response.text}'")
                return cls._error_result(brand_name, "Unexpected response format from V&R")
            
            if brand_id == 0:
                # Brand not found
                logger.warning(f"Brand '{brand_name}' not found in V&R database")
                return {
                    "is_valid": False,
                    "brand_id": None,
                    "message": f"❌ Brand '{brand_name}' is not accepted by Vintage & Rare",
                    "original_brand": brand_name
                }
            else:
                # Brand found
                logger.info(f"✅ Brand '{brand_name}' validated with V&R (ID: {brand_id})")
                return {
                    "is_valid": True,
                    "brand_id": brand_id,
                    "message": f"✅ Brand '{brand_name}' is accepted by Vintage & Rare",
                    "original_brand": brand_name
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error validating brand '{brand_name}': {str(e)}")
            return cls._error_result(brand_name, f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error validating brand '{brand_name}': {str(e)}")
            return cls._error_result(brand_name, f"Validation failed: {str(e)}")
    
    @classmethod
    def _error_result(cls, brand_name: str, error_message: str) -> Dict[str, Any]:
        """Standard error response format"""
        return {
            "is_valid": False,
            "brand_id": None,
            "message": f"⚠️ Could not validate brand '{brand_name}': {error_message}",
            "original_brand": brand_name
        }
    
    @classmethod
    def validate_multiple_brands(cls, brand_names: list) -> Dict[str, Dict[str, Any]]:
        """Validate multiple brands at once"""
        results = {}
        for brand in brand_names:
            results[brand] = cls.validate_brand(brand)
        return results

# Convenience functions
def is_brand_valid(brand_name: str) -> bool:
    """Simple boolean check for brand validity"""
    result = VRBrandValidator.validate_brand(brand_name)
    return result["is_valid"]

def get_brand_id(brand_name: str) -> int|None:
    """Get V&R brand ID for a valid brand"""
    result = VRBrandValidator.validate_brand(brand_name)
    return result["brand_id"] if result["is_valid"] else None