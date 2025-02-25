import pytest
from httpx import AsyncClient
from app.models.product import Product

@pytest.mark.asyncio
async def test_create_product(
    test_client,
    db_session,
    sample_product_data,
    mock_ebay_client,
    mock_reverb_client
):
    """Test creating a new product"""
    response = await test_client.post("/inventory/products/", json=sample_product_data)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == sample_product_data["name"]
    
    # Verify database entry
    product = await db_session.get(Product, data["id"])
    assert product is not None
    assert product.name == sample_product_data["name"]
    
    # Verify platform clients were called
    mock_ebay_client.create_listing.assert_called_once()
    mock_reverb_client.create_listing.assert_called_once()

@pytest.mark.asyncio
async def test_update_product(
    test_client,
    db_session,
    sample_product_data,
    mock_ebay_client
):
    """Test updating an existing product"""
    # First create a product
    product = Product(**sample_product_data)
    db_session.add(product)
    await db_session.commit()
    
    # Update the product
    update_data = {"price": 1099.99}
    response = await test_client.patch(
        f"/inventory/products/{product.id}",
        json=update_data
    )
    assert response.status_code == 200
    
    # Verify platform update was called
    mock_ebay_client.update_listing.assert_called_once()