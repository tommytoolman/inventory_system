# app/tools/product_matcher.py
import asyncio
import logging
from typing import Dict, List, Tuple, Set
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fuzzywuzzy import fuzz  # For fuzzy text matching

logger = logging.getLogger(__name__)

class ProductMatcher:
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def find_potential_matches(self, min_confidence=85, status="ACTIVE", 
                              platform1="reverb", platform2="ebay"):
        """
        Find potential product matches across platforms
        
        Args:
            min_confidence: Minimum confidence score (0-100) for matches
            status: Filter products by status (ACTIVE, SOLD, etc)
            platform1: First platform to match
            platform2: Second platform to match
            
        Returns:
            List of potential matches with confidence scores
        """
        # Get active products grouped by platform
        products_by_platform = await self._get_products_by_platform(status)
        
        # Get products for each platform
        platform1_products = products_by_platform.get(platform1, [])
        platform2_products = products_by_platform.get(platform2, [])
        
        print(f"Found {len(platform1_products)} products for {platform1}")
        print(f"Found {len(platform2_products)} products for {platform2}")
        
        # Pre-filter by brand to reduce cartesian product size
        brand_groups = {}
        
        # Group platform2 products by brand for faster lookup
        for product in platform2_products:
            brand = product['brand'].lower()
            if brand not in brand_groups:
                brand_groups[brand] = []
            brand_groups[brand].append(product)
        
        potential_matches = []
        
        # Compare each product from platform1 with only those from platform2 with same brand
        for product1 in platform1_products:
            brand1 = product1['brand'].lower()
            
            # Get platform2 products with the same brand
            matching_products = brand_groups.get(brand1, [])
            
            # If no exact brand match, try similar brands
            if not matching_products:
                for brand, products in brand_groups.items():
                    # Check if brands are similar
                    brand_similarity = fuzz.ratio(brand1, brand)
                    if brand_similarity >= 85:  # High threshold for brand similarity
                        matching_products.extend(products)
            
            for product2 in matching_products:
                confidence = self._calculate_match_confidence(product1, product2)
                
                if confidence >= min_confidence:
                    potential_matches.append({
                        f'{platform1}_product': product1,
                        f'{platform2}_product': product2,
                        'confidence': confidence
                    })
        
        # Additional filtering for better quality matches
        filtered_matches = []
        seen_products = {platform1: set(), platform2: set()}
        
        # Sort by confidence (highest first)
        potential_matches.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Take only the highest confidence match for each product
        for match in potential_matches:
            product1_id = match[f'{platform1}_product']['id']
            product2_id = match[f'{platform2}_product']['id']
            
            # If either product is already in a higher confidence match, skip
            if product1_id in seen_products[platform1] or product2_id in seen_products[platform2]:
                continue
            
            # Add to filtered matches
            filtered_matches.append(match)
            seen_products[platform1].add(product1_id)
            seen_products[platform2].add(product2_id)
        
        print(f"Found {len(filtered_matches)} potential matches after filtering")
        return filtered_matches
    
    def _calculate_match_confidence(self, product1, product2):
        """Calculate confidence score for a potential match"""
        scores = []
        
        # Check brand match (mandatory)
        brand1 = product1['brand'].lower()
        brand2 = product2['brand'].lower()
        
        # If brands don't match at all, very low confidence
        brand_ratio = fuzz.ratio(brand1, brand2)
        if brand_ratio < 70:
            return max(30, brand_ratio)  # Cap at 30 if brands don't match well
        
        # Check exact title match
        if product1['title'].lower() == product2['title'].lower():
            scores.append(100)
        
        # Check exact brand+model match
        if (brand1 == brand2 and 
            product1['model'].lower() == product2['model'].lower()):
            scores.append(95)
        
        # Fuzzy title matching
        title_ratio = fuzz.ratio(product1['title'].lower(), product2['title'].lower())
        scores.append(title_ratio)
        
        # Token sort ratio (handles word order differences)
        token_sort_ratio = fuzz.token_sort_ratio(product1['title'].lower(), product2['title'].lower())
        scores.append(token_sort_ratio)
        
        # Price similarity check
        # Get prices as floats with defaults if missing
        price1 = float(product1.get('price', 0) or 0)
        price2 = float(product2.get('price', 0) or 0)
        
        # Only compare if both products have prices
        if price1 > 0 and price2 > 0:
            # Calculate price difference as a percentage
            if price1 >= price2:
                price_diff_pct = (price1 - price2) / price1 * 100
            else:
                price_diff_pct = (price2 - price1) / price2 * 100
                
            # Convert to a similarity score (0-100)
            if price_diff_pct <= 2:  # Very close prices
                price_score = 95
            elif price_diff_pct <= 5:
                price_score = 90
            elif price_diff_pct <= 10:
                price_score = 80
            elif price_diff_pct <= 15:
                price_score = 70
            elif price_diff_pct <= 20:
                price_score = 60
            else:
                # Large price differences reduce confidence
                price_score = max(0, 100 - price_diff_pct)
                
            scores.append(price_score)
        
        # Add a model-specific score
        model_ratio = fuzz.ratio(product1['model'].lower(), product2['model'].lower())
        scores.append(model_ratio)
        
        # Return weighted average of scores
        return max(scores) if scores else 0
    
    async def _get_products_by_platform(self, status="ACTIVE"):
        """Get products grouped by platform"""
        query = text("""
            SELECT 
                p.id, p.sku, p.brand, p.model, p.description, p.base_price,
                pc.platform_name, pc.id as platform_common_id
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id
            WHERE p.status = :status
        """)
        
        result = await self.db.execute(query, {"status": status})
        rows = result.fetchall()
        
        products_by_platform = {}
        for row in rows:
            platform = row.platform_name
            
            if platform not in products_by_platform:
                products_by_platform[platform] = []
                
            # Create a title field from brand and model
            title = f"{row.brand} {row.model}".strip()
                
            products_by_platform[platform].append({
                'id': row.id,
                'sku': row.sku,
                'brand': row.brand,
                'model': row.model,
                'title': title,  # Create title from brand and model
                'description': row.description,
                'price': row.base_price,  # Include the price
                'platform_common_id': row.platform_common_id
            })
        
        return products_by_platform

    async def find_potential_match_groups(self, min_confidence=70, status="ACTIVE"):
        """
        Find potential product matches across all platforms
        
        Args:
            min_confidence: Minimum confidence score (0-100) for matches
            status: Filter products by status (ACTIVE, SOLD, etc)
            
        Returns:
            List of potential match groups
        """
        # Get active products grouped by platform
        products_by_platform = await self._get_products_by_platform(status)
        
        # We'll build groups of potentially matching products
        match_groups = []
        already_grouped = set()  # Track products already in groups
        
        # Start with all platforms
        platforms = list(products_by_platform.keys())
        
        # Use the first platform as the base
        base_platform = platforms[0]
        base_products = products_by_platform.get(base_platform, [])
        
        # For each base product, find matches in all other platforms
        for base_product in base_products:
            # Skip if already grouped
            if (base_platform, base_product['id']) in already_grouped:
                continue
                
            # Start a new group with this product
            group = {
                base_platform: base_product,
                'confidence': {}  # Store confidence between pairs
            }
            
            # Look for matches in other platforms
            for other_platform in platforms[1:]:
                other_products = products_by_platform.get(other_platform, [])
                
                best_match = None
                best_confidence = 0
                
                for other_product in other_products:
                    # Skip if already grouped
                    if (other_platform, other_product['id']) in already_grouped:
                        continue
                        
                    # Calculate match confidence
                    confidence = self._calculate_match_confidence(base_product, other_product)
                    
                    if confidence >= min_confidence and confidence > best_confidence:
                        best_match = other_product
                        best_confidence = confidence
                
                # If we found a match for this platform, add it to the group
                if best_match:
                    group[other_platform] = best_match
                    group['confidence'][(base_platform, other_platform)] = best_confidence
            
            # Only add groups with at least one match
            if len(group) > 2:  # More than just the base product and confidence dict
                match_groups.append(group)
                
                # Mark all products in this group as grouped
                already_grouped.add((base_platform, base_product['id']))
                for platform in platforms[1:]:
                    if platform in group:
                        already_grouped.add((platform, group[platform]['id']))
        
        # Sort by overall confidence (average of all pairs)
        match_groups.sort(key=lambda g: sum(g['confidence'].values()) / len(g['confidence']), reverse=True)
        return match_groups

    async def save_progress(self, confirmed_matches, processed_pairs):
        """Save confirmed matches and progress to a file"""
        # Convert processed_pairs set to a list of lists for JSON serialization
        serializable_pairs = []
        for pair in processed_pairs:
            serializable_pairs.append(list(pair))
        
        progress_data = {
            'confirmed_matches': confirmed_matches,
            'processed_pairs': serializable_pairs
        }
        
        # Save to a file with better error handling
        import json
        import os
        
        try:
            # Make a backup of the existing file if it exists
            if os.path.exists('product_matching_progress.json'):
                os.rename('product_matching_progress.json', 'product_matching_progress.json.bak')
                
            with open('product_matching_progress.json', 'w') as f:
                json.dump(progress_data, f, default=str)
            
            print(f"Progress saved: {len(confirmed_matches)} confirmed matches, {len(processed_pairs)} processed pairs")
            return True
        except Exception as e:
            print(f"Error saving progress: {str(e)}")
            return False

    async def load_progress(self):
        """Load progress from file"""
        import json
        import os
        
        if not os.path.exists('product_matching_progress.json'):
            print("No saved progress found.")
            return [], set()
            
        try:
            with open('product_matching_progress.json', 'r') as f:
                progress_data = json.load(f)
                
            confirmed_matches = progress_data.get('confirmed_matches', [])
            
            # Convert the processed pairs back to a set of tuples
            processed_pairs = set()
            for pair in progress_data.get('processed_pairs', []):
                if isinstance(pair, list) and len(pair) == 2:
                    processed_pairs.add(tuple(pair))
            
            print(f"Loaded progress: {len(confirmed_matches)} confirmed matches, {len(processed_pairs)} processed pairs")
            return confirmed_matches, processed_pairs
        except Exception as e:
            print(f"Error loading progress: {str(e)}")
            return [], set()
   
    async def merge_products(self, matches):
        """
        Merge matched products by updating platform_common records
        
        Args:
            matches: List of confirmed matches to merge
        """
        merged_count = 0
        error_count = 0
        
        for match in matches:
            # Start a new transaction for each match
            async with self.db.begin() as transaction:
                try:
                    # Figure out which products we're dealing with
                    platforms = []
                    products = {}
                    
                    for key in match.keys():
                        if key.endswith('_product') and isinstance(match[key], dict):
                            platform = key.replace('_product', '')
                            platforms.append(platform)
                            products[platform] = match[key]
                    
                    if len(platforms) < 2:
                        logger.warning(f"Not enough products in match: {platforms}")
                        continue
                        
                    # Choose which product to keep (first platform's product)
                    keep_platform = platforms[0]
                    keep_product = products[keep_platform]
                    
                    # Print the merge details
                    logger.info(f"Merging: Keeping {keep_platform} product {keep_product['sku']}")
                    
                    # Merge all other products to the kept one
                    for merge_platform in platforms[1:]:
                        merge_product = products[merge_platform]
                        logger.info(f"  → Merging {merge_platform} product {merge_product['sku']}")
                        
                        # Update platform_common to point to the product we're keeping
                        query = text("""
                            UPDATE platform_common
                            SET product_id = :keep_product_id
                            WHERE id = :platform_common_id
                        """)
                        
                        await self.db.execute(query, {
                            "keep_product_id": keep_product['id'],
                            "platform_common_id": merge_product['platform_common_id']
                        })
                        
                        # Optionally mark the merged product as merged instead of deleting it
                        query = text("""
                            UPDATE products
                            SET status = 'MERGED'
                            WHERE id = :product_id
                        """)
                        
                        await self.db.execute(query, {
                            "product_id": merge_product['id']
                        })
                    
                    merged_count += 1
                    logger.info(f"Successfully merged match {merged_count}")
                    
                except Exception as e:
                    # This will roll back the current transaction
                    error_count += 1
                    logger.error(f"Error merging products: {str(e)}")
                    # No need to call rollback explicitly - the context manager handles it
                    # Continue with the next match in a new transaction
        
        logger.info(f"Merged {merged_count} matches with {error_count} errors")
        return merged_count