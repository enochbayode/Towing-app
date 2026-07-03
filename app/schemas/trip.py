import enum
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal

# Import your Enums from the models file so Pydantic can validate against them!
from app.models.trip import TripStatus, TransactionType

# ==========================================
# TRIP SCHEMAS
# ==========================================

class TripBase(BaseModel):
    pickup_address: str = Field(..., description="The formatted address of the broken-down vehicle")
    pickup_lat: float = Field(..., description="Latitude of pickup location")
    pickup_lng: float = Field(..., description="Longitude of pickup location")
    
    dropoff_address: str = Field(..., description="The formatted destination address")
    dropoff_lat: float = Field(..., description="Latitude of dropoff location")
    dropoff_lng: float = Field(..., description="Longitude of dropoff location")
    
    vehicle_details: str = Field(..., description="e.g., '2018 Toyota Camry, Black, License Plate XYZ123'") 

class VehicleType(str, enum.Enum):
    SEDAN = "sedan"
    SUV = "suv"
    TRUCK = "truck"
    MOTORCYCLE = "motorcycle"

class TowTruckType(str, enum.Enum):
    FLATBED = "flatbed"
    WHEEL_LIFT = "wheel_lift" # Also known as chained/wrecker
    HEAVY_DUTY = "heavy_duty"

class TripCreateSchema(TripBase):
    """
    Data from the User's app. Notice base_cost is GONE.
    The user only tells us WHAT they need and WHERE they are.
    """
    vehicle_type: VehicleType = Field(..., description="The size/type of the user's vehicle")
    truck_type: TowTruckType = Field(..., description="The type of tow truck requested")

class TripConfirmSchema(BaseModel):
    trip_id: UUID

class TripUpdate(BaseModel):
    """
    Used by the Driver's mobile app to update the status of the trip.
    """
    status: Optional[TripStatus] = None
    driver_id: Optional[UUID] = Field(None, description="Set when a driver accepts the trip")
    company_id: Optional[UUID] = Field(None, description="Set when a company's driver accepts the trip")

class TripResponse(TripBase):
    """
    The unified response payload returning the trip details to the frontend.
    """
    id: UUID
    user_id: UUID
    company_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None
    
    status: TripStatus
    
    # Financials
    total_cost: Decimal
    platform_fee: Decimal
    company_payout: Decimal
    paystack_reference: Optional[str] = None
    
    # Timestamps
    created_at: datetime
    arrived_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


# ==========================================
# TRANSACTION SCHEMAS
# ==========================================
# Note: Users/Admins don't CREATE transactions directly via endpoints (the system does), 
# so we only need a Response schema for their dashboard ledger.

class TransactionResponse(BaseModel):
    id: UUID
    trip_id: UUID
    type: TransactionType
    amount: Decimal
    gateway_reference: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)