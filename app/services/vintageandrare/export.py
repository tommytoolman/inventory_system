# app/services/vintageandrare/export.py

import csv

from typing import List, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from io import StringIO
from datetime import datetime
from ...models.product import Product
from ...models.platform_common import PlatformCommon  # Updated import

class VRExportService:
    """ Service for exporting products to VintageAndRare CSV format.
        04/03/25: Modified VRExportService to work with the enhanced schema
    """

    # Column order matching the bulk upload template
    CSV_COLUMNS = [
        'brand name', 'category name', 'product id', 'external id',
        'product model name', 'product price', 'product price notax',
        'product description', 'product year', 'product sold',
        'product finish', 'product in collective', 'product in inventory',
        'product in reseller', 'collective discount', 'free shipping',
        'buy now', 'show vat', 'decade', 'product order',
        'local pickup', 'available for shipment', 'processing time',
        'offer discount', 'image url', 'video url', 'external link'
    ]

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    # async def get_products_for_export(self) -> List[Dict[str, Any]]:
    #     """Fetch all products and their VintageAndRare platform listings."""
    #     query = (
    #         select(Product, PlatformCommon)
    #         .outerjoin(PlatformCommon)
    #         .filter(PlatformCommon.platform_name == 'vintageandrare')
    #         .options(selectinload(Product.platform_listings))
    #     )

    #     result = await self.db_session.execute(query)
    #     products_data = []

    #     for product, platform_listing in result:
    #         products_data.append(self._format_product_for_export(product, platform_listing))

    #     return products_data

    # def _format_product_for_export(self, product: Product, platform_listing: PlatformCommon | None) -> Dict[str, str]:
    #     """Format a product for the VintageAndRare CSV export format."""
        
    #     # Get reverb_listing for reference if it exists
    #     reverb_listing = None
    #     if hasattr(product, 'platform_listings'):
    #         for pl in product.platform_listings:
    #             if pl.platform_name.lower() == 'reverb':
    #                 reverb_listing = pl.reverb_listing
    #                 break
        
    #     # Use enhanced pricing fields if available
    #     price = product.base_price or 0       
        
    #     if reverb_listing and hasattr(reverb_listing, 'list_price') and reverb_listing.list_price:
    #         price = reverb_listing.list_price

    #     return {
    #         'brand name': product.brand or '',
    #         'category name': product.category or '',
    #         'product id': str(platform_listing.external_id if platform_listing else ''),
    #         'external id': '',  # Left blank as per template
    #         'product model name': product.product or '',
    #         'product price': str(int(product.price) if product.price else ''),
    #         'product price notax': str(product.price_notax or ''),
    #         'product description': product.description or '',
    #         'product year': str(product.year or ''),
    #         'product sold': 'yes' if product.is_sold else 'no',
    #         'product finish': product.finish or '',
    #         'product in collective': 'yes' if product.in_collective else 'no',
    #         'product in inventory': 'yes' if product.in_inventory else 'no',
    #         'product in reseller': 'yes' if product.in_reseller else 'no',
    #         'collective discount': str(product.collective_discount or ''),
    #         'free shipping': 'yes' if product.free_shipping else 'no',
    #         'buy now': 'yes' if product.buy_now else 'no',
    #         'show vat': 'yes' if product.show_vat else 'no',
    #         'decade': str(product.decade or ''),
    #         'product order': '',  # Left blank as per template
    #         'local pickup': 'yes' if product.local_pickup else 'no',
    #         'available for shipment': 'yes' if product.available_for_shipment else 'no',
    #         'processing time': str(product.processing_time or ''),
    #         'offer discount': str(product.offer_discount or ''),
    #         'image url': product.image_url or '',
    #         'video url': product.video_url or '',
    #         'external link': product.external_link or ''
    #     }

    # async def generate_csv(self) -> StringIO:
    #     """Generate a CSV file in VintageAndRare format."""
    #     products_data = await self.get_products_for_export()
    #     output = StringIO()
    #     writer = csv.DictWriter(output, fieldnames=self.CSV_COLUMNS)

    #     # Write header
    #     writer.writeheader()

    #     # Write products
    #     writer.writerows(products_data)

    #     output.seek(0)
    #     return output
    
    async def get_products_for_export(self) -> List[Dict[str, Any]]:
        """Fetch all products with their VintageAndRare platform listings."""
        query = (
            select(Product, PlatformCommon)
            .join(PlatformCommon, isouter=True)
            .options(
                selectinload(Product.platform_listings)
            )
            .filter(
                (PlatformCommon.platform_name == 'vintageandrare') | 
                (PlatformCommon.platform_name.is_(None))
            )
        )

        try:
            result = await self.db_session.execute(query)
            products_data = []

            for product, platform_listing in result:
                print(f"Processing product: {product.id}, Platform Listing: {platform_listing}")
                products_data.append(self._format_product_for_export(product, platform_listing))

            print(f"Exported {len(products_data)} products")
            return products_data
        except Exception as e:
            print(f"Error in export: {e}")
            raise

    def _format_product_for_export(self, product: Product, platform_listing: Optional[PlatformCommon]) -> Dict[str, str]:
        """Format a product for the VintageAndRare CSV export format."""
        
        # Safely get platform-specific data
        platform_name = platform_listing.platform_name.lower() if platform_listing else None
        external_id = platform_listing.external_id if platform_listing else None
        
        # Find Reverb listing if it exists
        reverb_listing = None
        try:
            for pl in product.platform_listings:
                if pl.platform_name.lower() == 'reverb':
                    reverb_listing = pl.reverb_listing
                    break
        except Exception:
            reverb_listing = None

        # Use enhanced pricing fields if available
        price = product.base_price or 0
        if reverb_listing and hasattr(reverb_listing, 'list_price') and reverb_listing.list_price:
            price = reverb_listing.list_price

        return {
            'brand name': product.brand or '',
            'category name': product.category or '',
            'product id': str(external_id or ''),
            'external id': '',  # Left blank as per template
            'product model name': product.model or '',
            'product price': str(int(product.price) if product.price else int(price)),
            'product price notax': str(product.price_notax or ''),
            'product description': product.description or '',
            'product year': str(product.year or ''),
            'product sold': 'yes' if product.is_sold else 'no',
            'product finish': product.finish or '',
            'product in collective': 'yes' if product.in_collective else 'no',
            'product in inventory': 'yes' if product.in_inventory else 'no',
            'product in reseller': 'yes' if product.in_reseller else 'no',
            'collective discount': str(product.collective_discount or ''),
            'free shipping': 'yes' if product.free_shipping else 'no',
            'buy now': 'yes' if product.buy_now else 'no',
            'show vat': 'yes' if product.show_vat else 'no',
            'decade': str(product.decade or ''),
            'product order': '',  # Left blank as per template
            'local pickup': 'yes' if product.local_pickup else 'no',
            'available for shipment': 'yes' if product.available_for_shipment else 'no',
            'processing time': str(product.processing_time or ''),
            'offer discount': str(product.offer_discount or ''),
            'image url': product.primary_image or '',
            'video url': product.video_url or '',
            'external link': product.external_link or ''
        }

    async def generate_csv(self) -> StringIO:
        """Generate a CSV file in VintageAndRare format."""
        products_data = await self.get_products_for_export()
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=self.CSV_COLUMNS)

        # Write header
        writer.writeheader()

        # Write products
        writer.writerows(products_data)

        output.seek(0)
        return output
    