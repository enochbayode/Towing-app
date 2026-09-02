from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials 
from jose import jwt, JWTError
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload
from typing import Optional


# Adjust these imports based on your actual project structure
from app.core.config import settings
from app.db.session import get_session
from app.models.user import User
from app.models.admin import Admin
from app.models.driver import Driver
from app.models.courier_driver import CourierDriver



# 1. Using HTTPBearer instead of OAuth2PasswordBearer
token_auth_scheme = HTTPBearer()

# ==========================================
# 2. USER DEPENDENCY
# ==========================================
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(token_auth_scheme), 
    session: AsyncSession = Depends(get_session)
) -> User:
    
    token = credentials.credentials 
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        
        # SECURITY: Ensure ID exists AND role is specifically for users
        if user_id is None or role != "user":
            print("JWT ERROR: No 'sub' found in payload") # <--- ADD THIS
            raise credentials_exception
            
    except JWTError:
        e = JWTError("Invalid token or token has expired")
        print(f"JWT CRASH TRACE: {e}") # <--- ADD THIS TO UNMASK THE ERROR
        raise credentials_exception
        
    statement = select(User).where(User.id == user_id)
    result = await session.execute(statement)
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
        
    # SECURITY: Ensure the user is actually verified
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="User account is not verified."
        )
        
    return user


# ==========================================
# 3. DRIVER DEPENDENCY 
# ==========================================
async def get_current_driver(
    credentials: HTTPAuthorizationCredentials = Depends(token_auth_scheme), 
    session: AsyncSession = Depends(get_session)
) -> Driver:
    
    token = credentials.credentials 
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        driver_id: str = payload.get("sub")
        role: str = payload.get("role")
        
        # SECURITY: Ensure ID exists AND role is specifically for drivers
        if driver_id is None or role != "driver":
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception
        
    # Fetch the driver. 
    # (Uncomment the selectinload if you add a 'vehicle' or 'company' relationship later)
    statement = (
        select(Driver)
        .where(Driver.id == driver_id) 
        # .options(selectinload(Driver.vehicle)) 
    )
    
    result = await session.execute(statement)
    driver = result.scalar_one_or_none()
    
    if driver is None:
        raise credentials_exception
        
    # SECURITY: Ensure the driver has been vetted and accepted by admin
    if driver.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Driver account is pending verification, not active, or has been revoked."
        )
        
    return driver


# ==========================================
# 4. ADMIN DEPENDENCY
# ==========================================
async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(token_auth_scheme), 
    session: AsyncSession = Depends(get_session)
) -> Admin:
    
    token = credentials.credentials 
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        admin_id: str = payload.get("sub")
        role: str = payload.get("role")
        
        # SECURITY: Ensure ID exists AND role is specifically for admins
        if admin_id is None or role != "admin":
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception
        
    statement = select(Admin).where(Admin.id == admin_id)
    result = await session.execute(statement)
    admin = result.scalar_one_or_none()
    
    if admin is None:
        raise credentials_exception
        
    return admin

# ==========================================
# 5. COURIER DRIVER DEPENDENCY
# ==========================================
async def get_current_courier(
    credentials: HTTPAuthorizationCredentials = Depends(token_auth_scheme), 
    session: AsyncSession = Depends(get_session)
) -> CourierDriver:
    
    token = credentials.credentials 
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        courier_driver_id: str = payload.get("sub")
        role: str = payload.get("role")
        
        # SECURITY: Ensure ID exists AND role is specifically for courier drivers
        if courier_driver_id is None or role != "courier_driver":
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception
        
    # Fetch the courier driver explicitly
    statement = select(CourierDriver).where(CourierDriver.id == courier_driver_id) 
    
    result = await session.execute(statement)
    courier_driver = result.scalar_one_or_none()
    
    if courier_driver is None:
        raise credentials_exception
        
    # Notice: We removed the `is_admin_verified` block here.
    # Independent couriers need to access their profile to finish onboarding.
        
    return courier_driver