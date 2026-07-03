from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime

# ==========================================
# COMPANY SCHEMAS
# ==========================================

class CompanyBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    office_address: str = Field(..., min_length=5) 
    rc_number: str = Field(..., description="Official CAC RC or BN Number")
    
    # FIX: Use Field(default=None) to force Pydantic to ignore missing ORM attributes
    email: Optional[EmailStr] = Field(default=None) 
    phone_number: Optional[str] = Field(default=None)

class CompanyCreate(CompanyBase):
    pass

class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    office_address: Optional[str] = Field(None, min_length=5)
    rc_number: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None

class CompanyResponse(CompanyBase):
    id: UUID
    is_vetted: bool
    
    # FIX 3: Give is_active a default value so Pydantic doesn't crash if the DB omits it
    is_active: bool = True 

    bank_name: Optional[str] = None
    bank_code: Optional[str] = None
    account_number: Optional[str] = Field(None, min_length=10, max_length=10)
    account_name: Optional[str] = None
    
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