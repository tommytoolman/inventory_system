# tests/test_routes/test_inventory_routes.py
# FIXED VERSION

from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import Settings
from app.core.exceptions import ProductCreationError
from app.core.security import get_current_username
from app.dependencies import get_db
from app.main import app
from app.models.platform_common import PlatformCommon
from app.models.product import Product, ProductCondition, ProductStatus
from app.routes.inventory import add_product_form, list_products, product_detail
from app.services.product_service import ProductService
from fastapi.testclient import TestClient
from starlette.requests import Request


def create_mock_product(
    id: int,
    sku: str,
    brand: str,
    model: str,
    category: str,
    price: float,
    status: ProductStatus,
    image: Optional[str] = None,
) -> MagicMock:
    return MagicMock(
        spec=Product,
        id=id,
        sku=sku,
        brand=brand,
        model=model,
        category=category,
        created_at=datetime.now(),
        base_price=price,
        primary_image=image,
        status=MagicMock(value=status.value),
        year=2024,
        description="Mock Description",
        platform_listings=[],
    )


MOCK_PRODUCTS_FULL = [
    create_mock_product(1, "DSG-000-001", "Fender", "Stratocaster", "Electric Guitars", 1500.0, ProductStatus.ACTIVE),
    create_mock_product(
        2, "DSG-000-002", "Gibson", "Les Paul", "Electric Guitars", 2500.0, ProductStatus.ACTIVE, "img2.jpg"
    ),
    create_mock_product(3, "DSG-000-003", "Fender", "Telecaster", "Electric Guitars", 1400.0, ProductStatus.SOLD),
    create_mock_product(4, "DSG-000-004", "Marshall", "JCM800", "Amplifiers", 1800.0, ProductStatus.ACTIVE),
    create_mock_product(5, "DSG-000-005", "Gibson", "SG", "Electric Guitars", 2200.0, ProductStatus.DRAFT),
]

MOCK_CATEGORIES = [("Electric Guitars", 4), ("Amplifiers", 1)]
MOCK_BRANDS = [("Fender", 2), ("Gibson", 2), ("Marshall", 1)]


async def override_get_db():
    yield AsyncMock()


async def override_auth():
    return "test_user"


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


def make_mock_settings(tinymce_api_key="TEST_KEY"):
    s = MagicMock(spec=Settings)
    s.TINYMCE_API_KEY = tinymce_api_key
    s.EBAY_PRICE_MARKUP_PERCENT = 10
    s.VR_PRICE_MARKUP_PERCENT = 5
    s.REVERB_PRICE_MARKUP_PERCENT = 5
    s.SHOPIFY_PRICE_MARKUP_PERCENT = 0
    s.DRAFT_UPLOAD_DIR = "/tmp/drafts"
    s.STALE_LISTING_THRESHOLD_MONTHS = 6
    return s


test_scenarios = [
    pytest.param(
        "default_page1_per_page_2",
        {"page": 1, "per_page": 2},
        len(MOCK_PRODUCTS_FULL),
        MOCK_PRODUCTS_FULL[0:2],
        MOCK_CATEGORIES,
        MOCK_BRANDS,
        {
            "page": 1,
            "per_page": 2,
            "total_products": 5,
            "total_pages": 3,
            "has_prev": False,
            "has_next": True,
            "start_item": 1,
            "end_item": 2,
            "selected_category": None,
            "selected_brand": None,
            "search": None,
        },
        id="default_page1_per_page_2",
    ),
    pytest.param(
        "page2_per_page_2",
        {"page": 2, "per_page": 2},
        len(MOCK_PRODUCTS_FULL),
        MOCK_PRODUCTS_FULL[2:4],
        MOCK_CATEGORIES,
        MOCK_BRANDS,
        {
            "page": 2,
            "per_page": 2,
            "total_products": 5,
            "total_pages": 3,
            "has_prev": True,
            "has_next": True,
            "start_item": 3,
            "end_item": 4,
            "selected_category": None,
            "selected_brand": None,
            "search": None,
        },
        id="page2_per_page_2",
    ),
    pytest.param(
        "last_page_per_page_2",
        {"page": 3, "per_page": 2},
        len(MOCK_PRODUCTS_FULL),
        MOCK_PRODUCTS_FULL[4:5],
        MOCK_CATEGORIES,
        MOCK_BRANDS,
        {
            "page": 3,
            "per_page": 2,
            "total_products": 5,
            "total_pages": 3,
            "has_prev": True,
            "has_next": False,
            "start_item": 5,
            "end_item": 5,
            "selected_category": None,
            "selected_brand": None,
            "search": None,
        },
        id="last_page_per_page_2",
    ),
    pytest.param(
        "search_filter",
        {"page": 1, "per_page": 100, "search": "Stratocaster"},
        1,
        [MOCK_PRODUCTS_FULL[0]],
        MOCK_CATEGORIES,
        MOCK_BRANDS,
        {
            "page": 1,
            "per_page": 100,
            "total_products": 1,
            "total_pages": 1,
            "has_prev": False,
            "has_next": False,
            "start_item": 1,
            "end_item": 1,
            "selected_category": None,
            "selected_brand": None,
            "search": "Stratocaster",
        },
        id="search_filter",
    ),
    pytest.param(
        "category_filter",
        {"page": 1, "per_page": 100, "category": "Amplifiers"},
        1,
        [MOCK_PRODUCTS_FULL[3]],
        MOCK_CATEGORIES,
        MOCK_BRANDS,
        {
            "page": 1,
            "per_page": 100,
            "total_products": 1,
            "total_pages": 1,
            "has_prev": False,
            "has_next": False,
            "start_item": 1,
            "end_item": 1,
            "selected_category": "Amplifiers",
            "selected_brand": None,
            "search": None,
        },
        id="category_filter",
    ),
    pytest.param(
        "brand_filter",
        {"page": 1, "per_page": 100, "brand": "Gibson"},
        2,
        [MOCK_PRODUCTS_FULL[1], MOCK_PRODUCTS_FULL[4]],
        MOCK_CATEGORIES,
        MOCK_BRANDS,
        {
            "page": 1,
            "per_page": 100,
            "total_products": 2,
            "total_pages": 1,
            "has_prev": False,
            "has_next": False,
            "start_item": 1,
            "end_item": 2,
            "selected_category": None,
            "selected_brand": "Gibson",
            "search": None,
        },
        id="brand_filter",
    ),
    pytest.param(
        "no_products_found",
        {"page": 1, "per_page": 100, "search": "NonExistent"},
        0,
        [],
        MOCK_CATEGORIES,
        MOCK_BRANDS,
        {
            "page": 1,
            "per_page": 100,
            "total_products": 0,
            "total_pages": 0,
            "has_prev": False,
            "has_next": False,
            "start_item": 0,
            "end_item": 0,
            "selected_category": None,
            "selected_brand": None,
            "search": "NonExistent",
        },
        id="no_products_found",
    ),
    pytest.param(
        "per_page_all",
        {"page": 1, "per_page": "all"},
        len(MOCK_PRODUCTS_FULL),
        MOCK_PRODUCTS_FULL,
        MOCK_CATEGORIES,
        MOCK_BRANDS,
        {
            "page": 1,
            "per_page": "all",
            "total_products": 5,
            "total_pages": 1,
            "has_prev": False,
            "has_next": False,
            "start_item": 1,
            "end_item": 5,
            "selected_category": None,
            "selected_brand": None,
            "search": None,
        },
        id="per_page_all",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "test_id_str, route_params, mock_total, mock_products, mock_cats, mock_brands, expected_context",
    test_scenarios,
)
async def test_list_products_scenarios(
    mocker,
    test_id_str,
    route_params,
    mock_total,
    mock_products,
    mock_cats,
    mock_brands,
    expected_context,
):
    mock_session = AsyncMock()

    mock_execute_count_result = MagicMock()
    mock_execute_count_result.scalar_one.return_value = mock_total

    mock_execute_product_result = MagicMock()
    mock_scalar_result_for_products = MagicMock()
    mock_scalar_result_for_products.all.return_value = mock_products
    mock_execute_product_result.scalars.return_value = mock_scalar_result_for_products

    mock_execute_categories_result = MagicMock()
    mock_execute_categories_result.all.return_value = mock_cats

    mock_execute_brands_result = MagicMock()
    mock_execute_brands_result.all.return_value = mock_brands

    mock_execute_status_result = MagicMock()
    mock_execute_status_result.all.return_value = []

    async def execute_side_effect(query, *args, **kwargs):
        call_index = mock_session.execute.await_count - 1
        if call_index == 0:
            return mock_execute_count_result
        elif call_index == 1:
            return mock_execute_product_result
        elif call_index == 2:
            return mock_execute_categories_result
        elif call_index == 3:
            return mock_execute_brands_result
        else:
            return mock_execute_status_result

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)

    mock_request = MagicMock(spec=Request)
    mock_settings = make_mock_settings()
    mock_template_render = mocker.patch("app.routes.inventory.templates.TemplateResponse")

    await list_products(request=mock_request, db=mock_session, settings=mock_settings, **route_params)

    mock_template_render.assert_called_once()
    call_args, _ = mock_template_render.call_args
    context = call_args[1]
    template_name = call_args[0]

    assert template_name == "inventory/list.html"
    assert context["request"] == mock_request
    assert context["products"] == mock_products
    assert context["categories"] == mock_cats
    assert context["brands"] == mock_brands

    for key, expected_value in expected_context.items():
        assert context.get(key) == expected_value, f"Context mismatch for '{key}'"

    assert mock_session.execute.await_count >= 2
    mock_execute_count_result.scalar_one.assert_called_once()
    if mock_products:
        mock_execute_product_result.scalars().all.assert_called_once()


@pytest.mark.asyncio
async def test_product_detail_found(mocker):
    product_id_to_test = 1

    mock_product = create_mock_product(
        id=product_id_to_test,
        sku="DSG-000-001",
        brand="Fender",
        model="Stratocaster",
        category="Electric Guitars",
        price=1500.0,
        status=ProductStatus.ACTIVE,
    )
    mock_platform_listings = [
        MagicMock(spec=PlatformCommon, platform_name="eBay", status="ACTIVE", platform_message=None),
        MagicMock(spec=PlatformCommon, platform_name="Reverb", status="DRAFT", platform_message=None),
        MagicMock(spec=PlatformCommon, platform_name="VR", status="ERROR", platform_message="Sync failed"),
    ]

    mock_session = AsyncMock()
    mock_execute_product_result = MagicMock()
    mock_execute_product_result.scalar_one_or_none.return_value = mock_product

    mock_execute_platform_result = MagicMock()
    mock_platform_scalar_result = MagicMock()
    mock_platform_scalar_result.all.return_value = mock_platform_listings
    mock_execute_platform_result.scalars.return_value = mock_platform_scalar_result

    async def execute_side_effect(query, *args, **kwargs):
        call_index = mock_session.execute.await_count - 1
        if call_index == 0:
            return mock_execute_product_result
        elif call_index == 1:
            return mock_execute_platform_result
        else:
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            m.first.return_value = None
            m.scalars.return_value.all.return_value = []
            return m

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)
    mock_request = MagicMock(spec=Request)
    mock_request.cookies.get.return_value = None
    mock_request.query_params.get.return_value = None
    mock_template_render = mocker.patch("app.routes.inventory.templates.TemplateResponse")

    await product_detail(request=mock_request, product_id=product_id_to_test, db=mock_session)

    mock_template_render.assert_called_once()
    call_args, _ = mock_template_render.call_args
    assert call_args[0] == "inventory/detail.html"
    assert call_args[1]["product"] == mock_product


@pytest.mark.asyncio
async def test_product_detail_not_found(mocker):
    product_id_to_test = 999
    mock_session = AsyncMock()
    mock_execute_product_result = MagicMock()
    mock_execute_product_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_execute_product_result
    mock_request = MagicMock(spec=Request)
    mock_template_render = mocker.patch("app.routes.inventory.templates.TemplateResponse")

    await product_detail(request=mock_request, product_id=product_id_to_test, db=mock_session)

    mock_template_render.assert_called_once_with(
        "errors/404.html",
        {"request": mock_request, "error_message": f"Product ID {product_id_to_test} not found."},
        status_code=404,
    )
    assert mock_session.execute.await_count == 1


@pytest.mark.asyncio
async def test_add_product_form(mocker):
    mock_brands_list = [("Fender",), ("Gibson",)]
    mock_recent_products_list = [
        create_mock_product(5, "DSG-000-005", "Gibson", "SG", "Electric Guitars", 2200.0, ProductStatus.DRAFT),
        create_mock_product(4, "DSG-000-004", "Marshall", "JCM800", "Amplifiers", 1800.0, ProductStatus.ACTIVE),
    ]
    mock_api_key = "TEST_TINYMCE_KEY"
    mock_session = AsyncMock()

    mock_execute_brands_result = MagicMock()
    mock_execute_brands_result.all.return_value = mock_brands_list
    mock_execute_canonical_result = MagicMock()
    mock_execute_canonical_result.all.return_value = []
    mock_execute_recent_products_result = MagicMock()
    mock_recent_products_scalars = MagicMock()
    mock_recent_products_scalars.all.return_value = mock_recent_products_list
    mock_execute_recent_products_result.scalars.return_value = mock_recent_products_scalars

    async def execute_side_effect(query, *args, **kwargs):
        call_index = mock_session.execute.await_count - 1
        if call_index == 0:
            return mock_execute_brands_result
        elif call_index == 1:
            return mock_execute_canonical_result
        elif call_index == 2:
            return mock_execute_recent_products_result
        else:
            return mock_execute_canonical_result

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)
    mock_request = MagicMock(spec=Request)
    mock_settings = make_mock_settings(tinymce_api_key=mock_api_key)
    mock_template_render = mocker.patch("app.routes.inventory.templates.TemplateResponse")

    await add_product_form(request=mock_request, db=mock_session, settings=mock_settings)

    mock_template_render.assert_called_once()
    call_args, _ = mock_template_render.call_args
    context = call_args[1]
    assert call_args[0] == "inventory/add.html"
    assert context["tinymce_api_key"] == mock_api_key
    assert context["existing_products"] == mock_recent_products_list
    assert context["ebay_markup_percent"] == 10
    assert context["vr_markup_percent"] == 5


def _make_add_product_db_mock():
    mock_session = AsyncMock()
    mock_execute_brands = MagicMock(all=MagicMock(return_value=[("Fender",)]))
    mock_execute_canonical = MagicMock(all=MagicMock(return_value=[]))
    mock_execute_recent = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))

    async def db_side_effect(query, *args, **kwargs):
        idx = mock_session.execute.await_count - 1
        if idx == 0:
            return mock_execute_brands
        elif idx == 1:
            return mock_execute_canonical
        elif idx == 2:
            return mock_execute_recent
        else:
            return mock_execute_canonical

    mock_session.execute = AsyncMock(side_effect=db_side_effect)
    return mock_session


@pytest.mark.asyncio
async def test_add_product_success(mocker):
    mock_created_product_id = 99

    mock_product_read = MagicMock()
    mock_product_read.id = mock_created_product_id

    mock_product_model = MagicMock(spec=Product)
    mock_product_model.id = mock_created_product_id
    mock_product_model.sku = "NEW-SKU-123"
    mock_product_model.brand = "TestBrand"
    mock_product_model.model = "TestModel"
    mock_product_model.primary_image = None
    mock_product_model.additional_images = []
    mock_product_model.title = None
    mock_product_model.decade = None
    mock_product_model.quantity = None
    mock_product_model.shipping_profile_id = None
    mock_product_model.generate_title = MagicMock(return_value="TestBrand TestModel")

    mock_create = mocker.patch.object(ProductService, "create_product", return_value=mock_product_read)
    mocker.patch.object(ProductService, "get_product_model_instance", return_value=mock_product_model)
    mocker.patch("app.routes.inventory.save_upload_file", return_value="/static/uploads/fake.jpg")
    mocker.patch("app.routes.inventory.ShopifyService", return_value=MagicMock())

    mock_session = _make_add_product_db_mock()

    async def override_db():
        yield mock_session

    form_data = {
        "brand": "TestBrand",
        "model": "TestModel",
        "sku": "NEW-SKU-123",
        "category": "TestCategory",
        "condition": ProductCondition.GOOD.value,
        "base_price": 500.0,
        "status": ProductStatus.DRAFT.value,
        "in_inventory": "True",
        "buy_now": "True",
        "show_vat": "True",
        "available_for_shipment": "True",
        "cost_price": 250.0,
        "description": "Test description",
        "year": 2024,
        "sync_all": "false",
    }

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_username] = override_auth
    try:
        response = client.post("/inventory/add", data=form_data, follow_redirects=False)
    finally:
        del app.dependency_overrides[get_db]
        if get_current_username in app.dependency_overrides:
            del app.dependency_overrides[get_current_username]

    assert response.status_code in (
        200,
        303,
    ), f"Expected 200 or 303 but got {response.status_code}: {response.text[:200]}"
    if response.status_code == 303:
        assert f"/inventory/product/{mock_created_product_id}" in response.headers.get("location", "")
    else:
        body = response.json()
        assert body.get("product_id") == mock_created_product_id
        assert f"/inventory/product/{mock_created_product_id}" in body.get("redirect_url", "")
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_add_product_invalid_enum_value(mocker):
    mock_create = mocker.patch.object(ProductService, "create_product")
    mocker.patch("app.routes.inventory.ShopifyService", return_value=MagicMock())
    mock_session = _make_add_product_db_mock()

    async def override_db():
        yield mock_session

    form_data = {
        "brand": "TestBrand",
        "model": "TestModel",
        "sku": "INVALID-ENUM-SKU",
        "category": "TestCategory",
        "condition": "WAY_TOO_GOOD",
        "base_price": 500.0,
        "status": ProductStatus.DRAFT.value,
        "in_inventory": "True",
        "buy_now": "True",
        "show_vat": "True",
        "available_for_shipment": "True",
        "cost_price": 250.0,
        "description": "Test description",
        "year": 2024,
        "sync_all": "false",
    }

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_username] = override_auth
    try:
        response = client.post("/inventory/add", data=form_data, follow_redirects=False)
    finally:
        del app.dependency_overrides[get_db]
        if get_current_username in app.dependency_overrides:
            del app.dependency_overrides[get_current_username]

    assert response.status_code == 400, f"Expected status 400 but got {response.status_code}"
    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_add_product_creation_error(mocker):
    error_message = "SKU 'DUPLICATE-SKU' already exists."
    mock_create = mocker.patch.object(
        ProductService,
        "create_product",
        new_callable=AsyncMock,
        side_effect=ProductCreationError(error_message),
    )
    mocker.patch("app.routes.inventory.ShopifyService", return_value=MagicMock())
    mock_session = _make_add_product_db_mock()

    async def override_db():
        yield mock_session

    form_data = {
        "brand": "TestBrand",
        "model": "TestModel",
        "sku": "DUPLICATE-SKU",
        "category": "TestCategory",
        "condition": ProductCondition.GOOD.value,
        "base_price": 500.0,
        "status": ProductStatus.DRAFT.value,
        "in_inventory": "True",
        "buy_now": "True",
        "show_vat": "True",
        "available_for_shipment": "True",
        "cost_price": 250.0,
        "description": "Test description",
        "year": 2024,
        "sync_all": "false",
    }

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_username] = override_auth
    try:
        response = client.post("/inventory/add", data=form_data, follow_redirects=False)
    finally:
        del app.dependency_overrides[get_db]
        if get_current_username in app.dependency_overrides:
            del app.dependency_overrides[get_current_username]

    assert response.status_code == 400, f"Expected status 400 but got {response.status_code}"
    mock_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_inventory_route_success(mocker):
    mock_request = MagicMock(spec=Request)
    mock_session = AsyncMock()

    mock_products = [
        MagicMock(
            id=1,
            sku="DSG-001-001",
            brand="Fender",
            model="Stratocaster",
            category="Electric Guitars",
            base_price=1299.99,
            status=ProductStatus.ACTIVE,
        ),
        MagicMock(
            id=2,
            sku="DSG-001-002",
            brand="Gibson",
            model="Les Paul",
            category="Electric Guitars",
            base_price=2499.99,
            status=ProductStatus.ACTIVE,
        ),
    ]

    mock_execute_products_result = MagicMock()
    mock_products_scalar = MagicMock()
    mock_products_scalar.all.return_value = mock_products
    mock_execute_products_result.scalars.return_value = mock_products_scalar

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = len(mock_products)

    mock_execute_categories_result = MagicMock()
    mock_execute_categories_result.all.return_value = [("Electric Guitars", 2), ("Acoustic Guitars", 1)]

    mock_execute_brands_result = MagicMock()
    mock_execute_brands_result.all.return_value = [("Fender", 1), ("Gibson", 1)]

    mock_execute_status_result = MagicMock()
    mock_execute_status_result.all.return_value = [("active", 2)]

    async def execute_side_effect(query, *args, **kwargs):
        call_index = mock_session.execute.await_count - 1
        if call_index == 0:
            return mock_count_result
        elif call_index == 1:
            return mock_execute_products_result
        elif call_index == 2:
            return mock_execute_categories_result
        elif call_index == 3:
            return mock_execute_brands_result
        else:
            return mock_execute_status_result

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)
    mock_template_render = mocker.patch("app.routes.inventory.templates.TemplateResponse")

    await list_products(
        request=mock_request,
        db=mock_session,
        page=1,
        per_page=10,
        settings=make_mock_settings(),
    )

    mock_template_render.assert_called_once()
    call_args, _ = mock_template_render.call_args
    context = call_args[1]

    assert call_args[0] == "inventory/list.html"
    assert context["products"] == mock_products
    assert context["total_products"] == len(mock_products)
    assert mock_session.execute.await_count == 5
