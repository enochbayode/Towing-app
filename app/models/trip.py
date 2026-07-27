import enum
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
from decimal import Decimal

# --- ENUMS (State Machine) ---

class TripStatus(str, enum.Enum):
    PENDING_ESTIMATE = "pending_estimate" # Initial draft state
    SEARCHING = "searching"               # User requested, broadcasting to drivers
    EN_ROUTE = "en_route"                 # Driver accepted, heading to pickup
    TOWING = "towing"                     # Car hooked up, en route to drop-off
    ARRIVED = "arrived"                   # Driver arrived at drop-off (2-min timer active)
    COMPLETED = "completed"               # Trip finished successfully
    CANCELLED = "cancelled"               # Cancelled by user or driver
    DISPUTED = "disputed"                 # User raised an issue at drop-off


class PaymentMethod(str, enum.Enum):
    CASH = "CASH"                         # Default: Driver collects physical cash
    CARD = "CARD"                         # Paystack Split Payment


class PaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"                     # Cash not collected yet
    PAID = "paid"                         # Card processed successfully via Paystack
    DEBT_LOGGED = "debt_logged"           # Cash collected; commission debt logged on Company Ledger


class TransactionType(str, enum.Enum):
    CARD_PAYMENT = "card_payment"         # Paystack card charge
    PLATFORM_COMMISSION = "platform_commission" # Revenue cut
    REFUND = "refund"


class LedgerEntryType(str, enum.Enum):
    COMMISSION_DEBT = "commission_debt"   # Negative: Owed to platform from cash trip
    MANUAL_SETTLEMENT = "manual_settlement" # Positive: Company paid off accumulated debt
    CARD_PAYOUT = "card_payout"           # Positive: Company's share from card trips


# --- DATABASE MODELS ---

class Trip(SQLModel, table=True):
    __tablename__ = "trips"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    
    # Foreign Keys
    user_id: UUID = Field(foreign_key="users.id", index=True)
    company_id: Optional[UUID] = Field(default=None, foreign_key="company.id", index=True)
    driver_id: Optional[UUID] = Field(default=None, foreign_key="drivers.id", index=True)
    
    # Route & Vehicle Details
    pickup_address: str
    pickup_lat: float
    pickup_lng: float
    dropoff_address: str
    dropoff_lat: float
    dropoff_lng: float
    vehicle_details: str = Field(description="e.g., 2018 Toyota Camry, Black")
    
    # Financials & Payment Configuration
    payment_method: PaymentMethod = Field(default=PaymentMethod.CASH, index=True)
    payment_status: PaymentStatus = Field(default=PaymentStatus.UNPAID, index=True)
    
    total_cost: Decimal = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    platform_fee: Decimal = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    company_payout: Decimal = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    
    # Gateway Tracking
    paystack_reference: Optional[str] = Field(default=None, unique=True, index=True)
    
    # Status & Timestamps
    status: TripStatus = Field(default=TripStatus.PENDING_ESTIMATE, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    arrived_at: Optional[datetime] = Field(default=None, description="When driver arrived at drop-off")
    completed_at: Optional[datetime] = Field(default=None)

    # Relationships
    transactions: List["Transaction"] = Relationship(back_populates="trip")
    ledger_entries: List["CompanyLedger"] = Relationship(back_populates="trip")


class CompanyLedger(BaseTable := SQLModel, table=True):
    """
    Tracks running debt and payouts for fleet companies.
    Cash trip commissions appear as negative amounts linked to driver & trip.
    """
    __tablename__ = "company_ledgers"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    company_id: UUID = Field(foreign_key="company.id", index=True)
    driver_id: Optional[UUID] = Field(default=None, foreign_key="drivers.id", index=True)
    trip_id: Optional[UUID] = Field(default=None, foreign_key="trips.id", index=True)
    
    entry_type: LedgerEntryType = Field(index=True)
    amount: Decimal = Field(max_digits=10, decimal_places=2) # Negative for debt, Positive for credit
    description: str = Field(description="Context, e.g. Commission debt for cash trip #1234")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    trip: Optional[Trip] = Relationship(back_populates="ledger_entries")


class Transaction(SQLModel, table=True):
    """
    Immutable payment gateway audit record for Card transactions.
    """
    __tablename__ = "transactions"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    trip_id: UUID = Field(foreign_key="trips.id", index=True)
    
    type: TransactionType = Field(index=True)
    amount: Decimal = Field(max_digits=10, decimal_places=2)
    gateway_reference: str = Field(unique=True, index=True)
    status: str = Field(default="success", description="'pending', 'success', 'failed'")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    trip: Optional[Trip] = Relationship(back_populates="transactions")