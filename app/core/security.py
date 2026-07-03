import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Any, Union
from jose import jwt
from app.core.config import settings

# --- AUTHENTICATION LOGIC ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Checks if the password matches the hash.
    Uses the bcrypt library DIRECTLY to bypass Passlib's Python 3.14 bugs.
    """
    try:
        if not hashed_password:
            return False
            
        # Convert strings to bytes (Required by the bcrypt engine)
        password_bytes = plain_password.encode('utf-8')
        hash_bytes = hashed_password.encode('utf-8')
        
        # Manually truncate to 72 bytes to satisfy Bcrypt's hard limit
        # This stops the ValueError your dev is seeing.
        return bcrypt.checkpw(password_bytes[:72], hash_bytes)
    except Exception as e:
        print(f"AUTH ERROR on {settings.PROJECT_NAME}: {e}")
        return False

def get_password_hash(password: str) -> str:
    """
    Hashes a password directly using the bcrypt library.
    """
    # 1. Truncate to 72 chars (Bcrypt limit) and convert to bytes
    password_bytes = password.encode('utf-8')[:72]
    
    # 2. Generate a fresh salt and hash
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    
    # 3. Return as a string for the database
    return hashed.decode('utf-8')

# ---  TOKEN LOGIC ---

def create_access_token(subject: Union[str, Any], expires_delta: timedelta = None, **kwargs) -> str:
    """
    Generates a JWT Token for both Admin and Manager. 
    The **kwargs captures extra claims like role='admin' or role='kiosk_manager'.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        # Default to 72 hours
        expire = datetime.now(timezone.utc) + timedelta(hours=72)
    
    # 1. Standard claims
    to_encode = {"exp": expire, "sub": str(subject)}
    
    # 2. Merge extra claims (This ensures roles work for both Admin & Manager)
    to_encode.update(kwargs)
    
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.SECRET_KEY, 
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt