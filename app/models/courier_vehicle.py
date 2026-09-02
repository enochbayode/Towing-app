# app/models/courier_vehicle.py

import enum
from sqlmodel import SQLModel, Field
from uuid import UUID
from uuid6 import uuid7
from typing import Optional
from datetime import datetime, timezone

class CourierVehicleType(str, enum.Enum):
    MOTORCYCLE = "motorcycle" # Dispatch riders
    CARGO_VAN = "cargo_van"   # Small/Medium deliveries
    SPRINTER = "sprinter"     # Large deliveries / Relocations
    BOX_TRUCK = "box_truck"   # Commercial freight

def get_utc_now_naive() -> datetime:
    """Returns a UTC datetime perfectly stripped of timezone info for PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class CourierVehicle(SQLModel, table=True):
    __tablename__ = "courier_vehicles"

    # Core Identifiers
    id: UUID = Field(default_factory=uuid7, primary_key=True, index=True)
    
    # Ownership (Can belong to an independent driver or a logistics company)
    driver_id: Optional[UUID] = Field(default=None, foreign_key="courier_drivers.id", index=True)
    # company_id: Optional[UUID] = Field(default=None, foreign_key="companies.id", index=True)

    # Vehicle Details
    make: str = Field(..., description="e.g., Ford, Mercedes")
    model: str = Field(..., description="e.g., Transit, Sprinter")
    year: int
    license_plate: str = Field(unique=True, index=True)
    
    # Logistics Specifics
    vehicle_type: CourierVehicleType
    capacity_tons: float = Field(..., description="Max weight capacity")
    # You can now add courier-specific fields later without bloating the tow truck table!
    # e.g., volume_cubic_meters: float
    # e.g., is_refrigerated: bool 

    # Status
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False, description="Admin has checked the vehicle papers")

    created_at: datetime = Field(default_factory=get_utc_now_naive)
    updated_at: datetime = Field(default_factory=get_utc_now_naive)