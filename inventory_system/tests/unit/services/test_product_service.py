# tests/unit/services/test_product_service.py
# FIXED:
#   test_create_product_success: Don't patch Product class (breaks select(Product)).
#   test_create_product_rolls_back_on_commit_error: Same approach.
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.enums import ProductCondition, ProductStatus
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductRead
from app.services.product_service import ProductCreationError, ProductNotFoundError, ProductService

sample_create_data = ProductCreate(
    sku="NEW-SKU-001",
    brand="TestBrand",
    model="TestModel",
    category="TestCategory",
    condition=ProductCondition.NEW,
    base_price=100.0,
    status=ProductStatus.DRAFT,
)

now = datetime.now()
sample_read_data = ProductRead(
    id=1,
    sku="NEW-SKU-001",
    brand="TestBrand",
    model="TestModel",
    category="TestCategory",
    condition=ProductCondition.NEW,
    base_price=100.0,
    status=ProductStatus.DRAFT,
    created_at=now,
    updated_at=now,
)


def get_sample_paginated_result():
    return {
        "items": [MagicMock(spec=Product), MagicMock(spec=Product)],
        "page": 1,
        "page_size": 10,
        "total_items": 2,
        "total_pages": 1,
    }


sample_read_list = [sample_read_data, sample_read_data]


@pytest.mark.asyncio
async def test_sku_exists_returns_true_if_sku_found(mocker):
    mock_session = AsyncMock()
    mock_session.scalar.return_value = True
    product_service = ProductService(db=mock_session)
    result = await product_service.sku_exists("EXISTING-SKU-123")
    assert result is True
    mock_session.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_sku_exists_returns_false_if_sku_not_found(mocker):
    mock_session = AsyncMock()
    mock_session.scalar.return_value = False
    product_service = ProductService(db=mock_session)
    result = await product_service.sku_exists("NEW-SKU-456")
    assert result is False
    mock_session.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_product_success(mocker):
    mock_session = AsyncMock()
    mock_existing_result = MagicMock()
    mock_existing_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_existing_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.rollback = AsyncMock()

    mocker.patch("app.services.product_service.model_to_schema", new_callable=AsyncMock, return_value=sample_read_data)

    product_service = ProductService(db=mock_session)
    created_product_schema = await product_service.create_product(sample_create_data)

    assert created_product_schema == sample_read_data
    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited()
    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_create_product_fails_if_sku_exists(mocker):
    mock_session = AsyncMock()
    mock_existing_product = MagicMock(spec=Product)
    mock_existing_product.status = ProductStatus.ACTIVE
    mock_existing_product.sku = sample_create_data.sku

    mock_existing_result = MagicMock()
    mock_existing_result.scalars.return_value.first.return_value = mock_existing_product
    mock_session.execute = AsyncMock(return_value=mock_existing_result)
    mock_session.rollback = AsyncMock()

    product_service = ProductService(db=mock_session)

    with pytest.raises(ProductCreationError, match=f"SKU '{sample_create_data.sku}' already exists"):
        await product_service.create_product(sample_create_data)

    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_product_rolls_back_on_commit_error(mocker):
    mock_session = AsyncMock()
    mock_existing_result = MagicMock()
    mock_existing_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_existing_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock(side_effect=Exception("Simulated DB commit error"))
    mock_session.rollback = AsyncMock()
    mock_session.refresh = AsyncMock()

    mocker.patch("app.services.product_service.model_to_schema", new_callable=AsyncMock)

    product_service = ProductService(db=mock_session)

    with pytest.raises(ProductCreationError, match="Failed to create product: Simulated DB commit error"):
        await product_service.create_product(sample_create_data)

    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_product_success(mocker):
    mock_session = AsyncMock()
    mock_product_instance = MagicMock(spec=Product)

    mock_execute_result = AsyncMock()
    mock_execute_result.scalar_one_or_none = AsyncMock(return_value=mock_product_instance)
    mock_session.execute.return_value = mock_execute_result

    mock_model_to_schema = mocker.patch(
        "app.services.product_service.model_to_schema", new_callable=AsyncMock, return_value=sample_read_data
    )

    product_service = ProductService(db=mock_session)
    result_schema = await product_service.get_product(1)

    assert result_schema == sample_read_data
    mock_session.execute.assert_awaited_once()
    mock_execute_result.scalar_one_or_none.assert_awaited_once()
    mock_model_to_schema.assert_awaited_once_with(mock_product_instance, ProductRead)


@pytest.mark.asyncio
async def test_get_product_not_found(mocker):
    mock_session = AsyncMock()
    mock_execute_result = AsyncMock()
    mock_execute_result.scalar_one_or_none = AsyncMock(return_value=None)
    mock_session.execute.return_value = mock_execute_result

    mocker.patch("app.services.product_service.model_to_schema")

    product_service = ProductService(db=mock_session)

    with pytest.raises(ProductNotFoundError, match="Product with ID 999 not found"):
        await product_service.get_product(999)

    mock_session.execute.assert_awaited_once()
    mock_execute_result.scalar_one_or_none.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_products_no_filters(mocker):
    mock_session = AsyncMock()
    product_service = ProductService(db=mock_session)
    expected_pagination_result = get_sample_paginated_result()

    async def _mock_paginate(*args, **kwargs):
        return expected_pagination_result.copy()

    async def _mock_convert(*args, **kwargs):
        return sample_read_list

    mock_paginate_query = mocker.patch("app.services.product_service.paginate_query", side_effect=_mock_paginate)
    mock_models_to_schemas = mocker.patch("app.services.product_service.models_to_schemas", side_effect=_mock_convert)

    result = await product_service.list_products(page=1, page_size=10)

    expected_keys = {"items", "page", "page_size", "total_items", "total_pages"}
    assert set(result.keys()) == expected_keys
    assert result["items"] == sample_read_list
    mock_paginate_query.assert_awaited_once()
    mock_models_to_schemas.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_products_with_filters(mocker):
    mock_session = AsyncMock()
    product_service = ProductService(db=mock_session)
    expected_pagination_result = get_sample_paginated_result()

    async def _mock_paginate(*args, **kwargs):
        return expected_pagination_result.copy()

    async def _mock_convert(*args, **kwargs):
        return sample_read_list

    mock_paginate_query = mocker.patch("app.services.product_service.paginate_query", side_effect=_mock_paginate)
    mocker.patch("app.services.product_service.models_to_schemas", side_effect=_mock_convert)

    result = await product_service.list_products(
        page=1, page_size=10, search="Test", category="Guitars", brand="Fender"
    )

    assert result["items"] == sample_read_list
    mock_paginate_query.assert_awaited_once()
    call_args, _ = mock_paginate_query.call_args
    query_str = str(call_args[0].compile(compile_kwargs={"literal_binds": True})).upper()
    assert "WHERE" in query_str


@pytest.mark.asyncio
async def test_delete_product_success(mocker):
    mock_session = AsyncMock()
    mock_product_instance = MagicMock(spec=Product)

    mock_execute_result = AsyncMock()
    mock_execute_result.scalar_one_or_none = AsyncMock(return_value=mock_product_instance)
    mock_session.execute.return_value = mock_execute_result
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    product_service = ProductService(db=mock_session)
    result = await product_service.delete_product(1)

    assert result is True
    mock_session.execute.assert_awaited_once()
    mock_execute_result.scalar_one_or_none.assert_awaited_once()
    mock_session.delete.assert_awaited_once_with(mock_product_instance)
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_product_not_found(mocker):
    mock_session = AsyncMock()
    mock_execute_result = AsyncMock()
    mock_execute_result.scalar_one_or_none = AsyncMock(return_value=None)
    mock_session.execute.return_value = mock_execute_result
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    product_service = ProductService(db=mock_session)

    with pytest.raises(ProductNotFoundError, match="Product with ID 999 not found"):
        await product_service.delete_product(999)

    mock_session.delete.assert_not_called()
    mock_session.commit.assert_not_called()
