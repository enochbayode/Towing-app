import uuid
from uuid6 import uuid7
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship
if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.vehicle import Vehicle

class Driver(SQLModel, table=True):
    __tablename__ = "drivers"
    
    id: uuid.UUID = Field(default_factory=uuid7, primary_key=True, index=True)
    # Foreign Key linking to the Company (Mandatory)
    company_id: uuid.UUID = Field(foreign_key="company.id")
    
    full_name: str = Field(nullable=False)
    email: str = Field(unique=True, index=True, nullable=False)
    phone_number: str = Field(unique=True, index=True, nullable=True)
    hashed_password: str = Field(nullable=False)
    license_number: str = Field(unique=True, index=True, nullable=False, description="Nigerian Driver's License Number")
    
    # Driver Specific Status
    # status can be: "pending" (awaiting admin approval), "accepted", "suspended"
    status: str = Field(default="pending") 

    # Optional Foreign Key linking to the Vehicle (Nullable because a driver might not have a truck assigned yet)
    current_vehicle_id: Optional[uuid.UUID] = Field(default=None, index=True)
    
    # OTP & Verification
    is_verified: bool = Field(default=False) # whether the driver has completed KYC verification with lisense_number.
    is_active: bool = Field(default=True) # as how the driver is currently allowed to log in and accept jobs
    otp_code: Optional[str] = Field(default=None)
    otp_expires_at: Optional[datetime] = Field(default=None)

    is_online: bool = Field(default=False, index=True) # currently logged into the app
    is_available: bool = Field(default=True, index=True) # False if currently towing
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None

    photo_url: Optional[str] = Field(default=None)

    average_rating: float = Field(default=0.0)
    total_reviews: int = Field(default=0)

    fcm_token: Optional[str] = Field(default=None, nullable=True) # For push notifications to the driver's device
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # --- Relationships ---
    company: Optional["Company"] = Relationship(back_populates="drivers")
    vehicle: Optional["Vehicle"] = Relationship(back_populates="driver")