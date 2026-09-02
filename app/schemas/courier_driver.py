# app/schemas/courier_driver.py

from pydantic import BaseModel, ConfigDict, Field, EmailStr
from app.models.courier_vehicle import CourierVehicleType
from typing import Optional
from uuid import UUID
from datetime import datetime

class CourierDriverBase(BaseModel):
    can_do_labor: bool = Field(default=False, description="Can the driver lift heavy items?")
    interstate_enabled: bool = Field(default=False, description="Can they leave the state?")

class CourierDriverCreate(CourierDriverBase):
    """
    Payload for when a User upgrades their account to become a Courier Driver.
    We don't pass user_id here because the API extracts it securely from the JWT token.
    """
    pass

class CourierStatusUpdate(BaseModel):
    is_online: bool

class CourierDriverRegister(BaseModel):
    """Payload for a brand new van driver signing up."""
    full_name: str
    email: EmailStr
    phone_number: str
    password: str = Field(..., min_length=8)
    
    # Courier preferences
    can_do_labor: bool = False
    interstate_enabled: bool = False

class CourierDriverLogin(BaseModel):
    email: EmailStr
    password: str

class CourierDriverUpdate(BaseModel):
    """
    Payload for the Courier Driver to update their preferences or status.
    """
    can_do_labor: Optional[bool] = None
    interstate_enabled: Optional[bool] = None
    is_online: Optional[bool] = None
    is_available: Optional[bool] = None
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None

class CourierDriverResponse(CourierDriverBase):
    """
    The profile returned to the Courier Driver dashboard.
    """
    id: UUID
    user_id: UUID
    current_vehicle_id: Optional[UUID] = None
    
    is_verified: bool
    is_online: bool
    is_available: bool
    
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CourierVehicleCreate(BaseModel):
    make: str 
    model: str 
    year: int
    license_plate: str
    capacity_tons: float 
    
    # Now it is impossible to register a Flatbed as a Courier Vehicle!
    vehicle_type: CourierVehicleType = Field(
        ..., 
        description="Must be motorcycle, cargo_van, sprinter, or box_truck"
    )

class CourierVehicleUpdate(BaseModel):
    make: Optional[str] = Field(None, description="Vehicle make")
    model: Optional[str] = Field(None, description="Vehicle model")
    year: Optional[int] = Field(None, description="Manufacturing year")
    license_plate: Optional[str] = Field(None, description="Vehicle license plate number")
    capacity_tons: Optional[float] = Field(None, description="Cargo weight capacity")
    vehicle_type: Optional[str] = Field(None, description="Vehicle category")

class LicenseVerificationRequest(BaseModel):
    license_number: str = Field(
        ..., 
        min_length=10, 
        max_length=15, 
        description="The Nigerian Driver's License Number"
    )

class CourierBankUpdate(BaseModel):
    bank_name: str = Field(..., description="e.g., Guaranty Trust Bank")
    bank_code: str = Field(..., description="e.g., 058")
    account_number: str = Field(..., min_length=10, max_length=10)