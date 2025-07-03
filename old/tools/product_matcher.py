# app/tools/product_matcher.py
"""
Provides the ProductMatcher class, a tool designed to identify, merge,
and potentially restore duplicate product entries across different e-commerce
platforms linked within the application's database.

This tool is primarily intended for initial data loading and reconciliation
tasks where the same physical product might exist as separate entries
originating from different platforms (e.g., eBay, Reverb).

Workflow typically involves:
1. Finding potential match groups (`find_potential_match_groups` or `find_potential_matches`).
2. (External/Manual) Reviewing these potential matches. Progress can be saved/loaded.
3. Merging confirmed matches (`merge_products`), which consolidates database records.
4. Optionally restoring merged products if needed (`restore_merged_product`, `restore_platform_common`).
"""

import asyncio
import logging
import traceback
import os
import sys
import json
from dotenv import load_dotenv
from typing import Dict, List, Tuple, Set, Any, Optional # Added Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from fuzzywuzzy import fuzz

load_dotenv() # Load environment variables from .env file

# Configure logging
logging.basicConfig(level=logging.INFO) # Added basic logging config
logger = logging.getLogger(__name__)

# Define a type alias for product dictionaries for clarity
ProductDict = Dict[str, Any]

class ProductMatcher:
    """
    Handles finding, merging, and restoring product duplicates across platforms.

    Requires an active asynchronous database session (`AsyncSession`) connected
    to the application's database upon initialization.

    Merge and restore operations may require specific database permissions
    and utilize separate database connections/sessions for isolation.
    """
    def __init__(self, db: AsyncSession, database_url: Optional[str] = None):
        """
        Initializes the ProductMatcher.

        Args:
            db: The primary AsyncSession for finding matches.
            database_url: The database connection string, primarily needed for
                        merge/restore operations which create separate engines.
                        If None, attempts to read from DATABASE_URL env var.
        """
        self.db = db
        self._database_url = database_url or os.environ.get('DATABASE_URL')
        if not self._database_url:
            logger.warning("DATABASE_URL environment variable not set. "
                           "Merge/Restore operations may fail.")

    # --- Match Finding Methods ---

    async def find_potential_matches(self, min_confidence: int = 85, status: str = "ACTIVE",
                                     platform1: str = "reverb", platform2: str = "ebay") -> List[Dict[str, Any]]:
        """
        Finds potential product matches between two specific platforms.

        Compares each product from platform1 against products from platform2,
        filtering by brand first to optimize the process.

        Args:
            min_confidence: Minimum confidence score (0-100) required for a potential match.
            status: Filters products by the status field in the 'products' table.
            platform1: The name of the first platform (e.g., 'reverb').
            platform2: The name of the second platform (e.g., 'ebay').

        Returns:
            A list of dictionaries, each representing a potential match:
            {
                '<platform1>_product': ProductDict,
                '<platform2>_product': ProductDict,
                'confidence': float
            }
        """
        logger.info(f"Finding potential matches between {platform1} and {platform2} "
                    f"(min_confidence={min_confidence}, status={status})")
        # Get active products grouped by platform
        products_by_platform = await self._get_products_by_platform(status)

        # Get products for each platform
        platform1_products = products_by_platform.get(platform1, [])
        platform2_products = products_by_platform.get(platform2, [])

        logger.info(f"Found {len(platform1_products)} products for {platform1}")
        logger.info(f"Found {len(platform2_products)} products for {platform2}")

        if not platform1_products or not platform2_products:
            logger.warning("One or both platforms have no products matching the criteria. Cannot find matches.")
            return []

        # Pre-filter by brand to reduce cartesian product size
        brand_groups: Dict[str, List[ProductDict]] = {}

        # Group platform2 products by brand for faster lookup
        for product in platform2_products:
            brand = product.get('brand', '').lower() # Handle potential missing brand
            if brand: # Only group if brand exists
                if brand not in brand_groups:
                    brand_groups[brand] = []
                brand_groups[brand].append(product)

        potential_matches: List[Dict[str, Any]] = []

        # Compare each product from platform1 with only those from platform2 with same/similar brand
        for product1 in platform1_products:
            brand1 = product1.get('brand', '').lower()
            if not brand1: # Skip if product1 has no brand
                continue

            # Get platform2 products with the same brand
            matching_products = brand_groups.get(brand1, [])

            for product2 in matching_products:
                # Avoid comparing a product to itself if it somehow exists on both sides (unlikely with this structure)
                if product1['platform_common_id'] == product2['platform_common_id']:
                    continue

                confidence = self._calculate_match_confidence(product1, product2)

                if confidence >= min_confidence:
                    potential_matches.append({
                        f'{platform1}_product': product1,
                        f'{platform2}_product': product2,
                        'confidence': confidence
                    })

        # Additional filtering for better quality matches: keep only the best match per product
        filtered_matches: List[Dict[str, Any]] = []
        seen_products: Dict[str, Set[int]] = {platform1: set(), platform2: set()}

        # Sort by confidence (highest first)
        potential_matches.sort(key=lambda x: x['confidence'], reverse=True)

        # Take only the highest confidence match involving each product
        for match in potential_matches:
            # Use platform_common_id for uniqueness within this context
            product1_common_id = match[f'{platform1}_product']['platform_common_id']
            product2_common_id = match[f'{platform2}_product']['platform_common_id']

            # If either product is already in a higher confidence match, skip
            if product1_common_id in seen_products[platform1] or product2_common_id in seen_products[platform2]:
                continue

            # Add to filtered matches
            filtered_matches.append(match)
            seen_products[platform1].add(product1_common_id)
            seen_products[platform2].add(product2_common_id)

        logger.info(f"Found {len(filtered_matches)} potential high-confidence matches after filtering")
        return filtered_matches

    async def find_potential_match_groups(self, min_confidence: int = 70, status: str = "ACTIVE") -> List[Dict[str, Any]]:
        """
        Finds potential product match groups across all available platforms.

        Attempts to identify sets of products (one per platform ideally) that
        likely represent the same physical item.

        Args:
            min_confidence: Minimum confidence score (0-100) required for a
                            product to be considered a match to the base product in a group.
            status: Filters products by the status field in the 'products' table.

        Returns:
            A list of dictionaries, each representing a potential match group:
            {
                'platform_name1': ProductDict,
                'platform_name2': ProductDict,
                ...,
                'confidence': { ('base_platform', 'other_platform'): float, ... }
            }
            Only groups containing at least two potentially matching products
            (in addition to the confidence dictionary) are returned.
        """
        logger.info(f"Finding potential match groups across all platforms "
                    f"(min_confidence={min_confidence}, status={status})")
        # Get active products grouped by platform
        products_by_platform = await self._get_products_by_platform(status)

        # We'll build groups of potentially matching products
        match_groups: List[Dict[str, Any]] = []
        # Track products already in groups using (platform_name, platform_common_id) tuples
        already_grouped: Set[Tuple[str, int]] = set()

        platforms = list(products_by_platform.keys())
        if len(platforms) < 2:
            logger.warning("Need at least two platforms with products to find groups.")
            return []

        # Use the first platform as the base for forming groups
        # Consider choosing the platform with the most reliable data as base
        base_platform = platforms[0]
        base_products = products_by_platform.get(base_platform, [])
        other_platforms = platforms[1:]

        logger.info(f"Using '{base_platform}' as base platform with {len(base_products)} products.")

        # For each base product, find matches in all other platforms
        for base_product in base_products:
            base_product_common_id = base_product['platform_common_id']

            # Skip if already grouped
            if (base_platform, base_product_common_id) in already_grouped:
                continue

            # Start a new group with this product
            current_group: Dict[str, Any] = {
                base_platform: base_product,
                'confidence': {}  # Store confidence between base and others
            }
            group_product_ids: Set[Tuple[str, int]] = {(base_platform, base_product_common_id)}

            # Look for the best match in each other platform
            for other_platform in other_platforms:
                other_products = products_by_platform.get(other_platform, [])
                best_match_for_platform: Optional[ProductDict] = None
                best_confidence_for_platform: float = 0.0

                for other_product in other_products:
                    other_product_common_id = other_product['platform_common_id']

                    # Skip if already grouped
                    if (other_platform, other_product_common_id) in already_grouped:
                        continue

                    # Calculate match confidence against the base product
                    confidence = self._calculate_match_confidence(base_product, other_product)

                    if confidence >= min_confidence and confidence > best_confidence_for_platform:
                        best_match_for_platform = other_product
                        best_confidence_for_platform = confidence

                # If we found a suitable match for this platform, add it to the group
                if best_match_for_platform:
                    current_group[other_platform] = best_match_for_platform
                    current_group['confidence'][(base_platform, other_platform)] = best_confidence_for_platform
                    group_product_ids.add((other_platform, best_match_for_platform['platform_common_id']))

            # Only add groups with at least one match (i.e., more than just base product + confidence dict)
            if len(current_group) > 2:
                match_groups.append(current_group)
                # Mark all products in this group as grouped to avoid reusing them
                already_grouped.update(group_product_ids)


        logger.info(f"Found {len(match_groups)} potential match groups.")
        # Sort by overall confidence (e.g., average confidence score)
        # match_groups.sort(key=lambda g: sum(g['confidence'].values()) / len(g['confidence']) if g['confidence'] else 0, reverse=True)
        return match_groups


    def _calculate_match_confidence(self, product1: ProductDict, product2: ProductDict) -> float:
        """
        Calculates a confidence score (0-100) indicating the likelihood
        that two products represent the same physical item.

        Uses fuzzy string matching on brand, model, and title, along with price similarity.

        Args:
            product1: Dictionary representing the first product.
            product2: Dictionary representing the second product.

        Returns:
            A confidence score between 0 and 100.
        """
        scores: List[float] = [] # Changed to float for consistency

        # Normalize common fields, handling potential None values
        brand1 = product1.get('brand', '').lower()
        brand2 = product2.get('brand', '').lower()
        model1 = product1.get('model', '').lower()
        model2 = product2.get('model', '').lower()
        title1 = product1.get('title', '').lower() # Assuming title is generated
        title2 = product2.get('title', '').lower()

        # --- Brand Matching (High Importance) ---
        # Require at least some brand similarity
        brand_ratio = fuzz.ratio(brand1, brand2) if brand1 and brand2 else 0
        # Increase importance: if brands don't match reasonably well, confidence is low.
        if brand_ratio < 70: # Stricter threshold?
             # Return early with low score if brands are too dissimilar
             # logger.debug(f"Low brand match ({brand_ratio}) for {title1} vs {title2}")
             return max(0.0, brand_ratio * 0.5) # Scale down the score significantly

        # --- Model Matching ---
        # Model similarity is also important
        model_ratio = fuzz.ratio(model1, model2) if model1 and model2 else 0
        scores.append(model_ratio)

        # --- Title Matching (Fuzzy) ---
        # Use token_sort_ratio to handle word order differences better
        # title_ratio = fuzz.ratio(title1, title2)
        token_sort_ratio = fuzz.token_sort_ratio(title1, title2) if title1 and title2 else 0
        scores.append(token_sort_ratio * 1.1) # Slightly boost title match weight

        # --- Exact Matches (High Confidence Boost) ---
        # Check exact brand+model match
        if brand1 and model1 and brand1 == brand2 and model1 == model2:
            scores.append(98.0) # High score for exact brand/model

        # Check exact title match (less likely if generated, but possible)
        # if title1 and title1 == title2:
        #     scores.append(100.0)

        # --- Price Similarity Check ---
        try:
            price1 = float(product1.get('price') or 0.0)
            price2 = float(product2.get('price') or 0.0)
        except (ValueError, TypeError):
            price1 = 0.0
            price2 = 0.0

        # Only compare if both products have valid positive prices
        if price1 > 0 and price2 > 0:
            # Calculate price difference as a percentage of the higher price
            abs_diff = abs(price1 - price2)
            max_price = max(price1, price2)
            price_diff_pct = (abs_diff / max_price) * 100

            # Convert percentage difference to a similarity score (100 = identical)
            # Score decreases as percentage difference increases
            price_score = max(0.0, 100.0 - (price_diff_pct * 2)) # Penalize price diff more?
            scores.append(price_score)
        elif price1 > 0 or price2 > 0:
            # One has price, other doesn't - slightly reduces confidence
            scores.append(60.0) # Arbitrary score, maybe adjust
        # else: both prices are zero/missing, no price score added

        # --- Final Score Calculation ---
        # Use a weighted average or simply the maximum score found?
        # Using max might overemphasize one strong match (e.g., price)
        # Let's try a simple average, but ensure brand match is prerequisite.
        if not scores:
            return 0.0 # No scores calculated (shouldn't happen if brand matches)

        # Simple average for now, consider weighted average later if needed
        final_score = sum(scores) / len(scores)

        # Ensure final score reflects the initial brand check pass
        final_score = min(final_score, 100.0) # Cap at 100

        # logger.debug(f"Match score for {title1} vs {title2}: {final_score:.2f} (Scores: {scores})")
        return final_score


    async def _get_products_by_platform(self, status: str = "ACTIVE") -> Dict[str, List[ProductDict]]:
        """
        Fetches product data relevant for matching, grouped by platform name.

        Retrieves core product details and attempts to get the actual listing
        price from platform-specific tables (eBay, Reverb, V&R). If platform
        price is unavailable, falls back to the product's base_price.

        Args:
            status: Filters products by the status field in the 'products' table.

        Returns:
            A dictionary where keys are platform names (str) and values are lists
            of product dictionaries (ProductDict), each containing fields like:
            'id', 'sku', 'brand', 'model', 'title', 'description', 'price',
            'base_price', 'platform_common_id', 'external_id'.
        """
        # This SQL query joins products with platform_common and then uses CTEs
        # and LEFT JOINs to fetch the primary price from each known platform-specific table.
        # It defaults to products.base_price if a platform-specific price isn't found.
        query = text("""
        WITH ebay_prices AS (
            -- Select price from ebay_listings linked via platform_common
            SELECT pc.id as platform_common_id, el.price
            FROM platform_common pc
            JOIN ebay_listings el ON pc.external_id = el.ebay_item_id -- Assuming external_id stores ebay_item_id for eBay
            WHERE pc.platform_name = 'ebay'
        ),
        reverb_prices AS (
            -- Select list_price from reverb_listings linked via platform_common
            SELECT pc.id as platform_common_id, rl.list_price -- Use list_price? or price? Adjust if needed
            FROM platform_common pc
            JOIN reverb_listings rl ON pc.external_id = rl.reverb_listing_id -- Assuming external_id stores reverb_listing_id
            WHERE pc.platform_name = 'reverb'
        ),
        vintageandrare_prices AS (
             -- Select relevant price from vr_listings linked via platform_common
            SELECT pc.id as platform_common_id, vl.price_notax -- Or vl.price? Adjust if needed
            FROM platform_common pc
            JOIN vr_listings vl ON pc.external_id = vl.vr_listing_id -- Assuming external_id stores vr_listing_id
            WHERE pc.platform_name = 'vintageandrare'
        )
        -- Add CTEs for other platforms (e.g., website_prices) if needed

        -- Main query joining products, platform_common, and the price CTEs
        SELECT
            p.id, p.sku, p.brand, p.model, p.description, p.base_price, -- Core product fields
            pc.platform_name, pc.id as platform_common_id, pc.external_id, -- Platform link fields
            -- Select the specific platform price if available, otherwise use product's base_price
            COALESCE(ep.price, rp.list_price, vp.price_notax, p.base_price) as actual_price
            -- Add other platform prices to COALESCE if needed, e.g., wsp.price
        FROM products p
        JOIN platform_common pc ON p.id = pc.product_id
        LEFT JOIN ebay_prices ep ON pc.id = ep.platform_common_id -- Use alias 'ep'
        LEFT JOIN reverb_prices rp ON pc.id = rp.platform_common_id -- Use alias 'rp'
        LEFT JOIN vintageandrare_prices vp ON pc.id = vp.platform_common_id -- Use alias 'vp'
        -- LEFT JOIN website_prices wsp ON pc.id = wsp.platform_common_id -- Example for website
        WHERE p.status = :status -- Filter by product status
        ORDER BY p.id, pc.platform_name; -- Consistent ordering
        """)

        logger.debug(f"Executing _get_products_by_platform with status: {status}")
        result = await self.db.execute(query, {"status": status})
        rows = result.mappings().fetchall() # Use mappings() for dict-like rows
        logger.debug(f"Fetched {len(rows)} product/platform rows")

        products_by_platform: Dict[str, List[ProductDict]] = {}
        for row in rows:
            platform = row['platform_name']
            if platform not in products_by_platform:
                products_by_platform[platform] = []

            # Create a simple title field from brand and model for matching consistency
            # Handle potential None values for brand/model
            brand = row.get('brand', '') or ''
            model = row.get('model', '') or ''
            title = f"{brand} {model}".strip()

            products_by_platform[platform].append({
                'id': row['id'],
                'sku': row['sku'],
                'external_id': row['external_id'],
                'brand': brand,
                'model': model,
                'title': title, # Generated title
                'description': row['description'],
                'price': row['actual_price'], # Use derived actual_price
                'base_price': row['base_price'], # Keep base_price for reference
                'platform_common_id': row['platform_common_id']
            })

        for platform, products in products_by_platform.items():
            logger.debug(f"Processed {len(products)} products for platform '{platform}'")

        return products_by_platform


    # --- Merge & Restore Methods ---

    async def merge_products(self, matches: List[Dict[str, Any]], merged_by: str = 'product_matcher') -> int:
        """
        Merges confirmed product matches into single canonical product records.

        For each match group:
        1. Selects one product record to keep (typically the first one).
        2. Updates the `product_id` in `platform_common` for all other matched
           products in the group to point to the kept product's ID.
        3. Updates any *other* `platform_common` records that might still point
           to a product being merged.
        4. Records the merge action in the `product_merges` table, storing
           the full data of the merged product as JSONB for potential restoration.
        5. Deletes the merged `products` records *only if* no `platform_common`
           records still reference them (as a safety check).

        WARNING: This operation modifies database records significantly (updates
        foreign keys, deletes rows). Ensure matches are accurately confirmed
        before running. Merges are recorded, and restoration is possible via
        `restore_merged_product`.

        Uses a separate database connection/session with AUTOCOMMIT isolation
        for each match to ensure atomicity per merge operation.

        Args:
            matches: A list of confirmed match dictionaries, typically the output
                     of `find_potential_match_groups` after review/confirmation.
                     Each dictionary should contain '<platform_name>_product': ProductDict pairs.
            merged_by: Identifier for who/what triggered the merge (optional).

        Returns:
            The number of matches successfully processed (merged or attempted). Errors are logged.
        """
        if not self._database_url:
            logger.error("Cannot perform merge: DATABASE_URL is not configured.")
            return 0

        merged_count = 0
        error_count = 0
        products_removed = 0

        # Create engine/session factory for merge operations
        # Using AUTOCOMMIT isolation might simplify error handling per match,
        # but consider if READ COMMITTED is sufficient with explicit rollbacks.
        try:
            engine = create_async_engine(self._database_url, isolation_level="AUTOCOMMIT") # Or READ COMMITTED
            async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        except Exception as e:
            logger.error(f"Failed to create engine/session for merging: {e}")
            return 0

        # Ensure product_merges table exists
        await self._ensure_product_merges_table(async_session_factory)

        # Process matches one at a time
        for match_index, match in enumerate(matches):
            # Use a separate session for each match attempt
            async with async_session_factory() as session:
                try:
                    # Identify products involved in this specific match
                    platforms: List[str] = []
                    products_in_match: Dict[str, ProductDict] = {}
                    for key, value in match.items():
                        if key.endswith('_product') and isinstance(value, dict):
                            platform = key.replace('_product', '')
                            platforms.append(platform)
                            products_in_match[platform] = value

                    if len(platforms) < 2:
                        logger.warning(f"Match {match_index+1}: Skipping, only one product found: {platforms}")
                        continue

                    # --- Begin Transaction for this merge ---
                    # If using READ COMMITTED, begin transaction explicitly
                    # async with session.begin(): # Use if not using AUTOCOMMIT

                    # Determine product to keep (e.g., first one) and products to merge
                    keep_platform = platforms[0]
                    keep_product = products_in_match[keep_platform]
                    keep_product_id = keep_product['id']
                    products_to_merge_ids: Set[int] = set()

                    logger.info(f"Match {match_index+1}: Keeping {keep_platform} product "
                                f"SKU='{keep_product['sku']}' (ID: {keep_product_id})")

                    # Identify IDs of products to be merged (excluding the kept one)
                    for merge_platform in platforms:
                        merge_product = products_in_match[merge_platform]
                        merge_product_id = merge_product['id']
                        if merge_product_id != keep_product_id:
                            products_to_merge_ids.add(merge_product_id)
                            logger.info(f"  -> Will merge {merge_platform} product "
                                        f"SKU='{merge_product['sku']}' (ID: {merge_product_id})")

                    if not products_to_merge_ids:
                        logger.info(f"Match {match_index+1}: No other products to merge with {keep_product_id}. Skipping.")
                        continue

                    # 1. Update platform_common FKs for directly matched items
                    for merge_platform in platforms:
                        merge_product = products_in_match[merge_platform]
                        merge_product_id = merge_product['id']
                        if merge_product_id != keep_product_id: # Only update those being merged
                            pc_id = merge_product['platform_common_id']
                            logger.debug(f"Updating platform_common ID {pc_id} "
                                        f"to product_id {keep_product_id}")
                            update_pc_query = text("""
                                UPDATE platform_common SET product_id = :keep_id
                                WHERE id = :pc_id AND product_id != :keep_id
                            """)
                            await session.execute(update_pc_query, {
                                "keep_id": keep_product_id, "pc_id": pc_id
                            })


                    # 2. Update any *other* platform_common records pointing to products being merged
                    if products_to_merge_ids:
                        update_other_pc_query = text(f"""
                            UPDATE platform_common SET product_id = :keep_id
                            WHERE product_id = ANY(ARRAY[{",".join(map(str, products_to_merge_ids))}])
                            AND product_id != :keep_id
                        """)
                        update_result = await session.execute(update_other_pc_query, {"keep_id": keep_product_id})
                        logger.debug(f"Updated {update_result.rowcount} other platform_common records "
                                    f"pointing to merged products.")

                    # 3. Record merges and delete merged products
                    successful_deletes = 0
                    for product_id in products_to_merge_ids:
                        # 3a. Get full data and record merge
                        product_data_json = await self._get_product_json_for_merge(session, product_id)
                        if product_data_json:
                            await self._record_merge(session, keep_product_id, product_id, product_data_json, merged_by)
                        else:
                            logger.warning(f"Could not fetch data for merged product {product_id}. Skipping merge record.")
                            # Decide whether to proceed with deletion without history? Risky.
                            # continue # Skip deletion if we can't record it?

                        # 3b. Check for remaining references (safety check)
                        ref_count = await self._count_product_references(session, product_id)
                        logger.debug(f"Product {product_id} has {ref_count} platform_common references after updates.")

                        # 3c. Delete product if no references remain
                        if ref_count == 0:
                            logger.info(f"Deleting product {product_id} (no references)")
                            delete_query = text("DELETE FROM products WHERE id = :pid")
                            delete_result = await session.execute(delete_query, {"pid": product_id})
                            if delete_result.rowcount > 0:
                                products_removed += 1
                                successful_deletes += 1
                                logger.debug(f"Deleted product {product_id}")
                            else:
                                logger.warning(f"Attempted to delete product {product_id}, but no rows affected.")
                        else:
                            # Log details of remaining references
                            ref_details = await self._get_reference_details(session, product_id)
                            logger.warning(f"CANNOT delete product {product_id} - {ref_count} references remain: {ref_details}")

                    # If using READ COMMITTED, commit transaction here
                    # await session.commit() # Use if not using AUTOCOMMIT
                    merged_count += 1
                    logger.info(f"Successfully processed merge for match {match_index+1}")

                except Exception as e:
                    # If using READ COMMITTED, rollback would happen automatically with session.begin() context manager
                    error_count += 1
                    logger.error(f"Error processing merge for match {match_index+1}: {e}")
                    logger.error(traceback.format_exc())
                    # await session.rollback() # Use if not using AUTOCOMMIT or session.begin()

        # Clean up the engine
        await engine.dispose()

        logger.info(f"Merge process complete. Processed: {merged_count} matches. "
                    f"Errors: {error_count}. Products Removed: {products_removed}.")
        return merged_count

    async def _ensure_product_merges_table(self, session_factory):
        """Checks if product_merges table exists and creates it if not."""
        async with session_factory() as session:
            try:
                check_table_query = text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = current_schema() -- More robust check
                        AND table_name = 'product_merges'
                    );
                """)
                result = await session.execute(check_table_query)
                table_exists = result.scalar()

                if not table_exists:
                    logger.info("Creating 'product_merges' table for merge history.")
                    create_table_query = text("""
                        CREATE TABLE product_merges (
                            id SERIAL PRIMARY KEY,
                            kept_product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE, -- Or SET NULL?
                            merged_product_id INTEGER NOT NULL, -- Cannot be FK as product is deleted
                            merged_product_data JSONB, -- Store original data
                            merged_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT clock_timestamp(), -- Use timestamptz
                            merged_by VARCHAR(255),
                            reason VARCHAR(255) DEFAULT 'Product matching tool'
                        );
                        CREATE INDEX IF NOT EXISTS idx_product_merges_kept_id ON product_merges(kept_product_id);
                        CREATE INDEX IF NOT EXISTS idx_product_merges_merged_id ON product_merges(merged_product_id);
                    """)
                    await session.execute(create_table_query)
                    await session.commit() # Commit table creation separately
            except Exception as e:
                logger.error(f"Error checking/creating product_merges table: {e}", exc_info=True)
                raise # Re-raise to stop the merge process if table creation fails

    async def _get_product_json_for_merge(self, session: AsyncSession, product_id: int) -> Optional[str]:
        """Fetches the full product data as JSON for archival."""
        try:
            product_query = text("SELECT row_to_json(p) FROM products p WHERE p.id = :pid")
            result = await session.execute(product_query, {"pid": product_id})
            product_data = result.scalar() # Returns a dict representing the JSON
            return json.dumps(product_data) if product_data else None
        except Exception as e:
            logger.error(f"Error fetching JSON data for product {product_id}: {e}")
            return None

    async def _record_merge(self, session: AsyncSession, kept_id: int, merged_id: int, product_data_json: str, merged_by: str):
        """Inserts a record into the product_merges table."""
        try:
            merge_query = text("""
                INSERT INTO product_merges
                (kept_product_id, merged_product_id, merged_product_data, merged_by)
                VALUES (:kept_id, :merged_id, CAST(:p_data AS JSONB), :m_by)
            """)
            # VALUES (:kept_id, :merged_id, :p_data::jsonb, :m_by) -- Cast to JSONB
            await session.execute(merge_query, {
                "kept_id": kept_id,
                "merged_id": merged_id,
                "p_data": product_data_json,
                "m_by": merged_by
            })
            logger.debug(f"Recorded merge: Kept {kept_id}, Merged {merged_id}")
        except Exception as e:
            logger.error(f"Error recording merge (Kept {kept_id}, Merged {merged_id}): {e}")
            # Consider re-raising if recording failure should halt the process

    async def _count_product_references(self, session: AsyncSession, product_id: int) -> int:
        """Counts references to a product ID in platform_common."""
        try:
            check_query = text("SELECT COUNT(*) FROM platform_common WHERE product_id = :pid")
            result = await session.execute(check_query, {"pid": product_id})
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error counting references for product {product_id}: {e}")
            return -1 # Indicate error

    async def _get_reference_details(self, session: AsyncSession, product_id: int) -> str:
        """Gets details of platform_common records referencing a product."""
        try:
            ref_details_query = text("""
                SELECT platform_name, external_id FROM platform_common WHERE product_id = :pid
            """)
            refs = await session.execute(ref_details_query, {"pid": product_id})
            ref_rows = refs.mappings().fetchall()
            return ", ".join([f"{r['platform_name']}:{r['external_id']}" for r in ref_rows])
        except Exception as e:
            logger.error(f"Error getting reference details for product {product_id}: {e}")
            return "Error fetching details"


    async def restore_merged_product(self, merged_product_id: int, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Restores a previously merged product using data from the merge history.

        1. Finds the latest merge record for the `merged_product_id`.
        2. Checks if a product with this ID already exists (no need to restore).
        3. If not, re-inserts the product using the `merged_product_data` JSONB.
        4. Logs the restoration action in a hypothetical `restoration_log` table.
        5. Returns potential `platform_common` records currently linked to the
           product it was merged *into*, allowing the user to decide which ones
           to re-associate via `restore_platform_common`.

        Uses a separate database connection/session.

        Args:
            merged_product_id: The original ID of the product that was merged and deleted.
            reason: Optional reason for the restoration.

        Returns:
            A dictionary containing restoration status information:
            {
                "merged_product_id": int,
                "success": bool,
                "kept_product_id": Optional[int], # ID it was merged into
                "restored_product_id": Optional[int], # ID of the newly inserted product row
                "message": str,
                "potential_platform_common": Optional[List[Dict]] # Records to potentially re-link
            }
        """
        if not self._database_url:
            logger.error("Cannot perform restore: DATABASE_URL is not configured.")
            return {"success": False, "message": "Database URL not configured."}

        logger.info(f"Attempting restoration of original product ID {merged_product_id}")
        restoration_info: Dict[str, Any] = {
            "merged_product_id": merged_product_id, "success": False,
            "kept_product_id": None, "restored_product_id": None,
            "message": "", "potential_platform_common": None
        }

        try:
            engine = create_async_engine(self._database_url, isolation_level="READ COMMITTED") # Use standard isolation
            async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        except Exception as e:
            restoration_info["message"] = f"Failed to create engine/session for restoration: {e}"
            logger.error(restoration_info["message"])
            return restoration_info

        async with async_session_factory() as session:
            try:
                async with session.begin(): # Use transaction
                    # 1. Find the latest merge record for this product ID
                    # Assuming merged_product_id is the ID that was deleted
                    merge_query = text("""
                        SELECT kept_product_id, merged_product_data, merged_at
                        FROM product_merges
                        WHERE merged_product_id = :pid
                        ORDER BY merged_at DESC
                        LIMIT 1
                    """)
                    merge_result = await session.execute(merge_query, {"pid": merged_product_id})
                    merge_record = merge_result.fetchone()

                    if not merge_record or not merge_record.merged_product_data:
                        restoration_info["message"] = f"No merge record with data found for original product ID {merged_product_id}"
                        logger.warning(restoration_info["message"])
                        # No rollback needed as it's read-only so far
                        return restoration_info # Exit transaction context

                    kept_product_id = merge_record.kept_product_id
                    merged_product_data = merge_record.merged_product_data # This is already JSON(B) from DB
                    merge_timestamp = merge_record.merged_at
                    restoration_info["kept_product_id"] = kept_product_id

                    # 2. Check if the product ID is already in use (e.g., manually recreated?)
                    # Use the original ID for the check
                    check_query = text("SELECT EXISTS (SELECT 1 FROM products WHERE id = :pid)")
                    check_result = await session.execute(check_query, {"pid": merged_product_id})
                    product_exists = check_result.scalar()

                    if product_exists:
                        restoration_info["message"] = f"Product ID {merged_product_id} already exists in products table. Cannot restore."
                        logger.warning(restoration_info["message"])
                        return restoration_info

                    # 3. Restore product using saved JSON data
                    # IMPORTANT: This assumes the structure in merged_product_data is compatible
                    # with the current products table schema. May fail if schema evolved.
                    # Also, this re-inserts using the *original* ID. This requires the ID sequence
                    # to allow specifying IDs or the ID to be available. Alternatively, insert
                    # without specifying ID and get a *new* ID, which is safer but changes the ID.
                    # Let's try inserting with the original ID if possible.
                    # We need the original JSON data as a string for json_populate_record
                    try:
                        if isinstance(merged_product_data, dict):
                           merged_product_data_str = json.dumps(merged_product_data)
                        else: # Assume it's already a string representation
                           merged_product_data_str = str(merged_product_data)

                        # Attempt to insert using the original ID from the JSON data
                        # Ensure 'id' field exists and matches merged_product_id
                        if merged_product_data.get('id') != merged_product_id:
                             raise ValueError(f"ID mismatch in merge data: expected {merged_product_id}, got {merged_product_data.get('id')}")

                        restore_query = text("""
                            INSERT INTO products SELECT * FROM jsonb_populate_record(null::products, :p_data::jsonb);
                        """)
                        # json_populate_record uses the types and defaults from the 'products' table definition
                        # It will use the 'id' from the JSON data if present.
                        await session.execute(restore_query, {"p_data": merged_product_data_str})
                        # Since we specified the ID via the JSON, the ID is merged_product_id
                        restored_id = merged_product_id

                    except Exception as insert_err:
                         # If inserting with original ID fails (e.g., sequence issues, constraint violations)
                         # Log the error and potentially try inserting without ID to get a new one (less ideal)
                         logger.error(f"Failed to restore product {merged_product_id} with original ID: {insert_err}. Aborting.")
                         # Consider alternative strategy here if needed
                         raise # Re-raise to trigger rollback

                    restoration_info["restored_product_id"] = restored_id
                    logger.info(f"Restored product with original ID {restored_id}")

                    # 4. Log the restoration action (Example - adapt to your logging table)
                    # await self._log_restoration(session, restored_id, kept_product_id, merged_product_id, reason, merge_timestamp)


                    # 5. Identify potential platform_common records to re-link
                    # These are records currently pointing to the product it was merged INTO
                    pc_records_query = text("""
                        SELECT pc.id, pc.platform_name, pc.external_id,
                               pc.listing_data->>'title' as title, -- Example: Get title if stored
                               pc.created_at
                        FROM platform_common pc
                        WHERE pc.product_id = :kept_id
                        ORDER BY pc.platform_name
                    """)
                    pc_result = await session.execute(pc_records_query, {"kept_id": kept_product_id})
                    pc_records = pc_result.mappings().fetchall()

                    restoration_info["potential_platform_common"] = [dict(row) for row in pc_records]
                    restoration_info["success"] = True
                    restoration_info["message"] = (f"Product {restored_id} restored successfully. "
                                                  f"Review potential platform_common records to re-link.")

            except Exception as e:
                # Rollback will happen automatically via session.begin() context manager
                error_msg = f"Error during restore transaction for original product {merged_product_id}: {e}"
                logger.error(error_msg, exc_info=True)
                restoration_info["message"] = error_msg
                restoration_info["success"] = False # Ensure success is false on error

        await engine.dispose()
        return restoration_info


    async def restore_platform_common(self, restored_product_id: int, platform_common_ids: List[int]) -> Dict[str, Any]:
        """
        Updates specified platform_common records to point to a restored product.

        Should be called after `restore_merged_product` based on user selection
        of which platform listings belong to the restored product.

        Uses a separate database connection/session.

        Args:
            restored_product_id: The ID of the product that was restored.
            platform_common_ids: A list of `platform_common.id` values to update.

        Returns:
            A dictionary containing the status:
            {
                "restored_product_id": int,
                "success": bool,
                "restored_count": int,
                "message": str
            }
        """
        if not self._database_url:
            logger.error("Cannot restore platform_common: DATABASE_URL is not configured.")
            return {"success": False, "message": "Database URL not configured.", "restored_count": 0}
        if not platform_common_ids:
            logger.warning("No platform_common IDs provided for restoration.")
            return {"success": True, "message": "No IDs provided.", "restored_count": 0}

        logger.info(f"Attempting to link {len(platform_common_ids)} platform_common records "
                    f"to restored product {restored_product_id}")
        result_info: Dict[str, Any] = {
            "restored_product_id": restored_product_id, "success": False,
            "restored_count": 0, "message": ""
        }

        try:
            engine = create_async_engine(self._database_url, isolation_level="READ COMMITTED")
            async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        except Exception as e:
            result_info["message"] = f"Failed to create engine/session for restoration: {e}"
            logger.error(result_info["message"])
            return result_info

        async with async_session_factory() as session:
            try:
                async with session.begin(): # Use transaction
                    # 1. Verify the restored product exists
                    check_query = text("SELECT EXISTS (SELECT 1 FROM products WHERE id = :pid)")
                    check_result = await session.execute(check_query, {"pid": restored_product_id})
                    if not check_result.scalar():
                        result_info["message"] = f"Restored Product ID {restored_product_id} does not exist."
                        logger.warning(result_info["message"])
                        return result_info # Rollback happens automatically

                    # 2. Update the specified platform_common records
                    # Use IN operator - ensure list is not empty
                    pc_ids_tuple = tuple(platform_common_ids) # Use tuple for SQL parameter
                    update_query = text("""
                        UPDATE platform_common
                        SET product_id = :restored_pid
                        WHERE id = ANY(ARRAY[:pc_ids]::integer[]) -- Use ANY with array for safety/performance
                        RETURNING id -- Return updated IDs to confirm count
                    """)
                    # Example using ANY(ARRAY[:pc_ids])

                    update_result = await session.execute(update_query, {
                        "restored_pid": restored_product_id,
                        "pc_ids": list(pc_ids_tuple) # Pass as list for asyncpg array binding
                    })
                    updated_ids = update_result.scalars().fetchall()
                    restored_count = len(updated_ids)

                    result_info["restored_count"] = restored_count

                    # 3. Log the platform_common restoration action (optional)
                    # await self._log_platform_common_restoration(session, restored_product_id, updated_ids)

                    result_info["success"] = True
                    result_info["message"] = f"Successfully linked {restored_count} platform_common records to product {restored_product_id}."
                    logger.info(result_info["message"])

            except Exception as e:
                 # Rollback happens automatically
                error_msg = f"Error during platform_common restore transaction for product {restored_product_id}: {e}"
                logger.error(error_msg, exc_info=True)
                result_info["message"] = error_msg
                result_info["success"] = False
                result_info["restored_count"] = 0

        await engine.dispose()
        return result_info

    # --- Progress Saving/Loading Methods ---

    async def save_progress(self, confirmed_matches: List[Dict[str, Any]], processed_pairs: Set[Tuple[Any, ...]], filename: str = "product_matching_progress.json"):
        """
        Saves confirmed matches and processed pairs to a JSON file.

        Useful for pausing and resuming an interactive matching workflow.

        Args:
            confirmed_matches: List of match dictionaries that have been confirmed.
            processed_pairs: A set of tuples representing pairs already processed/reviewed.
            filename: The name of the file to save progress to.
        """
        logger.info(f"Saving progress to {filename}...")
        # Convert set of tuples to list of lists for JSON serialization
        serializable_pairs = [list(pair) for pair in processed_pairs]

        progress_data = {
            'confirmed_matches': confirmed_matches,
            'processed_pairs': serializable_pairs
            # Consider adding timestamp, other metadata
        }

        backup_filename = filename + ".bak"
        try:
            # Simple backup: rename existing file
            if os.path.exists(filename):
                os.replace(filename, backup_filename) # More atomic than rename on some OS
                logger.debug(f"Created backup: {backup_filename}")

            with open(filename, 'w') as f:
                json.dump(progress_data, f, indent=2, default=str) # Use indent, default=str for datetime etc.

            logger.info(f"Progress saved: {len(confirmed_matches)} confirmed matches, "
                        f"{len(processed_pairs)} processed pairs")

            # Optionally remove backup after successful save
            # if os.path.exists(backup_filename):
            #     os.remove(backup_filename)

        except Exception as e:
            logger.error(f"Error saving progress to {filename}: {e}", exc_info=True)
            # Attempt to restore backup if save failed?
            # if os.path.exists(backup_filename):
            #     try:
            #         os.replace(backup_filename, filename)
            #         logger.info("Restored backup file after save error.")
            #     except Exception as restore_e:
            #         logger.error(f"Failed to restore backup file: {restore_e}")


    async def load_progress(self, filename: str = "product_matching_progress.json") -> Tuple[List[Dict[str, Any]], Set[Tuple[Any, ...]]]:
        """
        Loads confirmed matches and processed pairs from a JSON file.

        Args:
            filename: The name of the file to load progress from.

        Returns:
            A tuple containing:
            - List of confirmed matches.
            - Set of processed pairs (as tuples).
            Returns empty list and empty set if the file doesn't exist or fails to load.
        """
        logger.info(f"Loading progress from {filename}...")
        if not os.path.exists(filename):
            logger.warning(f"Progress file '{filename}' not found. Starting fresh.")
            return [], set()

        try:
            with open(filename, 'r') as f:
                progress_data = json.load(f)

            confirmed_matches = progress_data.get('confirmed_matches', [])

            # Convert list of lists back to set of tuples
            processed_pairs_list = progress_data.get('processed_pairs', [])
            processed_pairs = set(tuple(pair) for pair in processed_pairs_list if isinstance(pair, list))

            logger.info(f"Loaded progress: {len(confirmed_matches)} confirmed matches, "
                        f"{len(processed_pairs)} processed pairs")
            return confirmed_matches, processed_pairs
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from progress file '{filename}': {e}. Starting fresh.", exc_info=True)
            # Optionally try loading the backup file if JSON is corrupt
            # backup_filename = filename + ".bak"
            # if os.path.exists(backup_filename): ... attempt load from backup ...
            return [], set()
        except Exception as e:
            logger.error(f"Error loading progress from '{filename}': {e}. Starting fresh.", exc_info=True)
            return [], set()
