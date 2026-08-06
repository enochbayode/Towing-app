# app/api/v1/endpoints/trip.py
import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID
from sqlalchemy import func

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.db.session import get_session
from app.api.deps import get_current_user, get_current_driver
from app.models.trip import (
    Trip, 
    TripStatus, 
    PaymentMethod, 
    PaymentStatus, 
    CompanyLedger, 
    LedgerEntryType, 
    Transaction, 
    TransactionType
)
from app.models.user import User
from app.models.driver import Driver
from app.models.company import Company
from app.services.paystack_integration import initialize_paystack_transaction
from app.models.vehicle import Vehicle
from app.schemas.trip import TripTrackingResponse, DriverTrackingInfo, CompanyTrackingInfo, VehicleTrackingInfo


from app.services.pricing_engine import calculate_tow_cost
from app.core.config import settings
from app.schemas.trip import TripCreateSchema, TripConfirmSchema
from app.schemas.user import APIResponse

router = APIRouter()
logger = logging.getLogger(__name__)


MAX_COMMISSION_DEBT_ALLOWED = settings.MAX_COMMISSION_DEBT_ALLOWED  # e.g., -10000.00 NGN

# ==========================================
# 1. ESTIMATE & CONFIRMATION FLOW
# ==========================================

@router.post("/estimate", response_model=APIResponse)
async def get_trip_estimate(
    trip_in: TripCreateSchema,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Step 1: Calculates cost (via Google Maps driving route) and creates a draft trip.
    """
    calculated_base_cost = await calculate_tow_cost(
        pickup_lat=trip_in.pickup_lat, pickup_lng=trip_in.pickup_lng,
        dropoff_lat=trip_in.dropoff_lat, dropoff_lng=trip_in.dropoff_lng,
        vehicle_type=trip_in.vehicle_type, truck_type=trip_in.truck_type
    )
    
    user_fee = round(calculated_base_cost * Decimal(str(settings.USER_FEE_PERCENTAGE)), 2)
    total_user_charge = round(calculated_base_cost + user_fee, 2)
    company_payout = round(calculated_base_cost * Decimal(str(settings.COMPANY_PAYOUT_PERCENTAGE)), 2)
    platform_fee = round((calculated_base_cost * Decimal(str(settings.PLATFORM_CUT_PERCENTAGE))) + user_fee, 2)

    new_trip = Trip(
        user_id=current_user.id,
        pickup_address=trip_in.pickup_address,
        pickup_lat=trip_in.pickup_lat,
        pickup_lng=trip_in.pickup_lng,
        dropoff_address=trip_in.dropoff_address,
        dropoff_lat=trip_in.dropoff_lat,
        dropoff_lng=trip_in.dropoff_lng,
        vehicle_details=trip_in.vehicle_details,
        total_cost=total_user_charge,
        platform_fee=platform_fee,
        company_payout=company_payout,
        payment_method=PaymentMethod.CASH, # Default to CASH
        status=TripStatus.PENDING_ESTIMATE
    )
    
    session.add(new_trip)
    await session.commit()
    await session.refresh(new_trip)

    return APIResponse(
        success=True,
        message="Estimate calculated successfully.",
        data={
            "trip_id": str(new_trip.id),
            "total_charge": str(total_user_charge),
            "currency": "NGN"
        }
    )

# ----confirmation endpoint is below, after the WebSocket and location update endpoints
@router.post("/confirm", response_model=APIResponse)
async def confirm_and_request_trip(
    payload: TripConfirmSchema,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Step 2: User selects payment method (CASH or CARD) and confirms.
    - If CASH: Immediately shifts status to SEARCHING for drivers.
    - If CARD: Initializes Paystack split payment flow and generates authorization URL.
    """
    statement = select(Trip).where(Trip.id == payload.trip_id, Trip.user_id == current_user.id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip estimate not found.")
        
    if trip.status != TripStatus.PENDING_ESTIMATE:
        raise HTTPException(status_code=400, detail="This trip has already been requested or processed.")

    selected_method = payload.payment_method if hasattr(payload, "payment_method") else PaymentMethod.CASH
    trip.payment_method = selected_method

    # --- CASH PAYMENT FLOW ---
    if selected_method == PaymentMethod.CASH:
        trip.status = TripStatus.SEARCHING
        session.add(trip)
        await session.commit()

        return APIResponse(
            success=True,
            message="Trip requested successfully. Searching for nearby tow drivers.",
            data={
                "trip_id": str(trip.id),
                "status": trip.status,
                "payment_method": PaymentMethod.CASH,
                "total_charge": str(trip.total_cost)
            }
        )

    # --- CARD PAYMENT FLOW (PAYSTACK SPLIT) ---
    else:
        payment_data = await initialize_paystack_transaction(
            email=current_user.email,
            total_cost_ngn=float(trip.total_cost),
            platform_fee_ngn=float(trip.platform_fee),
            trip_id=str(trip.id)
        )
        
        if not payment_data:
            raise HTTPException(
                status_code=status.HTTP_53_SERVICE_UNAVAILABLE,
                detail="Payment gateway is currently unavailable. Please select Cash or try again."
            )
            
        trip.paystack_reference = payment_data["reference"]
        trip.status = TripStatus.SEARCHING
        session.add(trip)
        await session.commit()

        return APIResponse(
            success=True,
            message="Trip confirmed. Proceed to complete secure card payment.",
            data={
                "trip_id": str(trip.id),
                "authorization_url": payment_data["authorization_url"],
                "payment_method": PaymentMethod.CARD,
                "total_charge": str(trip.total_cost)
            }
        )

# ----company ledger balance check for debt enforcement
async def get_company_ledger_balance(session: AsyncSession, company_id: UUID) -> Decimal:
    """
    Sums all entries (positive and negative) in the company's ledger.
    Returns 0.00 if the company has no ledger entries yet.
    """
    statement = select(func.coalesce(func.sum(CompanyLedger.amount), 0)).where(
        CompanyLedger.company_id == company_id
    )
    result = await session.execute(statement)
    balance = result.scalar_one()
    
    return Decimal(str(balance))


# ==========================================
# 2. DRIVER DISPATCH & ACCEPTANCE
# ==========================================

@router.post("/{trip_id}/driver/accept", response_model=APIResponse)
async def accept_trip(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
):
    """
    Driver accepts a dispatch request. 
    Includes the Debt Enforcer to prevent fleets with unpaid commissions from taking jobs.
    """
    if not current_driver.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be assigned to a registered fleet to accept trips."
        )

    # 1. NEW: Fail-Fast Vehicle Check
    if not current_driver.current_vehicle_id:
        raise HTTPException(
            status_code=403, 
            detail="You cannot accept a trip without an assigned vehicle. Please select a vehicle from the fleet first."
        )

    # --- THE DEBT ENFORCER ---
    current_balance = await get_company_ledger_balance(session, current_driver.company_id)
    
    # if current_balance <= MAX_COMMISSION_DEBT_ALLOWED:
    if current_balance < 0 and abs(current_balance) >= MAX_COMMISSION_DEBT_ALLOWED:
        # We use abs() to format "-10000" into a readable "10,000 NGN" for the error message
        debt_amount = abs(current_balance)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account suspended. Your fleet has an outstanding commission debt of {debt_amount:,.2f} NGN. Please settle this balance to continue receiving tow requests."
        )
    # -------------------------

    # 1. Fetch the trip
    statement = select(Trip).where(Trip.id == trip_id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    if trip.status != TripStatus.SEARCHING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This trip is no longer available. Another driver may have accepted it."
        )

    # 2. Assign the trip and update status
    trip.driver_id = current_driver.id
    trip.company_id = current_driver.company_id
    trip.status = TripStatus.EN_ROUTE

    session.add(trip)
    await session.commit()
    await session.refresh(trip)

    return APIResponse(
        success=True,
        message="Trip accepted successfully. Proceed to pickup location.",
        data={
            "trip_id": str(trip.id),
            "status": trip.status,
            "pickup_address": trip.pickup_address
        }
    )

# ==========================================
# 3. SETTLEMENT & COMPLETION LOGIC
# ==========================================

async def execute_trip_completion(trip_id: UUID, session: AsyncSession) -> bool:
    """
    Core settlement engine executed upon user confirmation or 2-minute timer expiry:
    - CASH TRIPS: Logs a negative commission entry (-platform_fee) on the Company Ledger.
    - CARD TRIPS: Validates Paystack status and records the platform fee transaction.
    """
    trip = await session.get(Trip, trip_id)
    if not trip or trip.status not in (TripStatus.ARRIVED, TripStatus.TOWING):
        return False

    # --- CASH SETTLEMENT FLOW ---
    if trip.payment_method == PaymentMethod.CASH:
        # Create negative ledger debt entry for the company
        debt_entry = CompanyLedger(
            company_id=trip.company_id,
            driver_id=trip.driver_id,
            trip_id=trip.id,
            entry_type=LedgerEntryType.COMMISSION_DEBT,
            amount=-trip.platform_fee, # NEGATIVE AMOUNT
            description=f"Commission debt for Cash Trip #{str(trip.id)[:8]}"
        )
        session.add(debt_entry)
        trip.payment_status = PaymentStatus.DEBT_LOGGED

    # --- CARD SETTLEMENT FLOW ---
    else:
        card_tx = Transaction(
            trip_id=trip.id,
            type=TransactionType.CARD_PAYMENT,
            amount=trip.total_cost,
            gateway_reference=trip.paystack_reference or f"card_{str(trip.id)[:12]}",
            status="success"
        )
        session.add(card_tx)
        trip.payment_status = PaymentStatus.PAID

    trip.status = TripStatus.COMPLETED
    trip.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    
    session.add(trip)
    await session.commit()
    logger.info(f"Trip {trip.id} settled ({trip.payment_method.value}). Status updated to COMPLETED.")
    return True

# ==========================================
# 4. BACKGROUND TIMER & ENDPOINTS
# ==========================================

async def wait_and_auto_complete_trip(trip_id: UUID, session_factory):
    """
    Background Task: Waits 2 minutes post-arrival before auto-completing the trip.
    """
    logger.info(f"Starting 2-minute auto-completion timer for Trip {trip_id}")
    await asyncio.sleep(120)

    async with session_factory() as session:
        trip = await session.get(Trip, trip_id)
        if trip and trip.status == TripStatus.ARRIVED:
            logger.info(f"Timer expired for Trip {trip_id}. Triggering auto-completion...")
            await execute_trip_completion(trip_id=trip.id, session=session)

#------driver location tracking and geofence logic is below, followed by arrival confirmation and dispute endpoints
@router.post("/driver/{trip_id}/arrive", response_model=APIResponse)
async def driver_arrive_at_destination(
    trip_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
) -> Any:
    """
    Driver signals arrival at drop-off location. Starts the 2-minute confirmation timer.
    """
    statement = select(Trip).where(Trip.id == trip_id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    if trip.driver_id != current_driver.id:
        raise HTTPException(status_code=403, detail="Unauthorized access to this trip.")

    trip.status = TripStatus.ARRIVED
    trip.arrived_at = datetime.now(timezone.utc).replace(tzinfo=None)
    
    session.add(trip)
    await session.commit()

    from app.db.session import async_session_factory
    background_tasks.add_task(wait_and_auto_complete_trip, trip.id, async_session_factory)

    return APIResponse(
        success=True,
        message="Arrival confirmed. User has 2 minutes to verify before automatic completion.",
        data={"trip_id": str(trip.id), "status": trip.status, "arrived_at": trip.arrived_at}
    )

# -------- confirm and complete trip endpoints are below, followed by dispute and tracking info endpoints
@router.post("/{trip_id}/confirm-completion", response_model=APIResponse)
async def user_confirm_completion(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    User manually confirms trip completion, triggering immediate ledger accounting.
    """
    statement = select(Trip).where(Trip.id == trip_id, Trip.user_id == current_user.id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    if trip.status != TripStatus.ARRIVED:
        raise HTTPException(status_code=400, detail=f"Cannot complete trip from state '{trip.status}'.")

    success = await execute_trip_completion(trip_id=trip.id, session=session)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to process trip completion.")

    return APIResponse(
        success=True,
        message="Trip completed successfully. Thank you for using SoulsDrive!",
        data={"trip_id": str(trip.id), "status": TripStatus.COMPLETED}
    )

# -----dispute and tracking info endpoints are below
@router.post("/{trip_id}/dispute", response_model=APIResponse)
async def user_dispute_trip(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    User flags an issue at drop-off, freezing auto-completion for admin review.
    """
    statement = select(Trip).where(Trip.id == trip_id, Trip.user_id == current_user.id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    if trip.status != TripStatus.ARRIVED:
        raise HTTPException(status_code=400, detail="Disputes can only be raised during active arrival validation.")

    trip.status = TripStatus.DISPUTED
    session.add(trip)
    await session.commit()

    return APIResponse(
        success=True,
        message="Dispute registered. Our support team will review this trip.",
        data={"trip_id": str(trip.id), "status": trip.status}
    )

# -----tracking info endpoint is below
@router.get("/{trip_id}/tracking-info", response_model=APIResponse)
async def get_trip_tracking_info(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Returns a lean payload of the assigned driver, tow truck, and company.
    Designed for the customer app UI (similar to Uber/Bolt).
    """
    trip = await session.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")
        
    if trip.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to track this trip.")

    if not trip.driver_id or not trip.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No driver has been assigned to this trip yet."
        )

    driver = await session.get(Driver, trip.driver_id)
    company = await session.get(Company, trip.company_id)
    
    vehicle = None
    if driver and driver.current_vehicle_id:
        vehicle = await session.get(Vehicle, driver.current_vehicle_id)

    # Construct the ultra-lean response
    tracking_data = TripTrackingResponse(
        trip_id=str(trip.id), 
        status=trip.status.value if hasattr(trip.status, "value") else trip.status,
        total_cost=trip.total_cost,

        driver=DriverTrackingInfo(
            full_name=driver.full_name,
            phone_number=driver.phone_number,
        ) if driver else None,

        company=CompanyTrackingInfo(
            name=company.name,
        ) if company else None,
        
        vehicle=VehicleTrackingInfo(
            make=vehicle.make,
            model=vehicle.model,
            license_plate=vehicle.license_plate,
            vehicle_type=vehicle.vehicle_type.value if hasattr(vehicle.vehicle_type, "value") else vehicle.vehicle_type,  
        ) if vehicle else None
    )

    return APIResponse(
        success=True,
        message="Tracking information retrieved successfully.",
        data=tracking_data.model_dump()
    )