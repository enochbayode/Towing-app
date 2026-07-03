import enum
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
from decimal import Decimal

# --- ENUMS (The State Machines) ---

class TripStatus(str, enum.Enum):
    SEARCHING = "searching"           # User requested, pending payment
    FUNDS_ESCROWED = "funds_escrowed" # Payment verified, platform holds funds
    EN_ROUTE = "en_route"             # Driver is heading to the pickup location
    TOWING = "towing"                 # Car is hooked up, heading to drop-off
    ARRIVED = "arrived"               # Driver arrived. THE 2-MINUTE TIMER STARTS HERE.
    COMPLETED = "completed"           # Funds released to company
    CANCELLED = "cancelled"           # Cancelled before towing
    DISPUTED = "disputed"             # User flagged an issue, funds frozen
    PENDING_PAYMENT = "pending_payment" # User has not paid yet

# --- ENUMS (Transaction Types) ---
class TransactionType(str, enum.Enum):
    ESCROW_DEPOSIT = "escrow_deposit" # User's card charged
    COMPANY_PAYOUT = "company_payout" # Escrow released to the fleet
    PLATFORM_FEE = "platform_fee"     # Your revenue cut
    REFUND = "refund"                 # Returned to user

# --- DATABASE MODELS ---
class Trip(SQLModel, table=True):
    __tablename__ = "trips"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    
    # Foreign Keys
    user_id: UUID = Field(foreign_key="users.id", index=True)
    company_id: Optional[UUID] = Field(default=None, foreign_key="company.id", index=True)
    driver_id: Optional[UUID] = Field(default=None, foreign_key="drivers.id", index=True)
    
    # Logistics Data (Store as JSON strings or distinct fields)
    pickup_address: str
    pickup_lat: float
    pickup_lng: float
    dropoff_address: str
    dropoff_lat: float
    dropoff_lng: float
    
    # What are we towing?
    vehicle_details: str = Field(description="e.g., 2018 Toyota Camry, Black")
    
    # Financials & Status
    status: TripStatus = Field(default=TripStatus.SEARCHING, index=True)
    total_cost: Decimal = Field(default=0, max_digits=10, decimal_places=2)
    platform_fee: Decimal = Field(default=0, max_digits=10, decimal_places=2)
    company_payout: Decimal = Field(default=0, max_digits=10, decimal_places=2)
    
    # Escrow Tracking
    paystack_reference: Optional[str] = Field(default=None, unique=True, index=True)
    
    # Timestamps (Crucial for the 2-minute timer)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    arrived_at: Optional[datetime] = Field(default=None, description="When the 2-min timer started")
    completed_at: Optional[datetime] = Field(default=None)

    # Relationships
    transactions: List["Transaction"] = Relationship(back_populates="trip")


class Transaction(SQLModel, table=True):
    """
    Immutable ledger of all money moving in and out of the platform.
    """
    __tablename__ = "transactions"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    trip_id: UUID = Field(foreign_key="trips.id", index=True)
    
    type: TransactionType = Field(index=True)
    amount: Decimal = Field(max_digits=10, decimal_places=2)
    
    # Paystack Transfer or Charge reference
    gateway_reference: str = Field(unique=True, index=True)
    
    status: str = Field(default="success", description="'pending', 'success', 'failed'")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationship
    trip: Optional[Trip] = Relationship(back_populates="transactions")