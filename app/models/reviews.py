import enum
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import ARRAY

class RatingCategory(str, enum.Enum):
    # The 5 positive categories strictly from image_b5b00a.png
    ON_TIME = "On time"
    CAREFUL_WITH_CAR = "Careful with my car"
    CLEAR_COMMUNICATION = "Clear communication"
    FAIR_PRICE = "Fair price"
    PROFESSIONAL = "Professional"
    
    # 2 new negative categories
    LATE_ARRIVAL = "Late arrival"
    UNPROFESSIONAL_BEHAVIOR = "Unprofessional behavior"

class TripReview(SQLModel, table=True):
    __tablename__ = "trip_reviews"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    trip_id: UUID = Field(foreign_key="trips.id", unique=True, index=True) # Ensures 1 review per trip
    driver_id: UUID = Field(foreign_key="drivers.id", index=True) # Update foreign_key to match your exact driver table name
    user_id: UUID = Field(foreign_key="users.id", index=True)
    
    rating: int = Field(ge=1, le=5)
    
    # Stores selected categories as an array of strings in PostgreSQL
    categories: List[str] = Field(default=[], sa_column=Column(ARRAY(String)))
    comment: Optional[str] = None
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# --- UPDATE YOUR DRIVER MODEL ---
# Add these two fields to your existing CourierDriver or TowingDriver model

    