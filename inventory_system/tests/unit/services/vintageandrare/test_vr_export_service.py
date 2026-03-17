# tests/unit/services/vintageandrare/test_vr_export_service.py
"""
Tests for VRExportService.

The export service queries the DB for products and formats them into a VR-compatible CSV.
We mock the DB session to control what products are returned.
"""
import csv
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.services.vintageandrare.export import VRExportService


def make_product(
    id=1,
    sku="EXP-001",
    brand="ExportBrand",
    model="ModelX",
    base_price=100.0,
    category="Cat1",
    is_sold=False,
    primary_image=None,
    description="",
    year=None,
):
    p = MagicMock(spec=Product)
    p.id = id
    p.sku = sku
    p.brand = brand
    p.model = model
    p.base_price = base_price
    p.price = base_price
    p.category = category
    p.is_sold = is_sold
    p.primary_image = primary_image or ""
    p.description = description
    p.year = year
    p.finish = ""
    p.in_collective = False
    p.in_inventory = True
    p.in_reseller = False
    p.collective_discount = None
    p.free_shipping = False
    p.buy_now = False
    p.show_vat = True
    p.decade = None
    p.local_pickup = False
    p.available_for_shipment = True
    p.processing_time = None
    p.offer_discount = None
    p.video_url = ""
    p.external_link = ""
    p.price_notax = None
    p.platform_listings = []
    return p


def make_platform_common(product_id=1, platform_name="vintageandrare", external_id="VR123"):
    pc = MagicMock(spec=PlatformCommon)
    pc.product_id = product_id
    pc.platform_name = platform_name
    pc.external_id = external_id
    return pc


@pytest.mark.asyncio
async def test_generate_csv_structure(db_session, mocker):
    """Test the generated CSV has correct headers and row count."""
    service = VRExportService(db_session=db_session)

    prod1 = make_product(id=1, sku="EXP-001", brand="ExportBrand", model="ModelX", base_price=100.0, category="Cat1")
    prod2 = make_product(
        id=2, sku="EXP-002", brand="ExportBrand", model="ModelY", base_price=200.0, category="Cat2", is_sold=True
    )
    pc1 = make_platform_common(product_id=1, platform_name="vintageandrare", external_id="VR123")

    mocker.patch.object(
        service,
        "get_products_for_export",
        new_callable=AsyncMock,
        return_value=[
            service._format_product_for_export(prod1, pc1),
            service._format_product_for_export(prod2, None),
        ],
    )

    csv_buffer = await service.generate_csv()
    csv_content = csv_buffer.getvalue()

    # FIX: use 'line' not 'l' (E741: ambiguous variable name)
    lines = [line for line in csv_content.strip().split("\n") if line.strip()]
    assert len(lines) == 3  # Header + 2 products

    header = lines[0]
    for col in VRExportService.CSV_COLUMNS:
        assert col in header


@pytest.mark.asyncio
async def test_generate_csv_content(db_session, mocker):
    """Test the CSV content is formatted correctly for exported products."""
    service = VRExportService(db_session=db_session)

    prod1 = make_product(
        id=1, sku="EXP-001", brand="ExportBrand", model="ModelX", base_price=100.0, category="Cat1", is_sold=False
    )
    prod2 = make_product(
        id=2, sku="EXP-002", brand="ExportBrand", model="ModelY", base_price=200.0, category="Cat2", is_sold=True
    )
    pc1 = make_platform_common(product_id=1, platform_name="vintageandrare", external_id="VR123")

    mocker.patch.object(
        service,
        "get_products_for_export",
        new_callable=AsyncMock,
        return_value=[
            service._format_product_for_export(prod1, pc1),
            service._format_product_for_export(prod2, None),
        ],
    )

    csv_buffer = await service.generate_csv()
    csv_reader = csv.DictReader(csv_buffer)
    rows = list(csv_reader)

    assert len(rows) == 2

    row1 = rows[0]
    assert row1["brand name"] == "ExportBrand"
    assert row1["product model name"] == "ModelX"
    assert row1["product price"] == "100"
    assert row1["product id"] == "VR123"
    assert row1["product sold"] == "no"
    assert row1["category name"] == "Cat1"

    row2 = rows[1]
    assert row2["brand name"] == "ExportBrand"
    assert row2["product model name"] == "ModelY"
    assert row2["product price"] == "200"
    assert row2["product id"] == ""
    assert row2["product sold"] == "yes"
    assert row2["category name"] == "Cat2"


@pytest.mark.asyncio
async def test_format_product_for_export_with_platform(db_session):
    """Test _format_product_for_export with a VR platform listing."""
    service = VRExportService(db_session=db_session)

    prod = make_product(brand="Fender", model="Strat", base_price=999.0, category="Electric Guitars")
    pc = make_platform_common(platform_name="vintageandrare", external_id="VR-999")

    result = service._format_product_for_export(prod, pc)

    assert result["brand name"] == "Fender"
    assert result["product model name"] == "Strat"
    assert result["product id"] == "VR-999"
    assert result["product price"] == "999"
    assert result["product sold"] == "no"


@pytest.mark.asyncio
async def test_format_product_for_export_without_platform(db_session):
    """Test _format_product_for_export without a platform listing."""
    service = VRExportService(db_session=db_session)

    prod = make_product(brand="Gibson", model="LP", base_price=1500.0, is_sold=True)

    result = service._format_product_for_export(prod, None)

    assert result["brand name"] == "Gibson"
    assert result["product model name"] == "LP"
    assert result["product id"] == ""
    assert result["product sold"] == "yes"


@pytest.mark.asyncio
async def test_generate_csv_column_count(db_session, mocker):
    """Test all CSV columns are present in every row."""
    service = VRExportService(db_session=db_session)

    prod = make_product()
    pc = make_platform_common()

    mocker.patch.object(
        service,
        "get_products_for_export",
        new_callable=AsyncMock,
        return_value=[service._format_product_for_export(prod, pc)],
    )

    csv_buffer = await service.generate_csv()
    csv_reader = csv.DictReader(csv_buffer)
    rows = list(csv_reader)

    assert len(rows) == 1
    for col in VRExportService.CSV_COLUMNS:
        assert col in rows[0], f"Missing column: {col}"
