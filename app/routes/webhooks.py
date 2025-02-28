
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_session
from app.models.webhook import WebhookEvent
from app.services.webhook_processor import process_website_sale
from app.core.config import get_webhook_secret
import hmac
import hashlib

router = APIRouter()

async def verify_webhook_signature(request: Request, webhook_secret: str = Depends(get_webhook_secret)):
    """Verify the webhook signature from the website"""
    signature = request.headers.get("X-Website-Signature")
    if not signature:
        raise HTTPException(status_code=401, detail="No signature provided")
    
    body = await request.body()
    expected_signature = hmac.new(
        webhook_secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

@router.post("/webhooks/website/sale")
async def website_sale_webhook(
    request: Request,
    db: AsyncSession = Depends(get_session),
    _: None = Depends(verify_webhook_signature)
):
    """Endpoint to receive sale webhooks from the website"""
    payload = await request.json()
    
    # Store the webhook event
    webhook_event = WebhookEvent(
        event_type="sale",
        platform="website",
        payload=payload
    )
    db.add(webhook_event)
    await db.commit()
    
    # Process the sale asynchronously
    await process_website_sale(payload, db)
    
    return {"status": "received"}