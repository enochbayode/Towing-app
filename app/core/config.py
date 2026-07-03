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
    
    DRIVER_APP_LOGIN_URL: AnyHttpUrl = Field(default="http://localhost:3000/driver/login")  # Default for local development
    
    DOJAH_API_KEY: str
    DOJAH_APP_ID: str

    USER_FEE_PERCENTAGE: float = 0.03
    COMPANY_PAYOUT_PERCENTAGE: float = 0.90
    PLATFORM_CUT_PERCENTAGE: float = 0.10

    PAYSTACK_SECRET_KEY: str

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