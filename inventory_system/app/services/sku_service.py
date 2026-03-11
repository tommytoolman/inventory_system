from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product


async def generate_next_riff_sku(db: AsyncSession) -> str:
    """
    Calculate the next internal RIFF SKU (RIFF-1xxxxxxx).

    Ensures we always advance numerically and provides a fallback
    to the starting range if the stored max is missing or invalid.
    """
    query = select(func.max(Product.sku)).where(Product.sku.like("RIFF-%"))
    result = await db.execute(query)
    highest_sku: Optional[str] = result.scalar_one_or_none()

    if not highest_sku or not highest_sku.startswith("RIFF-"):
        next_num = 10000001
    else:
        try:
            numeric_part = highest_sku.replace("RIFF-", "")
            next_num = int(numeric_part) + 1
            if next_num >= 20000000:
                next_num = 10000001
        except (ValueError, IndexError):
            next_num = 10000001

    return f"RIFF-{next_num}"
