# app/schemas/courier.py

from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal

# Import the Enums we just created in the models
from app.models.courier import CourierJobType, CourierStatus

def get_utc_now_naive() -> datetime:
    """Returns a UTC datetime perfectly stripped of timezone info for PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class CourierTripBase(BaseModel):
    """Shared fields for all courier requests and responses."""
    # Job Specifics
    job_type: CourierJobType = Field(..., description="Type of courier job (package, relocation, etc.)")
    cargo_description: str = Field(..., description="Clear description of the items to be moved")
    requires_labor: bool = Field(default=False, description="Does the user need help loading/unloading?")
    passenger_count: int = Field(default=0, ge=0, le=2, description="Number of passengers riding along (max 2)")
    
    # Distance
    is_interstate: bool = Field(default=False)
    estimated_distance_km: float = Field(..., gt=0, description="Estimated distance in kilometers")

    # Pickup Details
    pickup_address: str = Field(..., description="Full formatted pickup address")
    pickup_lat: float
    pickup_lng: float
    pickup_contact_name: str = Field(..., description="Name of the person at the pickup location")
    pickup_contact_phone: str = Field(..., description="Phone number of the pickup contact")
    pickup_instructions: Optional[str] = None

    # Dropoff Details
    dropoff_address: str = Field(..., description="Full formatted dropoff address")
    dropoff_lat: float
    dropoff_lng: float
    recipient_name: str = Field(..., description="Name of the person receiving the items")
    recipient_phone: str = Field(..., description="Phone number of the recipient")
    dropoff_instructions: Optional[str] = None


class CourierTripCreate(CourierTripBase):
    """
    Payload sent by the frontend app when a user requests a van.
    Financials, IDs, and timestamps are stripped out so they can't be spoofed.
    """
    # The frontend will likely pass the vehicle type they want (e.g., CARGO_VAN, SPRINTER)
    # We can accept it here to help the matching algorithm.
    requested_vehicle_type: str = Field(..., description="The type/size of van requested")


class CourierTripResponse(CourierTripBase):
    """
    Full payload returned to the frontend after a trip is created or fetched.
    Includes all database-generated fields.
    """
    id: UUID
    user_id: UUID
    driver_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    vehicle_id: Optional[UUID] = None
    
    status: CourierStatus
    
    # Financials
    total_cost: Decimal
    platform_fee: Decimal
    driver_payout: Decimal
    
    # Timestamps
    created_at: datetime = Field(default_factory=get_utc_now_naive)
    started_loading_at: Optional[datetime] = None
    started_transit_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CourierDriverTracking(BaseModel):
    driver_id: str
    name: str
    phone: str
    current_lat: Optional[float]
    current_lng: Optional[float]

class CourierVehicleTracking(BaseModel):
    make: str
    model: str
    license_plate: str
    vehicle_type: str

class CourierTrackingResponse(BaseModel):
    trip_id: str
    status: str
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float
    started_transit_at: Optional[datetime] = None
    driver: Optional[CourierDriverTracking] = None
    vehicle: Optional[CourierVehicleTracking] = None

class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"

class CourierTripConfirm(BaseModel):
    payment_method: PaymentMethod