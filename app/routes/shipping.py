from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional

from app.database import get_session
from app.services.shipping.carriers.dhl import DHLCarrier
from app.services.shipping.data import (
    uk_shipper, uk_receiver, eu_receiver, row_receiver,
    standard_package, eu_customs, row_customs
)

router = APIRouter(
    prefix="/shipping",
    tags=["shipping"],
    responses={404: {"description": "Not found"}},
)

@router.get("/test-dhl/{mode}")
async def test_dhl_endpoint(
    mode: str,
    db: AsyncSession = Depends(get_session)
):
    """Test DHL shipping integration via API."""
    
    # Validate mode
    if mode not in ["uk", "eu", "row"]:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Use 'uk', 'eu', or 'row'")
    
    # Initialize DHL carrier
    dhl_carrier = DHLCarrier(db)
    
    # Create appropriate shipment based on mode
    if mode == "uk":
        result = await dhl_carrier.create_uk_shipment(
            uk_shipper,
            uk_receiver,
            standard_package,
            "TEST-UK-REF-001"
        )
    elif mode == "eu":
        result = await dhl_carrier.create_eu_shipment(
            uk_shipper,
            eu_receiver,
            standard_package,
            eu_customs,
            "TEST-EU-REF-001"
        )
    else:  # mode == "row"
        result = await dhl_carrier.create_row_shipment(
            uk_shipper,
            row_receiver,
            standard_package,
            row_customs,
            "TEST-ROW-REF-001"
        )
    
    # Handle errors
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("details", "Unknown error"))
    
    # Return result
    return result

@router.get("/track/{tracking_number}")
async def track_shipment_endpoint(
    tracking_number: str,
    carrier_code: str = "dhl",
    db: AsyncSession = Depends(get_session)
):
    """Track a shipment using the specified carrier."""
    
    # Only support DHL for now
    if carrier_code.lower() != "dhl":
        raise HTTPException(status_code=400, detail=f"Carrier {carrier_code} not supported yet")
    
    # Initialize DHL carrier
    dhl_carrier = DHLCarrier(db)
    
    # Track shipment
    result = await dhl_carrier.track_shipment(tracking_number)
    
    # Handle errors
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("details", "Unknown error"))
    
    # Return tracking information
    return result