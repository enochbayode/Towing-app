import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, or_

# importing models and schemas
from app.db.session import get_session
from app.core import security
from app.models.user import User
from app.models.admin import Admin
from app.models.driver import Driver
from app.schemas.user import UserCreate, UserResponse, OTPVerify, OTPResend, APIResponse, TokenData, LoginRequest, ChangePasswordRequest
from app.schemas.admin import AdminCreate, AdminResponse, AdminTokenData
from app.services.email_services import send_otp
from app.api.deps import get_current_user, get_current_admin
from app.core.config import settings


router = APIRouter()

# --- 1. USER SIGNUP (NEW) ---
@router.post("/user/signup", response_model=APIResponse[UserResponse])
async def create_user(
    *,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user_in: UserCreate,
) -> APIResponse:
    """
    Create a new User Account and send verification OTP.
    """
    # 1. Check if email already exists
    statement = select(User).where(User.email == user_in.email)
    result = await session.execute(statement)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="A user with this email already exists.",
        )

    # 2. Generate OTP and Expiration
    secure_otp = "".join(str(secrets.randbelow(10)) for _ in range(6))
    expiration_time = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(tzinfo=None)

    # 3. Create and save the User
    user = User(
        email=user_in.email,
        hashed_password=security.get_password_hash(user_in.password),
        full_name=user_in.full_name,
        is_verified=False,
        otp_code=secure_otp,
        otp_expires_at=expiration_time
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # 4. SEND THE EMAIL
    # ==========================================
    # Using a generic function that can handle users, drivers, and admins
    background_tasks.add_task(
        send_otp,
        email=user.email,
        full_name=user.full_name,
        otp_code=secure_otp,
        role="user"
    )
    
    # 5. Format and return response
    user_data = UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name
    )

    return APIResponse(
        success=True,
        message="User account created. Please check your email for the verification code.",
        data=user_data
    )


# --- 2. VERIFY USER OTP ---
@router.post("/user/verify-otp", response_model=APIResponse[UserResponse])
async def verify_user_otp(
    *,
    session: AsyncSession = Depends(get_session),
    verify_in: OTPVerify,
) -> APIResponse:
    """
    Verify the OTP sent to the User's email.
    """
    # 1. Find the user by email
    statement = select(User).where(User.email == verify_in.email)
    result = await session.execute(statement)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    # 2. Check if already verified
    if user.is_verified:
        raise HTTPException(
            status_code=400,
            detail="Account is already verified. Please proceed to login.",
        )

    # 3. Validate OTP
    if user.otp_code != verify_in.otp_code:
        raise HTTPException(
            status_code=400,
            detail="Invalid verification code.",
        )

    # 4. Validate Expiration
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)
    if user.otp_expires_at and user.otp_expires_at < current_time:
        raise HTTPException(
            status_code=400,
            detail="Verification code has expired. Please request a new one.",
        )

    # 5. Update user status to verified
    user.is_verified = True
    user.otp_code = None
    user.otp_expires_at = None
    
    session.add(user)
    await session.commit()
    await session.refresh(user)


    # 6. Format and return response
    user_data = UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name
    )

    return APIResponse(
        success=True,
        message="Account verified successfully.",
        data=user_data
    )


# --- 3. RESEND USER OTP ---
@router.post("/user/resend-otp", response_model=APIResponse[None])
async def resend_user_otp(
    *,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    resend_in: OTPResend,
) -> APIResponse:
    """
    Generate and send a new OTP to the User's email.
    """
    # 1. Find the user
    statement = select(User).where(User.email == resend_in.email)
    result = await session.execute(statement)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    # 2. Check if already verified
    if user.is_verified:
        raise HTTPException(
            status_code=400,
            detail="Account is already verified. Please proceed to login.",
        )

    # 3. Generate New OTP and Expiration
    secure_otp = "".join(str(secrets.randbelow(10)) for _ in range(6))
    expiration_time = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(tzinfo=None)

    # 4. Update the User record
    user.otp_code = secure_otp
    user.otp_expires_at = expiration_time
    
    session.add(user)
    await session.commit()

    print ("====OTP==========")
    print (f"Generated OTP for user: {secure_otp}")

    print(f"--- ENDPOINT CHECK ---")
    print(f"SETTINGS KEY IN API: '{settings.RESEND_API_KEY}'")
    
    # 5. SEND THE EMAIL
    # ==========================================
    background_tasks.add_task(
        send_otp,
        email=user.email,
        full_name=user.full_name,
        otp_code=secure_otp,
        role="user"
    )

    return APIResponse(
        success=True,
        message="A new verification code has been sent to your email.",
        data=None
    )

# --- USER LOGIN ---
@router.post("/user/login", response_model=APIResponse[TokenData])
async def login_user(
    login_data: LoginRequest, 
    session: AsyncSession = Depends(get_session)
) -> APIResponse:
    """
    Authenticate User and return a JWT token alongside the user profile.
    """
    # 1. Find User by Email
    statement = select(User).where(User.email == login_data.email)
    result = await session.execute(statement)
    user = result.scalar_one_or_none()

    # 2. Verify Password
    if not user or not security.verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # 3. Prevent unverified users from logging in
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not verified. Please verify your email first.",
        )

    # 4. Generate Token (With the critical string cast fix!)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        subject=str(user.id), 
        expires_delta=access_token_expires,
        role="user"  # Injecting the "user" role into the token payload
    )
    
    # 5. Format User Data for the mobile app payload
    user_response_data = UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name
    )

    # 6. Create the TokenData payload with the user attached
    token_data = TokenData(
        access_token=access_token,
        token_type="bearer",
        user=user_response_data
    )

    # 7. Return the Wrapped Response
    return APIResponse(
        success=True,
        message="Login successful.",
        data=token_data
    )


# ---  GET CURRENT USER (ME) ---
@router.get("/user/me", response_model=APIResponse[UserResponse])
async def get_user_me(
    current_user: User = Depends(get_current_user)
) -> APIResponse:
    """
    Retrieve the profile of the currently logged-in User.
    Notice we don't query the DB directly here; the 'Depends(get_current_user)' handles it!
    """
    user_data = UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name
    )

    return APIResponse(
        success=True,
        message="User profile retrieved successfully.",
        data=user_data
    )

# ---  CHANGE User PASSWORD ---
@router.post("/user/change-password", response_model=APIResponse[None])
async def change_password(
    *,
    session: AsyncSession = Depends(get_session),
    password_in: ChangePasswordRequest,
    current_user: User = Depends(get_current_user)
) -> APIResponse:
    """
    Allow an authenticated User to change their password.
    """
    # 1. Verify the old password is correct
    if not security.verify_password(password_in.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="The current password provided is incorrect.",
        )
        
    # 2. Prevent changing to the exact same password
    if password_in.old_password == password_in.new_password:
         raise HTTPException(
            status_code=400,
            detail="New password cannot be the same as the old password.",
        )

    # 3. Hash and save the new password
    current_user.hashed_password = security.get_password_hash(password_in.new_password)
    
    session.add(current_user)
    await session.commit()

    return APIResponse(
        success=True,
        message="Password changed successfully.",
        data=None
    )

#=============================================================
# Note: The above code focuses on the User authentication flow. 
# Here are the admin authentication endpoints
#=============================================================

# --- 1. ADMIN SIGNUP ---
@router.post("/admin/signup", response_model=APIResponse[AdminResponse])
async def create_admin(
    *,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    admin_in: AdminCreate,
) -> APIResponse:
    """
    Create a new Admin Account and send verification OTP.
    """
    # 1. Check if email or phone number already exists
    statement = select(Admin).where(
        or_(Admin.email == admin_in.email, Admin.phone_number == admin_in.phone_number)
    )
    result = await session.execute(statement)
    if result.first():
        raise HTTPException(
            status_code=400,
            detail="An admin with this email or phone number already exists.",
        )

    # 2. Generate OTP and Expiration
    secure_otp = "".join(str(secrets.randbelow(10)) for _ in range(6))
    expiration_time = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(tzinfo=None)

    # 3. Create and save the Admin
    admin = Admin(
        full_name=admin_in.full_name,
        email=admin_in.email,
        phone_number=admin_in.phone_number,
        hashed_password=security.get_password_hash(admin_in.password),
        is_verified=False,
        otp_code=secure_otp,
        otp_expires_at=expiration_time
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)

    # 4. SEND THE EMAIL (Using role="admin")
    background_tasks.add_task(
        send_otp,
        email=admin.email,
        full_name=admin.full_name,
        otp_code=secure_otp,
        role="admin"
    )
    
    # 5. Format and return response
    admin_data = AdminResponse(
        id=str(admin.id),
        full_name=admin.full_name,
        email=admin.email,
        phone_number=admin.phone_number,
        company_id=str(admin.company_id) if admin.company_id else None
    )

    return APIResponse(
        success=True,
        message="Admin account created. Please check your email for the verification code.",
        data=admin_data
    )

# --- 2. VERIFY ADMIN OTP ---
@router.post("/admin/verify-otp", response_model=APIResponse[AdminResponse])
async def verify_admin_otp(
    *,
    session: AsyncSession = Depends(get_session),
    verify_in: OTPVerify,
) -> APIResponse:
    """
    Verify the OTP sent to the Admin's email.
    """
    statement = select(Admin).where(Admin.email == verify_in.email)
    result = await session.execute(statement)
    admin = result.scalar_one_or_none()

    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found.")

    if admin.is_verified:
        raise HTTPException(status_code=400, detail="Account is already verified.")

    if admin.otp_code != verify_in.otp_code:
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    current_time = datetime.now(timezone.utc).replace(tzinfo=None)
    if admin.otp_expires_at and admin.otp_expires_at < current_time:
        raise HTTPException(status_code=400, detail="Verification code has expired.")

    admin.is_verified = True
    admin.otp_code = None
    admin.otp_expires_at = None
    
    session.add(admin)
    await session.commit()
    await session.refresh(admin)

    admin_data = AdminResponse(
        id=str(admin.id),
        full_name=admin.full_name,
        email=admin.email,
        phone_number=admin.phone_number,
        company_id=str(admin.company_id) if admin.company_id else None
    )

    return APIResponse(
        success=True,
        message="Admin account verified successfully.",
        data=admin_data
    )

# --- 3. RESEND ADMIN OTP ---
@router.post("/admin/resend-otp", response_model=APIResponse[None])
async def resend_admin_otp(
    *,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    resend_in: OTPResend,
) -> APIResponse:
    """
    Generate and send a new OTP to the Admin's email.
    """
    statement = select(Admin).where(Admin.email == resend_in.email)
    result = await session.execute(statement)
    admin = result.scalar_one_or_none()

    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found.")

    if admin.is_verified:
        raise HTTPException(status_code=400, detail="Account is already verified.")

    secure_otp = "".join(str(secrets.randbelow(10)) for _ in range(6))
    expiration_time = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(tzinfo=None)

    admin.otp_code = secure_otp
    admin.otp_expires_at = expiration_time

    print ("====OTP==========")
    print (f"Generated OTP for Admin: {secure_otp}")
    
    session.add(admin)
    await session.commit()
    
    background_tasks.add_task(
        send_otp,
        email=admin.email,
        full_name=admin.full_name,
        otp_code=secure_otp,
        role="admin"
    )

    return APIResponse(
        success=True,
        message="A new verification code has been sent to your email.",
        data=None
    )

# --- 4. ADMIN LOGIN ---
@router.post("/admin/login", response_model=APIResponse[AdminTokenData])
async def login_admin(
    login_in: LoginRequest,
    session: AsyncSession = Depends(get_session)
) -> APIResponse:
    """
    Authenticate Admin and return a JWT token alongside the admin profile.
    """
    # 1. Find Admin by Email
    statement = select(Admin).where(Admin.email == login_in.email)
    result = await session.execute(statement)
    admin = result.scalar_one_or_none()

    # 2. Verify Password
    if not admin or not security.verify_password(login_in.password, admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # 3. Prevent unverified admins from logging in
    if not admin.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not verified. Please verify your email first.",
        )

    # 4. Generate Token (With the critical string cast AND role injection)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        subject=str(admin.id),         # <--- THE CRITICAL FIX
        expires_delta=access_token_expires,
        role="admin"                   # <--- ROLE INJECTED
    )
    
    # 5. Format Admin Data for the frontend payload
    admin_data = AdminResponse(
        id=str(admin.id),
        full_name=admin.full_name,
        email=admin.email,
        phone_number=admin.phone_number,
        company_id=str(admin.company_id) if admin.company_id else None
    )

    # 6. Create the AdminTokenData payload
    token_data = AdminTokenData(
        access_token=access_token,
        token_type="bearer",
        admin=admin_data
    )

    # 7. Return the Wrapped Response
    return APIResponse(
        success=True,
        message="Login successful.",
        data=token_data
    )
# --- 5. GET CURRENT ADMIN (ME) ---
@router.get("/admin/me", response_model=APIResponse[AdminResponse])
async def get_admin_me(
    current_admin: Admin = Depends(get_current_admin)
) -> APIResponse:
    """
    Retrieve the profile of the currently logged-in Admin.
    Protected by the HTTPBearer role-checking dependency.
    """
    admin_data = AdminResponse(
        id=str(current_admin.id),
        full_name=current_admin.full_name,
        email=current_admin.email,
        phone_number=current_admin.phone_number,
        company_id=str(current_admin.company_id) if current_admin.company_id else None
    )

    return APIResponse(
        success=True,
        message="Admin profile retrieved successfully.",
        data=admin_data
    )

# --- 6. CHANGE ADMIN PASSWORD ---
@router.post("/admin/change-password", response_model=APIResponse[None])
async def change_admin_password(
    *,
    session: AsyncSession = Depends(get_session),
    password_in: ChangePasswordRequest,
    current_admin: Admin = Depends(get_current_admin)
) -> APIResponse:
    """
    Allow an authenticated Admin to change their password.
    """
    if not security.verify_password(password_in.old_password, current_admin.hashed_password):
        raise HTTPException(status_code=400, detail="The current password provided is incorrect.")
        
    if password_in.old_password == password_in.new_password:
         raise HTTPException(status_code=400, detail="New password cannot be the same as the old password.")

    current_admin.hashed_password = security.get_password_hash(password_in.new_password)
    
    session.add(current_admin)
    await session.commit()

    return APIResponse(
        success=True,
        message="Password changed successfully.",
        data=None
    )

