import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship
if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.vehicle import Vehicle

class Driver(SQLModel, table=True):
    __tablename__ = "drivers"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, index=True)
    # Foreign Key linking to the Company (Mandatory)
    company_id: uuid.UUID = Field(foreign_key="company.id")
    
    full_name: str = Field(nullable=False)
    email: str = Field(unique=True, index=True, nullable=False)
    phone_number: str = Field(unique=True, index=True, nullable=True)
    hashed_password: str = Field(nullable=False)
    
    # Driver Specific Status
    # status can be: "pending" (awaiting admin approval), "accepted", "suspended"
    status: str = Field(default="pending") 

    # Optional Foreign Key linking to the Vehicle (Nullable because a driver might not have a truck assigned yet)
    current_vehicle_id: Optional[uuid.UUID] = Field(default=None, index=True)
    
    # OTP & Verification
    is_verified: bool = Field(default=False)
    is_active: bool = Field(default=True)
    otp_code: Optional[str] = Field(default=None)
    otp_expires_at: Optional[datetime] = Field(default=None)

    is_online: bool = Field(default=False, index=True)
    is_available: bool = Field(default=True, index=True) # False if currently towing
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None

    fcm_token: Optional[str] = Field(default=None, nullable=True) # For push notifications to the driver's device
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # --- Relationships ---
    company: Optional["Company"] = Relationship(back_populates="drivers")
    vehicle: Optional["Vehicle"] = Relationship(back_populates="driver")