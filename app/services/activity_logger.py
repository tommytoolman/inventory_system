# app/services/activity_logger.py
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog

logger = logging.getLogger(__name__)

class ActivityLogger:
    """
    Service for logging activities throughout the application.
    
    This provides a consistent way to record user and system activities
    for auditing, monitoring, and reporting purposes.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def log_activity(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        platform: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None
    ) -> ActivityLog:
        """
        Log an activity in the system.
        
        Args:
            action: The action performed (create, update, delete, sync, sale)
            entity_type: The type of entity affected (product, listing, etc.)
            entity_id: The ID of the affected entity
            platform: Optional platform name (ebay, reverb, vr, website)
            details: Optional additional details as a dictionary
            user_id: Optional ID of the user who performed the action
        
        Returns:
            The created ActivityLog instance
        """
        try:
            log_entry = ActivityLog(
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),  # Convert to string for consistency
                platform=platform,
                details=details,
                user_id=user_id,
                created_at=datetime.now(timezone.utc)
            )
            
            self.db.add(log_entry)
            await self.db.flush()  # Get the ID without committing transaction
            
            logger.debug(
                f"Activity logged: {action} {entity_type} {entity_id} "
                f"(platform: {platform or 'N/A'})"
            )
            
            return log_entry
            
        except Exception as e:
            logger.error(f"Error logging activity: {str(e)}")
            # Don't raise, as logging should not interrupt the main flow
            return None
    
    async def log_sync(
        self,
        platform: str,
        status: str,
        details: Dict[str, Any]
    ) -> ActivityLog:
        """
        Log a platform sync activity.
        
        Args:
            platform: The platform that was synced (ebay, reverb, vr, website)
            status: The sync status (success, error, partial)
            details: Additional details about the sync
        
        Returns:
            The created ActivityLog instance
        """
        return await self.log_activity(
            action="sync",
            entity_type="platform",
            entity_id=platform,
            platform=platform,
            details={
                "status": status,
                "processed": details.get("processed", 0),
                "new_products": details.get("new_products", 0),
                "updated_products": details.get("updated_products", 0),
                "status_changes": details.get("status_changes", 0),
                "errors": details.get("errors", 0),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
    
    async def log_sale(
        self,
        product_id: int,
        platform: str,
        external_id: str,
        details: Dict[str, Any]
    ) -> ActivityLog:
        """
        Log a product sale.
        
        Args:
            product_id: ID of the sold product
            platform: Platform where the sale occurred
            external_id: External order/sale ID
            details: Sale details (price, buyer, etc.)
        
        Returns:
            The created ActivityLog instance
        """
        return await self.log_activity(
            action="sale",
            entity_type="product",
            entity_id=str(product_id),
            platform=platform,
            details={
                "external_id": external_id,
                "sale_price": details.get("sale_price"),
                "buyer": details.get("buyer"),
                "sale_date": details.get("sale_date", datetime.now(timezone.utc).isoformat()),
                **details  # Include all other details
            }
        )

# Factory function for dependency injection
async def get_activity_logger(db: AsyncSession) -> ActivityLogger:
    return ActivityLogger(db)