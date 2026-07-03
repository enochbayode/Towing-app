from pydantic import BaseModel, EmailStr, Field
from typing import Optional

# --- Input Schemas ---
class AdminCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone_number: str = Field(..., description="Admin's contact phone number")
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")

# --- Output Schemas ---
class AdminResponse(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    phone_number: str
    company_id: Optional[str] = None  # Will be null until they register their company

class AdminTokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminResponse