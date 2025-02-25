class BaseServiceError(Exception):
    """Base exception for all service-related errors."""
    pass

class ProductServiceError(BaseServiceError):
    """Base exception for product service errors."""
    pass

class ProductCreationError(ProductServiceError):
    """Raised when product creation fails."""
    pass

class ProductNotFoundError(ProductServiceError):
    """Raised when product is not found."""
    pass

class PlatformServiceError(BaseServiceError):
    """Base exception for platform service errors."""
    pass

class EbayServiceError(PlatformServiceError):
    """Base exception for eBay-specific errors."""
    pass

class EbayAPIError(EbayServiceError):
    """Raised when eBay API calls fail."""
    pass

class ListingNotFoundError(PlatformServiceError):
    """Raised when a platform listing is not found."""
    pass

class SyncError(PlatformServiceError):
    """Raised when platform synchronization fails."""
    pass

class ValidationError(BaseServiceError):
    """Raised when data validation fails."""
    pass

class PlatformIntegrationError(PlatformServiceError):
    """Raised when data validation fails."""
    pass