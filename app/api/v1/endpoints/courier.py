# app/api/v1/endpoints/courier.py
import asyncio
import random
from decimal import Decimal
from sqlmodel import select
import secrets
from datetime import timedelta, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlmodel.ext.asyncio.session import AsyncSession

# Import your database and auth dependencies (adjust paths as needed)
from app.db.session import get_session
from app.api.deps import get_current_courier, get_current_user
from app.models.user import User

from app.db.session import get_session
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.config import settings
from app.core import security

# Import the schemas we just built
from app.schemas.courier import CourierTripCreate, CourierTripResponse, TripCancelRequest
from app.models.courier_driver import CourierDriver
from app.models.courier_vehicle import CourierVehicle
from app.schemas.courier_driver import CourierVehicleCreate
from app.schemas.courier_driver import (
    CourierDriverRegister, 
    CourierDriverLogin, 
    CourierDriverResponse,
    CourierDriverUpdate,
    CourierStatusUpdate,
    CourierVehicleUpdate,
    LicenseVerificationRequest
)
from app.schemas.response import APIResponse
from app.services.email_services import send_otp
from app.services.identity import verify_drivers_license

from app.models.courier_driver import CourierDriver
from app.schemas.courier_driver import CourierBankUpdate
from app.services.paystack_integration import resolve_account_name

from app.api.deps import get_current_driver

router = APIRouter()

# register courier driver endpoint
@router.post("/register", response_model=APIResponse)
async def register_courier_driver(
    payload: CourierDriverRegister,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """
    Registers a new independent courier driver and triggers a background email with their OTP.
    """
    existing_driver = await session.execute(
        select(CourierDriver).where(
            (CourierDriver.email == payload.email) | 
            (CourierDriver.phone_number == payload.phone_number)
        )
    )
    if existing_driver.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A courier driver with this email or phone number already exists."
        )

    # Generate OTP and expiration
    secure_otp = f"{random.randint(100000, 999999)}"
    otp_expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15)

    # Create the standalone driver record
    new_driver = CourierDriver(
        full_name=payload.full_name,
        email=payload.email,
        phone_number=payload.phone_number,
        hashed_password=get_password_hash(payload.password),
        can_do_labor=payload.can_do_labor,
        interstate_enabled=payload.interstate_enabled,
        verification_token=secure_otp,
        verification_token_expires_at=otp_expiry,
        is_email_verified=False,
        is_verified=False
    )

    session.add(new_driver)
    await session.commit()
    await session.refresh(new_driver)

    print("===================================")
    print(f"Generated OTP for {new_driver.email}: {secure_otp} (expires at {otp_expiry})")
    print("===================================")

    # Trigger the background email task
    background_tasks.add_task(
        send_otp,
        email=new_driver.email,
        full_name=new_driver.full_name,
        otp_code=secure_otp,
        role="courier_driver"
    )

    return APIResponse(
        success=True,
        message="Courier registered successfully. Please check your email for the verification code.",
        data={"courier_driver_id": str(new_driver.id)}
    )

# Verify courier email endpoint
@router.post("/verify-email", response_model=APIResponse)
async def verify_courier_email(
    email: str,
    otp_code: str,
    session: AsyncSession = Depends(get_session)
)-> APIResponse:
    """
    Verifies the courier's email using the standalone profile OTP.
    """
    result = await session.execute(
        select(CourierDriver).where(CourierDriver.email == email)
    )
    driver = result.scalar_one_or_none()

    if not driver:
        raise HTTPException(status_code=404, detail="Courier driver not found.")

    if driver.is_email_verified:
        raise HTTPException(status_code=400, detail="Email is already verified.")

    current_time = datetime.now(timezone.utc).replace(tzinfo=None)

    if driver.verification_token != otp_code:
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    if driver.verification_token_expires_at and driver.verification_token_expires_at < current_time:
        raise HTTPException(status_code=400, detail="Verification code has expired.")

    # Mark as verified and clean up
    driver.is_email_verified = True
    driver.verification_token = None
    driver.verification_token_expires_at = None

    session.add(driver)
    await session.commit()

    return APIResponse(
        success=True,
        message="Email verified successfully. You can now log in and register your vehicle.",
        data={"courier_id": str(driver.id)}
    )

# Login endpoint for courier drivers
@router.post("/login", response_model=APIResponse)
async def courier_login(
    email: str,
    password: str,
    session: AsyncSession = Depends(get_session)
)-> APIResponse:
    """
    Authenticates a courier driver and returns a secure JWT access token.
    """
    result = await session.execute(
        select(CourierDriver).where(CourierDriver.email == email)
    )
    driver = result.scalar_one_or_none()

    if not driver or not verify_password(password, driver.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password."
        )

    if not driver.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in."
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    access_token = security.create_access_token(
        subject=str(driver.id),
        expires_delta=access_token_expires,
        role="courier_driver"  # Injecting the distinct courier role
    )

    return APIResponse(
        success=True,
        message="Login successful.",
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "courier_driver_id": str(driver.id)
        }
    )

# resend OTP endpoint for courier drivers
@router.post("/resend-otp", response_model=APIResponse)
async def resend_otp(
    email: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
)-> APIResponse:
    """
    Resends a new OTP to the courier driver's email for verification.
    """
    result = await session.execute(
        select(CourierDriver).where(CourierDriver.email == email)
    )
    driver = result.scalar_one_or_none()

    if not driver:
        raise HTTPException(status_code=404, detail="Courier driver not found.")

    if driver.is_email_verified:
        raise HTTPException(status_code=400, detail="Email is already verified.")

    # Generate a new OTP and expiration
    new_otp = f"{random.randint(100000, 999999)}"
    otp_expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15)

    driver.verification_token = new_otp
    driver.verification_token_expires_at = otp_expiry

    session.add(driver)
    await session.commit()

    print("===================================")
    print(f"Resent OTP for {driver.email}: {new_otp} (expires at {otp_expiry})")
    print("===================================")

    # Trigger the background email task
    background_tasks.add_task(
        send_otp,
        email=driver.email,
        full_name=driver.full_name,
        otp_code=new_otp,
        role="courier_driver"
    )

    return APIResponse(
        success=True,
        message="A new verification code has been sent to your email.",
        data={"courier_id": str(driver.id)}
    )

# get courier profile endpoint
@router.get("/me", response_model=APIResponse)
async def get_courier_profile(
    current_courier: CourierDriver = Depends(get_current_courier)
)-> APIResponse:
    """
    Retrieves the authenticated courier's profile. 
    The frontend should check `current_vehicle_id` before allowing the driver to go online.
    """
    return APIResponse(
        success=True,
        message="Courier profile retrieved successfully.",
        data={
            "id": str(current_courier.id),
            "full_name": current_courier.full_name,
            "email": current_courier.email,
            "phone_number": current_courier.phone_number,
            "is_verified": current_courier.is_verified,
            "is_online": current_courier.is_online,
            "is_available": current_courier.is_available,
            "can_do_labor": current_courier.can_do_labor,
            "interstate_enabled": current_courier.interstate_enabled,
            "current_vehicle_id": str(current_courier.current_vehicle_id) if current_courier.current_vehicle_id else None
        }
    )

# toggle online status endpoint for courier drivers
@router.patch("/status", response_model=APIResponse)
async def toggle_online_status(
    payload: CourierStatusUpdate,
    current_courier: CourierDriver = Depends(get_current_courier),
    session: AsyncSession = Depends(get_session)
)-> APIResponse:
    """
    Allows an independent courier to toggle their online status.
    Enforces NIN verification and vehicle registration before going online.
    """
    # 1. Enforce constraints if the driver is trying to go ONLINE
    if payload.is_online:
        if not current_courier.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must verify your driving liscense before you can go online."
            )
            
        if not current_courier.current_vehicle_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must register an active vehicle before you can go online."
            )

    # 2. Update the status
    current_courier.is_online = payload.is_online
    
    # Optional: Automatically toggle `is_available` to match `is_online`.
    # (If they go offline, they definitely aren't available).
    if not payload.is_online:
        current_courier.is_available = False
    else:
        current_courier.is_available = True

    session.add(current_courier)
    await session.commit()

    status_text = "online and ready for trips" if current_courier.is_online else "offline"

    return APIResponse(
        success=True,
        message=f"You are now {status_text}.",
        data={
            "is_online": current_courier.is_online,
            "is_available": current_courier.is_available
        }
    )

# Verify Driver's License Endpoint
@router.post("/verify-license", response_model=APIResponse)
async def verify_courier_license(
    payload: LicenseVerificationRequest,
    current_courier: CourierDriver = Depends(get_current_courier),
    session: AsyncSession = Depends(get_session)
)-> APIResponse:
    """
    Accepts the courier's Driver's License number, validates it via Dojah/Smile ID, 
    and updates their verification status.
    """
    if current_courier.is_verified:
        return APIResponse(
            success=True,
            message="Your account is already verified.",
            data={"is_verified": True}
        )

    # Trigger the DL helper function
    is_valid = await verify_drivers_license(payload.license_number)

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver's license verification failed. Please check the number and try again."
        )

    # Update the courier profile upon successful verification
    current_courier.is_verified = True
    
    session.add(current_courier)
    await session.commit()

    return APIResponse(
        success=True,
        message="Driver's License verified successfully. You can now register a vehicle.",
        data={"is_verified": current_courier.is_verified}
    )

# Courier Vehicle & Trip Endpoints
@router.post("/vehicles", response_model=APIResponse)
async def register_courier_vehicle(
    payload: CourierVehicleCreate,
    current_courier: CourierDriver = Depends(get_current_courier),
    session: AsyncSession = Depends(get_session)
)-> APIResponse:
    """
    Registers a new delivery vehicle for the authenticated courier driver
    and automatically sets it as their active vehicle.
    """
    # 1. Prevent registering duplicate license plates across the platform
    existing_vehicle = await session.execute(
        select(CourierVehicle).where(CourierVehicle.license_plate == payload.license_plate)
    )
    if existing_vehicle.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A vehicle with this license plate is already registered on the platform."
        )

    # 2. Create the vehicle record linked directly to this courier
    new_vehicle = CourierVehicle(
        driver_id=current_courier.id,
        make=payload.make,
        model=payload.model,
        year=payload.year,
        license_plate=payload.license_plate.upper(),
        capacity_tons=payload.capacity_tons,
        vehicle_type=payload.vehicle_type,
        is_active=True
    )

    session.add(new_vehicle)
    await session.commit()
    await session.refresh(new_vehicle)

    # 3. Automatically link this as the courier's current active vehicle
    current_courier.current_vehicle_id = new_vehicle.id
    session.add(current_courier)
    await session.commit()

    return APIResponse(
        success=True,
        message="Vehicle registered and set as your active vehicle successfully.",
        data={
            "vehicle_id": str(new_vehicle.id),
            "make": new_vehicle.make,
            "model": new_vehicle.model,
            "license_plate": new_vehicle.license_plate,
            "vehicle_type": new_vehicle.vehicle_type,
            "capacity_tons": new_vehicle.capacity_tons
        }
    )

# Update courier vehicle endpoint
@router.patch("/vehicles/{vehicle_id}", response_model=APIResponse)
async def update_courier_vehicle(
    vehicle_id: str,
    payload: CourierVehicleUpdate,
    current_courier: CourierDriver = Depends(get_current_courier),
    session: AsyncSession = Depends(get_session)
)-> APIResponse:
    """
    Updates a courier's vehicle details. 
    Ensures they only modify their own vehicle and checks plate uniqueness.
    """
    # 1. Fetch vehicle and verify ownership
    vehicle = await session.get(CourierVehicle, vehicle_id)
    if not vehicle or str(vehicle.driver_id) != str(current_courier.id):
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    # 2. Check for license plate collisions if they are changing it
    if payload.license_plate and payload.license_plate.upper() != vehicle.license_plate:
        existing = await session.execute(
            select(CourierVehicle).where(CourierVehicle.license_plate == payload.license_plate.upper())
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="This license plate is already registered.")
        vehicle.license_plate = payload.license_plate.upper()

    # 3. Apply partial updates to other fields
    update_data = payload.model_dump(exclude_unset=True, exclude={"license_plate"})
    for key, value in update_data.items():
        setattr(vehicle, key, value)

    session.add(vehicle)
    await session.commit()
    await session.refresh(vehicle)

    return APIResponse(
        success=True,
        message="Vehicle updated successfully.",
        data={
            "vehicle_id": str(vehicle.id),
            "make": vehicle.make,
            "model": vehicle.model,
            "license_plate": vehicle.license_plate
        }
    )

# Delete courier vehicle endpoint
@router.delete("/vehicles/{vehicle_id}", response_model=APIResponse)
async def delete_courier_vehicle(
    vehicle_id: str,
    current_courier: CourierDriver = Depends(get_current_courier),
    session: AsyncSession = Depends(get_session)
)-> APIResponse:
    """
    Deletes a vehicle. If the vehicle is currently active, it kicks 
    the driver offline and unlinks the vehicle from their profile.
    """
    vehicle = await session.get(CourierVehicle, vehicle_id)
    if not vehicle or str(vehicle.driver_id) != str(current_courier.id):
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    # Business Logic: If they delete their active van, pull them offline immediately
    if str(current_courier.current_vehicle_id) == str(vehicle.id):
        current_courier.current_vehicle_id = None
        current_courier.is_online = False
        current_courier.is_available = False
        session.add(current_courier)

    # Note: If trips are tied to this vehicle ID via foreign keys, a hard delete will crash.
    # If that's the case, replace `await session.delete(vehicle)` with a soft delete: 
    # vehicle.is_active = False 
    # session.add(vehicle)
    
    await session.delete(vehicle)
    await session.commit()

    return APIResponse(
        success=True,
        message="Vehicle deleted successfully.",
        data=None
    )


@router.put("/bank-details", response_model=APIResponse)
async def update_bank_details(
    payload: CourierBankUpdate,
    session: AsyncSession = Depends(get_session),
    current_driver: CourierDriver = Depends(get_current_driver)
)-> APIResponse:
    """
    Adds or updates a driver's bank account.
    Calls Paystack's Account Resolution API to verify the name before saving.
    """
    # 1. Call Paystack to verify the account
    verified_name = await resolve_account_name(
        account_number=payload.account_number,
        bank_code=payload.bank_code
    )

    # 2. Reject if Paystack says it's invalid
    if not verified_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account details. Please check the account number and bank."
        )

    # 3. Save the details to the database (including the verified name)
    current_driver.bank_name = payload.bank_name
    current_driver.bank_code = payload.bank_code
    current_driver.account_number = payload.account_number
    current_driver.account_name = verified_name # Save the exact name from the bank

    session.add(current_driver)
    await session.commit()
    await session.refresh(current_driver)

    return APIResponse(
        success=True,
        message="Bank account verified and saved successfully.",
        data={
            "bank_name": current_driver.bank_name,
            "account_number": current_driver.account_number,
            "account_name": current_driver.account_name
        }
    )

# delete bank details endpoint
@router.delete("/bank-details", response_model=APIResponse)
async def delete_bank_details(
    session: AsyncSession = Depends(get_session),
    current_driver: CourierDriver = Depends(get_current_driver)
)-> APIResponse:
    """
    Deletes the driver's saved bank account details.
    """
    current_driver.bank_name = None
    current_driver.bank_code = None
    current_driver.account_number = None
    current_driver.account_name = None

    session.add(current_driver)
    await session.commit()

    return APIResponse(
        success=True,
        message="Bank account details removed successfully.",
        data=None
    )

