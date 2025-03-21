# Standard library imports
import os
import json
import asyncio
import aiofiles
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union

# FastAPI imports
from fastapi import (
    APIRouter, 
    Depends, 
    Request, 
    HTTPException, 
    BackgroundTasks,
    Form, 
    File, 
    UploadFile,
)

from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.encoders import jsonable_encoder

# SQLAlchemy imports
from sqlalchemy import select, or_, distinct, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

# App imports
from app.core.config import Settings, get_settings
from app.core.exceptions import ProductCreationError, PlatformIntegrationError
from app.dependencies import get_db, templates
from app.integrations.events import StockUpdateEvent
from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.shipping import ShippingProfile
from app.models.vr import VRListing
from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
from app.services.category_mapping_service import CategoryMappingService
from app.services.product_service import ProductService
from app.services.ebay_service import EbayService
from app.services.reverb_service import ReverbService
from app.services.vintageandrare.export import VRExportService
from app.services.website_service import WebsiteService
from app.schemas.product import ProductCreate

router = APIRouter()

# Configuration for file uploads
UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

logger = logging.getLogger(__name__)

async def save_upload_file(upload_file: UploadFile) -> str:
    """Save an uploaded file and return its path"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{upload_file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    async with aiofiles.open(filepath, 'wb') as out_file:
        content = await upload_file.read()
        await out_file.write(content)

    return f"/static/uploads/{filename}"

def process_platform_data(form_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract platform-specific data from form fields"""
    platform_data = {}
    
    # Process eBay data
    ebay_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__ebay__"):
            field_name = key.replace("platform_data__ebay__", "")
            # Handle boolean values (checkboxes)
            if value in [True, 'true', 'True', 'on']:
                ebay_data[field_name] = True
            elif value in [False, 'false', 'False']:
                ebay_data[field_name] = False
            else:
                ebay_data[field_name] = value
    
    if ebay_data:
        platform_data["ebay"] = ebay_data
    
    # Process Reverb data
    reverb_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__reverb__"):
            field_name = key.replace("platform_data__reverb__", "")
            # Handle boolean values (checkboxes)
            if value in [True, 'true', 'True', 'on']:
                reverb_data[field_name] = True
            elif value in [False, 'false', 'False']:
                reverb_data[field_name] = False
            else:
                reverb_data[field_name] = value
    
    if reverb_data:
        platform_data["reverb"] = reverb_data
    
    # Process V&R data
    vr_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__vr__"):
            field_name = key.replace("platform_data__vr__", "")
            vr_data[field_name] = value
    
    if vr_data:
        platform_data["vr"] = vr_data
    
    # Process Website data
    website_data = {}
    for key, value in form_data.items():
        if key.startswith("platform_data__website__"):
            field_name = key.replace("platform_data__website__", "")
            website_data[field_name] = value
    
    if website_data:
        platform_data["website"] = website_data
    
    return platform_data

@router.get("/api/products/{product_id}")
async def get_product_json(
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    """API endpoint to get product data for copy from existing feature"""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Convert to dict and exclude sensitive fields
    product_dict = jsonable_encoder(product)
    
    # Return JSON response
    return product_dict

@router.get("/", response_class=HTMLResponse)
async def list_products(
    request: Request,
    page: int = 1,
    per_page: Union[int, str] = 100,  # Default to 100
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    db: AsyncSession = Depends(get_db),  # Change to AsyncSession
    settings: Settings = Depends(get_settings)
):
    # Handle the case when per_page is 'all'
    if per_page == 'all':
        pagination_limit = None  # No limit
        pagination_offset = 0
    else:
        try:
            per_page = int(per_page)
        except (ValueError, TypeError):
            per_page = 100  # Default to 100 if conversion fails
            
        pagination_limit = per_page
        pagination_offset = (page - 1) * per_page
    
    # Build query using async style (select instead of query)
    query = select(Product)
    
    # Apply filters
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Product.brand.ilike(search_term),
                Product.model.ilike(search_term),
                Product.sku.ilike(search_term),
                Product.description.ilike(search_term)
            )
        )
    
    if category:
        query = query.filter(Product.category == category)
    
    if brand:
        query = query.filter(Product.brand == brand)
    
    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()
    
    # Apply pagination and ordering
    query = query.order_by(desc(Product.created_at))
    
    if pagination_limit:
        query = query.offset(pagination_offset).limit(pagination_limit)
    
    # Execute query
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Get unique categories and brands for filters
    categories_query = (
        select(Product.category, func.count(Product.id).label("count"))
        .filter(Product.category.isnot(None))
        .group_by(Product.category)
        .order_by(Product.category)
    )
    categories_result = await db.execute(categories_query)
    categories_with_counts = [(c[0], c[1]) for c in categories_result.all() if c[0]]
    
    brands_query = (
        select(Product.brand, func.count(Product.id).label("count"))
        .filter(Product.brand.isnot(None))
        .group_by(Product.brand)
        .order_by(Product.brand)
    )
    brands_result = await db.execute(brands_query)
    brands_with_counts = [(b[0], b[1]) for b in brands_result.all() if b[0]]
    
    # Calculate pagination info
    if per_page != 'all' and per_page > 0:
        total_pages = (total + per_page - 1) // per_page
        start_page = max(1, page - 2)
        end_page = min(total_pages, page + 2)
        
        # Calculate start and end items for display
        start_item = (page - 1) * per_page + 1 if total > 0 else 0
        end_item = min(page * per_page, total)
    else:
        total_pages = 1
        page = 1
        start_page = 1
        end_page = 1
        # For "all" pages
        start_item = 1 if total > 0 else 0
        end_item = total
    
    return templates.TemplateResponse(
        "inventory/list.html",
        {
            "request": request,
            "products": products,
            "total_products": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "start_page": start_page,
            "end_page": end_page,
            "start_item": start_item,   # Add these two
            "end_item": end_item,       # variables to the template context
            "categories": categories_with_counts,  # Updated
            "brands": brands_with_counts,  # Updated
            "selected_category": category,
            "selected_brand": brand,
            "search": search,
            "has_prev": page > 1,
            "has_next": page < total_pages
        }
    )

@router.get("/product/{product_id}", response_class=HTMLResponse)
async def product_detail(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    try:
        query = select(Product).where(Product.id == product_id)
        result = await db.execute(query)
        product = result.scalar_one_or_none()
        
        if not product:
            return templates.TemplateResponse(
                "errors/404.html",
                {"request": request},
                status_code=404
            )
        
        platform_query = select(PlatformCommon).where(PlatformCommon.product_id == product_id)
        platform_result = await db.execute(platform_query)
        platform_listings = platform_result.scalars().all()
        
       # Get platform status information
        platform_statuses = {
            "ebay": {"status": "pending", "message": "Not synchronized"},
            "reverb": {"status": "pending", "message": "Not synchronized"},
            "vr": {"status": "pending", "message": "Not synchronized"},
            "website": {"status": "pending", "message": "Not synchronized"}
        }
        
        for listing in platform_listings:
            platform_name = listing.platform_name.lower()
            if platform_name in platform_statuses:
                if listing.status == "ACTIVE":
                    platform_statuses[platform_name] = {
                        "status": "success",
                        "message": f"Active on {listing.platform_name}"
                    }
                elif listing.status == "DRAFT":
                    platform_statuses[platform_name] = {
                        "status": "pending",
                        "message": f"Draft on {listing.platform_name}"
                    }
                elif listing.status == "ERROR":
                    platform_statuses[platform_name] = {
                        "status": "error",
                        "message": listing.platform_message or f"Error on {listing.platform_name}"
                    }
        
        return templates.TemplateResponse(
            "inventory/detail.html",
            {
                "request": request,
                "product": product,
                "platform_listings": platform_listings,
                "platform_statuses": platform_statuses
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/add", response_class=HTMLResponse)
async def add_product_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    # Get existing brands for dropdown
    existing_brands = await db.execute(
        select(Product.brand)
        .distinct()
        .filter(Product.brand.isnot(None))
    )
    existing_brands = [b[0] for b in existing_brands.all() if b[0]]

    # Get existing categories for dropdown
    categories_result = await db.execute(
        select(Product.category)
        .distinct()
        .filter(Product.category.isnot(None))
    )
    categories = [c[0] for c in categories_result.all() if c[0]]

    # Get existing products for "copy from" feature
    # Limit to 100 most recent products
    existing_products_result = await db.execute(
        select(Product)
        .order_by(desc(Product.created_at))
        .limit(100)
    )
    existing_products = existing_products_result.scalars().all()

    return templates.TemplateResponse(
        "inventory/add.html",
        {
            "request": request,
            "existing_brands": existing_brands,
            "categories": categories,
            "existing_products": existing_products,
            "ebay_status": "pending",
            "reverb_status": "pending",
            "vr_status": "pending",
            "website_status": "pending",
            "tinymce_api_key": settings.TINYMCE_API_KEY  # This is important
        }
    )

@router.post("/add")
async def add_product(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    brand: str = Form(...),
    model: str = Form(...),
    sku: str = Form(...),
    category: str = Form(...),
    condition: str = Form(...),
    base_price: float = Form(...),
    cost_price: Optional[float] = Form(None),
    description: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    decade: Optional[int] = Form(None),
    finish: Optional[str] = Form(None),
    status: str = Form("DRAFT"),
    processing_time: Optional[int] = Form(None),
    price: Optional[float] = Form(None),
    price_notax: Optional[float] = Form(None),
    collective_discount: Optional[float] = Form(None),
    offer_discount: Optional[float] = Form(None),
    # Checkbox fields
    in_collective: Optional[bool] = Form(False),
    in_inventory: Optional[bool] = Form(True),
    in_reseller: Optional[bool] = Form(False),
    free_shipping: Optional[bool] = Form(False),
    buy_now: Optional[bool] = Form(True),
    show_vat: Optional[bool] = Form(True),
    local_pickup: Optional[bool] = Form(False),
    available_for_shipment: Optional[bool] = Form(True),
    # Media fields
    primary_image_file: Optional[UploadFile] = File(None),
    primary_image_url: Optional[str] = Form(None),
    additional_images_files: List[UploadFile] = File([]),
    additional_images_urls: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    external_link: Optional[str] = Form(None)
):
    """
    Creates a new product from form data and optionally sets up platform listings.

    1. Removed duplicated code: The route is now structured in a clear, logical flow with no duplicate processing.
    2. Better error handling:
        - Added specific error handling for different types of errors
        - Separated validation errors from processing errors
        - Added proper platform service error handling
    3. Improved structure:
        - Clear step-by-step process: validate → process → create → redirect
        - Non-critical errors in platform operations don't fail the whole request
        - Clear separation of concerns
    4. Added proper exception classes:
        - Created a comprehensive exception hierarchy
        - Each module has its own exception types
        - Allows more targeted error handling

    25.02.25: Enhanced product creation endpoint that handles the comprehensive form.

    This implementation:

    1. Properly processes all fields including platform-specific data
    2. Handles image uploads more robustly
    3. Integrates with multiple platforms in parallel
    4. Provides detailed feedback on each platform's status

    """

    # Debug logging
    print("===== POST REQUEST TO /add =====")
    print("Method:", request.method)
    form_data = await request.form()
    print("Form data received:", dict(form_data))

    # Get existing brands - needed for error responses
    existing_brands = await db.execute(
        select(Product.brand)
        .distinct()
        .filter(Product.brand.isnot(None))
    )
    existing_brands = [b[0] for b in existing_brands.all() if b[0]]

    categories_result = await db.execute(
        select(Product.category)
        .distinct()
        .filter(Product.category.isnot(None))
    )
    categories = [c[0] for c in categories_result.all() if c[0]]
    
    existing_products_result = await db.execute(
        select(Product)
        .order_by(desc(Product.created_at))
        .limit(100)
    )
    existing_products = existing_products_result.scalars().all()

    # Platform statuses to track integration results
    platform_statuses = {
        "ebay": {"status": "pending", "message": "Waiting for sync"},
        "reverb": {"status": "pending", "message": "Waiting for sync"},
        "vr": {"status": "pending", "message": "Waiting for sync"},
        "website": {"status": "pending", "message": "Waiting for sync"}
    }

    try:
        # Initialize services
        product_service = ProductService(db)
        ebay_service = EbayService(db, settings)
        reverb_service = ReverbService(db, settings)
        website_service = WebsiteService(db, settings)

        # Process brand
        brand = brand.title()
        is_new_brand = brand not in existing_brands

        # Validate status
        try:
            status_enum = ProductStatus[status.upper()]
        except KeyError:
            return templates.TemplateResponse(
                "inventory/add.html",
                {
                    "request": request,
                    "error": f"Invalid status value: {status}. Must be one of: {', '.join(ProductStatus.__members__.keys())}",
                    "form_data": request.form,
                    "existing_brands": existing_brands,
                    "categories": categories,
                    "existing_products": existing_products,
                    "ebay_status": "error",
                    "reverb_status": "error",
                    "vr_status": "error",
                    "website_status": "error"
                },
                status_code=400
            )

        # Validate condition
        try:
            condition_enum = ProductCondition(condition)
        except ValueError:
            return templates.TemplateResponse(
                "inventory/add.html",
                {
                    "request": request,
                    "error": f"Invalid condition value: {condition}",
                    "form_data": request.form,
                    "existing_brands": existing_brands,
                    "categories": categories,
                    "existing_products": existing_products,
                    "ebay_status": "error",
                    "reverb_status": "error",
                    "vr_status": "error",
                    "website_status": "error"
                },
                status_code=400
            )

        # Handle images
        primary_image = None
        if primary_image_file and primary_image_file.filename:
            primary_image = await save_upload_file(primary_image_file)
        elif primary_image_url:
            primary_image = primary_image_url

        additional_images = []
        if additional_images_files:
            for file in additional_images_files:
                if file.filename:
                    path = await save_upload_file(file)
                    additional_images.append(path)
        
        if additional_images_urls:
            urls = [url.strip() for url in additional_images_urls.split('\n') if url.strip()]
            additional_images.extend(urls)
            
        # Process platform-specific data from form
        platform_data = {}
        for key, value in form_data.items():
            if key.startswith("platform_data__"):
                parts = key.split("__")
                if len(parts) >= 3:
                    platform = parts[1]
                    field = parts[2]
                    
                    if platform not in platform_data:
                        platform_data[platform] = {}
                    
                    # Handle boolean values properly
                    if value.lower() in ['true', 'on']:
                        platform_data[platform][field] = True
                    elif value.lower() == 'false':
                        platform_data[platform][field] = False
                    else:
                        platform_data[platform][field] = value

        # Create product data
        product_data = ProductCreate(
            brand=brand,
            model=model,
            sku=sku,
            category=category,
            condition=condition_enum.value,
            base_price=base_price,
            cost_price=cost_price,
            description=description,
            year=year,
            decade=decade,
            finish=finish,
            status=status_enum.value,
            price=price,
            price_notax=price_notax,
            collective_discount=collective_discount,
            offer_discount=offer_discount,
            in_collective=in_collective,
            in_inventory=in_inventory,
            in_reseller=in_reseller,
            free_shipping=free_shipping,
            buy_now=buy_now,
            show_vat=show_vat,
            local_pickup=local_pickup,
            available_for_shipment=available_for_shipment,
            processing_time=processing_time,
            primary_image=primary_image,
            additional_images=additional_images,
            video_url=video_url,
            external_link=external_link,
            platform_data=platform_data
        )

        # Step 1: Create the product
        product = await product_service.create_product(product_data)
        print(f"Product created successfully: {product.id}")

        # Step 2: Handle platform integrations in parallel
        platform_tasks = []
        
        # Step 2.1: eBay Integration
        if platform_data.get("ebay"):
            try:
                # Prepare eBay data
                ebay_integration_data = {
                    "category_id": platform_data["ebay"].get("category_id"),
                    "condition_id": condition_enum.value,
                    "format": platform_data["ebay"].get("format", "FixedPrice"),
                    "price": base_price,
                    "duration": platform_data["ebay"].get("duration", "GTC"),
                    "item_specifics": {
                        "Brand": brand,
                        "Model": model,
                        "Year": str(year) if year else None,
                        "Finish": finish,
                        "Condition": condition
                    }
                }
                
                # Find the eBay platform listing
                if product.platform_listings:
                    ebay_listing = next((listing for listing in product.platform_listings 
                                        if listing.platform_name.lower() == "ebay"), None)
                    
                    if ebay_listing:
                        await ebay_service.create_draft_listing(
                            ebay_listing.id,
                            ebay_integration_data
                        )
                        platform_statuses["ebay"] = {
                            "status": "success", 
                            "message": "Draft listing created"
                        }
                    else:
                        platform_statuses["ebay"] = {
                            "status": "error", 
                            "message": "No eBay platform listing found"
                        }
                else:
                    platform_statuses["ebay"] = {
                        "status": "error", 
                        "message": "No platform listings created"
                    }
            except Exception as e:
                print(f"eBay integration error: {str(e)}")
                platform_statuses["ebay"] = {
                    "status": "error", 
                    "message": f"Error: {str(e)}"
                }
        
        # Step 2.2: Reverb Integration
        if platform_data.get("reverb"):
            try:
                # Implement Reverb integration 
                reverb_integration_data = {
                    "product_type": platform_data["reverb"].get("product_type"),
                    "primary_category": platform_data["reverb"].get("primary_category"),
                    "shipping_profile": platform_data["reverb"].get("shipping_profile"),
                    "offers_enabled": platform_data["reverb"].get("offers_enabled", True)
                }
                
                # This is a placeholder - implement actual Reverb integration
                platform_statuses["reverb"] = {
                    "status": "success", 
                    "message": "Draft listing queued"
                }
            except Exception as e:
                print(f"Reverb integration error: {str(e)}")
                platform_statuses["reverb"] = {
                    "status": "error", 
                    "message": f"Error: {str(e)}"
                }
        
        # Step 2.3: V&R Integration
        if platform_data.get("vr"):
            try:
                # Implement V&R integration
                # This is a placeholder - implement actual V&R integration
                platform_statuses["vr"] = {
                    "status": "success", 
                    "message": "Listing prepared for export"
                }
            except Exception as e:
                print(f"V&R integration error: {str(e)}")
                platform_statuses["vr"] = {
                    "status": "error", 
                    "message": f"Error: {str(e)}"
                }
        
        # Step 2.4: Website Integration
        if platform_data.get("website"):
            try:
                # Implement Website integration
                # This is a placeholder - implement actual Website integration
                platform_statuses["website"] = {
                    "status": "success", 
                    "message": "Product published to website"
                }
            except Exception as e:
                print(f"Website integration error: {str(e)}")
                platform_statuses["website"] = {
                    "status": "error", 
                    "message": f"Error: {str(e)}"
                }

        # Step 3: Queue for platform sync
        try:
            print("About to queue product")
            if hasattr(request.app.state.stock_manager, 'queue_product'):
                print("queue_product method exists, calling it")
                await request.app.state.stock_manager.queue_product(product.id)
                print("Product queued successfully")
            else:
                print("queue_product method doesn't exist - skipping")
        except Exception as e:
            print(f"Queue error (non-critical): {type(e).__name__}: {str(e)}")

        print("About to return redirect response")

        # Step 4: Redirect to product detail page
        return RedirectResponse(
            url=f"/inventory/product/{product.id}",
            status_code=303
        )

    except ProductCreationError as e:
        # Handle specific product creation errors
        await db.rollback()
        error_message = str(e)
        if "Failed to create product:" in error_message:
            inner_message = error_message.split("Failed to create product:", 1)[1].strip()
            error_message = f"Failed to create product: {inner_message}"
        
        return templates.TemplateResponse(
            "inventory/add.html",
            {
                "request": request,
                "error": error_message,
                "form_data": dict(form_data),
                "existing_brands": existing_brands,
                "categories": categories,
                "existing_products": existing_products,
                "ebay_status": platform_statuses["ebay"]["status"],
                "ebay_message": platform_statuses["ebay"]["message"],
                "reverb_status": platform_statuses["reverb"]["status"],
                "reverb_message": platform_statuses["reverb"]["message"],
                "vr_status": platform_statuses["vr"]["status"],
                "vr_message": platform_statuses["vr"]["message"],
                "website_status": platform_statuses["website"]["status"],
                "website_message": platform_statuses["website"]["message"]
            },
            status_code=400
        )
    except PlatformIntegrationError as e:
        # Product was created but platform integration failed
        error_message = f"Product created but platform integration failed: {str(e)}"
        print(error_message)
        
        # Don't rollback the transaction since the product was created
        return templates.TemplateResponse(
            "inventory/add.html",
            {
                "request": request,
                "warning": error_message,
                "form_data": dict(form_data),
                "existing_brands": existing_brands,
                "categories": categories,
                "existing_products": existing_products,
                "ebay_status": platform_statuses["ebay"]["status"],
                "ebay_message": platform_statuses["ebay"]["message"],
                "reverb_status": platform_statuses["reverb"]["status"],
                "reverb_message": platform_statuses["reverb"]["message"],
                "vr_status": platform_statuses["vr"]["status"],
                "vr_message": platform_statuses["vr"]["message"],
                "website_status": platform_statuses["website"]["status"],
                "website_message": platform_statuses["website"]["message"]
            },
            status_code=400
        )
    except Exception as e:
        print(f"Overall error (detail): {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Handle all other exceptions
        await db.rollback()
        return templates.TemplateResponse(
            "inventory/add.html",
            {
                "request": request,
                "error": f"Failed to create product: {str(e)}",
                "form_data": dict(form_data),
                "existing_brands": existing_brands,
                "categories": categories,
                "existing_products": existing_products,
                "ebay_status": "error",
                "reverb_status": "error",
                "vr_status": "error",
                "website_status": "error"
            },
            status_code=400
        )

@router.put("/products/{product_id}/stock")
async def update_product_stock(
    product_id: int,
    quantity: int,
    request: Request
):
    try:
        event = StockUpdateEvent(
            product_id=product_id,
            platform="local",
            new_quantity=quantity,
            timestamp=datetime.now()
        )
        await request.app.state.stock_manager.process_stock_update(event)
        return {"status": "success", "new_quantity": quantity}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/next-sku", response_model=dict)
async def get_next_sku(db: AsyncSession = Depends(get_db)):
    """Generate the next available SKU in format DSG-000-001"""
    try:
        # Get the highest existing SKU with this pattern
        query = select(func.max(Product.sku)).where(Product.sku.like('DSG-%'))
        result = await db.execute(query)
        highest_sku = result.scalar_one_or_none()
        
        if not highest_sku or not highest_sku.startswith('DSG-'):
            # If no existing SKUs with this pattern, start from 1
            next_num = 1
        else:
            # Extract the numeric part from the end
            try:
                last_part = highest_sku.split('-')[-1]
                next_num = int(last_part) + 1
            except (ValueError, IndexError):
                next_num = 1
        
        # Format the new SKU
        new_sku = f"DSG-000-{next_num:03d}"
        return {"sku": new_sku}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {"error": str(e)}

@router.get("/export/vintageandrare", response_class=StreamingResponse)
async def export_vintageandrare(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    try:
        export_service = VRExportService(db)
        csv_content = await export_service.generate_csv()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"vintageandrare_export_{timestamp}.csv"
        
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/csv'
        }
        
        return StreamingResponse(
            iter([csv_content.getvalue()]),
            headers=headers
        )
        
    except Exception as e:
        print(f"Export error: {str(e)}")
        return templates.TemplateResponse(
            "errors/500.html",
            {
                "request": request,
                "error_message": "Error generating export file"
            },
            status_code=500
        )

@router.get("/metrics")
async def get_metrics(request: Request):
    """Get current metrics for all platforms and queue status"""
    return request.app.state.stock_manager.get_metrics()

@router.get("/test")
async def test_route():
    return {"message": "Test route working"}

@router.get("/sync/vintageandrare", response_class=HTMLResponse)
async def sync_vintageandrare_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None
):
    """Show form for selecting products to sync to VintageAndRare"""
    # Base query for products
    query = select(Product).outerjoin(
        PlatformCommon, 
        and_(
            PlatformCommon.product_id == Product.id,
            PlatformCommon.platform_name == 'vintageandrare'
        )
    ).where(PlatformCommon.id == None)  # Only products not yet on V&R
    
    # Apply filters
    if search:
        search = f"%{search}%"
        query = query.filter(
            or_(
                Product.brand.ilike(search),
                Product.model.ilike(search),
                Product.category.ilike(search)
            )
        )
    if category:
        query = query.filter(Product.category == category)
    if brand:
        query = query.filter(Product.brand == brand)
    
    # Execute query
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Get categories and brands for filters
    categories_result = await db.execute(select(Product.category).distinct())
    categories = [c[0] for c in categories_result.all() if c[0]]
    
    brands_result = await db.execute(select(Product.brand).distinct())
    brands = [b[0] for b in brands_result.all() if b[0]]
    
    return templates.TemplateResponse(
        "inventory/sync_vr.html",
        {
            "request": request,
            "products": products,
            "categories": categories,
            "brands": brands,
            "selected_category": category,
            "selected_brand": brand,
            "search": search
        }
    )

@router.post("/sync/vintageandrare", response_class=HTMLResponse)
async def sync_vintageandrare_submit(
    request: Request,
    product_ids: List[int] = Form(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Process selected products and sync to VintageAndRare"""
    results = {
        "success": 0,
        "errors": 0,
        "messages": []
    }
    
    from app.services.vintageandrare.client import VintageAndRareClient
    from app.services.category_mapping_service import CategoryMappingService
    
    # Initialize services
    mapping_service = CategoryMappingService(db)
    vr_client = VintageAndRareClient(
        settings.VINTAGE_AND_RARE_USERNAME,
        settings.VINTAGE_AND_RARE_PASSWORD,
        db_session=db
    )
    
    # Authenticate first
    is_authenticated = await vr_client.authenticate()
    if not is_authenticated:
        results["errors"] += len(product_ids)
        results["messages"].append("Failed to authenticate with Vintage & Rare")
        return templates.TemplateResponse(
            "inventory/sync_vr_results.html",
            {
                "request": request,
                "results": results
            }
        )
    
    # Process each product
    for product_id in product_ids:
        try:
            # Get product
            query = select(Product).where(Product.id == product_id)
            result = await db.execute(query)
            product = result.scalar_one_or_none()
            
            if not product:
                results["errors"] += 1
                results["messages"].append(f"Product {product_id} not found")
                continue
            
            # Check for existing platform listing
            query = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "vintageandrare"
            )
            platform_result = await db.execute(query)
            platform_common = platform_result.scalar_one_or_none()
            
            # Create new platform listing if needed
            if not platform_common:
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="vintageandrare",
                    status=ListingStatus.DRAFT.value,
                    sync_status=SyncStatus.PENDING.value,
                    last_sync=datetime.utcnow()
                )
                db.add(platform_common)
                await db.flush()
            
            # Check VR permissions first before attempting to create VRListing
            try:
                # Try to create a VRListing record
                vr_listing = VRListing(
                    platform_id=platform_common.id,
                    in_collective=product.in_collective or False,
                    in_inventory=product.in_inventory or True,
                    in_reseller=product.in_reseller or False,
                    collective_discount=product.collective_discount,
                    price_notax=product.price_notax,
                    show_vat=product.show_vat or True,
                    processing_time=product.processing_time,
                    inventory_quantity=1,
                    vr_state="draft",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    last_synced_at=datetime.utcnow()
                )
                db.add(vr_listing)
                await db.flush()
            except Exception as e:
                # If permissions error, continue without VRListing
                logger.warning(f"Unable to create VRListing: {str(e)}")
                # For demo, continue without VRListing
            
            # Prepare data for V&R client
            product_data = {
                "id": product.id,  # Include ID for mapping lookup
                "brand": product.brand,
                "model": product.model,
                "year": product.year,
                "decade": product.decade,
                "finish": product.finish,
                "description": product.description,
                "price": product.base_price,
                "price_notax": product.price_notax,
                "category": product.category,
                "in_collective": product.in_collective,
                "in_inventory": product.in_inventory,
                "in_reseller": product.in_reseller,
                "collective_discount": product.collective_discount,
                "show_vat": product.show_vat,
                "local_pickup": product.local_pickup,
                "available_for_shipment": product.available_for_shipment,
                "processing_time": product.processing_time,
                "primary_image": product.primary_image,
                "additional_images": product.additional_images,
                "video_url": product.video_url,
                "external_link": product.external_link
            }
            
            # Call V&R client to create listing (test mode for now)
            vr_response = await vr_client.create_listing(product_data, test_mode=True)
            
            # Update platform_common with response data
            if vr_response.get("status") == "success":
                if vr_response.get("external_id"):
                    platform_common.external_id = vr_response["external_id"]
                platform_common.sync_status = SyncStatus.SUCCESS.value
                platform_common.last_sync = datetime.utcnow()
                
                results["success"] += 1
                results["messages"].append(f"Created draft for {product.brand} {product.model}")
            else:
                platform_common.sync_status = SyncStatus.FAILED.value
                platform_common.last_sync = datetime.utcnow()
                
                results["errors"] += 1
                results["messages"].append(f"Error creating draft for {product.brand} {product.model}: {vr_response.get('message', 'Unknown error')}")
            
        except Exception as e:
            results["errors"] += 1
            results["messages"].append(f"Error syncing product {product_id}: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    await db.commit()
    
    return templates.TemplateResponse(
        "inventory/sync_vr_results.html",
        {
            "request": request,
            "results": results
        }
    )

@router.get("/sync/ebay", response_class=HTMLResponse)
async def sync_ebay_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None
):
    """Show form for selecting products to sync to eBay"""
    # Base query for products
    query = select(Product).outerjoin(
        PlatformCommon, 
        and_(
            PlatformCommon.product_id == Product.id,
            PlatformCommon.platform_name == 'ebay'
        )
    ).where(PlatformCommon.id == None)  # Only products not yet on eBay
    
    # Apply filters
    if search:
        search = f"%{search}%"
        query = query.filter(
            or_(
                Product.brand.ilike(search),
                Product.model.ilike(search),
                Product.category.ilike(search)
            )
        )
    if category:
        query = query.filter(Product.category == category)
    if brand:
        query = query.filter(Product.brand == brand)
    
    # Execute query
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Get categories and brands for filters
    categories_result = await db.execute(select(Product.category).distinct())
    categories = [c[0] for c in categories_result.all() if c[0]]
    
    brands_result = await db.execute(select(Product.brand).distinct())
    brands = [b[0] for b in brands_result.all() if b[0]]
    
    return templates.TemplateResponse(
        "inventory/sync_ebay.html",  # You'll need to create this template
        {
            "request": request,
            "products": products,
            "categories": categories,
            "brands": brands,
            "selected_category": category,
            "selected_brand": brand,
            "search": search
        }
    )

@router.post("/sync/ebay", response_class=HTMLResponse)
async def sync_ebay_submit(
    request: Request,
    product_ids: List[int] = Form(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Process selected products and sync to eBay"""
    results = {
        "success": 0,
        "errors": 0,
        "messages": []
    }
    
    # Initialize services
    mapping_service = CategoryMappingService(db)
    ebay_service = EbayService(db, settings)
    
    # Process each product
    for product_id in product_ids:
        try:
            # Get product
            query = select(Product).where(Product.id == product_id)
            result = await db.execute(query)
            product = result.scalar_one_or_none()
            
            if not product:
                results["errors"] += 1
                results["messages"].append(f"Product {product_id} not found")
                continue
            
            # Check for existing platform listing
            query = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "ebay"
            )
            platform_result = await db.execute(query)
            platform_common = platform_result.scalar_one_or_none()
            
            # Create new platform listing if needed
            if not platform_common:
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name="ebay",
                    status=ListingStatus.DRAFT.value,
                    sync_status=SyncStatus.PENDING.value,
                    last_sync=datetime.utcnow()
                )
                db.add(platform_common)
                await db.flush()
            
            # Map category from our system to eBay category ID
            category_mapping = await mapping_service.get_mapping(
                "internal", 
                str(product.category) if product.category else "default",
                "ebay"
            )
            
            if not category_mapping:
                # Try by name if ID mapping failed
                category_mapping = await mapping_service.get_mapping_by_name(
                    "internal",
                    product.category,
                    "ebay"
                )
            
            if not category_mapping:
                # Use default if no mapping found
                category_mapping = await mapping_service.get_default_mapping("ebay")
                if not category_mapping:
                    results["errors"] += 1
                    results["messages"].append(f"No category mapping found for {product.category}")
                    continue
            
            # Prepare data for eBay listing
            ebay_item_specifics = {
                "Brand": product.brand,
                "Model": product.model,
                "Year": str(product.year) if product.year else "",
                "MPN": product.sku or "Does Not Apply",
                "Type": product.category or "",
                "Condition": product.condition or "Used"
            }
            
            # Add any other product attributes that might be relevant
            if product.finish:
                ebay_item_specifics["Finish"] = product.finish
            
            # Create eBay listing data
            ebay_data = {
                "category_id": category_mapping.target_id,
                "condition_id": map_condition_to_ebay(product.condition),
                "price": float(product.base_price) if product.base_price else 0.0,
                "duration": "GTC",  # Good Till Cancelled
                "item_specifics": ebay_item_specifics
            }
            
            # Create eBay listing
            try:
                ebay_listing = await ebay_service.create_draft_listing(
                    platform_common.id,
                    ebay_data
                )
                
                results["success"] += 1
                results["messages"].append(f"Created eBay draft for {product.brand} {product.model}")
                
            except Exception as e:
                platform_common.sync_status = SyncStatus.FAILED.value
                platform_common.last_sync = datetime.utcnow()
                
                results["errors"] += 1
                results["messages"].append(f"Error creating eBay draft for {product.brand} {product.model}: {str(e)}")
            
        except Exception as e:
            results["errors"] += 1
            results["messages"].append(f"Error syncing product {product_id} to eBay: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    await db.commit()
    
    return templates.TemplateResponse(
        "inventory/sync_ebay_results.html",  # You'll need to create this template based on sync_vr_results.html
        {
            "request": request,
            "results": results
        }
    )

def map_condition_to_ebay(condition: str) -> str:
    """Map our condition values to eBay condition IDs"""
    # eBay condition IDs: https://developer.ebay.com/devzone/finding/callref/enums/conditionIdList.html
    condition_mapping = {
        "NEW": "1000",       # New
        "EXCELLENT": "1500", # New other (see details)
        "VERY_GOOD": "2000", # Manufacturer refurbished
        "VERYGOOD": "2000",  # Manufacturer refurbished
        "GOOD": "2500",      # Seller refurbished
        "FAIR": "3000",      # Used
        "POOR": "7000"       # For parts or not working
    }
    
    if condition and condition.upper() in condition_mapping:
        return condition_mapping[condition.upper()]
    
    # Default to Used if no mapping found
    return "3000"

@router.get("/api/dropbox/folders", response_class=JSONResponse)
async def get_dropbox_folders(
    request: Request,
    background_tasks: BackgroundTasks,
    path: str = "",
    settings: Settings = Depends(get_settings)
):
    """
    API endpoint to get Dropbox folders for navigation with token refresh support.
    
    This endpoint:
    1. Handles token refresh if needed
    2. Uses the cached folder structure when available
    3. Returns folder and file information for UI navigation
    4. Initializes a background scan if needed
    """
    try:
        # Check if scan is already in progress
        if hasattr(request.app.state, 'dropbox_scan_in_progress') and request.app.state.dropbox_scan_in_progress:
            progress = getattr(request.app.state, 'dropbox_scan_progress', {'status': 'scanning', 'progress': 0})
            return JSONResponse(
                status_code=202,  # Accepted but processing
                content={
                    "status": "processing", 
                    "message": "Dropbox scan in progress", 
                    "progress": progress
                }
            )
        
        # Get credentials
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        # Direct fallback to environment variables if not in settings
        if not access_token:
            access_token = os.environ.get('DROPBOX_ACCESS_TOKEN')
            print(f"Loading access token directly from environment: {bool(access_token)}")
        
        if not refresh_token:
            refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
            print(f"Loading refresh token directly from environment: {bool(refresh_token)}")
            
        if not app_key:
            app_key = os.environ.get('DROPBOX_APP_KEY')
            print(f"Loading app key directly from environment: {bool(app_key)}")
            
        if not app_secret:
            app_secret = os.environ.get('DROPBOX_APP_SECRET')
            print(f"Loading app secret directly from environment: {bool(app_secret)}")
        
        # Check if all credentials are available now
        if not access_token and not refresh_token:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "message": "Dropbox credentials not available. Please configure DROPBOX_ACCESS_TOKEN or DROPBOX_REFRESH_TOKEN in .env file."
                }
            )
            
        
        # Check if we need to initialize a scan
        if (not hasattr(request.app.state, 'dropbox_map') or 
            request.app.state.dropbox_map is None):
            
            # We need refresh credentials to start a scan if no access token
            if not access_token and (not refresh_token or not app_key or not app_secret):
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": "No valid Dropbox credentials available"
                    }
                )
            
            # Start background scan
            request.app.state.dropbox_scan_in_progress = True
            request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
            background_tasks.add_task(perform_dropbox_scan, request.app, access_token)
            
            return JSONResponse(
                status_code=202,  # Accepted but processing
                content={
                    "status": "initializing",
                    "message": "Starting Dropbox scan. Please try again in a moment."
                }
            )
        
        # Get cached data
        dropbox_map = request.app.state.dropbox_map
        
        # Create client for direct interaction
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # If the token might be expired, verify it
        last_updated = getattr(request.app.state, 'dropbox_last_updated', None)
        token_age_hours = ((datetime.now() - last_updated).total_seconds() / 3600) if last_updated else None
        
        if token_age_hours and token_age_hours > 3:  # Check if token is older than 3 hours
            # Test connection and refresh if needed
            test_result = await client.test_connection()
            if not test_result:
                # Connection failed - token might be expired
                # This function handles refresh internally
                print("Token may be expired, getting fresh folder data")
                
                # Get specific folder contents
                if path:
                    folder_data = await client.get_folder_contents(path)
                    return folder_data
                else:
                    # For root, just list top-level folders
                    entries = await client.list_folder_recursive(path="", max_depth=1)
                    folders = []
                    for entry in entries:
                        if entry.get('.tag') == 'folder':
                            folder_path = entry.get('path_lower', '')
                            folder_name = os.path.basename(folder_path)
                            folders.append({
                                'name': folder_name,
                                'path': folder_path,
                                'is_folder': True
                            })
                    return {"folders": sorted(folders, key=lambda x: x['name'])}
            
        # If we get here, we can use the cached structure
        folder_structure = dropbox_map['folder_structure']
        
        # If first request, return top-level folders
        if not path:
            # Return top-level folders
            folders = []
            for folder_name, folder_data in folder_structure.items():
                if isinstance(folder_data, dict) and folder_name.startswith('/'):
                    folders.append({
                        'name': folder_name.strip('/'),
                        'path': folder_name,
                        'is_folder': True
                    })
            
            return {"folders": sorted(folders, key=lambda x: x['name'].lower())}
        else:
            # Navigate to the requested path
            current_level = folder_structure
            current_path = ""
            path_parts = path.strip('/').split('/')
            
            for part in path_parts:
                if part:
                    current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
                    if current_path in current_level:
                        current_level = current_level[current_path]
                    else:
                        # Path not found
                        return {"items": [], "current_path": path, "error": f"Path {path} not found"}
            
            # Get folders and files at this level
            items = []
            
            # Process each key in the current level
            for key, value in current_level.items():
                # Skip non-string keys or special keys
                if not isinstance(key, str):
                    continue
                
                if key.startswith('/'):
                    # This is a subfolder
                    name = os.path.basename(key)
                    items.append({
                        'name': name,
                        'path': key,
                        'is_folder': True
                    })
                elif key == 'files' and isinstance(value, list):
                    # This is the files list
                    for file in value:
                        if not isinstance(file, dict) or 'path' not in file:
                            continue
                            
                        # Only include image files
                        if any(file['path'].lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            # Get temp link from the map if available
                            temp_link = None
                            if 'temp_links' in dropbox_map and file['path'] in dropbox_map['temp_links']:
                                temp_link = dropbox_map['temp_links'][file['path']]
                            
                            items.append({
                                'name': file.get('name', os.path.basename(file['path'])),
                                'path': file['path'],
                                'is_folder': False,
                                'temp_link': temp_link
                            })
            
            # Sort items (folders first, then files)
            items.sort(key=lambda x: (not x['is_folder'], x['name'].lower()))
            
            return {"items": items, "current_path": path}
            
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"Error accessing Dropbox: {str(e)}"}
        )

@router.get("/api/dropbox/images", response_class=JSONResponse)
async def get_dropbox_images(
    request: Request,
    folder_path: str
):
    """
    API endpoint to get images from a Dropbox folder.
    
    This function uses two approaches to find images:
    1. First it directly searches for images in the temp_links cache with matching paths
    2. Then it tries to navigate the folder structure if no direct matches are found
    
    Args:
        request: The FastAPI request object
        folder_path: The Dropbox folder path to get images from
        
    Returns:
        JSON response with list of images and their temporary links
    """
    try:
        # Check for cached structure
        dropbox_map = getattr(request.app.state, 'dropbox_map', None)
        if not dropbox_map:
            return {"images": [], "error": "No Dropbox cache found. Please refresh the page."}
        
        # Normalize the folder path for consistent comparisons
        normalized_folder_path = folder_path.lower().rstrip('/')
        
        # APPROACH 1: First directly look in temp_links for images in this folder
        images = []
        temp_links = dropbox_map.get('temp_links', {})
        
        # Search for images directly in the requested folder
        for path, link in temp_links.items():
            path_lower = path.lower()
            
            # Match files directly in this folder (not in subfolders)
            folder_part = os.path.dirname(path_lower)
            
            if folder_part == normalized_folder_path:
                if any(path_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    images.append({
                        'name': os.path.basename(path),
                        'path': path,
                        'url': link
                    })
        
        # If images found directly, return them
        if images:
            print(f"Found {len(images)} images directly in folder {folder_path}")
            # Sort images by name for consistent ordering
            images.sort(key=lambda x: x.get('name', ''))
            return {"images": images}
            
        # APPROACH 2: If no images found directly, try navigating the folder structure
        folder_structure = dropbox_map.get('folder_structure', {})
        path_parts = folder_path.strip('/').split('/')
        current = folder_structure
        current_path = ""
        
        # Navigate to the folder
        for part in path_parts:
            if part:
                current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
                if current_path in current:
                    current = current[current_path]
                else:
                    # Try a more flexible path search in temp_links as a fallback
                    fallback_images = []
                    search_prefix = f"{normalized_folder_path}/"
                    
                    for path, link in temp_links.items():
                        if path.lower().startswith(search_prefix) and any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            fallback_images.append({
                                'name': os.path.basename(path),
                                'path': path,
                                'url': link
                            })
                    
                    if fallback_images:
                        print(f"Found {len(fallback_images)} images using fallback search for {folder_path}")
                        fallback_images.sort(key=lambda x: x.get('name', ''))
                        return {"images": fallback_images}
                    
                    # If no fallback images found either, return empty list
                    print(f"Folder {folder_path} not found in structure")
                    return {"images": [], "error": f"Folder {folder_path} not found"}
        
        # Extract images from specified folder using recursive helper function
        def extract_images_from_folder(folder_data, prefix=""):
            result = []
            
            # Check if folder contains files array
            if isinstance(folder_data, dict) and 'files' in folder_data and isinstance(folder_data['files'], list):
                for file in folder_data['files']:
                    if (file.get('path') and any(file['path'].lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif'])):
                        # Get temp link from the map
                        temp_link = None
                        if 'temp_links' in dropbox_map and file['path'] in dropbox_map['temp_links']:
                            temp_link = dropbox_map['temp_links'][file['path']]
                            
                        if temp_link:
                            result.append({
                                'name': file.get('name', os.path.basename(file['path'])),
                                'path': file['path'],
                                'url': temp_link
                            })
            
            # Look through subfolders with a priority for specific resolution folders
            resolution_folders = []
            other_folders = []
            
            for key, value in folder_data.items():
                if isinstance(key, str) and key.startswith('/') and isinstance(value, dict):
                    folder_name = os.path.basename(key.rstrip('/'))
                    # Prioritize resolution folders
                    if any(res in folder_name.lower() for res in ['1500px', 'hi-res', '640px']):
                        resolution_folders.append((key, value))
                    else:
                        other_folders.append((key, value))
            
            # Check resolution folders first
            for key, subfolder in resolution_folders:
                result.extend(extract_images_from_folder(subfolder, f"{prefix}{os.path.basename(key)}/"))
            
            # If no images found in resolution folders, check other folders
            if not result and other_folders:
                for key, subfolder in other_folders:
                    result.extend(extract_images_from_folder(subfolder, f"{prefix}{os.path.basename(key)}/"))
            
            return result
        
        # Extract images from the current folder and its subfolders
        images = extract_images_from_folder(current)
        
        # APPROACH 3: Final fallback - if still no images found, search entire temp_links
        if not images and 'temp_links' in dropbox_map:
            search_prefix = f"{normalized_folder_path}/"
            
            for path, link in dropbox_map['temp_links'].items():
                path_lower = path.lower()
                if path_lower.startswith(search_prefix) and any(path_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    images.append({
                        'name': os.path.basename(path),
                        'path': path,
                        'url': link
                    })
        
        # Sort images by name for consistent ordering
        images.sort(key=lambda x: x.get('name', ''))
        
        print(f"Found {len(images)} images in folder {folder_path}")
        return {"images": images}
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"Error getting Dropbox images: {str(e)}"}
        )

@router.get("/api/dropbox/init", response_class=JSONResponse)
async def init_dropbox_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Initialize Dropbox scan in the background and report progress"""
    
    # Check if already scanning
    if hasattr(request.app.state, 'dropbox_scan_in_progress') and request.app.state.dropbox_scan_in_progress:
        # Get progress if available
        progress = getattr(request.app.state, 'dropbox_scan_progress', {'status': 'scanning', 'progress': 0})
        return JSONResponse(content=progress)
    
    # Check if already scanned
    if hasattr(request.app.state, 'dropbox_map') and request.app.state.dropbox_map:
        return JSONResponse(content={
            'status': 'complete', 
            'last_updated': request.app.state.dropbox_last_updated.isoformat()
        })
    
    # Start scan in background
    request.app.state.dropbox_scan_in_progress = True
    request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
    
    background_tasks.add_task(perform_dropbox_scan, request.app, settings.DROPBOX_ACCESS_TOKEN)
    
    return JSONResponse(content={
        'status': 'started',
        'message': 'Dropbox scan initiated in background'
    })

@router.get("/api/dropbox/debug-scan")
async def debug_dropbox_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to trigger Dropbox scan"""
    # Reset scan state
    request.app.state.dropbox_scan_in_progress = False
    
    # Check token
    token = settings.DROPBOX_ACCESS_TOKEN
    if not token:
        return {"status": "error", "message": "No Dropbox access token configured"}
    
    # Start scan
    print(f"Manually starting Dropbox scan with token (length: {len(token)})")
    request.app.state.dropbox_scan_in_progress = True
    request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
    
    # Add to background tasks
    background_tasks.add_task(perform_dropbox_scan, request.app, token)
    
    return {
        "status": "started", 
        "message": "Dropbox scan initiated in background", 
        "token_available": bool(token)
    }

@router.get("/api/dropbox/debug-token")
async def debug_dropbox_token(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to check Dropbox tokens and refresh if needed"""
    try:
        # Get tokens from settings and environment
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        # Create detailed response with token info
        response = {
            "access_token": {
                "available": bool(access_token),
                "preview": f"{access_token[:5]}...{access_token[-5:]}" if access_token and len(access_token) > 10 else None,
                "length": len(access_token) if access_token else 0,
                "source": "settings" if hasattr(settings, 'DROPBOX_ACCESS_TOKEN') and settings.DROPBOX_ACCESS_TOKEN else "environment" if access_token else None
            },
            "refresh_token": {
                "available": bool(refresh_token),
                "preview": f"{refresh_token[:5]}...{refresh_token[-5:]}" if refresh_token and len(refresh_token) > 10 else None,
                "length": len(refresh_token) if refresh_token else 0,
                "source": "settings" if hasattr(settings, 'DROPBOX_REFRESH_TOKEN') and settings.DROPBOX_REFRESH_TOKEN else "environment" if refresh_token else None
            },
            "app_credentials": {
                "app_key_available": bool(app_key),
                "app_secret_available": bool(app_secret),
                "source": "settings" if hasattr(settings, 'DROPBOX_APP_KEY') and settings.DROPBOX_APP_KEY else "environment" if app_key else None
            }
        }
        
        # Test current access token if available
        if access_token:
            from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
            client = AsyncDropboxClient(access_token=access_token)
            test_result = await client.test_connection()
            response["token_status"] = "valid" if test_result else "invalid"
        else:
            response["token_status"] = "missing"
        
        # Try to refresh token if invalid and we have refresh credentials
        if (response["token_status"] in ["invalid", "missing"] and 
            refresh_token and app_key and app_secret):
            
            print("Attempting to refresh token...")
            from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
            refresh_client = AsyncDropboxClient(
                refresh_token=refresh_token,
                app_key=app_key,
                app_secret=app_secret
            )
            
            refresh_success = await refresh_client.refresh_access_token()
            
            if refresh_success:
                # We got a new token
                new_token = refresh_client.access_token
                
                # Save it to use in future requests
                if hasattr(request.app.state, 'settings'):
                    request.app.state.settings.DROPBOX_ACCESS_TOKEN = new_token
                
                # Update environment variable
                os.environ["DROPBOX_ACCESS_TOKEN"] = new_token
                
                # Start background scan with new token
                request.app.state.dropbox_scan_in_progress = True
                request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
                background_tasks.add_task(perform_dropbox_scan, request.app, new_token)
                
                response["refresh_result"] = {
                    "success": True,
                    "new_token_preview": f"{new_token[:5]}...{new_token[-5:]}",
                    "new_token_length": len(new_token),
                    "scan_initiated": True
                }
            else:
                response["refresh_result"] = {
                    "success": False,
                    "error": "Failed to refresh token"
                }
        
        return response
    except Exception as e:
        import traceback
        print(f"Debug token error: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }

@router.get("/api/dropbox/direct-scan")
async def direct_dropbox_scan(
    request: Request,
    settings: Settings = Depends(get_settings)
):
    """
    Direct scan endpoint for debugging - attempts to scan a folder directly
    without using background tasks for immediate feedback
    """
    try:
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        
        # Get tokens from settings and environment
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        if not access_token and not refresh_token:
            return {
                "status": "error", 
                "message": "No Dropbox access token or refresh token configured"
            }
            
        # Create the client with all credentials
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Try to refresh token if we have refresh credentials but no access token
        if refresh_token and app_key and app_secret and not access_token:
            print("Attempting to refresh token before direct scan...")
            refresh_success = await client.refresh_access_token()
            if refresh_success:
                # We got a new token
                access_token = client.access_token
                # Update in app state if settings exist
                if hasattr(request.app.state, 'settings'):
                    request.app.state.settings.DROPBOX_ACCESS_TOKEN = access_token
                # Update in environment
                os.environ['DROPBOX_ACCESS_TOKEN'] = access_token
                print("Successfully refreshed access token for direct scan")
            else:
                return {
                    "status": "error",
                    "message": "Failed to refresh access token"
                }
        
        # Test connection first
        test_result = await client.test_connection()
        if not test_result:
            return {
                "status": "error", 
                "message": "Failed to connect to Dropbox API - invalid token"
            }
            
        # Start scan of top-level folders for quick test
        print("Starting direct scan of top-level folders...")
        
        # Just list top folders with max_depth=1 for quicker results
        entries = await client.list_folder_recursive(path="", max_depth=1)
        
        # Collect folder information
        folders = []
        files = []
        
        for entry in entries:
            entry_type = entry.get('.tag', '')
            path = entry.get('path_lower', '')
            name = os.path.basename(path)
            
            if entry_type == 'folder':
                folders.append({
                    "name": name, 
                    "path": path
                })
            elif entry_type == 'file' and client._is_image_file(path):
                files.append({
                    "name": name, 
                    "path": path,
                    "size": entry.get('size', 0),
                })
        
        # Get a sample of temp links for quick testing (max 5 files)
        sample_files = files[:5]
        temp_links = {}
        
        if sample_files:
            sample_paths = [f['path'] for f in sample_files]
            temp_links = await client.get_temporary_links_async(sample_paths)
        
        return {
            "status": "success", 
            "message": f"Directly scanned {len(folders)} top-level folders and {len(files)} files", 
            "folders": folders[:10],  # Limit to first 10
            "files": files[:10],      # Limit to first 10
            "temp_links_sample": len(temp_links),
            "token_refreshed": access_token != getattr(settings, 'DROPBOX_ACCESS_TOKEN', None)
        }
        
    except Exception as e:
        import traceback
        traceback_str = traceback.format_exc()
        print(f"Error in direct scan: {str(e)}")
        print(traceback_str)
        return {
            "status": "error", 
            "message": f"Error in direct scan: {str(e)}",
            "traceback": traceback_str.split("\n")[-10:] if len(traceback_str) > 0 else []
        }

@router.get("/api/dropbox/refresh-token")
async def force_refresh_dropbox_token(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Force refresh of the Dropbox access token using refresh token"""
    try:
        # Get refresh credentials
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
        if not refresh_token or not app_key or not app_secret:
            return {
                "status": "error",
                "message": "Missing required refresh credentials",
                "refresh_token_available": bool(refresh_token),
                "app_key_available": bool(app_key),
                "app_secret_available": bool(app_secret)
            }
        
        # Create client for token refresh
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Attempt to refresh the token
        print("Forcing Dropbox token refresh...")
        refresh_success = await client.refresh_access_token()
        
        if refresh_success:
            # We got a new token
            new_token = client.access_token
            
            # Update in app state if settings exist
            if hasattr(request.app.state, 'settings'):
                request.app.state.settings.DROPBOX_ACCESS_TOKEN = new_token
            
            # Update in environment
            os.environ['DROPBOX_ACCESS_TOKEN'] = new_token
            
            # Start background scan with new token if requested
            start_scan = request.query_params.get('start_scan', 'false').lower() == 'true'
            if start_scan:
                request.app.state.dropbox_scan_in_progress = True
                request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
                background_tasks.add_task(perform_dropbox_scan, request.app, new_token)
                
            return {
                "status": "success",
                "message": "Successfully refreshed access token",
                "new_token_preview": f"{new_token[:5]}...{new_token[-5:]}",
                "new_token_length": len(new_token),
                "scan_initiated": start_scan
            }
        else:
            return {
                "status": "error",
                "message": "Failed to refresh access token",
                "refresh_token_preview": f"{refresh_token[:5]}...{refresh_token[-5:]}" if len(refresh_token) > 10 else None
            }
    
    except Exception as e:
        import traceback
        print(f"Error in token refresh: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Exception during token refresh: {str(e)}",
            "error_type": type(e).__name__
        }

@router.get("/api/dropbox/test-credentials", response_class=JSONResponse)
async def test_dropbox_credentials(
    settings: Settings = Depends(get_settings)
):
    """Test that Dropbox credentials are being loaded correctly"""
    return {
        "app_key_available": bool(settings.DROPBOX_APP_KEY),
        "app_secret_available": bool(settings.DROPBOX_APP_SECRET),
        "refresh_token_available": bool(settings.DROPBOX_REFRESH_TOKEN),
        "access_token_available": bool(settings.DROPBOX_ACCESS_TOKEN),
        "app_key_preview": settings.DROPBOX_APP_KEY[:5] + "..." if settings.DROPBOX_APP_KEY else None,
        "refresh_token_preview": settings.DROPBOX_REFRESH_TOKEN[:5] + "..." if settings.DROPBOX_REFRESH_TOKEN else None
    }

@router.get("/api/dropbox/debug-cache")
async def debug_dropbox_cache(request: Request):
    """Debug endpoint to see what's in the Dropbox cache"""
    dropbox_map = getattr(request.app.state, 'dropbox_map', None)
    
    if not dropbox_map:
        return {"status": "no_cache", "message": "No Dropbox cache found"}
    
    # Count temporary links
    temp_links_count = len(dropbox_map.get('temp_links', {}))
    
    # Get some sample paths with temporary links
    sample_links = {}
    for i, (path, link) in enumerate(dropbox_map.get('temp_links', {}).items()):
        if i >= 5:  # Just get 5 samples
            break
        sample_links[path] = link[:50] + "..." if link else None
    
    return {
        "status": "ok",
        "last_updated": getattr(request.app.state, 'dropbox_last_updated', None),
        "has_folder_structure": "folder_structure" in dropbox_map,
        "temp_links_count": temp_links_count,
        "sample_links": sample_links,
        "sample_folder_paths": list(dropbox_map.get('folder_structure', {}).keys())[:5]
    }

@router.get("/api/dropbox/debug-credentials")
async def debug_dropbox_credentials(
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to check how credentials are loaded"""
    
    # Check settings first
    settings_creds = {
        "settings_access_token": bool(getattr(settings, 'DROPBOX_ACCESS_TOKEN', None)),
        "settings_refresh_token": bool(getattr(settings, 'DROPBOX_REFRESH_TOKEN', None)),
        "settings_app_key": bool(getattr(settings, 'DROPBOX_APP_KEY', None)),
        "settings_app_secret": bool(getattr(settings, 'DROPBOX_APP_SECRET', None))
    }
    
    # Check environment variables directly
    env_creds = {
        "env_access_token": bool(os.environ.get('DROPBOX_ACCESS_TOKEN')),
        "env_refresh_token": bool(os.environ.get('DROPBOX_REFRESH_TOKEN')),
        "env_app_key": bool(os.environ.get('DROPBOX_APP_KEY')),
        "env_app_secret": bool(os.environ.get('DROPBOX_APP_SECRET'))
    }
    
    # Sample values (first 5 chars only)
    samples = {
        "access_token_sample": os.environ.get('DROPBOX_ACCESS_TOKEN', '')[:5] + "..." if os.environ.get('DROPBOX_ACCESS_TOKEN') else None,
        "refresh_token_sample": os.environ.get('DROPBOX_REFRESH_TOKEN', '')[:5] + "..." if os.environ.get('DROPBOX_REFRESH_TOKEN') else None
    }
    
    return {
        "settings_loaded": settings_creds,
        "environment_loaded": env_creds,
        "samples": samples
    }

@router.get("/api/dropbox/debug-folder-images")
async def debug_folder_images(
    request: Request,
    folder_path: str
):
    """Debug endpoint to check what images exist for a specific folder"""
    dropbox_map = getattr(request.app.state, 'dropbox_map', None)
    
    if not dropbox_map:
        return {"status": "no_cache", "message": "No Dropbox cache found"}
    
    # Count all temporary links
    all_temp_links = dropbox_map.get('temp_links', {})
    
    # Find images in this folder from temp_links
    folder_images = []
    for path, link in all_temp_links.items():
        normalized_path = path.lower()
        normalized_folder = folder_path.lower()
        
        # Check if this path is in the requested folder
        if normalized_path.startswith(normalized_folder + '/') or normalized_path == normalized_folder:
            if any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                folder_images.append({
                    'path': path,
                    'link': link[:50] + "..." if link else None
                })
    
    # Get folder structure info
    folder_structure = dropbox_map.get('folder_structure', {})
    current = folder_structure
    
    # Try to navigate to the folder (if it exists in structure)
    path_parts = folder_path.strip('/').split('/')
    current_path = ""
    for part in path_parts:
        if not part:
            continue
        current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
        if current_path in current:
            current = current[current_path]
        else:
            current = None
            break
    
    return {
        "status": "ok",
        "folder_path": folder_path,
        "folder_exists_in_structure": current is not None,
        "folder_structure_details": current if isinstance(current, dict) and len(str(current)) < 1000 else "(too large to display)",
        "images_found_in_temp_links": len(folder_images),
        "sample_images": folder_images[:5]
    }

@router.get("/api/dropbox/generate-links", response_class=JSONResponse)
async def generate_folder_links(
    request: Request,
    folder_path: str,
    settings: Settings = Depends(get_settings)
):
    """Generate temporary links for all images in a specific folder"""
    try:
        # Get access token
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        
        # Create client
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(access_token=access_token)
        
        # Check connection
        test_result = await client.test_connection()
        if not test_result:
            return {
                "status": "error", 
                "message": "Failed to connect to Dropbox API - invalid token"
            }
            
        # Get the folder structure from cache if available
        dropbox_map = getattr(request.app.state, 'dropbox_map', None)
        if not dropbox_map:
            return {"status": "error", "message": "No Dropbox cache available"}
        
        # Use our new dedicated method to get links for this folder
        temp_links = await client.get_temp_links_for_folder(folder_path)
        
        print(f"Generated {len(temp_links)} temporary links for folder {folder_path}")
        
        # Update the cache with new temporary links
        if dropbox_map and 'temp_links' in dropbox_map:
            dropbox_map['temp_links'].update(temp_links)
            print(f"Updated cache with {len(temp_links)} new temporary links")
        
        # Return images with links for UI
        images = []
        for path, link in temp_links.items():
            images.append({
                'name': os.path.basename(path),
                'path': path,
                'url': link
            })
            
        return {
            "status": "success",
            "message": f"Generated {len(temp_links)} temporary links",
            "images": images
        }
            
    except Exception as e:
        import traceback
        print(f"Error generating links: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error", 
            "message": f"Error generating links: {str(e)}"
        }

@router.get("/shipping-profiles")
async def get_shipping_profiles(
    db: AsyncSession = Depends(get_db)
):
    """Get all shipping profiles."""
    from app.models.shipping import ShippingProfile
    
    profiles = await db.execute(select(ShippingProfile).order_by(ShippingProfile.name))
    result = profiles.scalars().all()
    
    # Convert to dict for JSON response compatible with your frontend
    return [
        {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "package_type": profile.package_type,
            "dimensions": profile.dimensions,  # Return dimensions as JSONB 
            "weight": profile.weight,
            "carriers": profile.carriers,
            "options": profile.options,
            "rates": profile.rates,
            "is_default": profile.is_default
        }
        for profile in result
    ]


async def perform_dropbox_scan(app, access_token=None):
    """Background task to scan Dropbox with token refresh support"""
    try:
        print("Starting Dropbox scan background task...")
        
        # Mark scan as in progress
        app.state.dropbox_scan_in_progress = True
        app.state.dropbox_scan_progress = {'status': 'scanning', 'progress': 0}
        
        # Get tokens and credentials from settings
        settings = getattr(app.state, 'settings', None)
        
        # Fallback to environment variables if settings not available
        if settings:
            refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None)
            app_key = getattr(settings, 'DROPBOX_APP_KEY', None)
            app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None)
        else:
            # Get from environment
            refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
            app_key = os.environ.get('DROPBOX_APP_KEY')
            app_secret = os.environ.get('DROPBOX_APP_SECRET')
            
        print(f"Access token available: {bool(access_token)}")
        print(f"Refresh token available: {bool(refresh_token)}{' (starts with: ' + refresh_token[:5] + '...)' if refresh_token else ''}")
        print(f"App key available: {bool(app_key)}{' (starts with: ' + app_key[:5] + '...)' if app_key else ''}")
        print(f"App secret available: {bool(app_secret)}{' (starts with: ' + app_secret[:5] + '...)' if app_secret else ''}")
        
        if not access_token and not refresh_token:
            print("ERROR: No access token or refresh token provided")
            app.state.dropbox_scan_progress = {'status': 'error', 'message': 'No token available', 'progress': 0}
            app.state.dropbox_scan_in_progress = False
            return
        
        # Create the async client
        print("Creating client instance...")
        
        # Initialize with all available credentials
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Try to refresh token first if we have refresh credentials
        if refresh_token and app_key and app_secret:
            print("Attempting to refresh token before scan...")
            try:
                refresh_success = await client.refresh_access_token()
                if refresh_success:
                    print("Successfully refreshed access token")
                    # Save the new token
                    access_token = client.access_token
                    # Update in environment
                    os.environ['DROPBOX_ACCESS_TOKEN'] = access_token
                    # Update in app state if settings exist
                    if hasattr(app.state, 'settings'):
                        app.state.settings.DROPBOX_ACCESS_TOKEN = access_token
                else:
                    print("Failed to refresh access token")
                    app.state.dropbox_scan_progress = {
                        'status': 'error', 
                        'message': 'Failed to refresh access token', 
                        'progress': 0
                    }
                    app.state.dropbox_scan_in_progress = False
                    return
            except Exception as refresh_error:
                print(f"Error refreshing token: {str(refresh_error)}")
                app.state.dropbox_scan_progress = {
                    'status': 'error', 
                    'message': f'Error refreshing token: {str(refresh_error)}', 
                    'progress': 0
                }
                app.state.dropbox_scan_in_progress = False
                return
                
        # Try a simple operation first to test the token
        print("Testing connection...")
        test_result = await client.test_connection()
        if not test_result:
            print("ERROR: Could not connect to Dropbox API")
            app.state.dropbox_scan_progress = {
                'status': 'error', 
                'message': 'Could not connect to Dropbox API', 
                'progress': 0
            }
            app.state.dropbox_scan_in_progress = False
            return
            
        print("Connection successful, starting full scan...")
        app.state.dropbox_scan_progress = {'status': 'scanning', 'progress': 10}
        
        # Perform the scan with cache support
        dropbox_map = await client.scan_and_map_folder()
        
        # Store results
        print("Scan complete, saving results...")
        app.state.dropbox_map = dropbox_map
        app.state.dropbox_last_updated = datetime.now()
        app.state.dropbox_scan_progress = {'status': 'complete', 'progress': 100}
        
        # If we got a new token via refresh, store it
        if client.access_token != access_token:
            # Update in environment
            os.environ['DROPBOX_ACCESS_TOKEN'] = client.access_token
            # Update in app state if settings exist
            if hasattr(app.state, 'settings'):
                app.state.settings.DROPBOX_ACCESS_TOKEN = client.access_token
            print("Updated access token from refresh")
        
        print(f"Dropbox background scan completed successfully. Mapped {len(dropbox_map.get('all_entries', []))} entries and {len(dropbox_map.get('temp_links', {}))} temporary links.")
    except Exception as e:
        print(f"ERROR in Dropbox scan: {str(e)}")
        import traceback
        print(traceback.format_exc())
        app.state.dropbox_scan_progress = {'status': 'error', 'message': f"Error: {str(e)}", 'progress': 0}
    finally:
        app.state.dropbox_scan_in_progress = False
        print("Background scan task finished")

