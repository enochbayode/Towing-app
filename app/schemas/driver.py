from pydantic import BaseModel, EmailStr, Field, model_validator
from typing import Optional

class DriverInvite(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr

class DriverStatusUpdate(BaseModel):
    status: str = Field(..., description="E.g., 'suspended', 'accepted', 'pending'")

class DriverResponse(BaseModel):
    id: str
    company_id: str
    full_name: str
    email: EmailStr
    phone_number: Optional[str]
    status: str
    is_verified: bool

class DriverInviteAction(BaseModel):
    email: EmailStr
    temp_password: str
    action: str = Field(..., description="Must be 'accept' or 'decline'")

    @model_validator(mode='after')
    def validate_action_logic(self) -> 'DriverInviteAction':
        if self.action not in ["accept", "decline"]:
            raise ValueError("Action must be exactly 'accept' or 'decline'.")
        
        if self.action == "accept":
            if not self.new_password or len(self.new_password) < 8:
                raise ValueError("A new password of at least 8 characters is required to accept the invite.")
        return self
    
class DriverTokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    driver: DriverResponse