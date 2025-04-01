# app/cli/match_products.py
import asyncio
import logging
import click
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import async_session
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

@click.command()
@click.option('--threshold', default=0.7, help='Similarity threshold (0.0-1.0)')
@click.option('--limit', default=1000, help='Maximum number of products to process')
@click.option('--platform1', default='ebay', help='First platform to match')
@click.option('--platform2', default='vintageandrare', help='Second platform to match')
@click.option('--commit', is_flag=True, help='Commit matches to database')
def match_products(threshold, limit, platform1, platform2, commit):
    """Find and match similar products across platforms"""
    logging.basicConfig(level=logging.INFO)
    
    start_time = datetime.now()
    logger.info(f"Starting product matching at {start_time}")
    
    try:
        asyncio.run(run_matching(threshold, limit, platform1, platform2, commit))
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed matching in {duration}")
    except Exception as e:
        logger.exception("Error during product matching")
        click.echo(f"Error: {str(e)}")

async def run_matching(threshold, limit, platform1, platform2, commit):
    """Run the product matching process"""
    async with async_session() as session:
        # 1. Load products from both platforms
        platform1_products = await get_platform_products(session, platform1, limit)
        platform2_products = await get_platform_products(session, platform2, limit)
        
        logger.info(f"Loaded {len(platform1_products)} products from {platform1}")
        logger.info(f"Loaded {len(platform2_products)} products from {platform2}")
        
        if not platform1_products or not platform2_products:
            logger.warning("Not enough products to compare")
            return
        
        # 2. Find potential matches
        matches = find_potential_matches(platform1_products, platform2_products, threshold)
        
        logger.info(f"Found {len(matches)} potential matches above threshold {threshold}")
        
        # 3. Display matches for manual verification
        for i, match in enumerate(matches):
            score, product1, product2 = match
            print(f"\nPotential Match #{i+1} (score: {score:.2f}):")
            print(f"  {platform1.upper()}: {product1['sku']} - {product1['brand']} {product1['model']} ({product1['year']})")
            print(f"  {platform2.upper()}: {product2['sku']} - {product2['brand']} {product2['model']} ({product2['year']})")
            
            if commit:
                verified = click.confirm("Confirm this match?", default=True)
                if verified:
                    await create_product_mapping(session, product1['id'], product2['id'], score, 'algorithm')
                    click.echo("Match recorded ✓")
        
        # If commit flag not set, just show summary
        if not commit:
            logger.info("Dry run completed - matches not committed to database")
            logger.info("Use --commit flag to save matches")

async def get_platform_products(session: AsyncSession, platform_name: str, limit: int):
    """Get products from a specific platform"""
    stmt = text("""
        SELECT 
            p.id, p.sku, p.brand, p.model, p.year, p.category, p.base_price, 
            p.description, pc.external_id
        FROM products p
        JOIN platform_common pc ON p.id = pc.product_id
        WHERE pc.platform_name = :platform
        LIMIT :limit
    """)
    
    result = await session.execute(stmt, {"platform": platform_name, "limit": limit})
    
    products = []
    for row in result.fetchall():
        products.append({
            "id": row[0],
            "sku": row[1],
            "brand": row[2] or "",
            "model": row[3] or "",
            "year": row[4] or "",
            "category": row[5] or "",
            "price": row[6] or 0,
            "description": row[7] or "",
            "external_id": row[8] or "",
            # Create a combined text field for matching
            "text": f"{row[2] or ''} {row[3] or ''} {row[5] or ''}"
        })
    
    return products

def find_potential_matches(products1, products2, threshold):
    """Find potential matches between two sets of products using TF-IDF"""
    # Extract text for vectorization
    texts1 = [p["text"] for p in products1]
    texts2 = [p["text"] for p in products2]
    
    # Create TF-IDF matrix
    vectorizer = TfidfVectorizer(min_df=1, analyzer='word', 
                                ngram_range=(1, 2), stop_words='english')
    
    tfidf1 = vectorizer.fit_transform(texts1)
    tfidf2 = vectorizer.transform(texts2)
    
    # Calculate cosine similarity
    cosine_similarities = cosine_similarity(tfidf1, tfidf2)
    
    # Find potential matches
    matches = []
    for i, similarities in enumerate(cosine_similarities):
        best_match_idx = np.argmax(similarities)
        score = similarities[best_match_idx]
        
        if score >= threshold:
            matches.append((score, products1[i], products2[best_match_idx]))
    
    # Sort by score (highest first)
    matches.sort(reverse=True, key=lambda x: x[0])
    
    return matches

async def create_product_mapping(session: AsyncSession, product1_id, product2_id, confidence, method):
    """Create a mapping between two products"""
    # Ensure product1_id is the lower value to maintain consistency
    master_id = min(product1_id, product2_id)
    related_id = max(product1_id, product2_id)
    
    # Check if mapping already exists
    stmt = text("""
        SELECT id FROM product_mappings 
        WHERE master_product_id = :master_id AND related_product_id = :related_id
    """)
    
    result = await session.execute(stmt, {
        "master_id": master_id, 
        "related_id": related_id
    })
    
    existing = result.scalar()
    
    if existing:
        logger.info(f"Mapping already exists with ID: {existing}")
        return existing
    
    # Create new mapping
    stmt = text("""
        INSERT INTO product_mappings (
            master_product_id, related_product_id, match_confidence, match_method, created_at
        ) VALUES (
            :master_id, :related_id, :confidence, :method, NOW()
        ) RETURNING id
    """)
    
    result = await session.execute(stmt, {
        "master_id": master_id,
        "related_id": related_id,
        "confidence": confidence,
        "method": method
    })
    
    mapping_id = result.scalar()
    await session.commit()
    
    logger.info(f"Created new product mapping with ID: {mapping_id}")
    return mapping_id

if __name__ == "__main__":
    match_products()