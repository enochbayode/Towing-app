import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel



class User(SQLModel, table=True):
    __tablename__ = "users"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, index=True)
    email: str = Field(unique=True, index=True, nullable=False)
    hashed_password: str = Field(nullable=False)
    full_name: str = Field(nullable=False)
    phone_number: Optional[str] = Field(default=None)
    home_address: Optional[str] = Field(default=None)
    
    # OTP & Verification
    is_verified: bool = Field(default=False)
    otp_code: Optional[str] = Field(default=None)
    otp_expires_at: Optional[datetime] = Field(default=None)
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))