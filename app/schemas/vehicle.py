from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime

# Import the Enum from our newly created model
from app.models.vehicle import TowTruckType 
from app.schemas.driver import DriverResponse

class VehicleBase(BaseModel):
    make: str = Field(..., description="e.g., Ford, Isuzu")
    model: str = Field(..., description="e.g., F-450, NQR")
    year: int = Field(..., ge=1990, le=2030, description="Year of manufacture")
    license_plate: str = Field(..., description="Unique license plate number")
    vehicle_type: Optional[str] = Field(..., description="Type of tow truck (flatbed, wheel_lift, etc.)")
    capacity_tons: Optional[float] = Field(default=None, description="Towing capacity in tons")

class VehicleCreate(VehicleBase):
    """Payload for an Admin adding a new truck to their fleet"""
    pass

class VehicleUpdate(BaseModel):
    """Payload for updating truck details or assigning it to a driver"""
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = Field(default=None, ge=1990, le=2030)
    license_plate: Optional[str] = None
    vehicle_type: Optional[TowTruckType] = None
    capacity_tons: Optional[float] = None
    
    is_active: Optional[bool] = None
    driver_id: Optional[UUID] = Field(default=None, description="Assign a specific driver to this truck")

class VehicleResponse(VehicleBase):
    """Response returned to the frontend"""
    id: UUID
    company_id: UUID
    driver: Optional[DriverResponse] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

# class VehicleTrackingInfo(BaseModel):
#     id: str
#     company_id: str
#     driver_id: Optional[str] = None
#     is_active: bool

#     model_config = ConfigDict(from_attributes=True)