import os
from functools import lru_cache
from typing import List, Union

from pydantic import AnyHttpUrl, Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- PROJECT SETTINGS ---
    PROJECT_NAME: str = "VOCAAFRICA Kiosk API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True
    
    # --- SECURITY ---
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 4320  # Changed default to 24 hours to satisfy frontend requirements


    # --- DATABASE ---
    # We use a Field to allow environment variable overrides
    DATABASE_URL: str
    DIRECT_DATABASE_URL: str  # This is the non-async URL for tools that don't support async drivers (like Supabase Studio or DBeaver)

    # RESEND EMAIL CONFIGURATION
    RESEND_API_KEY: str
    RESEND_FROM_EMAIL: str

    # --- OFFLINE AI MODELS ---
    # Defaulting to local paths if not set in .env
    
    DRIVER_LOGIN_PAGE_URL: AnyHttpUrl = Field(default="http://localhost:3000/driver/login")  # Default for local development
    FRONTEND_URL: AnyHttpUrl = Field(default="http://localhost:3000")  # Default for local development
    
    DOJAH_API_KEY: str
    DOJAH_APP_ID: str
    DOJAH_BASE_URL: str

    PREMBLY_SECRET_KEY: str

    GOOGLE_MAPS_API_KEY: str 

    REDIS_URL: str #"redis://localhost:6379" # Default fallback for local testing

    USER_FEE_PERCENTAGE: float = 0.03
    COMPANY_PAYOUT_PERCENTAGE: float = 0.90
    PLATFORM_CUT_PERCENTAGE: float = 0.10

    PAYSTACK_SECRET_KEY: str

    SUPABASE_URL: str 
    SUPABASE_SERVICE_KEY : str  # Use Service Role key to bypass RLS for url generation

    # MAX_COMMISSION_DEBT: float = 15000.00

    # Courier Pricing Config
    COURIER_BASE_FARE: float 
    COURIER_PER_KM_RATE: float
    COURIER_LABOR_SURCHARGE: float
    COURIER_PASSENGER_SURCHARGE: float
    COURIER_INTERSTATE_SURCHARGE: float
    COURIER_NIGHT_MULTIPLIER: float 
    COURIER_PLATFORM_COMMISSION: float 

    # Vehicle Type Multipliers
    COURIER_MULT_MOTORCYCLE: float
    COURIER_MULT_SPRINTER: float 
    COURIER_MULT_BOX_TRUCK: float 

    # Debt Ceiling for Companies: If a company's debt exceeds this limit, they will be suspended from using the platform until they clear their dues.
    MAX_DEBT_CEILING_ALLOWED: float  # NGN 100,000.00

    # Cancellation Fee: If a user cancels a trip after the driver has accepted it, they will be charged this fee.
    CANCELLATION_FEE_NGN: float  # NGN 100.00

    # --- CORS ---
    # This parses the string in .env into a real Python list
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:5173", # Vite default
        "http://127.0.0.1:5173",
        "http://localhost", 
        "http://localhost:8000",
        "https://localhost:8080"
    ]

    # ALLOWED_ORIGINS: List[str] = [ 
    #     "*"
    #     ]

    @validator("ALLOWED_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # --- PYDANTIC CONFIG ---
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore", 
        case_sensitive=True  # Production standard: keeps env vars predictable
    )


@lru_cache()
def get_settings() -> Settings:
    """
    Using lru_cache ensures the .env file is only read once.
    This is much faster for a high-traffic production API.
    """
    return Settings()

# Global settings instance
settings = get_settings()