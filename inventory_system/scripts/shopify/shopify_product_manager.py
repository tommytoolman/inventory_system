# scripts/shopify_product_manager.py
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.shopify.client import ShopifyGraphQLClient
from app.core.config import get_settings

class ProductManager:
    def __init__(self):
        self.client = ShopifyGraphQLClient()
    
    def create_guitar_product(self, guitar_data):
        """Create a complete guitar product from your inventory data"""
        product_input = {
            "title": guitar_data["title"],
            "handle": guitar_data["handle"],
            "descriptionHtml": guitar_data["description"],
            "vendor": guitar_data["brand"],
            "productType": "Guitar",
            "status": "DRAFT",
            "variants": [{
                "price": str(guitar_data["price"]),
                "sku": guitar_data["sku"],
                "inventoryQuantities": [{
                    "availableQuantity": 1,
                    "locationId": "gid://shopify/Location/109766639956"
                }],
                "inventoryItem": {"tracked": True},
                "inventoryPolicy": "DENY"
            }]
        }
        
        result = self.client.create_product(product_input)
        
        if result and result.get("product"):
            product_gid = result["product"]["id"]
            
            # Add images if provided
            if guitar_data.get("images"):
                self.client.create_product_images(product_gid, guitar_data["images"])
            
            return product_gid
        
        return None
    
    def update_existing_product(self, product_gid, updates):
        """Update an existing product with new data"""
        return self.client.update_complete_product(product_gid, updates)

if __name__ == "__main__":
    # Example usage
    manager = ProductManager()
    
    guitar_data = {
        "title": "1965 Fender Stratocaster Sunburst",
        "handle": "1965-fender-stratocaster-sunburst",
        "description": "<p>Vintage 1965 Fender Stratocaster in excellent condition.</p>",
        "brand": "Fender", 
        "price": 12500.00,
        "sku": "FENDER-STRAT-1965-001",
        "images": ["https://example.com/strat1.jpg"]
    }
    
    product_gid = manager.create_guitar_product(guitar_data)
    print(f"Created product: {product_gid}")