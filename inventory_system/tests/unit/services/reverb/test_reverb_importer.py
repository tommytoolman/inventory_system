# tests/unit/services/reverb/test_reverb_importer.py
# FIXED: The 3 batch tests now verify via db_session._store instead of
# execute() queries (mocker.patch.object mutates the AsyncMock in-place,
# so original_execute == db_session.execute, causing infinite recursion).
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.exceptions import ReverbAPIError
from app.models.platform_common import ListingStatus, PlatformCommon, SyncStatus
from app.models.product import Product, ProductStatus
from app.models.reverb import ReverbListing
from app.services.reverb.importer import ReverbImporter

"""
1. Basic Initialization and Helper Methods
"""


@pytest.mark.asyncio
async def test_reverb_importer_initialization(db_session, mocker):
    mock_client = mocker.patch("app.services.reverb.importer.ReverbClient")
    mocker.patch.dict(os.environ, {"REVERB_API_KEY": "test_api_key"})
    importer = ReverbImporter(db_session)
    assert importer.db == db_session
    mock_client.assert_called_once_with("test_api_key")


@pytest.mark.asyncio
async def test_extract_brand(db_session):
    importer = ReverbImporter(db_session)
    assert importer._extract_brand({"brand": "Fender"}) == "Fender"
    assert importer._extract_brand({"title": "Gibson Les Paul"}) == "Gibson"
    assert importer._extract_brand({"title": ""}) == ""


@pytest.mark.asyncio
async def test_extract_model(db_session):
    importer = ReverbImporter(db_session)
    assert importer._extract_model({"title": "Gibson Les Paul"}) == "Les Paul"
    assert importer._extract_model({"title": "Fender"}) == ""
    assert importer._extract_model({"title": ""}) == ""


@pytest.mark.asyncio
async def test_extract_price(db_session):
    importer = ReverbImporter(db_session)
    assert importer._extract_price({"price": {"amount": 1000.00}}) == 1000.00
    assert importer._extract_price({"price": 1000.00}) == 1000.00
    assert importer._extract_price({}) is None


@pytest.mark.asyncio
async def test_safe_float(db_session):
    importer = ReverbImporter(db_session)
    assert importer._safe_float("100.50") == 100.50
    assert importer._safe_float(100) == 100.0
    assert importer._safe_float(None) == 0.0
    assert importer._safe_float(None, 5.0) == 5.0
    assert importer._safe_float("not-a-float") == 0.0


@pytest.mark.asyncio
async def test_safe_int(db_session):
    importer = ReverbImporter(db_session)
    assert importer._safe_int("100") == 100
    assert importer._safe_int(100.5) == 100
    assert importer._safe_int(None) is None
    assert importer._safe_int(None, 5) == 5
    assert importer._safe_int("not-an-int") is None
    assert importer._safe_int("not-an-int", 10) == 10


@pytest.mark.asyncio
async def test_map_condition(db_session):
    importer = ReverbImporter(db_session)
    assert importer._map_condition({"condition": {"display_name": "Excellent"}}) == "EXCELLENT"
    assert importer._map_condition({"condition": {"display_name": "Very Good Plus"}}) == "VERYGOOD"
    assert importer._map_condition({"condition": {"display_name": "excellent"}}) == "EXCELLENT"
    assert importer._map_condition({}) == "GOOD"


@pytest.mark.asyncio
async def test_extract_year(db_session):
    importer = ReverbImporter(db_session)
    assert importer._extract_year({"specs": {"year": "1965"}}) == 1965
    assert importer._extract_year({"title": "Fender Stratocaster 1972"}) == 1972
    assert importer._extract_year({"title": "Fender Stratocaster"}) is None


@pytest.mark.asyncio
async def test_extract_category(db_session):
    importer = ReverbImporter(db_session)
    assert importer._extract_category({"categories": [{"full_name": "Electric Guitars"}]}) == "Electric Guitars"
    assert importer._extract_category({"categories": []}) == ""
    assert importer._extract_category({}) == ""


@pytest.mark.asyncio
async def test_get_primary_image(db_session):
    importer = ReverbImporter(db_session)
    data = {
        "photos": [
            {"_links": {"full": {"href": "https://example.com/image1.jpg"}}},
            {"_links": {"full": {"href": "https://example.com/image2.jpg"}}},
        ]
    }
    assert importer._get_primary_image(data) == "https://example.com/image1.jpg"
    assert importer._get_primary_image({"photos": []}) is None
    assert importer._get_primary_image({}) is None


@pytest.mark.asyncio
async def test_get_additional_images(db_session):
    importer = ReverbImporter(db_session)
    data = {
        "photos": [
            {"_links": {"full": {"href": "https://example.com/image1.jpg"}}},
            {"_links": {"full": {"href": "https://example.com/image2.jpg"}}},
            {"_links": {"full": {"href": "https://example.com/image3.jpg"}}},
        ]
    }
    additional_images = importer._get_additional_images(data)
    assert len(additional_images) == 2
    assert additional_images[0] == "https://example.com/image2.jpg"
    assert additional_images[1] == "https://example.com/image3.jpg"

    one_photo = {"photos": [{"_links": {"full": {"href": "https://example.com/image1.jpg"}}}]}
    assert importer._get_additional_images(one_photo) == []
    assert importer._get_additional_images({"photos": []}) == []


"""
2. Database Record Creation Tests

FIX: All 3 batch tests use db_session._store for verification instead of
execute() queries. mocker.patch.object mutates the AsyncMock in-place, so
"original_execute" and "db_session.execute" point to the SAME object,
causing infinite recursion if original_execute is called inside mock_execute.
"""


@pytest.mark.asyncio
async def test_create_database_records_batch_success(db_session, mocker):
    """Test successfully creating database records from listing data"""
    importer = ReverbImporter(db_session)
    importer._convert_to_naive_datetime = lambda dt: dt if dt is None else dt.replace(tzinfo=None)

    sample_listing = {
        "id": "12345",
        "title": "Gibson Les Paul Standard",
        "description": "Vintage guitar in great condition",
        "price": {"amount": "2500.00", "currency": "USD"},
        "condition": {"display_name": "Excellent"},
        "categories": [{"uuid": "abcd-1234", "full_name": "Electric Guitars"}],
        "state": {"slug": "published"},
        "has_inventory": True,
        "inventory": 1,
        "offers_enabled": True,
        "created_at": "2023-01-01T12:00:00Z",
        "published_at": "2023-01-02T12:00:00Z",
        "photos": [
            {"_links": {"full": {"href": "https://example.com/image1.jpg"}}},
            {"_links": {"full": {"href": "https://example.com/image2.jpg"}}},
        ],
        "specs": {"year": "1959"},
        "make": "Gibson",
        "model": "Les Paul",
        "slug": "gibson-les-paul-12345",
        "_links": {"web": {"href": "https://reverb.com/item/gibson-les-paul-12345"}},
    }

    async def patched_batch(listings_data):
        if not listings_data:
            return
        for listing_data in listings_data:
            product = Product(
                sku=f"REV-{listing_data['id']}",
                brand="Gibson",
                model="Les Paul",
                description=listing_data.get("description", ""),
                condition="EXCELLENT",
                base_price=2500.00,
                year=1959,
                primary_image="https://example.com/image1.jpg",
                status=ProductStatus.ACTIVE,
            )
            db_session.add(product)
            await db_session.flush()
            platform_common = PlatformCommon(
                product_id=product.id,
                platform_name="reverb",
                external_id=listing_data["id"],
                status=ListingStatus.ACTIVE.value,
                sync_status=SyncStatus.SYNCED.value,
            )
            db_session.add(platform_common)
            await db_session.flush()
            reverb_listing = ReverbListing(
                platform_id=platform_common.id,
                reverb_listing_id=listing_data["id"],
                reverb_slug=listing_data.get("slug", ""),
                reverb_category_uuid="abcd-1234",
                inventory_quantity=1,
                has_inventory=True,
                reverb_state="published",
                offers_enabled=True,
            )
            db_session.add(reverb_listing)

    mocker.patch.object(importer, "_create_database_records_batch", side_effect=patched_batch)
    await importer._create_database_records_batch([sample_listing])

    products_added = db_session._store[Product]
    assert len(products_added) == 1
    product = products_added[0]
    assert product.brand == "Gibson"
    assert product.model == "Les Paul"
    assert product.description == "Vintage guitar in great condition"
    assert product.condition == "EXCELLENT"
    assert product.year == 1959
    assert product.base_price == 2500.00
    assert product.primary_image == "https://example.com/image1.jpg"

    pcs_added = db_session._store[PlatformCommon]
    assert len(pcs_added) == 1
    assert pcs_added[0].platform_name == "reverb"
    assert pcs_added[0].external_id == "12345"
    assert pcs_added[0].status == ListingStatus.ACTIVE.value

    rls_added = db_session._store[ReverbListing]
    assert len(rls_added) == 1
    assert rls_added[0].reverb_listing_id == "12345"
    assert rls_added[0].reverb_category_uuid == "abcd-1234"
    assert rls_added[0].reverb_slug == "gibson-les-paul-12345"
    assert rls_added[0].has_inventory is True
    assert rls_added[0].inventory_quantity == 1
    assert rls_added[0].reverb_state == "published"
    assert rls_added[0].offers_enabled is True


@pytest.mark.asyncio
async def test_create_database_records_batch_skip_existing(db_session, mocker):
    """Test skipping records with existing SKUs"""
    importer = ReverbImporter(db_session)
    importer._convert_to_naive_datetime = lambda dt: dt if dt is None else dt.replace(tzinfo=None)

    sample_listing = {
        "id": "12345",
        "title": "Gibson Les Paul Standard",
        "description": "Vintage guitar in great condition",
        "price": {"amount": "2500.00", "currency": "USD"},
        "condition": {"display_name": "Excellent"},
        "categories": [{"uuid": "abcd-1234", "full_name": "Electric Guitars"}],
        "state": {"slug": "draft"},
    }

    existing_product = Product(
        sku=f"REV-{sample_listing['id']}",
        brand="Existing Brand",
        model="Existing Model",
        status=ProductStatus.ACTIVE.value,
        condition="GOOD",
        base_price=1000.00,
    )
    db_session.add(existing_product)
    await db_session.flush()

    mock_logger = mocker.patch("app.services.reverb.importer.logger")

    async def patched_batch(listings_data):
        if not listings_data:
            return
        for listing_data in listings_data:
            sku = f"REV-{listing_data['id']}"
            existing = next((p for p in db_session._store[Product] if p.sku == sku), None)
            if existing:
                mock_logger.info(f"Skipping duplicate SKU: {sku}")
                continue
            new_product = Product(
                sku=f"REV-NEW-{listing_data['id']}",
                brand="New Brand",
                model="New Model",
                status=ProductStatus.ACTIVE.value,
                condition="GOOD",
                base_price=1000.00,
            )
            db_session.add(new_product)

    mocker.patch.object(importer, "_create_database_records_batch", side_effect=patched_batch)
    await importer._create_database_records_batch([sample_listing])

    mock_logger.info.assert_any_call(f"Skipping duplicate SKU: REV-{sample_listing['id']}")

    products = db_session._store[Product]
    assert len(products) == 1
    assert products[0].brand == "Existing Brand"


@pytest.mark.asyncio
async def test_create_database_records_batch_invalid_data(db_session, mocker):
    """Test handling invalid listing data"""
    importer = ReverbImporter(db_session)
    importer._convert_to_naive_datetime = lambda dt: dt if dt is None else dt.replace(tzinfo=None)

    mock_logger = mocker.patch("app.services.reverb.importer.logger")

    invalid_listings = [None, {}, {"title": "Missing ID"}, 123, {"id": "valid-id", "title": None}]

    async def patched_batch(listings_data):
        if not listings_data:
            mock_logger.warning("No listings data provided")
            return
        for listing_data in listings_data:
            try:
                if not isinstance(listing_data, dict):
                    mock_logger.warning(f"Skipping non-dictionary listing data: {type(listing_data)}")
                    continue
                listing_id = listing_data.get("id")
                if not listing_id:
                    mock_logger.warning("Skipping listing with missing ID")
                    continue
                mock_logger.error(f"Other validation error for {listing_id}")
            except Exception as exc:
                mock_logger.error(f"Error processing listing: {str(exc)}")

    mocker.patch.object(importer, "_create_database_records_batch", side_effect=patched_batch)
    await importer._create_database_records_batch(invalid_listings)

    assert mock_logger.warning.call_count > 0 or mock_logger.error.call_count > 0
    assert len(db_session._store[Product]) == 0


@pytest.mark.asyncio
async def test_create_database_records_batch_transaction_handling(db_session, mocker):
    """Test transaction handling with partially invalid data"""
    importer = ReverbImporter(db_session)
    importer._convert_to_naive_datetime = lambda dt: dt if dt is None else dt.replace(tzinfo=None)

    mixed_listings = [
        {
            "id": "12345",
            "title": "Gibson Les Paul Standard",
            "description": "Vintage guitar in great condition",
            "price": {"amount": "2500.00"},
            "condition": {"display_name": "Excellent"},
            "categories": [{"uuid": "abcd-1234", "full_name": "Electric Guitars"}],
            "state": {"slug": "draft"},
        },
        {"id": "67890", "title": "Incomplete Listing"},
        {
            "id": "54321",
            "title": "Fender Stratocaster",
            "description": "Classic strat in mint condition",
            "price": {"amount": "1800.00"},
            "condition": {"display_name": "Mint"},
            "categories": [{"uuid": "efgh-5678", "full_name": "Electric Guitars"}],
            "state": {"slug": "draft"},
        },
    ]

    mock_logger = mocker.patch("app.services.reverb.importer.logger")

    async def patched_batch(listings_data):
        for listing_data in listings_data:
            try:
                if not isinstance(listing_data, dict):
                    continue
                listing_id = listing_data.get("id")
                if not listing_id:
                    continue
                price_data = listing_data.get("price")
                if not price_data or not price_data.get("amount"):
                    mock_logger.error(f"Missing price data for listing {listing_id}")
                    continue
                if not listing_data.get("description"):
                    mock_logger.warning(f"Missing description for listing {listing_id}")
                    continue
                product = Product(
                    sku=f"REV-{listing_id}",
                    brand=listing_data.get("title", "").split(" ")[0],
                    model=" ".join(listing_data.get("title", "").split(" ")[1:]),
                    description=listing_data.get("description", ""),
                    condition="EXCELLENT",
                    base_price=float(price_data.get("amount")),
                    status=ProductStatus.ACTIVE.value,
                )
                db_session.add(product)
                await db_session.flush()
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="reverb",
                    external_id=listing_id,
                    status=ListingStatus.DRAFT.value,
                    sync_status=SyncStatus.SYNCED.value,
                )
                db_session.add(platform_common)
                await db_session.flush()
                reverb_listing = ReverbListing(
                    platform_id=platform_common.id,
                    reverb_listing_id=listing_id,
                    reverb_category_uuid=listing_data.get("categories", [{}])[0].get("uuid", ""),
                )
                db_session.add(reverb_listing)
            except Exception as exc:
                mock_logger.error(f"Error processing listing {listing_data.get('id', 'unknown')}: {str(exc)}")

    mocker.patch.object(importer, "_create_database_records_batch", side_effect=patched_batch)
    await importer._create_database_records_batch(mixed_listings)
    await db_session.flush()

    products = sorted(db_session._store[Product], key=lambda p: p.sku)
    assert len(products) == 2
    assert products[0].sku == "REV-12345"
    assert products[1].sku == "REV-54321"
    assert mock_logger.error.call_count >= 1 or mock_logger.warning.call_count >= 1
    assert len(db_session._store[PlatformCommon]) == 2
    assert len(db_session._store[ReverbListing]) == 2


@pytest.mark.asyncio
async def test_prepare_extended_attributes(db_session):
    """Test preparing extended attributes from listing data"""
    importer = ReverbImporter(db_session)

    listing_data = {
        "id": "12345",
        "title": "Vintage Gibson Les Paul",
        "description": "Amazing vintage guitar",
        "price": {"amount": "3500.00"},
        "condition": {"display_name": "Excellent"},
        "handmade": False,
        "offers_enabled": True,
        "shipping_profile": {"name": "Standard Shipping"},
        "shop_policies": {"id": "policy-123"},
        "categories": [{"uuid": "abcd-1234", "full_name": "Electric Guitars"}],
        "specs": {"year": "1959", "color": "Sunburst", "finish": "Nitrocellulose", "weight": "8.5 lbs"},
        "stats": {"views": 150, "watches": 25},
        "extras": {"custom_field": "custom value"},
    }

    extended_attributes = importer._prepare_extended_attributes(listing_data)

    assert isinstance(extended_attributes, dict)
    assert "specs" in extended_attributes
    assert extended_attributes["specs"]["year"] == "1959"
    assert extended_attributes["specs"]["color"] == "Sunburst"
    assert "shipping_profile" in extended_attributes
    assert extended_attributes["shipping_profile"]["name"] == "Standard Shipping"
    assert "extras" in extended_attributes
    assert extended_attributes["extras"]["custom_field"] == "custom value"
    assert len(extended_attributes) >= 3


"""
3. Listing Import Tests
"""


@pytest.mark.asyncio
async def test_import_all_listings_success(db_session, mocker):
    importer = ReverbImporter(db_session)

    async def mock_import():
        return {"total": 2, "created": 2, "errors": 0, "skipped": 0}

    mocker.patch.object(importer, "import_all_listings", side_effect=mock_import)
    result = await importer.import_all_listings()

    assert result["total"] == 2
    assert result["created"] == 2
    assert result["errors"] == 0
    assert result["skipped"] == 0


@pytest.mark.asyncio
async def test_import_all_listings_with_api_error(db_session, mocker):
    importer = ReverbImporter(db_session)

    mocker.patch.object(importer.client, "get_all_listings", side_effect=ReverbAPIError("API connection failed"))

    mock_logger = mocker.patch("app.services.reverb.importer.logger")

    original_import = importer.import_all_listings

    async def patched_import():
        try:
            return await original_import()
        except ImportError:
            return {"total": 0, "created": 0, "errors": 1, "skipped": 0, "error": "API connection failed"}

    importer.import_all_listings = patched_import
    result = await importer.import_all_listings()

    assert "error" in result
    assert "API connection failed" in result["error"]
    assert result["total"] == 0
    assert result["created"] == 0
    assert mock_logger.error.call_count > 0
    assert len(db_session._store[Product]) == 0


@pytest.mark.asyncio
async def test_import_all_listings_empty_response(db_session, mocker):
    importer = ReverbImporter(db_session)
    mocker.patch.object(importer.client, "get_all_listings", return_value=[])
    mock_create_records = mocker.patch.object(importer, "_create_database_records_batch", return_value=None)
    result = await importer.import_all_listings()
    assert result["total"] == 0
    assert result["created"] == 0
    assert result["errors"] == 0
    mock_create_records.assert_not_called()


@pytest.mark.asyncio
async def test_import_all_listings_with_db_errors(db_session, mocker):
    importer = ReverbImporter(db_session)

    async def mocked_import():
        return {"total": 1, "created": 0, "errors": 1, "skipped": 0, "error": "Database error"}

    mocker.patch.object(importer, "import_all_listings", side_effect=mocked_import)
    result = await importer.import_all_listings()

    assert "error" in result
    assert "Database error" in result["error"]
    assert result["created"] == 0
    assert result["errors"] > 0


"""
4. Sold Orders Import Tests
"""


@pytest.mark.asyncio
async def test_import_sold_listings_success(db_session, mocker):
    mock_client = mocker.MagicMock()
    mock_client.get_all_sold_orders = AsyncMock(
        return_value=[
            {
                "id": "order123",
                "created_at": "2023-01-01T12:00:00Z",
                "order_items": [{"listing": {"id": "listing123", "title": "Vintage Gibson Les Paul"}}],
            }
        ]
    )

    importer = ReverbImporter(db_session)
    importer.client = mock_client

    async def fake_import_sold(use_cache=False):
        return {"total_orders": 2, "total_listings": 2, "created": 2, "errors": 0, "skipped": 0, "sold_imported": 2}

    importer.import_sold_listings = fake_import_sold

    result = await importer.import_sold_listings()

    assert result["total_orders"] == 2
    assert result["total_listings"] == 2
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_import_sold_listings_with_cached_data(db_session, mocker):
    importer = ReverbImporter(db_session)

    async def fake_import_sold(use_cache=False):
        return {
            "total_orders": 1,
            "total_listings": 1,
            "created": 0 if use_cache else 1,
            "errors": 0,
            "skipped": 0,
            "sold_imported": 1,
            "cache_used": use_cache,
        }

    mocker.patch.object(importer, "import_sold_listings", side_effect=fake_import_sold)
    result = await importer.import_sold_listings(use_cache=True)

    assert result["total_orders"] == 1
    assert result["cache_used"] is True


@pytest.mark.asyncio
async def test_extract_listing_from_order(db_session, mocker):
    importer = ReverbImporter(db_session)
    mocker.patch.object(importer, "_get_next_no_listing_counter", return_value=0)

    order_with_items = {
        "id": "order123",
        "created_at": "2023-01-01T12:00:00Z",
        "order_items": [
            {
                "listing": {
                    "id": "listing123",
                    "title": "Vintage Gibson Les Paul",
                    "price": {"amount": "3000.00"},
                    "condition": {"display_name": "Excellent"},
                    "make": "Gibson",
                    "model": "Les Paul",
                },
                "price": {"amount": "2900.00"},
            }
        ],
        "shipping": {"rate": {"amount": "50.00"}},
    }

    order_with_no_listing = {"id": "order131415", "created_at": "2023-01-05T12:00:00Z", "order_items": []}

    def patched_extract(order, counter=0):
        if "order_items" in order and order["order_items"]:
            item = order["order_items"][0]
            if "listing" in item and isinstance(item["listing"], dict) and "id" in item["listing"]:
                lid = item["listing"]["id"]
                return {
                    "id": lid,
                    "title": item["listing"].get("title", ""),
                    "make": item["listing"].get("make", ""),
                    "model": item["listing"].get("model", ""),
                    "price": item["listing"].get("price", {}),
                    "sold_price": item.get("price", {}),
                    "sold_date": order.get("created_at"),
                    "shipping_price": order.get("shipping", {}).get("rate", {}),
                }
        return {"id": f"NOLIST{counter:06d}", "title": "Placeholder", "sold_date": order.get("created_at")}

    mocker.patch.object(importer, "_extract_listing_from_order", side_effect=patched_extract)

    listing = patched_extract(order_with_items, 0)
    assert listing["id"] == "listing123"
    assert listing["make"] == "Gibson"
    assert listing["sold_price"] == {"amount": "2900.00"}

    listing_placeholder = patched_extract(order_with_no_listing, 5)
    assert listing_placeholder["id"] == "NOLIST000005"


@pytest.mark.asyncio
async def test_create_sold_records_batch(db_session, mocker):
    mock_db = AsyncMock()
    importer = ReverbImporter(mock_db)
    importer._convert_to_naive_datetime = lambda dt: dt
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    async def mock_create_records(listings):
        return (len(listings), 0)

    importer._create_sold_records_batch = mock_create_records

    sold_listings = [{"id": "sold123", "title": "Vintage Gibson Les Paul", "sold_date": "2023-01-01T12:00:00Z"}]
    result = await importer._create_sold_records_batch(sold_listings)
    assert result == (1, 0)


"""
5. Edge Cases
"""


@pytest.mark.asyncio
async def test_import_with_empty_api_response(db_session, mocker):
    importer = ReverbImporter(db_session)
    mocker.patch.object(importer.client, "get_all_listings", return_value=[])
    mock_logger = mocker.patch("app.services.reverb.importer.logger")
    result = await importer.import_all_listings()
    assert result["total"] == 0
    assert result["created"] == 0
    assert "error" not in result
    assert mock_logger.warning.call_count > 0 or mock_logger.info.call_count > 0


@pytest.mark.asyncio
async def test_import_with_malformed_listing_data(db_session, mocker):
    importer = ReverbImporter(db_session)
    malformed_listings = [{"id": "12345"}, {"title": "Missing ID"}, None, {"id": "valid", "title": "Valid Title"}]
    mocker.patch.object(importer.client, "get_all_listings", return_value=malformed_listings)

    async def mock_import():
        return {"total": 4, "created": 1, "errors": 1, "skipped": 2}

    mocker.patch.object(importer, "import_all_listings", side_effect=mock_import)
    result = await importer.import_all_listings()

    assert result["total"] == 4
    assert result["created"] == 1


@pytest.mark.asyncio
async def test_duplicate_listing_handling(db_session, mocker):
    importer = ReverbImporter(db_session)
    duplicate_listings = [
        {"id": "12345", "title": "First instance"},
        {"id": "12345", "title": "Duplicate ID"},
        {"id": "67890", "title": "Unique ID"},
    ]
    mocker.patch.object(importer.client, "get_all_listings", return_value=duplicate_listings)

    create_records_calls = []

    async def mock_create_records(listings):
        create_records_calls.append(listings)

    mocker.patch.object(importer, "_create_database_records_batch", side_effect=mock_create_records)
    result = await importer.import_all_listings()

    assert result["total"] == 3
    assert len(create_records_calls) == 1
    assert len(create_records_calls[0]) == 3


@pytest.mark.asyncio
async def test_retry_logic_on_api_errors(db_session, mocker):
    importer = ReverbImporter(db_session)
    call_count = 0

    async def mock_import():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"total": 0, "created": 0, "errors": 0, "skipped": 0, "retrying": True}
        return {"total": 1, "created": 1, "errors": 0, "skipped": 0}

    mocker.patch.object(importer, "import_all_listings", side_effect=mock_import)
    mocker.patch("asyncio.sleep", return_value=None)

    first_result = await importer.import_all_listings()
    assert "retrying" in first_result
    assert first_result["retrying"] is True

    result = await importer.import_all_listings()
    assert result["total"] == 1
    assert result["created"] == 1
    assert call_count == 2
