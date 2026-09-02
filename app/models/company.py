import uuid
from uuid6 import uuid7
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship

# 1. HIDE THE IMPORTS INSIDE THIS BLOCK
if TYPE_CHECKING:
    from app.models.admin import Admin
    from app.models.driver import Driver
    from app.models.vehicle import Vehicle

class Company(SQLModel, table=True):
    __tablename__ = "company" 
    
    id: uuid.UUID = Field(default_factory=uuid7, primary_key=True, index=True)
    name: str = Field(nullable=False, description="Registered name of the towing company")
    rc_number: str = Field(unique=True, index=True, description="CAC Registration Number for vetting")
    office_address: str = Field(nullable=False)
    email: str = Field(nullable=False)
    phone_number: str = Field(nullable=False)
    
    # Security/Vetting Status
    is_vetted: bool = Field(default=False, description="Platform super-admin approves the company")
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # --- Relationships ---
    # A string is used in Relationship() to avoid Circular Import errors in Python
    admins: List["Admin"] = Relationship(back_populates="company")
    drivers: List["Driver"] = Relationship(back_populates="company")
    vehicles: List["Vehicle"] = Relationship(back_populates="company")

    payment_account: Optional["PaymentAccount"] = Relationship(
        back_populates="company", 
        sa_relationship_kwargs={"uselist": False, "cascade": "all, delete-orphan"}
    )


class PaymentAccount(SQLModel, table=True):
    __tablename__ = "payment_accounts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, index=True)
    bank_name: str = Field(..., description="Name of the financial institution")
    bank_code: str = Field(..., description="The 3-digit CBN bank code (e.g., '058' for GTB)") 
    account_number: str = Field(..., min_length=10, max_length=10, description="10-digit account number")
    account_name: Optional[str] = Field(None, description="Verified name on the bank account")
    is_verified: bool = Field(default=False)

    paystack_subaccount_code: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Foreign Key pointing to the Company
    company_id: uuid.UUID = Field(foreign_key="company.id", unique=True, ondelete="CASCADE")

    # Relationship back to the Company
    company: Optional[Company] = Relationship(back_populates="payment_account")