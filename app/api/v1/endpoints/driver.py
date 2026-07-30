from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

# Adjust paths to match your project
from app.db.session import get_session
from app.core import security
from app.api.deps import get_current_driver
from app.models.driver import Driver
from app.schemas.user import APIResponse, LoginRequest, ChangePasswordRequest
from app.schemas.driver import DriverInviteAction, DriverResponse, DriverTokenData, DriverProfileUpdate

router = APIRouter()

# --- 1. RESPOND TO INVITATION ---
@router.post("/auth/respond-invite", response_model=APIResponse[Any])
async def respond_to_invite(
    *,
    session: AsyncSession = Depends(get_session),
    response_in: DriverInviteAction,
) -> Any:
    """
    Process the driver's response to a fleet invitation.
    Uses the temporary password for authentication.
    """
    # 1. Find the driver by email
    statement = select(Driver).where(Driver.email == response_in.email)
    result = await session.execute(statement)
    driver = result.scalar_one_or_none()

    if not driver:
        raise HTTPException(status_code=404, detail="Driver profile not found.")

    # 2. Check if the invite is still valid
    if driver.status != "pending":
        raise HTTPException(
            status_code=400, 
            detail=f"This invitation has already been processed. Current status: {driver.status}."
        )

    # 3. Verify the temporary password
    if not security.verify_password(response_in.temp_password, driver.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid temporary password.")

    # 4. Handle DECLINE
    if response_in.action == "decline":
        driver.status = "declined"
        session.add(driver)
        await session.commit()
        
        return APIResponse(
            success=True,
            message="You have successfully declined the invitation.",
            data=None
        )

    # 5. Handle ACCEPT
    # Update password, status, and verification state
    driver.hashed_password = security.get_password_hash(response_in.new_password)
    driver.status = "accepted"
    driver.is_verified = True
    
    session.add(driver)
    await session.commit()
    await session.refresh(driver)

    # 6. Auto-Login: Generate the JWT token with the "driver" role
    access_token = security.create_access_token(subject=driver.id, role="driver")
    
    driver_data = DriverResponse(
        id=str(driver.id),
        company_id=str(driver.company_id),
        full_name=driver.full_name,
        email=driver.email,
        phone_number=driver.phone_number,
        status=driver.status,
        is_verified=driver.is_verified
    )

    return APIResponse(
        success=True,
        message="Invitation accepted successfully. Welcome to the fleet.",
        data=DriverTokenData(
            access_token=access_token,
            driver=driver_data
        )
    )

# --- 2. DRIVER LOGIN ---
@router.post("/auth/login", response_model=APIResponse[DriverTokenData])
async def login_driver(
    *,
    session: AsyncSession = Depends(get_session),
    login_in: LoginRequest,
) -> Any:
    """
    Authenticate an active Driver and return a JWT token.
    """
    statement = select(Driver).where(Driver.email == login_in.email)
    result = await session.execute(statement)
    driver = result.scalar_one_or_none()

    if not driver or not security.verify_password(login_in.password, driver.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    if driver.status == "pending":
        raise HTTPException(status_code=403, detail="You must accept your invitation before logging in.")
        
    if driver.status == "declined":
        raise HTTPException(status_code=403, detail="Your account is marked as declined.")
        
    if driver.status == "suspended":
        raise HTTPException(status_code=403, detail="Your account has been suspended by your fleet administrator.")

    # Inject the "driver" role
    access_token = security.create_access_token(subject=driver.id, role="driver")
    
    driver_data = DriverResponse(
        id=str(driver.id),
        company_id=str(driver.company_id),
        full_name=driver.full_name,
        email=driver.email,
        phone_number=driver.phone_number,
        status=driver.status,
        is_verified=driver.is_verified
    )

    return APIResponse(
        success=True,
        message="Login successful.",
        data=DriverTokenData(
            access_token=access_token,
            driver=driver_data
        )
    )

# --- 3. GET CURRENT DRIVER (ME) ---
@router.get("/me", response_model=APIResponse[DriverResponse])
async def get_driver_me(
    current_driver: Driver = Depends(get_current_driver)
) -> Any:
    """
    Retrieve the profile of the currently logged-in Driver.
    """
    driver_data = DriverResponse(
        id=str(current_driver.id),
        company_id=str(current_driver.company_id),
        full_name=current_driver.full_name,
        email=current_driver.email,
        phone_number=current_driver.phone_number,
        status=current_driver.status,
        is_verified=current_driver.is_verified
    )

    return APIResponse(
        success=True,
        message="Driver profile retrieved successfully.",
        data=driver_data
    )


# --- 4. CHANGE DRIVER PASSWORD ---
@router.post("/auth/change-password", response_model=APIResponse[None])
async def change_driver_password(
    *,
    session: AsyncSession = Depends(get_session),
    password_in: ChangePasswordRequest,
    current_driver: Driver = Depends(get_current_driver)
) -> Any:
    """
    Allow an authenticated Driver to change their password securely.
    """
    # 1. Verify the old password is correct
    if not security.verify_password(password_in.old_password, current_driver.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The current password provided is incorrect.",
        )
        
    # 2. Prevent changing to the exact same password
    if password_in.old_password == password_in.new_password:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as the old password.",
        )

    # 3. Hash and save the new password
    current_driver.hashed_password = security.get_password_hash(password_in.new_password)
    
    session.add(current_driver)
    await session.commit()

    return APIResponse(
        success=True,
        message="Your password has been changed successfully.",
        data=None
    )

@router.patch("/profile", response_model=APIResponse)
async def update_driver_profile(
    payload: DriverProfileUpdate,
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
):
    """
    Updates the authenticated driver's profile information.
    Excludes sensitive fields like passwords and emails.
    """
    # 1. Extract ONLY the fields the client sent in the request
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="No valid fields provided for update."
        )

    # 2. Iterate through the dictionary and update the SQLModel instance
    for key, value in update_data.items():
        setattr(current_driver, key, value)

    # 3. Save to database
    session.add(current_driver)
    await session.commit()
    await session.refresh(current_driver)

    return APIResponse(
        success=True,
        message="Profile updated successfully.",
        data={
            "id": str(current_driver.id),
            "full_name": current_driver.full_name,
            "phone_number": current_driver.phone_number,
            "email": current_driver.email, # Safe to return, just not safe to edit here
        }
    )