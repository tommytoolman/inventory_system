"""
Base schemas with common functionality.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, create_model
from typing import Type, TypeVar, Dict, Any, Optional

T = TypeVar('T', bound='BaseSchema')

class BaseSchema(BaseModel):
    """Base schema with common functionality for all schemas"""
    
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True
    )
    
    @classmethod
    def from_orm_model(cls: Type[T], orm_model: Any) -> T:
        """Create a schema instance from an ORM model"""
        return cls.model_validate(orm_model)
    
    @classmethod
    def create_update_model(cls, name: str = None):
        """
        Create an update model based on this schema with all fields optional.
        Useful for PATCH endpoints where all fields should be optional.
        """
        if not name:
            name = f"{cls.__name__}Update"
            
        fields = {}
        for field_name, field in cls.model_fields.items():
            # Make all fields optional
            if hasattr(field, 'annotation'):
                if not str(field.annotation).startswith('Optional'):
                    field.annotation = Optional[field.annotation]
            fields[field_name] = (field.annotation, None)
            
        return create_model(
            name,
            __base__=BaseSchema,
            **fields
        )

class TimestampedSchema(BaseSchema):
    """Base schema for models with timestamp fields"""
    created_at: datetime
    updated_at: datetime