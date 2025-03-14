"""
Package Model

Defines the Package data model for shipping operations, 
including dimensions, weight, and package characteristics.

Used for:
- Rate calculation
- Label generation
- Package type specification
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, validator
from enum import Enum

class PackageType(str, Enum):
    """Standard package types across carriers"""
    CUSTOM = "custom"
    ENVELOPE = "envelope"
    SMALL_BOX = "small_box"
    MEDIUM_BOX = "medium_box"
    LARGE_BOX = "large_box"
    PALLET = "pallet"

class WeightUnit(str, Enum):
    """Weight measurement units"""
    KG = "kg"
    LB = "lb"
    OZ = "oz"
    G = "g"

class DimensionUnit(str, Enum):
    """Dimension measurement units"""
    CM = "cm"
    IN = "in"
    MM = "mm"
    M = "m"

class Package(BaseModel):
    """Package model for shipping"""
    length: float
    width: float
    height: float
    weight: float
    dimension_unit: DimensionUnit = DimensionUnit.CM
    weight_unit: WeightUnit = WeightUnit.KG
    package_type: PackageType = PackageType.CUSTOM
    is_fragile: bool = False
    reference: Optional[str] = None
    items: Optional[List[Dict[str, Any]]] = None
    
    @validator('weight')
    def weight_must_be_positive(cls, v):
        """Validate weight is positive"""
        if v <= 0:
            raise ValueError('Weight must be positive')
        return v
    
    @validator('length', 'width', 'height')
    def dimensions_must_be_positive(cls, v):
        """Validate dimensions are positive"""
        if v <= 0:
            raise ValueError('Dimensions must be positive')
        return v
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for API requests"""
        return {
            "length": self.length,
            "width": self.width,
            "height": self.height,
            "weight": self.weight,
            "dimensionUnit": self.dimension_unit,
            "weightUnit": self.weight_unit,
            "packageType": self.package_type,
            "isFragile": self.is_fragile,
            "reference": self.reference,
            "items": self.items
        }
        
    def get_volume(self) -> float:
        """Calculate package volume"""
        return self.length * self.width * self.height
        
    def convert_weight_to(self, unit: WeightUnit) -> float:
        """Convert weight to specified unit"""
        if self.weight_unit == unit:
            return self.weight
            
        # Conversion logic
        if self.weight_unit == WeightUnit.KG and unit == WeightUnit.LB:
            return self.weight * 2.20462
        elif self.weight_unit == WeightUnit.LB and unit == WeightUnit.KG:
            return self.weight * 0.453592
        
        # Add more conversion logic as needed
        return self.weight
        
    def convert_dimensions_to(self, unit: DimensionUnit) -> Dict[str, float]:
        """Convert dimensions to specified unit"""
        if self.dimension_unit == unit:
            return {"length": self.length, "width": self.width, "height": self.height}
            
        # Conversion logic
        conversion_factor = 1.0
        if self.dimension_unit == DimensionUnit.CM and unit == DimensionUnit.IN:
            conversion_factor = 0.393701
        elif self.dimension_unit == DimensionUnit.IN and unit == DimensionUnit.CM:
            conversion_factor = 2.54
        
        # Add more conversion logic as needed
        
        return {
            "length": self.length * conversion_factor,
            "width": self.width * conversion_factor,
            "height": self.height * conversion_factor
        }

