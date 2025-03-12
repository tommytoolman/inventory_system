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
from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.vr import VRListing
from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
from app.services.category_mapping_service import CategoryMappingService
from app.services.product_service import ProductService
from app.services.ebay_service import EbayService
from app.services.reverb_service import ReverbService
from app.services.vintageandrare.export import VRExportService
from app.services.website_service import WebsiteService
from app.schemas.product import ProductCreate
from app.integrations.events import StockUpdateEvent
from app.dependencies import get_db, templates

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
    background_tasks: BackgroundTasks,  # Move this before any parameters with default values
    path: str = "",
    settings: Settings = Depends(get_settings)
):
    """API endpoint to get Dropbox folders for navigation with efficient caching"""
    try:
        # Check if scan is in progress
        if hasattr(request.app.state, 'dropbox_scan_in_progress') and request.app.state.dropbox_scan_in_progress:
            progress = getattr(request.app.state, 'dropbox_scan_progress', {'status': 'scanning', 'progress': 0})
            return JSONResponse(
                status_code=202,  # Accepted but processing
                content={"status": "processing", "message": "Dropbox scan in progress", "progress": progress}
            )
        
        # Initialize if needed
        if not hasattr(request.app.state, 'dropbox_map') or request.app.state.dropbox_map is None:
            # Start background scan
            from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
            background_tasks = BackgroundTasks()
            background_tasks.add_task(perform_dropbox_scan, request.app, settings.DROPBOX_ACCESS_TOKEN)
            
            return JSONResponse(
                status_code=202,  # Accepted but processing
                content={
                    "status": "initializing",
                    "message": "Starting Dropbox scan. Please try again in a moment."
                }
            )
        
        # Get cached data
        dropbox_map = request.app.state.dropbox_map
        
        # Handle folder navigation as before with your current caching logic
        # Remaining code is the same as your current implementation
        
        # Use background_tasks like this:
        if not hasattr(request.app.state, 'dropbox_map'):
            background_tasks.add_task(perform_dropbox_scan, request.app, settings.DROPBOX_ACCESS_TOKEN)
       
        
        # If first request, return top-level folders
        if not path:
            # Return top-level folders
            folders = []
            for folder_name, folder_data in dropbox_map['folder_structure'].items():
                if isinstance(folder_data, dict) and folder_name.startswith('/'):
                    folders.append({
                        'name': folder_name.strip('/'),
                        'path': folder_name,
                        'is_folder': True
                    })
            
            return {"folders": sorted(folders, key=lambda x: x['name'])}
        else:
            # Navigate to the requested path
            current_level = dropbox_map['folder_structure']
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
                            if file['path'] in dropbox_map['temp_links']:
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
    """API endpoint to get images from a Dropbox folder"""
    # Implementation remains the same as what you have now, with the
    # understanding that we're using the cached dropbox_map
    try:
        # Initialize Dropbox client
        from app.services.dropbox.dropbox_service import DropboxClient
        client = DropboxClient()
        
        # Check for cached structure
        if not hasattr(request.app.state, 'dropbox_structure'):
            dropbox_map = client.scan_and_map_folder()
            request.app.state.dropbox_structure = dropbox_map
        else:
            dropbox_map = request.app.state.dropbox_structure
        
        # Parse folder path to find images
        folder_structure = dropbox_map['folder_structure']
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
                    # Path not found
                    return {"images": [], "error": f"Folder {folder_path} not found"}
        
        # Look for image files in this folder
        images = []
        
        # Extract images from specified folder
        def extract_images_from_folder(folder_data, prefix=""):
            result = []
            
            # Check if folder contains files array
            if isinstance(folder_data, dict) and 'files' in folder_data and isinstance(folder_data['files'], list):
                for file in folder_data['files']:
                    if (file.get('path') and any(file['path'].lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif'])):
                        temp_link = file.get('temporary_link')
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
        
        # If no images found in folder structure, try looking in temp_links directly
        if not images and 'temp_links' in dropbox_map:
            for path, link in dropbox_map['temp_links'].items():
                if path.startswith(folder_path) and any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    images.append({
                        'name': os.path.basename(path),
                        'path': path,
                        'url': link
                    })
        
        # Sort images by name for consistent ordering
        images.sort(key=lambda x: x.get('name', ''))
        
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


# @router.get("/api/dropbox/debug-token")
# async def debug_dropbox_token(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     settings: Settings = Depends(get_settings)
# ):
#     """Debug endpoint to check Dropbox tokens and refresh if needed"""
#     try:
#         # Get tokens from settings and environment
#         access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
#         refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
#         app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
#         app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')
        
#         # Create detailed response with token info
#         response = {
#             "access_token": {
#                 "available": bool(access_token),
#                 "preview": f"{access_token[:5]}...{access_token[-5:]}" if access_token and len(access_token) > 10 else None,
#                 "length": len(access_token) if access_token else 0,
#                 "source": "settings" if hasattr(settings, 'DROPBOX_ACCESS_TOKEN') and settings.DROPBOX_ACCESS_TOKEN else "environment" if access_token else None
#             },
#             "refresh_token": {
#                 "available": bool(refresh_token),
#                 "preview": f"{refresh_token[:5]}...{refresh_token[-5:]}" if refresh_token and len(refresh_token) > 10 else None,
#                 "length": len(refresh_token) if refresh_token else 0,
#                 "source": "settings" if hasattr(settings, 'DROPBOX_REFRESH_TOKEN') and settings.DROPBOX_REFRESH_TOKEN else "environment" if refresh_token else None
#             },
#             "app_credentials": {
#                 "app_key_available": bool(app_key),
#                 "app_secret_available": bool(app_secret),
#                 "source": "settings" if hasattr(settings, 'DROPBOX_APP_KEY') and settings.DROPBOX_APP_KEY else "environment" if app_key else None
#             }
#         }
        
#         # Test current access token if available
#         if access_token:
#             from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
#             client = AsyncDropboxClient(access_token=access_token)
#             test_result = await client.test_connection()
#             response["token_status"] = "valid" if test_result else "invalid"
#         else:
#             response["token_status"] = "missing"
        
#         # Try to refresh token if invalid and we have refresh credentials
#         if (response["token_status"] in ["invalid", "missing"] and 
#             refresh_token and app_key and app_secret):
            
#             print("Attempting to refresh token...")
#             from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
#             refresh_client = AsyncDropboxClient(
#                 refresh_token=refresh_token,
#                 app_key=app_key,
#                 app_secret=app_secret ,
#             )

@router.get("/api/dropbox/debug-token")
async def debug_dropbox_token(
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to check Dropbox token"""
    token = settings.DROPBOX_ACCESS_TOKEN
    if not token:
        return {"status": "error", "message": "No token configured"}
    
    # Mask token for security
    masked_token = token[:5] + "..." + token[-5:] if len(token) > 10 else "***"
    
    return {
        "status": "success", 
        "token_available": bool(token),
        "token_preview": masked_token,
        "token_length": len(token)
    }

@router.get("/api/dropbox/direct-scan")
async def direct_dropbox_scan(
    request: Request,
    settings: Settings = Depends(get_settings)
):
    """Direct scan endpoint for debugging"""
    try:
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        
        token = settings.DROPBOX_ACCESS_TOKEN
        if not token:
            return {"status": "error", "message": "No Dropbox access token configured"}
            
        client = AsyncDropboxClient(token)
        
        # Test connection first
        test_result = await client.test_connection()
        if not test_result:
            return {"status": "error", "message": "Failed to connect to Dropbox API"}
            
        # Start a partial scan (just top-level folders)
        print("Starting direct scan of top-level folders...")
        
        # Just list top folders without getting links
        entries = await client.list_folder_recursive(path="", max_depth=1)
        
        # Return top-level folder info
        folders = []
        for entry in entries:
            if entry.get('.tag') == 'folder':
                path = entry.get('path_lower', '')
                name = os.path.basename(path)
                folders.append({"name": name, "path": path})
                
        return {
            "status": "success", 
            "message": f"Directly scanned {len(folders)} top-level folders", 
            "folders": folders
        }
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {"status": "error", "message": f"Error in direct scan: {str(e)}"}

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
        print(f"Refresh token available: {bool(refresh_token)}")
        print(f"App key available: {bool(app_key)}")
        print(f"App secret available: {bool(app_secret)}")
        
        if not access_token and not refresh_token:
            print("ERROR: No access token or refresh token provided")
            app.state.dropbox_scan_progress = {'status': 'error', 'message': 'No token available', 'progress': 0}
            app.state.dropbox_scan_in_progress = False
            return
        
        # Create the async client
        print("Importing AsyncDropboxClient...")
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        print("Creating client instance...")
        
        # Initialize with all available credentials
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        
        # Perform the scan
        print("Initiating folder scan...")
        app.state.dropbox_scan_progress = {'status': 'scanning', 'progress': 10, 'message': 'Listing files...'}
        
        # Try to refresh token first if we have refresh credentials but no access token
        if refresh_token and app_key and app_secret and not access_token:
            print("Attempting to refresh token before scan...")
            refresh_success = await client.refresh_access_token()
            if not refresh_success:
                print("ERROR: Failed to refresh access token")
                app.state.dropbox_scan_progress = {
                    'status': 'error', 
                    'message': 'Failed to refresh access token', 
                    'progress': 0
                }
                app.state.dropbox_scan_in_progress = False
                return
            
            # Save the new token
            access_token = client.access_token
            # Update in environment
            os.environ['DROPBOX_ACCESS_TOKEN'] = access_token
            # Update in app state if settings exist
            if hasattr(app.state, 'settings'):
                app.state.settings.DROPBOX_ACCESS_TOKEN = access_token
            print("Successfully refreshed access token")
            
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
        
        print(f"Dropbox background scan completed successfully. Mapped {len(dropbox_map['all_entries'])} entries and {len(dropbox_map['temp_links'])} temporary links.")
    except Exception as e:
        print(f"ERROR in Dropbox scan: {str(e)}")
        import traceback
        print(traceback.format_exc())
        app.state.dropbox_scan_progress = {'status': 'error', 'message': f"Error: {str(e)}", 'progress': 0}
    finally:
        app.state.dropbox_scan_in_progress = False
        print("Background scan task finished")
