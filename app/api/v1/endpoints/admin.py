import secrets
import string
import os
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, or_

# Adjust paths to match your project
from app.db.session import get_session
from app.core import security
from app.api.deps import get_current_admin
from app.models.admin import Admin
from app.models.driver import Driver
from app.models.company import Company
from app.schemas.user import APIResponse
from app.schemas.driver import DriverInvite, DriverResponse, DriverStatusUpdate
from app.utils.email import send_driver_invite_email


router = APIRouter()

# Get the frontend URL from environment variables, fallback to a default
DRIVER_APP_LOGIN_URL = os.getenv("DRIVER_APP_LOGIN_URL", "http://localhost:3000/driver/login")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://app.towingapp.com")

def generate_temp_password(length: int = 10) -> str:
    """Generate a secure, random temporary password."""
    alphabet = string.ascii_letters + string.digits + "@#$%"
    return ''.join(secrets.choice(alphabet) for i in range(length))



# --- 1. INVITE A DRIVER ---
@router.post("/drivers/invite", response_model=APIResponse[DriverResponse])
async def invite_driver(
    *,
    session: AsyncSession = Depends(get_session),
    invite_in: DriverInvite, # This schema now only requires full_name and email
    current_admin: Admin = Depends(get_current_admin)
) -> Any:
    """
    Invite a new driver to the Admin's company. Generates a temporary password,
    creates the account as 'pending' using only email and name, and sends an onboarding email.
    The driver will provide their phone number and other details upon accepting the invite.
    """
    # 1. Ensure the Admin actually has a registered company
    if not current_admin.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must register a company profile before inviting drivers."
        )

    # Fetch company details for the email template
    statement = select(Company).where(Company.id == current_admin.company_id)
    result = await session.execute(statement)
    company = result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated company profile not found."
        )

    # 2. Check if the driver email already exists globally
    statement = select(Driver).where(Driver.email == invite_in.email)
    result = await session.execute(statement)
    existing_driver = result.scalars().first()
    
    if existing_driver:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A driver with this email is already registered on the platform."
        )

    # 3. Generate Temporary Password
    temp_password = generate_temp_password()

    # 4. Create the Driver as PENDING (phone_number is left empty/NULL)
    driver = Driver(
        company_id=current_admin.company_id,
        full_name=invite_in.full_name,
        email=invite_in.email,
        phone_number=None, # Left Null at invite stage
        hashed_password=security.get_password_hash(temp_password),
        status="pending",   
        is_verified=False,
        is_online=False,
        is_available=True
    )
    
    session.add(driver)
    await session.commit()
    await session.refresh(driver)

    # 5. Generate the Invite Link and Send the Email
    invite_link = f"{FRONTEND_URL}/driver/accept-invite?email={driver.email}"
    
    try:
        send_driver_invite_email(
            driver_email=driver.email,
            driver_name=driver.full_name,
            temp_password=temp_password,
            invite_link=invite_link,
            company_name=company.name
        )
    except Exception as e:
        # We don't fail the transaction if email fails, but we should log it
        import logging
        logging.getLogger(__name__).error(f"Failed to send invite email to {driver.email}: {str(e)}")

    # 6. Return response with explicitly casted UUID fields to strings
    return APIResponse(
        success=True,
        message=f"Driver invited successfully. Login credentials sent to {driver.email}.",
        data=DriverResponse(
            id=str(driver.id),                 # Cast UUID to string to resolve validation error
            company_id=str(driver.company_id), # Cast UUID to string to resolve validation error
            full_name=driver.full_name,
            email=driver.email,
            phone_number=None,                 # Returned as Null until they complete onboarding
            status=driver.status,
            is_verified=driver.is_verified
        )
    )


# --- 2. GET ALL COMPANY DRIVERS ---
@router.get("/get-drivers", response_model=APIResponse[List[DriverResponse]])
async def get_company_drivers(
    *,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
) -> Any:
    """
    Retrieve a list of all drivers (pending, accepted, or suspended) 
    operating under the current Admin's company.
    """
    if not current_admin.company_id:
        return APIResponse(success=True, message="No company registered.", data=[])

    statement = select(Driver).where(Driver.company_id == current_admin.company_id)
    result = await session.execute(statement)
    drivers = result.scalars().all()

    drivers_data = [
        DriverResponse(
            id=str(d.id),
            company_id=str(d.company_id),
            full_name=d.full_name,
            email=d.email,
            phone_number=d.phone_number,
            status=d.status,
            is_verified=d.is_verified
        ) for d in drivers
    ]

    return APIResponse(
        success=True,
        message="Drivers retrieved successfully.",
        data=drivers_data
    )


# --- 3. SUSPEND DRIVER ---
@router.patch("/drivers/{driver_id}/suspend", response_model=APIResponse[DriverResponse])
async def suspend_driver(
    *,
    session: AsyncSession = Depends(get_session),
    driver_id: str,
    current_admin: Admin = Depends(get_current_admin)
) -> Any:
    """
    Suspend a driver. This prevents them from logging in or receiving dispatch requests.
    Admins can only suspend drivers within their own company.
    """
    if not current_admin.company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No company registered.")

    # 1. Find the driver securely
    statement = select(Driver).where(
        (Driver.id == driver_id) & (Driver.company_id == current_admin.company_id)
    )
    result = await session.execute(statement)
    driver = result.scalar_one_or_none()

    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found or does not belong to your company."
        )

    # 2. Prevent redundant actions
    if driver.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This driver is already suspended."
        )

    # 3. Apply suspension
    driver.status = "suspended"
    
    session.add(driver)
    await session.commit()
    await session.refresh(driver)

    return APIResponse(
        success=True,
        message=f"Driver {driver.full_name} has been suspended.",
        data=DriverResponse(
            id=str(driver.id),
            company_id=str(driver.company_id),
            full_name=driver.full_name,
            email=driver.email,
            phone_number=driver.phone_number,
            status=driver.status,
            is_verified=driver.is_verified
        )
    )


# --- 4. REACTIVATE DRIVER ---
@router.patch("/drivers/{driver_id}/reactivate", response_model=APIResponse[DriverResponse])
async def reactivate_driver(
    *,
    session: AsyncSession = Depends(get_session),
    driver_id: str,
    current_admin: Admin = Depends(get_current_admin)
) -> Any:
    """
    Reactivate a previously suspended driver. 
    Restores them to 'accepted' if they previously verified, or 'pending' if they haven't.
    """
    if not current_admin.company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No company registered.")

    # 1. Find the driver securely
    statement = select(Driver).where(
        (Driver.id == driver_id) & (Driver.company_id == current_admin.company_id)
    )
    result = await session.execute(statement)
    driver = result.scalar_one_or_none()

    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found or does not belong to your company."
        )

    # 2. Prevent reactivating an active driver
    if driver.status != "suspended":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This driver is not currently suspended."
        )

    # 3. Smart Reactivation Logic
    if driver.is_verified:
        driver.status = "accepted"
    else:
        driver.status = "pending"
    
    session.add(driver)
    await session.commit()
    await session.refresh(driver)

    return APIResponse(
        success=True,
        message=f"Driver {driver.full_name} has been reactivated.",
        data=DriverResponse(
            id=str(driver.id),
            company_id=str(driver.company_id),
            full_name=driver.full_name,
            email=driver.email,
            phone_number=driver.phone_number,
            status=driver.status,
            is_verified=driver.is_verified
        )
    )

