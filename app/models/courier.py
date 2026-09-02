# app/models/courier.py

import enum
from sqlmodel import SQLModel, Field
from uuid import UUID
from uuid6 import uuid7
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal

def get_utc_now_naive() -> datetime:
    """Returns a UTC datetime perfectly stripped of timezone info for PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class CourierJobType(str, enum.Enum):
    PACKAGE = "package"              # Standard small/medium parcel
    STORE_PICKUP = "store_pickup"    # Market purchases (furniture, appliances)
    RELOCATION = "relocation"        # Moving apartments/houses
    FREIGHT = "freight"              # Heavy commercial/business bulk

class CourierStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING = "pending"
    ACCEPTED = "accepted"
    EN_ROUTE_TO_PICKUP = "en_route_to_pickup"
    LOADING = "loading"
    IN_TRANSIT = "in_transit"
    UNLOADING = "unloading"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class CourierTrip(SQLModel, table=True):
    __tablename__ = "courier_trips"

    # Core Identifiers
    id: UUID = Field(default_factory=uuid7, primary_key=True, index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    driver_id: Optional[UUID] = Field(default=None, foreign_key="courier_drivers.id", index=True)
    # company_id: Optional[UUID] = Field(default=None, foreign_key="companies.id")
    vehicle_id: Optional[UUID] = Field(default=None, foreign_key="courier_vehicles.id")

    # Job Specifics
    job_type: CourierJobType = Field(default=CourierJobType.PACKAGE)
    cargo_description: str = Field(..., description="e.g., 'A 3-seater sofa from the market'")
    requires_labor: bool = Field(default=False, description="Does the driver need to help load/unload?")
    passenger_count: int = Field(default=0, description="Number of people riding in the van with the cargo")
    
    # Distance & Scale
    is_interstate: bool = Field(default=False, index=True)
    estimated_distance_km: float = Field(default=0.0)

    # Pickup Data (Where to go, who to call)
    pickup_address: str
    pickup_lat: float
    pickup_lng: float
    pickup_contact_name: str     
    pickup_contact_phone: str    
    pickup_instructions: Optional[str] = None

    # Dropoff Data (Where to deliver, who receives it)
    dropoff_address: str
    dropoff_lat: float
    dropoff_lng: float
    recipient_name: str          
    recipient_phone: str         
    dropoff_instructions: Optional[str] = None

    # State Machine
    status: CourierStatus = Field(default=CourierStatus.PENDING)

    # Financials
    total_cost: Decimal = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    platform_fee: Decimal = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    driver_payout: Decimal = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    payment_method: str = Field(default="CASH")
    paystack_reference: Optional[str] = Field(default=None)
    payment_status: str = Field(default="PENDING", description="PENDING, PAID, or FAILED")

    # Timestamps
    created_at: datetime = Field(default_factory=get_utc_now_naive)
    started_loading_at: Optional[datetime] = None
    started_transit_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None



class CourierLedgerEntryType(str, enum.Enum):
    COMMISSION_DEBT = "COMMISSION_DEBT"
    PAYOUT = "PAYOUT"
    BONUS = "BONUS"

class CourierDriverHistory(SQLModel, table=True):
    __tablename__ = "courier_driver_history"
    
    id: UUID = Field(default_factory=uuid7, primary_key=True)
    driver_id: UUID = Field(foreign_key="courier_drivers.id", index=True)
    trip_id: Optional[UUID] = Field(default=None, foreign_key="courier_trips.id")
    
    entry_type: CourierLedgerEntryType
    amount: float = Field(description="Negative for debt, positive for payouts")
    description: str
    
    created_at: datetime = Field(default_factory=get_utc_now_naive)