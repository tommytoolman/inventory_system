# # app/cli/match_products.py
# import asyncio
# import logging
# import click
# from datetime import datetime
# from sqlalchemy import text
# from sqlalchemy.ext.asyncio import AsyncSession
# from app.database import async_session
# from sklearn.feature_extraction.text import TfidfVectorizer
# from sklearn.metrics.pairwise import cosine_similarity
# import pandas as pd
# import numpy as np

# logger = logging.getLogger(__name__)

# @click.command()
# @click.option('--threshold', default=0.7, help='Similarity threshold (0.0-1.0)')
# @click.option('--limit', default=1000, help='Maximum number of products to process')
# @click.option('--platform1', default='ebay', help='First platform to match')
# @click.option('--platform2', default='vintageandrare', help='Second platform to match')
# @click.option('--commit', is_flag=True, help='Commit matches to database')
# def match_products(threshold, limit, platform1, platform2, commit):
#     """Find and match similar products across platforms"""
#     logging.basicConfig(level=logging.INFO)
    
#     start_time = datetime.now()
#     logger.info(f"Starting product matching at {start_time}")
    
#     try:
#         asyncio.run(run_matching(threshold, limit, platform1, platform2, commit))
        
#         end_time = datetime.now()
#         duration = end_time - start_time
#         logger.info(f"Completed matching in {duration}")
#     except Exception as e:
#         logger.exception("Error during product matching")
#         click.echo(f"Error: {str(e)}")

# async def run_matching(threshold, limit, platform1, platform2, commit):
#     """Run the product matching process"""
#     async with async_session() as session:
#         # 1. Load products from both platforms
#         platform1_products = await get_platform_products(session, platform1, limit)
#         platform2_products = await get_platform_products(session, platform2, limit)
        
#         logger.info(f"Loaded {len(platform1_products)} products from {platform1}")
#         logger.info(f"Loaded {len(platform2_products)} products from {platform2}")
        
#         if not platform1_products or not platform2_products:
#             logger.warning("Not enough products to compare")
#             return
        
#         # 2. Find potential matches
#         matches = find_potential_matches(platform1_products, platform2_products, threshold)
        
#         logger.info(f"Found {len(matches)} potential matches above threshold {threshold}")
        
#         # 3. Display matches for manual verification
#         for i, match in enumerate(matches):
#             score, product1, product2 = match
#             print(f"\nPotential Match #{i+1} (score: {score:.2f}):")
#             print(f"  {platform1.upper()}: {product1['sku']} - {product1['brand']} {product1['model']} ({product1['year']})")
#             print(f"  {platform2.upper()}: {product2['sku']} - {product2['brand']} {product2['model']} ({product2['year']})")
            
#             if commit:
#                 verified = click.confirm("Confirm this match?", default=True)
#                 if verified:
#                     await create_product_mapping(session, product1['id'], product2['id'], score, 'algorithm')
#                     click.echo("Match recorded ✓")
        
#         # If commit flag not set, just show summary
#         if not commit:
#             logger.info("Dry run completed - matches not committed to database")
#             logger.info("Use --commit flag to save matches")

# async def get_platform_products(session: AsyncSession, platform_name: str, limit: int):
#     """Get products from a specific platform"""
#     stmt = text("""
#         SELECT 
#             p.id, p.sku, p.brand, p.model, p.year, p.category, p.base_price, 
#             p.description, pc.external_id
#         FROM products p
#         JOIN platform_common pc ON p.id = pc.product_id
#         WHERE pc.platform_name = :platform
#         LIMIT :limit
#     """)
    
#     result = await session.execute(stmt, {"platform": platform_name, "limit": limit})
    
#     products = []
#     for row in result.fetchall():
#         products.append({
#             "id": row[0],
#             "sku": row[1],
#             "brand": row[2] or "",
#             "model": row[3] or "",
#             "year": row[4] or "",
#             "category": row[5] or "",
#             "price": row[6] or 0,
#             "description": row[7] or "",
#             "external_id": row[8] or "",
#             # Create a combined text field for matching
#             "text": f"{row[2] or ''} {row[3] or ''} {row[5] or ''}"
#         })
    
#     return products

# def find_potential_matches(products1, products2, threshold):
#     """Find potential matches between two sets of products using TF-IDF"""
#     # Extract text for vectorization
#     texts1 = [p["text"] for p in products1]
#     texts2 = [p["text"] for p in products2]
    
#     # Create TF-IDF matrix
#     vectorizer = TfidfVectorizer(min_df=1, analyzer='word', 
#                                 ngram_range=(1, 2), stop_words='english')
    
#     tfidf1 = vectorizer.fit_transform(texts1)
#     tfidf2 = vectorizer.transform(texts2)
    
#     # Calculate cosine similarity
#     cosine_similarities = cosine_similarity(tfidf1, tfidf2)
    
#     # Find potential matches
#     matches = []
#     for i, similarities in enumerate(cosine_similarities):
#         best_match_idx = np.argmax(similarities)
#         score = similarities[best_match_idx]
        
#         if score >= threshold:
#             matches.append((score, products1[i], products2[best_match_idx]))
    
#     # Sort by score (highest first)
#     matches.sort(reverse=True, key=lambda x: x[0])
    
#     return matches

# async def create_product_mapping(session: AsyncSession, product1_id, product2_id, confidence, method):
#     """Create a mapping between two products"""
#     # Ensure product1_id is the lower value to maintain consistency
#     master_id = min(product1_id, product2_id)
#     related_id = max(product1_id, product2_id)
    
#     # Check if mapping already exists
#     stmt = text("""
#         SELECT id FROM product_mappings 
#         WHERE master_product_id = :master_id AND related_product_id = :related_id
#     """)
    
#     result = await session.execute(stmt, {
#         "master_id": master_id, 
#         "related_id": related_id
#     })
    
#     existing = result.scalar()
    
#     if existing:
#         logger.info(f"Mapping already exists with ID: {existing}")
#         return existing
    
#     # Create new mapping
#     stmt = text("""
#         INSERT INTO product_mappings (
#             master_product_id, related_product_id, match_confidence, match_method, created_at
#         ) VALUES (
#             :master_id, :related_id, :confidence, :method, NOW()
#         ) RETURNING id
#     """)
    
#     result = await session.execute(stmt, {
#         "master_id": master_id,
#         "related_id": related_id,
#         "confidence": confidence,
#         "method": method
#     })
    
#     mapping_id = result.scalar()
#     await session.commit()
    
#     logger.info(f"Created new product mapping with ID: {mapping_id}")
#     return mapping_id

# if __name__ == "__main__":
#     match_products()

# app/cli/match_products.py
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

from app.tools.product_matcher import ProductMatcher

load_dotenv()

async def main():
    # Create database connection
    db_url = os.environ.get('DATABASE_URL')
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        matcher = ProductMatcher(session)
        
        # Load previous progress
        confirmed_matches, processed_pairs = await matcher.load_progress()
        
        while True:
            # Display main menu
            print("\n" + "="*80)
            print("PRODUCT MATCHER MENU")
            print("="*80)
            print("1. Find new matches to review")
            print("2. Show pending confirmed matches")
            print("3. Edit confirmed matches")
            print("4. Commit confirmed matches to database")
            print("5. Exit (without committing)")
            print("="*80)
            
            choice = input("Enter your choice (1-5): ")
            
            if choice == "1":
                # Find and review new matches
                await find_and_review_matches(matcher, confirmed_matches, processed_pairs)
            
            elif choice == "2":
                # Show matches waiting to be committed
                show_pending_matches(confirmed_matches)
            
            elif choice == "3":
                # Edit confirmed matches
                await edit_confirmed_matches(matcher, confirmed_matches)
            
            elif choice == "4":
                # Commit confirmed matches to database
                if confirmed_matches:
                    print(f"\nCommitting {len(confirmed_matches)} confirmed matches to database...")
                    merged = await matcher.merge_products(confirmed_matches)
                    print(f"Successfully merged {merged} products.")
                    # Clear confirmed matches after processing
                    confirmed_matches = []
                    await matcher.save_progress(confirmed_matches, processed_pairs)
                else:
                    print("No confirmed matches to commit.")
            
            elif choice == "5":
                # Save progress and exit
                await matcher.save_progress(confirmed_matches, processed_pairs)
                print("Progress saved. Exiting without committing changes.")
                break
            
            else:
                print("Invalid choice. Please try again.")

async def find_and_review_matches(matcher, confirmed_matches, processed_pairs):
    """Find and review new matches"""
    # Get available platforms
    platforms_data = await matcher._get_products_by_platform()
    available_platforms = list(platforms_data.keys())
    
    print(f"Available platforms: {', '.join(available_platforms)}")
    
    # Choose platforms to compare
    platform1 = input(f"First platform (default: {available_platforms[0]}): ").lower() or available_platforms[0]
    platform2 = input(f"Second platform (default: {available_platforms[1]}): ").lower() or available_platforms[1]
    
    # Set minimum confidence threshold
    min_confidence = int(input("Minimum confidence threshold (1-100, default: 85): ") or "85")
    
    # Find potential matches
    print(f"Finding potential matches between {platform1} and {platform2}...")
    matches = await matcher.find_potential_matches(min_confidence=min_confidence, 
                                             platform1=platform1, 
                                             platform2=platform2)
    
    # Filter out already processed matches
    new_matches = []
    for match in matches:
        match_key = (match[f'{platform1}_product']['id'], match[f'{platform2}_product']['id'])
        if match_key not in processed_pairs:
            new_matches.append(match)
    
    if not new_matches:
        print("No new potential matches found!")
        return
        
    print(f"Found {len(new_matches)} new potential matches.")
    
    # Interactive review
    for i, match in enumerate(new_matches):
        product1 = match[f'{platform1}_product']
        product2 = match[f'{platform2}_product']
        confidence = match['confidence']
        
        print("\n" + "="*80)
        print(f"Match {i+1}/{len(new_matches)} (Confidence: {confidence}%)")
        print("-"*80)
        
        # Display match details
        price1 = f"£{product1['price']:,.0f}" if product1.get('price') else "No price"
        print(f"{platform1.upper()}: [{product1['sku']}] {product1['title']} - {price1}")
        print(f"Brand: {product1['brand']}, Model: {product1['model']}")
        
        print("-"*80)
        
        price2 = f"£{product2['price']:,.0f}" if product2.get('price') else "No price"
        print(f"{platform2.upper()}: [{product2['sku']}] {product2['title']} - {price2}")
        print(f"Brand: {product2['brand']}, Model: {product2['model']}")
        
        print("="*80)
        
        # Expanded options for input
        print("Options: y (confirm), n (reject), s (save & quit), b (back), q (quit without saving)")
        choice = input("Your choice: ").lower()
        
        # Mark as processed regardless of choice
        prod1_id = product1['id']
        prod2_id = product2['id']
        
        if choice == 's':
            # Save progress and quit
            processed_pairs.add((prod1_id, prod2_id))
            await matcher.save_progress(confirmed_matches, processed_pairs)
            return
        elif choice == 'q':
            # Quit without saving this pair
            return
        elif choice == 'b' and i > 0:
            # Go back to previous match (if not the first one)
            i -= 2  # Will be incremented by the loop, net -1
            continue
        elif choice == 'y':
            # Confirm match
            processed_pairs.add((prod1_id, prod2_id))
            match['platforms'] = [platform1, platform2]  # Store platforms for later use
            confirmed_matches.append(match)
            # Save after each confirmation
            await matcher.save_progress(confirmed_matches, processed_pairs)
        else:
            # Default to rejecting
            processed_pairs.add((prod1_id, prod2_id))
            await matcher.save_progress(confirmed_matches, processed_pairs)

def show_pending_matches(confirmed_matches):
    """Display matches waiting to be committed"""
    if not confirmed_matches:
        print("No confirmed matches pending database commit.")
        return
        
    print(f"\nYou have {len(confirmed_matches)} confirmed matches waiting to be committed:")
    
    for i, match in enumerate(confirmed_matches):
        # Get the platform names from the match object
        platforms = match.get('platforms', [])
        if not platforms:
            # If platforms not stored, extract from keys
            platforms = [k.replace('_product', '') for k in match.keys() if k.endswith('_product')]
        
        print(f"\nMatch {i+1}:")
        for platform in platforms:
            if f'{platform}_product' in match:
                product = match[f'{platform}_product']
                price = f"£{product['price']:,.0f}" if product.get('price') else "No price"
                print(f"  {platform.upper()}: {product['sku']} - {product['title']} - {price}")
    
    print("\nUse 'Commit confirmed matches' to apply these changes to the database.")

async def edit_confirmed_matches(matcher, confirmed_matches):
    """Review and edit previously confirmed matches"""
    if not confirmed_matches:
        print("No confirmed matches to edit.")
        return
    
    while True:
        # Display the confirmed matches
        show_pending_matches(confirmed_matches)
        
        print("\nEdit Options:")
        print("  number: Select a match to remove (e.g., '3' to remove match #3)")
        print("  c: Clear all confirmed matches")
        print("  q: Return to main menu")
        
        choice = input("\nYour choice: ").lower()
        
        if choice == 'q':
            break
        elif choice == 'c':
            if input("Are you sure you want to clear ALL confirmed matches? (y/n): ").lower() == 'y':
                confirmed_matches.clear()
                await matcher.save_progress(confirmed_matches, set())
                print("All confirmed matches cleared.")
                break
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(confirmed_matches):
                    match = confirmed_matches[idx]
                    
                    # Print match details
                    platforms = match.get('platforms', [])
                    if not platforms:
                        platforms = [k.replace('_product', '') for k in match.keys() if k.endswith('_product')]
                    
                    print(f"\nRemoving match {idx+1}:")
                    for platform in platforms:
                        if f'{platform}_product' in match:
                            product = match[f'{platform}_product']
                            print(f"  {platform.upper()}: {product['sku']} - {product['title']}")
                    
                    if input("Are you sure you want to remove this match? (y/n): ").lower() == 'y':
                        confirmed_matches.pop(idx)
                        await matcher.save_progress(confirmed_matches, set())
                        print("Match removed.")
                else:
                    print("Invalid match number.")
            except ValueError:
                print("Invalid input. Please enter a number, 'c', or 'q'.")

if __name__ == "__main__":
    asyncio.run(main())