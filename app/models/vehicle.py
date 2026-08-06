import enum
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, TYPE_CHECKING
from uuid import UUID, uuid4
from datetime import datetime, timezone

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.driver import Driver

class TowTruckType(str, enum.Enum):
    FLATBED = "flatbed"   # also known as vechicle carrier
    WHEEL_LIFT = "wheel_lift"  # another name for chained 
    HEAVY_DUTY = "heavy_duty"  # can be used for large vehicles like buses or trucks
    # INTEGRATED = "integrated"  # a

class Vehicle(SQLModel, table=True):
    __tablename__ = "vehicle"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    
    # Relationships & Foreign Keys
    # Links to the singular "company" table as we fixed earlier
    company_id: UUID = Field(foreign_key="company.id", index=True)
    # Links to the "drivers" table. Nullable because a truck might not have a driver assigned today.
    driver_id: Optional[UUID] = Field(default=None, foreign_key="drivers.id", index=True)
    
    # Vehicle Details
    make: str = Field(max_length=50, description="e.g., Ford, Isuzu")
    model: str = Field(max_length=50, description="e.g., F-450, NQR")
    year: int
    license_plate: str = Field(unique=True, index=True, max_length=20)
    
    # Towing capabilities
    vehicle_type: TowTruckType
    capacity_tons: Optional[float] = Field(default=None, description="Max weight it can tow")
    
    # Status
    is_active: bool = Field(default=True, description="False if the truck is in the mechanic shop")
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Note: If you want fully resolved objects via ORM, add these later:
    company: Optional["Company"] = Relationship(back_populates="vehicles")
    driver: Optional["Driver"] = Relationship(back_populates="vehicle")