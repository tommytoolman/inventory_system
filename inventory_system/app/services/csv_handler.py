# app/services/csv_handler.py
"""
Handlers for processing CSV imports (mosly from V&R) in the inventory management system.

This module provides functionality for importing and validating CSV files,
specifically handling the VintageAndRare format while maintaining flexibility
for other platforms.
"""

import pandas as pd
from typing import Dict, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models.product import Product, PlatformListing, CSVImportLog


class CSVHandler:
    """
    Handles CSV file processing and database operations for product imports.

    This class provides methods for validating and processing CSV files,
    creating or updating product records, and maintaining import logs.

    Attributes:
        session (AsyncSession): SQLAlchemy async session for database operations.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize the CSV handler.

        Args:
            session (AsyncSession): SQLAlchemy async session for database operations.
        """
        self.session = session

    async def process_vintage_and_rare_csv(self, file_path: str) -> Tuple[int, int, Dict]:
        """
        Process a VintageAndRare format CSV file and import products.

        Reads the CSV file, processes each row, creates or updates product records,
        and maintains an import log.

        Args:
            file_path (str): Path to the CSV file to process.

        Returns:
            Tuple[int, int, Dict]: A tuple containing:
                - Total number of rows processed
                - Number of successfully processed rows
                - Dictionary of errors keyed by row index

        Raises:
            Exception: If there's an error reading the file or processing the data.
        """
        try:
            # Read CSV file
            df = pd.read_csv(file_path)

            # Track results
            total_rows = len(df)
            successful_rows = 0
            error_log = {}

            # Process each row
            for index, row in df.iterrows():
                try:
                    product_data = {
                        'brand': row['brand name'],
                        'category': row['category name'],
                        'model': row['product model name'],
                        'year': int(row['product year']) if pd.notna(row['product year']) else None,
                        'decade': int(row['decade']) if pd.notna(row['decade']) else None,
                        'finish': row['product finish'],
                        'description': row['product description'],
                        'price': float(row['product price']) if pd.notna(row['product price']) else 0.0,
                        'price_notax': float(row['product price notax']) if pd.notna(row['product price notax']) else None,
                        'is_sold': row['product sold'].lower() == 'true' if pd.notna(row['product sold']) else False,
                        'in_collective': row['product in collective'].lower() == 'true' if pd.notna(row['product in collective']) else False,
                        'in_inventory': row['product in inventory'].lower() == 'true' if pd.notna(row['product in inventory']) else False,
                        'in_reseller': row['product in reseller'].lower() == 'true' if pd.notna(row['product in reseller']) else False,
                        'collective_discount': float(row['collective discount']) if pd.notna(row['collective discount']) else None,
                        'free_shipping': row['free shipping'].lower() == 'true' if pd.notna(row['free shipping']) else False,
                        'buy_now': row['buy now'].lower() == 'true' if pd.notna(row['buy now']) else False,
                        'show_vat': row['show vat'].lower() == 'true' if pd.notna(row['show vat']) else False,
                        'local_pickup': row['local pickup'].lower() == 'true' if pd.notna(row['local pickup']) else False,
                        'available_for_shipment': row['available for shipment'].lower() == 'true' if pd.notna(row['available for shipment']) else True,
                        'processing_time': int(row['processing time']) if pd.notna(row['processing time']) else None,
                        'image_url': row['image url'] if pd.notna(row['image url']) else None,
                        'video_url': row['video url'] if pd.notna(row['video url']) else None,
                        'external_link': row['external link'] if pd.notna(row['external link']) else None,
                    }

                    # Check if product exists (by external_id)
                    external_id = str(int(row['external id'])) if pd.notna(row['external id']) else None
                    if external_id:
                        existing_listing = await self.session.execute(
                            select(PlatformListing).where(
                                PlatformListing.platform_name == 'vintageandrare',
                                PlatformListing.external_id == external_id
                            )
                        )
                        platform_listing = existing_listing.scalar_one_or_none()

                        if platform_listing:
                            # Update existing product
                            product = platform_listing.product
                            for key, value in product_data.items():
                                setattr(product, key, value)
                        else:
                            # Create new product
                            product = Product(**product_data)
                            self.session.add(product)
                            await self.session.flush()

                            # Create platform listing
                            platform_listing = PlatformListing(
                                platform_name='vintageandrare',
                                external_id=external_id,
                                product_id=product.id,
                                sync_status='synced'
                            )
                            self.session.add(platform_listing)

                    successful_rows += 1

                except Exception as e:
                    error_log[index] = str(e)

            # Create import log
            import_log = CSVImportLog(
                filename=file_path,
                platform='vintageandrare',
                total_rows=total_rows,
                successful_rows=successful_rows,
                failed_rows=total_rows - successful_rows,
                error_log=error_log
            )
            self.session.add(import_log)

            await self.session.commit()
            return total_rows, successful_rows, error_log

        except Exception as e:
            await self.session.rollback()
            raise e

    @staticmethod
    def validate_csv_template(file_path: str) -> Tuple[bool, List[str]]:
        """
        Validate that a CSV file matches the expected template format.

        Checks if all required columns are present in the CSV file.

        Args:
            file_path (str): Path to the CSV file to validate.

        Returns:
            Tuple[bool, List[str]]: A tuple containing:
                - Boolean indicating if the file is valid
                - List of missing column names (empty if valid)

        Raises:
            Exception: If there's an error reading the file.
        """
        required_columns = {
            'brand name', 'category name', 'product id', 'external id',
            'product model name', 'product price', 'product description'
        }

        try:
            df = pd.read_csv(file_path)
            existing_columns = set(df.columns)
            missing_columns = required_columns - existing_columns

            return len(missing_columns) == 0, list(missing_columns)
        except Exception as e:
            return False, [str(e)]