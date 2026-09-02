from sqlmodel import SQLModel, Field
from sqlalchemy import ForeignKey
from typing import Optional
from datetime import datetime, timezone
from uuid import UUID
from uuid6 import uuid7

def get_utc_now_naive() -> datetime:
    """Returns a UTC datetime perfectly stripped of timezone info for PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CourierDriver(SQLModel, table=True):
    __tablename__ = "courier_drivers"

    # Core Identifiers
    id: UUID = Field(default_factory=uuid7, primary_key=True, index=True)
    
    # --- COMPLETELY INDEPENDENT AUTH & PROFILE ---
    full_name: str
    email: str = Field(unique=True, index=True)
    phone_number: str = Field(unique=True, index=True)
    hashed_password: str

    # Email OTP Flow
    is_email_verified: bool = Field(default=False)
    verification_token: Optional[str] = None
    verification_token_expires_at: Optional[datetime] = None

    # The van they are currently driving
    current_vehicle_id: Optional[UUID] = Field(
        default=None, 
        sa_column_args=[ForeignKey("courier_vehicles.id", use_alter=True)])

    # Courier-Specific Capabilities
    can_do_labor: bool = Field(default=False, description="Willing to help load/unload heavy items")
    interstate_enabled: bool = Field(default=False, description="Willing to do long-haul/inter-state runs")

    # Status Flags
    is_verified: bool = Field(default=False, description="NIN has been verified by the platform")
    is_online: bool = Field(default=False, description="Driver app is open")
    is_available: bool = Field(default=False, description="Ready to accept new trips")

    # Live Location Tracking
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None

    # Account details 
    bank_name: Optional[str] = Field(default=None)
    bank_code: Optional[str] = Field(default=None)
    account_number: Optional[str] = Field(default=None)
    account_name: Optional[str] = Field(default=None, description="Verified by Paystack")

    # Timestamps
    created_at: datetime = Field(default_factory=get_utc_now_naive)
    updated_at: datetime = Field(default_factory=get_utc_now_naive)