# app/api/v1/endpoints/company.py
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func
from sqlmodel import select
from typing import Any
from decimal import Decimal
from uuid import UUID
from sqlalchemy.exc import IntegrityError

from app.schemas.company import (
    CompanyCreate, 
    CompanyResponse, 
    PaymentAccountCreate, 
    PaymentAccountResponse,
    CompanyUpdate
)

from app.models.driver import Driver
from app.models.vehicle import Vehicle
from app.models.trip import Trip, TripStatus
from app.utils.financials import get_company_ledger_balance
from app.models.company import Company, PaymentAccount
from app.services.paystack_integration import resolve_account_name 
from app.models.admin import Admin
from app.db.session import get_session
from app.api.deps import get_current_admin
from app.utils.background_tasks import process_company_verification
from app.schemas.user import APIResponse
from app.schemas.driver import DriverStatusUpdate
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
from app.services.paystack_integration import create_paystack_subaccount, initialize_debt_settlement
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/admin/register", response_model=APIResponse[CompanyResponse])
async def register_company(
    company_in: CompanyCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin) # Ensures they are logged in
) -> APIResponse:
    
    # 1. Check if the admin already has a company registered
    if current_admin.company_id:
        raise HTTPException(
            status_code=400, 
            detail="You already have a registered company."
        )

    # 2. Save the new company to the DB (is_vetted defaults to False)
    new_company = Company(
        **company_in.model_dump(),
        admin_id=current_admin.id
    )
    session.add(new_company)
    await session.commit()
    await session.refresh(new_company)
    
    # 3. Link the company back to the Admin
    current_admin.company_id = new_company.id
    session.add(current_admin)
    await session.commit()

    # 4. Fire the background worker
    background_tasks.add_task(
        process_company_verification,
        company_id=new_company.id,
        rc_number=new_company.rc_number,
        company_name=new_company.name,
        admin_email=current_admin.email
    )

    # 5. Return success to the UI immediately
    return APIResponse(
        success=True,
        message="Company registered successfully. Verification is pending.",
        data=new_company
    )

# get company 
@router.get("/me", response_model=APIResponse[CompanyResponse])
async def get_my_company(
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
) -> APIResponse:
    """
    Retrieves the company profile owned by the currently logged-in Admin.
    """
    # 1. Check if they have a company linked
    if not current_admin.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have not registered a company yet."
        )

    # 2. Fetch the company
    statement = select(Company).where(Company.id == current_admin.company_id)
    result = await session.execute(statement)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile could not be found."
        )

    return APIResponse(
        success=True,
        message="Company details retrieved successfully.",
        data=company
    )

# update company information
@router.patch("/me", response_model=APIResponse[CompanyResponse])
async def update_my_company(
    company_update: CompanyUpdate,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
) -> APIResponse:
    """
    Updates the company profile owned by the currently logged-in Admin.
    Allows partial updates (e.g., just updating the address).
    """
    if not current_admin.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have not registered a company yet."
        )

    # Fetch the company
    statement = select(Company).where(Company.id == current_admin.company_id)
    result = await session.execute(statement)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile could not be found."
        )

    # Extract only the fields the user actually sent in the request payload
    update_data = company_update.model_dump(exclude_unset=True)
    
    # Loop through and update the company attributes
    for key, value in update_data.items():
        setattr(company, key, value)

    session.add(company)
    await session.commit()
    await session.refresh(company)

    return APIResponse(
        success=True,
        message="Company profile updated successfully.",
        data=company
    )

@router.post("/payment-account", response_model=APIResponse[PaymentAccountResponse])
async def add_payment_account(
    account_in: PaymentAccountCreate,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
) -> APIResponse:
    
    if not current_admin.company_id:
        raise HTTPException(status_code=400, detail="Register a company profile first.")
    
    statement = select(PaymentAccount).where(PaymentAccount.company_id == current_admin.company_id)
    result = await session.execute(statement)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Your company already has a payout account.")

    # --- 1. THE VERIFICATION STEP (Your existing code) ---
    verified_account_name = await resolve_account_name(
        account_number=account_in.account_number,
        bank_code=account_in.bank_code
    )
    
    if not verified_account_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not verify this bank account. Please check the account number and bank."
        )

    # --- 2. THE SUBACCOUNT CREATION STEP (The new injection) ---
    subaccount_code = await create_paystack_subaccount(
        business_name=verified_account_name, # Paystack will use the official bank name
        bank_code=account_in.bank_code,
        account_number=account_in.account_number
    )

    if not subaccount_code:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Bank verified successfully, but failed to create the split-payment profile. Please try again."
        )

    # --- 3. SAVE THE VERIFIED DATA AND SUBACCOUNT CODE ---
    new_account = PaymentAccount(
        bank_name=account_in.bank_name,
        bank_code=account_in.bank_code,
        account_number=account_in.account_number,
        account_name=verified_account_name, 
        company_id=current_admin.company_id,
        is_verified=True, 
        paystack_subaccount_code=subaccount_code # Saved for future trips!
    )
    
    session.add(new_account)
    await session.commit()
    await session.refresh(new_account)

    return APIResponse(
        success=True,
        message=f"Account linked successfully for {verified_account_name}.",
        data=new_account
    )

@router.patch("/payment-account", response_model=APIResponse[PaymentAccountResponse])
async def update_payment_account(
    account_in: PaymentAccountCreate,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
) -> APIResponse:
    """
    Updates an existing payment account.
    Requires full bank details to re-verify the account name and 
    generates a new Paystack split-payment subaccount code.
    """
    if not current_admin.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Register a company profile first."
        )

    # 1. Check if the payment account actually exists
    statement = select(PaymentAccount).where(PaymentAccount.company_id == current_admin.company_id)
    result = await session.execute(statement)
    existing_account = result.scalar_one_or_none()

    if not existing_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="No payment account found. Please add a payment account first."
        )

    # 2. Re-verify the newly provided bank details
    verified_account_name = await resolve_account_name(
        account_number=account_in.account_number,
        bank_code=account_in.bank_code
    )
    
    if not verified_account_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not verify the new bank account. Please check the account number and bank code."
        )

    # 3. Create a NEW Paystack Subaccount for the updated bank details
    new_subaccount_code = await create_paystack_subaccount(
        business_name=verified_account_name, 
        bank_code=account_in.bank_code,
        account_number=account_in.account_number
    )

    if not new_subaccount_code:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Bank verified successfully, but failed to generate a new split-payment profile. Please try again."
        )

    # 4. Update the existing record with the verified data and new subaccount code
    existing_account.bank_name = account_in.bank_name
    existing_account.bank_code = account_in.bank_code
    existing_account.account_number = account_in.account_number
    existing_account.account_name = verified_account_name
    existing_account.paystack_subaccount_code = new_subaccount_code # Overwrite the old code
    existing_account.is_verified = True
    
    session.add(existing_account)
    await session.commit()
    await session.refresh(existing_account)

    return APIResponse(
        success=True,
        message=f"Payment account successfully updated to {verified_account_name}.",
        data=existing_account
    )


# Dashboard metrics for the company
@router.get("/dashboard", response_model=APIResponse)
async def get_company_dashboard(
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
)-> APIResponse:
    """
    Returns the core metrics for the company dashboard:
    Total earnings, commission debt, completed trips, and active assets.
    """
    company_id = current_admin.company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="Register a company profile first.")

    # 1. Calculate Current Commission Debt (or Balance)
    current_balance = await get_company_ledger_balance(session, company_id)
    
    # 2. Calculate Total Lifetime Earnings (Sum of company_payout for COMPLETED trips)
    earnings_statement = select(func.coalesce(func.sum(Trip.company_payout), 0)).where(
        Trip.company_id == company_id,
        Trip.status == TripStatus.COMPLETED
    )
    earnings_result = await session.execute(earnings_statement)
    total_earnings = Decimal(str(earnings_result.scalar_one()))

    # 3. Count Total Completed Trips
    trips_statement = select(func.count(Trip.id)).where(
        Trip.company_id == company_id,
        Trip.status == TripStatus.COMPLETED
    )
    trips_result = await session.execute(trips_statement)
    total_trips = trips_result.scalar_one()

    # 4. Count Active Drivers
    drivers_statement = select(func.count(Driver.id)).where(
        Driver.company_id == company_id,
        Driver.is_active == True
    )
    drivers_result = await session.execute(drivers_statement)
    active_drivers = drivers_result.scalar_one()

    # 5. Count Active Vehicles
    vehicles_statement = select(func.count(Vehicle.id)).where(
        Vehicle.company_id == company_id,
        Vehicle.is_active == True
    )
    vehicles_result = await session.execute(vehicles_statement)
    active_vehicles = vehicles_result.scalar_one()

    return APIResponse(
        success=True,
        message="Dashboard metrics retrieved successfully.",
        data={
            "financials": {
                "total_earnings_ngn": float(total_earnings),
                "current_ledger_balance_ngn": float(current_balance),
                "is_suspended": current_balance <= -(settings.MAX_DEBT_CEILING_ALLOWED) # Tied to your debt enforcer limit!
            },
            "operations": {
                "total_completed_trips": total_trips,
                "active_drivers_count": active_drivers,
                "active_vehicles_count": active_vehicles
            }
        }
    )

# debt settlement endpoint
@router.post("/settle-debt", response_model=APIResponse)
async def settle_company_debt(
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
)-> APIResponse:
    """
    Checks the company's ledger and initializes a Paystack checkout 
    if they have a negative balance.
    """
    company_id = current_admin.company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="Register a company profile first.")

    # 1. Get the current ledger balance
    current_balance = await get_company_ledger_balance(session, company_id)

    # 2. Prevent them from paying if they don't owe anything
    if current_balance >= Decimal("0.00"):
        raise HTTPException(
            status_code=400, 
            detail="Your company currently has no outstanding commission debt."
        )

    # 3. The balance is negative, so convert it to a positive absolute amount for checkout
    amount_to_pay = abs(float(current_balance))

    # 4. Initialize Paystack
    paystack_data = await initialize_debt_settlement(
        email=current_admin.email, # Ensure Admin model has an email field, or fetch company email
        amount_ngn=amount_to_pay,
        company_id=str(company_id)
    )

    if not paystack_data:
        raise HTTPException(
            status_code=502, 
            detail="Failed to connect to the payment gateway. Try again later."
        )

    return APIResponse(
        success=True,
        message="Payment initialized successfully.",
        data={
            "authorization_url": paystack_data["authorization_url"],
            "reference": paystack_data["reference"],
            "amount_ngn": amount_to_pay
        }
    )

# get all drivers in the company
@router.get("/drivers", response_model=APIResponse)
async def get_company_drivers(
    skip: int = 0,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
)-> APIResponse:
    """Returns a paginated list of all drivers in the company's fleet."""
    company_id = current_admin.company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="Register a company profile first.")

    # Fetch drivers belonging to this company, newest first
    statement = select(Driver).where(
        Driver.company_id == company_id
    ).order_by(Driver.created_at.desc()).offset(skip).limit(limit)
    
    result = await session.execute(statement)
    drivers = result.scalars().all()

    return APIResponse(
        success=True,
        message="Drivers retrieved successfully.",
        data=drivers
    )

# Admin can activate or deactivate a driver in their fleet
@router.patch("/drivers/{driver_id}/status", response_model=APIResponse)
async def update_driver_status(
    driver_id: UUID,
    payload: DriverStatusUpdate,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
)-> APIResponse:
    """
    Activates or deactivates a driver. 
    A deactivated driver cannot accept new trip dispatches.
    """
    company_id = current_admin.company_id
    
    # Ensure the driver actually belongs to this specific fleet
    statement = select(Driver).where(
        Driver.id == driver_id, 
        Driver.company_id == company_id
    )
    result = await session.execute(statement)
    driver = result.scalar_one_or_none()

    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found in your fleet.")

    driver.is_active = payload.is_active
    session.add(driver)
    await session.commit()
    await session.refresh(driver)

    status_msg = "activated" if driver.is_active else "deactivated"
    
    return APIResponse(
        success=True,
        message=f"Driver has been successfully {status_msg}.",
        data={"driver_id": str(driver.id), "is_active": driver.is_active}
    )

# Admin can view all trips associated with their company
@router.get("/trips", response_model=APIResponse)
async def get_company_trips(
    skip: int = 0,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
)-> APIResponse:
    """
    Returns a paginated list of the company's dispatch history.
    """
    company_id = current_admin.company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="Register a company profile first.")

    statement = select(Trip).where(
        Trip.company_id == company_id
    ).order_by(Trip.created_at.desc()).offset(skip).limit(limit)
    
    result = await session.execute(statement)
    trips = result.scalars().all()

    return APIResponse(
        success=True,
        message="Trip history retrieved successfully.",
        data=trips
    )


#===========Company Vehicle Management Endpoints===========

@router.post("/add-vehicle", response_model=APIResponse)
async def add_vehicle(
    payload: VehicleCreate,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
)-> APIResponse:
    """Adds a new tow truck to the company's fleet."""
    if not current_admin.company_id:
        raise HTTPException(status_code=400, detail="Register a company profile first.")

    # Check for duplicate license plates
    statement = select(Vehicle).where(Vehicle.license_plate == payload.license_plate)
    result = await session.execute(statement)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A vehicle with this license plate already exists.")

    new_vehicle = Vehicle(
        **payload.model_dump(),
        company_id=current_admin.company_id,
        is_active=True
    )
    
    session.add(new_vehicle)
    await session.commit()
    await session.refresh(new_vehicle)

    return APIResponse(success=True, message="Vehicle added successfully.", data=new_vehicle)


@router.patch("/{vehicle_id}", response_model=APIResponse)
async def update_vehicle(
    vehicle_id: UUID,
    payload: VehicleUpdate,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
)-> APIResponse:
    """Edits an existing vehicle's details."""
    statement = select(Vehicle).where(
        Vehicle.id == vehicle_id, 
        Vehicle.company_id == current_admin.company_id
    )
    result = await session.execute(statement)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(vehicle, key, value)

    session.add(vehicle)
    await session.commit()
    await session.refresh(vehicle)

    return APIResponse(
        success=True, 
        message="Vehicle updated successfully.", 
        data=vehicle
    )


# Delete Vehicle Endpoint
@router.delete("/{vehicle_id}", response_model=APIResponse)
async def delete_vehicle(
    vehicle_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
)-> APIResponse:
    """
    Permanently deletes a vehicle from the company's fleet.
    Will fail if the vehicle is already associated with historical trips.
    """
    if not current_admin.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Register a company profile first."
        )

    # 1. Verify the vehicle exists and belongs to this company
    statement = select(Vehicle).where(
        Vehicle.id == vehicle_id, 
        Vehicle.company_id == current_admin.company_id
    )
    result = await session.execute(statement)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Vehicle not found."
        )

    # 2. Attempt the Hard Delete
    try:
        await session.delete(vehicle)
        await session.commit()
    except IntegrityError:
        # If it fails, rollback the transaction to prevent database locking
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot delete this vehicle because it has already been used for dispatch trips. "
                "Please use the update endpoint to set 'is_active' to false instead."
            )
        )

    return APIResponse(
        success=True, 
        message="Vehicle deleted successfully.", 
        data=None
    )