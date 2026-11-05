import enum
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime
# from app.models.company import VerificationStatus

# ==========================================
# COMPANY SCHEMAS
# ==========================================

class CompanyBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    office_address: str = Field(..., min_length=5) 
    
    # FIX: Use Field(default=None) to force Pydantic to ignore missing ORM attributes
    email: Optional[EmailStr] = Field(default=None) 
    phone_number: Optional[str] = Field(default=None)

class CompanyCreate(CompanyBase):
    pass

class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    office_address: Optional[str] = Field(None, min_length=5)
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None

# business verification status enums
class VerificationStatus(str, enum.Enum):
    UNVERIFIED = "unverified"
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    REJECTED = "rejected"

class CompanyVerificationSubmit(BaseModel):
    nin_number: str = Field(..., min_length=11, max_length=11, description="11-digit Director NIN")
    cac_rc_number: str = Field(..., description="Business Registration Number (e.g., RC123456)")

class CompanyResponse(CompanyBase):
    id: UUID
    # is_vetted: Optional[bool] = False  # FIX 1: Make is_vetted optional to avoid Pydantic validation errors
    
    # FIX 3: Give is_active a default value so Pydantic doesn't crash if the DB omits it
    is_active: bool = True 

    bank_name: Optional[str] = None
    bank_code: Optional[str] = None
    account_number: Optional[str] = Field(None, min_length=10, max_length=10)
    account_name: Optional[str] = None

    verification_status: VerificationStatus
    
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

# ==========================================
# PAYMENT ACCOUNT SCHEMAS
# ==========================================

class PaymentAccountBase(BaseModel):
    bank_name: str = Field(..., description="Name of the financial institution")
    bank_code: str = Field(..., description="The 3-digit CBN bank code (e.g., '058' for GTB)")
    account_number: str = Field(..., min_length=10, max_length=10, description="10-digit account number")
    account_name: Optional[str] = Field(None, description="Verified name on the bank account")

class PaymentAccountCreate(PaymentAccountBase):
    pass

class PaymentAccountUpdate(BaseModel):
    bank_name: Optional[str] = None
    bank_code: Optional[str] = None
    account_number: Optional[str] = Field(None, min_length=10, max_length=10)
    account_name: Optional[str] = None

class PaymentAccountResponse(PaymentAccountBase):
    id: UUID
    company_id: UUID
    is_verified: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)