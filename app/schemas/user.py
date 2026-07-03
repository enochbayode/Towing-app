from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Generic, TypeVar

# Generic Type Variable for the API Response data payload
T = TypeVar('T')

# --- Generic Wrapper Schema ---
class APIResponse(BaseModel, Generic[T]):
    success: bool
    message: str
    data: Optional[T] = None

# --- Input Schemas (Requests) ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    full_name: str = Field(..., min_length=2, max_length=100)

class OTPVerify(BaseModel):
    email: EmailStr
    otp_code: str = Field(..., min_length=6, max_length=6)

class OTPResend(BaseModel):
    email: EmailStr

# --- Output Schemas (Responses) ---
class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse  # Attach the user profile so the mobile app has it immediately

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8, description="New password must be at least 8 characters")