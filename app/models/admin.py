import uuid
from uuid6 import uuid7
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship
if TYPE_CHECKING:
    from app.models.company import Company

class Admin(SQLModel, table=True):
    __tablename__ = "admins"
    
    id: uuid.UUID = Field(default_factory=uuid7, primary_key=True, index=True)
    # Foreign Key linking to the Company
    company_id: Optional[uuid.UUID] = Field(default=None, foreign_key="company.id")
    
    full_name: str = Field(nullable=False)
    email: str = Field(unique=True, index=True, nullable=False)
    phone_number: str = Field(unique=True, index=True, nullable=False)
    hashed_password: str = Field(nullable=False)
    
    # OTP & Verification
    is_verified: bool = Field(default=False)
    otp_code: Optional[str] = Field(default=None)
    otp_expires_at: Optional[datetime] = Field(default=None)
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # --- Relationships ---
    company: Optional["Company"] = Relationship(back_populates="admins")