from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

# Adjust paths to match your project
from uuid6 import uuid7
from app.core.supabase import supabase
from app.db.session import get_session
from app.core import security
from app.api.deps import get_current_driver
from app.models.driver import Driver
from app.models.vehicle import Vehicle
from app.schemas.user import APIResponse, LoginRequest, ChangePasswordRequest
from app.schemas.driver import DriverInviteAction, DriverResponse, DriverTokenData, DriverProfileUpdate
from app.services.kyc import verify_drivers_license, DojahNetworkError

router = APIRouter()

# --- 1. RESPOND TO INVITATION ---
@router.post("/auth/respond-invite", response_model=APIResponse[Any])
async def respond_to_invite(
    *,
    session: AsyncSession = Depends(get_session),
    response_in: DriverInviteAction,
) -> APIResponse:
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
        is_verified=False,  # Newly accepted drivers are not verified until they complete KYC
        
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
) -> APIResponse:
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
        is_verified=driver.is_verified,
        current_vehicle_id=str(driver.current_vehicle_id) if driver.current_vehicle_id else None
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
) -> APIResponse:
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
        is_verified=current_driver.is_verified,
        current_vehicle_id=str(current_driver.current_vehicle_id) if current_driver.current_vehicle_id else None,
        photo_url=current_driver.photo_url,
        average_rating=current_driver.average_rating,
        total_reviews=current_driver.total_reviews
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
) -> APIResponse:
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

# --- 5. DRIVER PROFILE MANAGEMENT ---

@router.patch("/profile", response_model=APIResponse)
async def update_driver_profile(
    payload: DriverProfileUpdate,
    session: AsyncSession = Depends(get_session),
    current_driver = Depends(get_current_driver)
) -> APIResponse:
    """
    Updates the authenticated driver's profile information.
    Excludes sensitive fields like passwords and emails.
    Triggers Driver's License verification if updated.
    """
    # 1. Extract ONLY the fields the client sent in the request
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="No valid fields provided for update."
        )

    # 2. Handle Driver's License Verification
    if "license_number" in update_data:
        new_license = update_data["license_number"]
        
        # Only trigger API call if it's a new license OR if they are currently unverified
        if new_license != current_driver.license_number or not current_driver.is_verified:
            
            # Check if another driver is already using this license
            statement = select(current_driver.__class__).where(
                current_driver.__class__.license_number == new_license, 
                current_driver.__class__.id != current_driver.id
            )
            result = await session.execute(statement)
            if result.scalar_one_or_none():
                raise HTTPException(
                    status_code=400, 
                    detail="This license number is already registered to another driver."
                )

            # Run Dojah Verification
            try:
                is_license_valid = await verify_drivers_license(new_license)
                if not is_license_valid:
                    raise HTTPException(
                        status_code=400, 
                        detail="Invalid Driver's License. Could not verify records."
                    )
                # Verification passed! 
                current_driver.is_verified = True
            except DojahNetworkError:
                raise HTTPException(
                    status_code=503, 
                    detail="License verification service is temporarily unavailable. Please try again."
                )

    # 3. Iterate through the dictionary and apply all other updates
    for key, value in update_data.items():
        setattr(current_driver, key, value)

    # 4. Save to database
    session.add(current_driver)
    await session.commit()
    await session.refresh(current_driver)

    return APIResponse(
        success=True,
        message="Profile updated successfully.",
        data={
            "id": str(current_driver.id),
            "full_name": getattr(current_driver, "full_name", None),
            "phone_number": current_driver.phone_number,
            "email": current_driver.email, 
            "photo_url": getattr(current_driver, "photo_url", None),
            "license_number": current_driver.license_number,
            "is_verified": current_driver.is_verified # Return the new status to the frontend
        }
    )

# --- 6. DRIVER VEHICLE MANAGEMENT ---
@router.get("/fleet/vehicles", response_model=APIResponse)
async def get_fleet_vehicles(
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
)-> APIResponse:
    """
    Returns all active vehicles in the driver's company.
    The frontend can use `driver_id` to show if a truck is 'Available' or 'In Use'.
    """

    # first check if the driver is verified before allowing them to see the fleet vehicles
    if not current_driver.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must complete KYC verification with a valid Driver's License before accessing fleet vehicles."
        )

    statement = select(Vehicle).where(
        Vehicle.company_id == current_driver.company_id,
        Vehicle.is_active == True
    )
    result = await session.execute(statement)
    vehicles = result.scalars().all()

    return APIResponse(
        success=True,
        message="Fleet vehicles retrieved successfully.",
        data=vehicles
    )

# --- 7. DRIVER VEHICLE SELECTION ---
@router.post("/vehicles/{vehicle_id}/select", response_model=APIResponse)
async def select_vehicle(
    vehicle_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
)-> APIResponse:
    """
    Assigns the driver to a vehicle for their shift.
    Automatically releases their previously assigned vehicle if they are switching.
    """
    # 1. Fetch the requested vehicle
    vehicle = await session.get(Vehicle, vehicle_id)
    
    if not vehicle or vehicle.company_id != current_driver.company_id:
        raise HTTPException(status_code=404, detail="Vehicle not found in your fleet.")
        
    if not vehicle.is_active:
        raise HTTPException(status_code=400, detail="This vehicle is marked as inactive/in maintenance.")

    # 2. Conflict Resolution: Is someone else already driving it?
    if vehicle.driver_id and vehicle.driver_id != current_driver.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail="This vehicle is currently occupied by another driver."
        )

    # 3. Release the driver's OLD vehicle (if they are switching trucks)
    if current_driver.current_vehicle_id and current_driver.current_vehicle_id != vehicle_id:
        old_vehicle = await session.get(Vehicle, current_driver.current_vehicle_id)
        if old_vehicle:
            old_vehicle.driver_id = None
            session.add(old_vehicle)

    # check if the driver is verified before allowing them to select a vehicle
    if not current_driver.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must complete KYC verification with a valid Driver's License before selecting a vehicle."
        )

    # 4. Secure the NEW vehicle (Sync both tables)
    vehicle.driver_id = current_driver.id
    current_driver.current_vehicle_id = vehicle.id
    
    session.add(vehicle)
    session.add(current_driver)
    await session.commit()

    return APIResponse(
        success=True,
        message=f"You are now driving the {vehicle.make} {vehicle.model} ({vehicle.license_plate}).",
        data={"vehicle_id": str(vehicle.id)}
    )

# --- 8. DRIVER VEHICLE RELEASE ---
@router.post("/vehicles/release", response_model=APIResponse)
async def release_current_vehicle(
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
)-> APIResponse:
    """
    Frees the driver's current vehicle at the end of their shift.
    """
    if not current_driver.current_vehicle_id:
        return APIResponse(
            success=True,
            message="You are not currently assigned to any vehicle.",
            data=None
        )

    # 1. Fetch the vehicle they are currently holding
    vehicle = await session.get(Vehicle, current_driver.current_vehicle_id)
    
    # 2. Break the link on both sides
    if vehicle:
        vehicle.driver_id = None
        session.add(vehicle)
        
    current_driver.current_vehicle_id = None
    session.add(current_driver)
    
    await session.commit()

    return APIResponse(
        success=True,
        message="Vehicle released successfully. Shift ended.",
        data=None
    )

# --- 9. DRIVER AVATAR ---
@router.post("/profile/photo/upload-url", response_model=APIResponse)
async def generate_profile_photo_url(
    current_driver: Driver = Depends(get_current_driver)
) -> APIResponse:
    """
    Generates a secure Supabase upload URL for the driver's profile picture.
    """
    # 1. Create a clean file path: driver-avatars/{driver_id}/avatar_{uuid}.jpg
    # Using a UUID prevents browser caching issues when they change their photo
    file_id = uuid7()
    file_path = f"driver-avatars/{current_driver.id}/avatar_{file_id}.jpg"
    
    # We use a public bucket named 'avatars' 
    BUCKET_NAME = "avatars"

    # 2. Generate the Signed Upload URL
    upload_res = supabase.storage.from_(BUCKET_NAME).create_signed_upload_url(file_path)
    
    upload_url = upload_res.get("signed_url")
    if not upload_url:
        raise HTTPException(status_code=500, detail="Failed to generate Supabase upload URL")

    # 3. Get the final public URL
    final_image_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)

    return APIResponse(
        success=True,
        message="Profile photo upload URL generated.",
        data={
            "upload_url": upload_url,       # Frontend PUTs the image file here
            "final_image_url": final_image_url # Frontend sends this to the PATCH endpoint later
        }
    )