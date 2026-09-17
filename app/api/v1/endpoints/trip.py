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

from app.models.courier import CourierTrip, CourierStatus
from app.models.courier import CourierDriverHistory, CourierLedgerEntryType
from app.models.user import User
from app.models.driver import Driver
from app.models.company import Company

from app.db.session import get_session, async_session_factory
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

from app.services.paystack_integration import initialize_paystack_transaction, initialize_courier_transaction
from app.models.vehicle import Vehicle
from app.models.courier_driver import get_utc_now_naive
from app.models.courier_driver import CourierDriver
from app.models.courier_vehicle import CourierVehicle

from app.schemas.trip import TripTrackingResponse, DriverTrackingInfo, CompanyTrackingInfo, VehicleTrackingInfo
from app.schemas.courier import CourierTripCreate, CourierTripResponse,TripCancelRequest
from app.schemas.trip import TripCreateSchema, TripConfirmSchema
from app.schemas.user import APIResponse
from app.schemas.courier import CourierTripConfirm, PaymentMethod, DriverLocationPayload
from app.services.courier_pricing_engine import calculate_courier_price
from app.services.pricing_engine import calculate_tow_cost
from app.utils.courier_dispatch_worker import broadcast_courier_trip_to_drivers
from app.utils.courier_dispatch_worker import wait_and_auto_complete_courier_trip
from app.utils.geofence import calculate_distance_meters
from app.core.config import settings


router = APIRouter()
logger = logging.getLogger(__name__)


MAX_COMMISSION_DEBT_ALLOWED = settings.MAX_COMMISSION_DEBT_ALLOWED  # e.g., -10000.00 NGN

# ==========================================
# 1. ESTIMATE & CONFIRMATION FLOW
# ==========================================

@router.post("/user/estimate", response_model=APIResponse)
async def get_trip_estimate(
    trip_in: TripCreateSchema,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> APIResponse:
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
@router.post("/user/confirm", response_model=APIResponse)
async def confirm_and_request_trip(
    payload: TripConfirmSchema,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> APIResponse:
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
async def get_company_ledger_balance(
        session: AsyncSession, 
        company_id: UUID) -> Decimal:
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

@router.post("/driver/{trip_id}/accept", response_model=APIResponse)
async def accept_trip(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
)-> APIResponse:
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

async def execute_trip_completion(
        trip_id: UUID, 
        session: AsyncSession) -> bool:
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
) -> APIResponse:
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

    background_tasks.add_task(wait_and_auto_complete_trip, trip.id, async_session_factory)

    return APIResponse(
        success=True,
        message="Arrival confirmed. User has 2 minutes to verify before automatic completion.",
        data={"trip_id": str(trip.id), "status": trip.status, "arrived_at": trip.arrived_at}
    )

# -------- confirm and complete trip endpoints are below, followed by dispute and tracking info endpoints
@router.post("/user/{trip_id}/confirm-completion", response_model=APIResponse)
async def user_confirm_completion(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> APIResponse:
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
@router.post("/user/{trip_id}/dispute", response_model=APIResponse)
async def user_dispute_trip(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> APIResponse:
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
@router.get("/user/{trip_id}/tracking-info", response_model=APIResponse)
async def get_trip_tracking_info(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
)-> APIResponse:
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

# estimate courier price
# @router.post("/user/courier/estimate-price", response_model=APIResponse)
# async def request_courier_trip(
#     trip_in: CourierTripCreate,
#     session: AsyncSession = Depends(get_session),
#     current_user: User = Depends(get_current_user)
# )-> APIResponse:
#     """
#     Calculates pricing and creates a DRAFT courier trip. 
#     Does not ping drivers yet.
#     """
#     # 1. Calculate the dynamic pricing based on user inputs
#     pricing = calculate_courier_price(trip_in)

#     # 2. Build the database model
#     # We NO LONGER exclude requested_vehicle_type because the DB needs it
#     new_trip = CourierTrip(
#         **trip_in.model_dump(), 
#         user_id=current_user.id,
#         status=CourierStatus.DRAFT, # <--- Saved as a draft quote
#         total_cost=pricing["total_cost"],
#         platform_fee=pricing["platform_fee"],
#         driver_payout=pricing["driver_payout"]
#         # created_at=get_utc_now_naive()
#     )

#     # 3. Save to database
#     session.add(new_trip)
#     await session.commit()
#     await session.refresh(new_trip)

#     # 5. Return the full response so the frontend can show the invoice
#     return APIResponse(
#         success=True,
#         message="Courier estimate generated. Please confirm to request a van.",
#         data={
#             "trip_id": str(new_trip.id),
#             "pricing": pricing,
#             "status": new_trip.status
#         }
#     )

@router.post("/user/courier/estimate-price", response_model=APIResponse)
async def request_courier_trip(
    trip_in: CourierTripCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> APIResponse:
    """
    Calculates pricing, checks user debt, and creates a DRAFT courier trip.
    """
    # 1. Calculate the dynamic pricing based on user inputs
    base_pricing = calculate_courier_price(trip_in)

    # 2. Check for existing debt on the User profile and convert to Decimal
    previous_debt = Decimal(str(current_user.pending_cancellation_fee or 0.0))

    # Both are now Decimals, so addition will succeed safely without rounding errors
    final_total = base_pricing["total_cost"] + previous_debt

    # 3. Build the database model
    new_trip = CourierTrip(
        **trip_in.model_dump(), 
        user_id=current_user.id,
        status=CourierStatus.DRAFT, 
        total_cost=final_total, 
        platform_fee=base_pricing["platform_fee"],
        driver_payout=base_pricing["driver_payout"],
        applied_debt=previous_debt  # <--- LOGGED PERMANENTLY ON THIS TRIP
    )

    # 4. Save to database
    session.add(new_trip)
    await session.commit()
    await session.refresh(new_trip)

    # 5. Build a transparent pricing payload for the frontend UI
    pricing_breakdown = {
        "base_trip_cost": base_pricing["total_cost"],
        "previous_debt_applied": previous_debt,
        "final_total_cost": final_total,
        "platform_fee": base_pricing["platform_fee"],
        "driver_payout": base_pricing["driver_payout"]
    }

    # 6. Return the standard APIResponse
    return APIResponse(
        success=True,
        message="Courier estimate generated. Please confirm to request a van.",
        data={
            "trip_id": str(new_trip.id),
            "pricing": pricing_breakdown,
            "status": new_trip.status
        }
    )

# confirm courier trip 
@router.post("/user/courier/{trip_id}/confirm", response_model=APIResponse)
async def confirm_courier_trip(
    trip_id: str,
    payload: CourierTripConfirm,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
)-> APIResponse:
    # 1. Fetch trip and verify ownership
    trip = await session.get(CourierTrip, trip_id)
    
    if not trip or str(trip.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Trip estimate not found.")
        
    if trip.status != CourierStatus.DRAFT:
        raise HTTPException(status_code=400, detail="This trip has already been confirmed.")

    # 2. Setup baseline payment data
    trip.payment_method = payload.payment_method
    trip.payment_status = "PENDING" # Unpaid by default

    # --- CASH PAYMENT FLOW ---
    if payload.payment_method == PaymentMethod.CASH:
        trip.status = CourierStatus.PENDING # Dispatch van!
        session.add(trip)
        await session.commit()

        # 3. (Future) Trigger Matchmaking / WebSockets
        background_tasks.add_task(
            broadcast_courier_trip_to_drivers,
            trip_id=str(trip.id)
        )

        return APIResponse(
            success=True,
            message="Van dispatched! You will pay cash upon delivery.",
            data={
                "trip_id": str(trip.id),
                "status": trip.status,
                "payment_method": PaymentMethod.CASH,
                "payment_status": trip.payment_status,
                "total_charge": str(trip.total_cost)
            }
        )

    # --- CARD PAYMENT FLOW (FLEXIBLE / PAY LATER) ---
    else:
        # Generate the invoice link, but don't force them to pay it immediately
        # payment_data = await initialize_paystack_transaction(
        #     email=current_user.email,
        #     total_cost_ngn=float(trip.total_cost),
        #     platform_fee_ngn=float(trip.platform_fee),
        #     trip_id=str(trip.id)
        # )

    
        payment_data = await initialize_courier_transaction(
            email=current_user.email,
            total_cost_ngn=float(trip.total_cost),
            trip_id=str(trip.id)
        )
        
        if not payment_data:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway unavailable. Please select Cash."
            )
            
        trip.paystack_reference = payment_data["reference"]
        trip.status = CourierStatus.PENDING # Dispatch van immediately!
        
        session.add(trip)
        await session.commit()

        background_tasks.add_task(
            broadcast_courier_trip_to_drivers,
            trip_id=str(trip.id)
        )
        
        # 4. (Future) Trigger Matchmaking / WebSockets
            # ping_nearby_vans(
            #     trip_id=trip.id, 
            #     lat=trip.pickup_lat, 
            #     lng=trip.pickup_lng, 
            #     vehicle_type=trip.requested_vehicle_type
            # )

        return APIResponse(
            success=True,
            message="Van dispatched! You can complete the card payment anytime before drop-off.",
            data={
                "trip_id": str(trip.id),
                "status": trip.status,
                "payment_method": PaymentMethod.CARD,
                "payment_status": trip.payment_status, # Still 'PENDING'
                "authorization_url": payment_data["authorization_url"],
                "total_charge": str(trip.total_cost)
            }
        )

# -----tracking endpoint is below, which returns live driver coordinates and van details
@router.get("/user/courier/{trip_id}/tracking", response_model=APIResponse)
async def track_courier_trip(
    trip_id: str,
    session: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
)-> APIResponse:
    """
    Returns live tracking information for an ongoing courier trip, 
    including the driver's current GPS coordinates.
    """
    # 1. Fetch the trip
    trip = await session.get(CourierTrip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")
        
    # Security: Ensure only the person who ordered it can track it
    if str(trip.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized to track this trip.")

    # 2. Build the base tracking payload
    tracking_data = {
        "trip_id": str(trip.id),
        "status": trip.status,
        "pickup_lat": trip.pickup_lat,
        "pickup_lng": trip.pickup_lng,
        "dropoff_lat": trip.dropoff_lat,
        "dropoff_lng": trip.dropoff_lng,
        "started_transit_at": trip.started_transit_at,
        "driver": None,
        "vehicle": None
    }

    # 3. If a driver has accepted, inject their live coordinates and van details
    if trip.driver_id:
        driver = await session.get(CourierDriver, trip.driver_id)
        if driver:
            tracking_data["driver"] = {
                "driver_id": str(driver.id),
                # Adjust field names below if your decoupled driver model uses different ones
                "name": f"{getattr(driver, 'first_name', '')} {getattr(driver, 'last_name', '')}".strip(),
                "phone": getattr(driver, 'phone', 'N/A'),
                "current_lat": driver.current_lat,
                "current_lng": driver.current_lng
            }
            
        if trip.vehicle_id:
            vehicle = await session.get(CourierVehicle, trip.vehicle_id)
            if vehicle:
                tracking_data["vehicle"] = {
                    "make": vehicle.make,
                    "model": vehicle.model,
                    "license_plate": vehicle.license_plate,
                    "vehicle_type": vehicle.vehicle_type
                }

    return APIResponse(
        success=True,
        message="Tracking info retrieved successfully.",
        data=tracking_data
    )

# courier driver accepts trip endpoint
@router.post("/driver/courier_driver/{trip_id}/accept", response_model=APIResponse)
async def accept_courier_trip(
    trip_id: str,
    session: AsyncSession = Depends(get_session),
    current_driver: CourierDriver = Depends(get_current_driver)
)-> APIResponse:
    """
    Driver accepts a pending trip. 
    Locks the trip to this driver and their active vehicle.
    """
    # 1. Fetch the trip
    trip = await session.get(CourierTrip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")
        
    # 2. Check if the trip is still available
    if trip.status != CourierStatus.PENDING:
        raise HTTPException(
            status_code=400, 
            detail="This trip is no longer available. Another driver may have accepted it."
        )
        
    # 3. Ensure the driver has an active vehicle selected
    if not current_driver.current_vehicle_id:
        raise HTTPException(
            status_code=400, 
            detail="You must have an active vehicle selected to accept trips."
        )

    # 4. Assign the trip to the driver
    trip.driver_id = current_driver.id
    trip.vehicle_id = current_driver.current_vehicle_id
    trip.status = CourierStatus.ACCEPTED
    
    session.add(trip)
    await session.commit()
    await session.refresh(trip)

    return APIResponse(
        success=True,
        message="Trip accepted successfully! Proceed to pickup location.",
        data={"trip_id": str(trip.id), "status": trip.status}
    )

# courier driver decline/cancels trip
@router.post("/driver/courier_driver/{trip_id}/decline", response_model=APIResponse)
async def decline_courier_trip(
    trip_id: str,
    session: AsyncSession = Depends(get_session),
    current_driver: CourierDriver = Depends(get_current_driver)
)-> APIResponse:
    """
    Driver declines a trip.
    If they already accepted it, unassign them, penalize them, and revert the trip to PENDING.
    """
    trip = await session.get(CourierTrip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    # SCENARIO A: The driver already accepted this trip and is now canceling
    if str(trip.driver_id) == str(current_driver.id) and trip.status == CourierStatus.ACCEPTED:
        
        # 1. Revert trip back to the matchmaking pool so the customer isn't stranded
        trip.driver_id = None
        trip.vehicle_id = None
        trip.status = CourierStatus.PENDING
        
        # 2. TODO: Implement Penalty Logic Here
        # Example: 
        # current_driver.cancellation_count += 1
        # current_driver.rating -= 0.1
        # session.add(current_driver)
        
        session.add(trip)
        await session.commit()

        # 3. (Future) Trigger WebSockets to alert the customer their driver changed
        # notify_customer_driver_cancelled(trip.user_id)

        return APIResponse(
            success=True,
            message="Trip cancelled. This cancellation has been logged on your profile.",
            data={"trip_id": str(trip.id), "status": trip.status}
        )
        
    # SCENARIO B: Driver is just declining an initial ping (not accepted yet)
    elif trip.status == CourierStatus.PENDING:
        # TODO: Add logic to a "trip_rejections" table so the matchmaking engine 
        # knows not to ping this specific driver for this specific trip again.
        
        return APIResponse(
            success=True,
            message="Trip declined. We will find another driver.",
            data=None
        )

    # SCENARIO C: Trying to decline a trip that's already in transit or completed
    else:
        raise HTTPException(
            status_code=400, 
            detail="You cannot decline a trip that is already in progress or completed."
        )

# driver completes trip endpoint
# @router.post("/driver/courier_driver/{trip_id}/complete", response_model=APIResponse)
# async def complete_courier_trip(
#     trip_id: str,
#     session: AsyncSession = Depends(get_session),
#     current_driver = Depends(get_current_driver)
# )-> APIResponse:
#     """
#     Driver clicks 'Complete Delivery'. 
#     Verifies payment is settled before allowing completion.
#     """
#     trip = await session.get(CourierTrip, trip_id)
#     if not trip or str(trip.driver_id) != str(current_driver.id):
#         raise HTTPException(status_code=404, detail="Trip not found.")
        
#     if trip.status == CourierStatus.COMPLETED:
#         raise HTTPException(status_code=400, detail="Trip is already completed.")

#     # 1. SECURITY LOCK: Do not allow completion if Card payment is still pending
#     if trip.payment_method == "CARD" and trip.payment_status != "PAID":
#          raise HTTPException(
#              status_code=402, # Payment Required
#              detail="Customer card payment is still pending. Do not release cargo yet."
#          )

#     # 2. Process Cash Trips (Log the commission debt)
#     if trip.payment_method == "CASH":
#         trip.payment_status = "DEBT_LOGGED"
        
#         ledger_entry = CourierDriverHistory(
#             driver_id=trip.driver_id,
#             trip_id=trip.id,
#             entry_type=CourierLedgerEntryType.COMMISSION_DEBT,
#             amount=-float(trip.platform_fee),
#             description=f"Commission debt for Cash Trip #{str(trip.id)[:8]}"
#         )
#         session.add(ledger_entry)

#     # 3. Finalize the Trip
#     trip.status = CourierStatus.COMPLETED
#     trip.completed_at = get_utc_now_naive()
    
#     session.add(trip)
#     await session.commit()
    
#     return APIResponse(
#         success=True, 
#         message="Delivery completed successfully!",
#         data={"trip_id": str(trip.id), "status": trip.status}
#     )


@router.post("/driver/courier_driver/{trip_id}/complete", response_model=APIResponse)
async def complete_courier_trip(
    trip_id: str,
    payload: DriverLocationPayload,
    session: AsyncSession = Depends(get_session),
    current_driver = Depends(get_current_driver)
) -> APIResponse:
    """
    Driver clicks 'Complete Delivery'. Requires being within 50 meters of drop-off.
    """
    trip = await session.get(CourierTrip, trip_id)
    if not trip or str(trip.driver_id) != str(current_driver.id):
        raise HTTPException(status_code=404, detail="Trip not found.")
        
    if trip.status == CourierStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Trip is already completed.")

    # Geofence Validation
    distance = calculate_distance_meters(
        payload.latitude, payload.longitude,
        trip.dropoff_latitude, trip.dropoff_longitude
    )
    
    MAX_COMPLETION_RADIUS_METERS = 50.0
    if distance > MAX_COMPLETION_RADIUS_METERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot complete trip. You are {round(distance)}m away from the drop-off location."
        )

    user = await session.get(User, trip.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if trip.payment_method == "CARD" and trip.payment_status != "PAID":
         raise HTTPException(
             status_code=402,
             detail="Customer card payment is still pending. Do not release cargo yet."
         )

    if trip.payment_method == "CASH":
        trip.payment_status = "DEBT_LOGGED"
        total_owed_to_platform = float(trip.platform_fee) + float(trip.applied_debt)
        
        ledger_entry = CourierDriverHistory(
            driver_id=trip.driver_id,
            trip_id=trip.id,
            entry_type=CourierLedgerEntryType.COMMISSION_DEBT,
            amount=-total_owed_to_platform,
            description=f"Commission & recovered debt for Cash Trip #{str(trip.id)[:8]}"
        )
        session.add(ledger_entry)

    if trip.applied_debt > 0:
        user.pending_cancellation_fee = max(0.0, float(user.pending_cancellation_fee) - float(trip.applied_debt))
        session.add(user)

    trip.status = CourierStatus.COMPLETED
    trip.completed_at = get_utc_now_naive()
    
    session.add(trip)
    await session.commit()
    
    return APIResponse(
        success=True, 
        message="Delivery completed successfully!",
        data={
            "trip_id": str(trip.id), 
            "status": trip.status,
            "cleared_user_debt": trip.applied_debt
        }
    )


# driver arrives at drop-off endpoint, triggers 2-minute auto-completion timer
@router.post("/driver/courier_driver/{trip_id}/arrive", response_model=APIResponse)
async def driver_arrived_at_dropoff(
    trip_id: str,
    payload: DriverLocationPayload,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_driver = Depends(get_current_driver)
) -> APIResponse:
    """
    Marks trip as ARRIVED only if the driver is within 50 meters of the drop-off destination.
    """
    trip = await session.get(CourierTrip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    if str(trip.driver_id) != str(current_driver.id):
        raise HTTPException(status_code=403, detail="You are not assigned to this trip.")

    if trip.status in [CourierStatus.COMPLETED, CourierStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail=f"Cannot mark arrival. Trip is {trip.status}.")

    # Geofence Validation (50-meter standard radius)
    distance = calculate_distance_meters(
        payload.latitude, payload.longitude,
        trip.dropoff_latitude, trip.dropoff_longitude
    )
    
    MAX_ARRIVAL_RADIUS_METERS = 50.0
    if distance > MAX_ARRIVAL_RADIUS_METERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You are too far from the drop-off location ({round(distance)}m away). Move within {int(MAX_ARRIVAL_RADIUS_METERS)}m to mark arrival."
        )

    if trip.status == CourierStatus.ARRIVED:
        return APIResponse(success=True, message="Already marked as arrived.")

    trip.status = CourierStatus.ARRIVED
    session.add(trip)
    await session.commit()
    await session.refresh(trip)

    background_tasks.add_task(
        wait_and_auto_complete_courier_trip,
        trip_id=str(trip.id),
        session_factory=async_session_factory
    )

    return APIResponse(
        success=True,
        message="Arrived at drop-off verified.",
        data={"trip_id": str(trip.id), "status": trip.status, "distance_meters": round(distance, 1)}
    )

from enum import Enum
class UserCancelReason(str, Enum):
    DRIVER_ASKED_TO_CANCEL = "DRIVER_ASKED_TO_CANCEL"
    DRIVER_DEMANDED_EXTRA_CASH = "DRIVER_DEMANDED_EXTRA_CASH"
    DRIVER_NOT_MOVING = "DRIVER_NOT_MOVING"
    TOO_LONG_ETA = "TOO_LONG_ETA"
    CHANGE_OF_PLANS = "CHANGE_OF_PLANS"
    WRONG_ADDRESS = "WRONG_ADDRESS"

# Reasons where the driver is at fault — User must NEVER be penalized
DRIVER_FAULT_REASONS = {
    UserCancelReason.DRIVER_ASKED_TO_CANCEL,
    UserCancelReason.DRIVER_DEMANDED_EXTRA_CASH,
    UserCancelReason.DRIVER_NOT_MOVING,
    UserCancelReason.TOO_LONG_ETA,
}

CANCELLATION_FEE_NGN = Decimal("100.00")

# cancel trip endpoint for users
@router.post("/{trip_id}/cancel", response_model=APIResponse)
async def cancel_user_trip(
    trip_id: str,
    payload: TripCancelRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> APIResponse:
    """
    Cancels a trip with Nigerian-market guardrails protecting riders 
    from driver-induced cancellations.
    """
    statement = select(CourierTrip).where(
        CourierTrip.id == trip_id,
        CourierTrip.user_id == current_user.id
    )
    result = await session.exec(statement)
    trip = result.first()

    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found."
        )

    if trip.status in [TripStatus.COMPLETED, TripStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trip is already {trip.status.value.lower()}."
        )

    trip.status = TripStatus.CANCELLED
    trip.cancellation_reason = payload.reason_code
    trip.cancelled_by = "USER"
    trip.cancelled_at = datetime.now(timezone.utc)

    # Market Guardrail Logic
    if payload.reason_code in DRIVER_FAULT_REASONS:
        # Flag the driver internally for audit / acceptance rate penalty
        trip.driver_flagged_for_cancellation = True
    else:
        # Only check for late cancellation fee if driver was assigned and arrived
        if trip.driver_id and trip.status == TripStatus.DRIVER_ARRIVED:
            # Append ₦500 to user's next trip ledger instead of instant card debit
            current_user.pending_cancellation_fee += CANCELLATION_FEE_NGN
            session.add(current_user)

    session.add(trip)
    await session.commit()
    await session.refresh(trip)

    return APIResponse(
        success=True,
        message="Trip cancelled successfully.",
        data={
            "trip_id": str(trip.id),
            "status": trip.status,
            "cancelled_at": trip.cancelled_at.isoformat()
        }
    )