# app/api/v1/endpoints/trip.py
import asyncio
import httpx
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

# Adjust imports based on your structure
from app.db.session import get_session
from app.api.deps import get_current_user
from app.models.trip import Trip, TripStatus, Transaction, TransactionType 
from app.services.payment import initialize_paystack_transaction
from app.services.pricing_engine import calculate_tow_cost
from app.core.config import settings
from app.schemas.trip import TripCreateSchema, TripConfirmSchema
from app.schemas.user import APIResponse
from app.models.user import User
from app.models.driver import Driver
from app.models.company import Company, PaymentAccount
from app.api.deps import get_current_driver
from app.core.config import settings
from app.services.notification import notify_drivers_in_area


router = APIRouter()
logger = logging.getLogger(__name__)

# user requests a trip
# @router.post("/request", response_model=APIResponse)
# async def request_trip(
#     trip_in: TripCreateSchema, # Contains pickup/dropoff coords, vehicle_type, and truck_type
#     session: AsyncSession = Depends(get_session),
#     current_user: User = Depends(get_current_user)
# ) -> Any:
#     """
#     User requests a tow. Calculates flexible fees via the pricing engine 
#     based on coordinates and vehicle configurations, then generates a Paystack checkout.
#     """
#     # 1. Calculate the secure base cost from backend parameters (removes frontend tampering risk)
#     calculated_base_cost = calculate_tow_cost(
#         pickup_lat=trip_in.pickup_lat,
#         pickup_lng=trip_in.pickup_lng,
#         dropoff_lat=trip_in.dropoff_lat,
#         dropoff_lng=trip_in.dropoff_lng,
#         vehicle_type=trip_in.vehicle_type,
#         truck_type=trip_in.truck_type
#     )
    
#     # 2. Calculate the dynamic financial splits based on environment variables
#     user_fee = calculated_base_cost * Decimal(str(settings.USER_FEE_PERCENTAGE))
#     total_user_charge = calculated_base_cost + user_fee
    
#     company_payout = calculated_base_cost * Decimal(str(settings.COMPANY_PAYOUT_PERCENTAGE))
#     platform_fee = (calculated_base_cost * Decimal(str(settings.PLATFORM_CUT_PERCENTAGE))) + user_fee

#     # 3. Create the Trip in the database (Status is SEARCHING)
#     new_trip = Trip(
#         user_id=current_user.id,
#         pickup_address=trip_in.pickup_address,
#         pickup_lat=trip_in.pickup_lat,
#         pickup_lng=trip_in.pickup_lng,
#         dropoff_address=trip_in.dropoff_address,
#         dropoff_lat=trip_in.dropoff_lat,
#         dropoff_lng=trip_in.dropoff_lng,
#         vehicle_details=trip_in.vehicle_details,
        
#         # Save the calculated financials securely
#         total_cost=total_user_charge,
#         platform_fee=platform_fee,
#         company_payout=company_payout,
#         status=TripStatus.SEARCHING
#     )
    
#     session.add(new_trip)
#     await session.commit()
#     await session.refresh(new_trip)

#     # 4. Call Paystack to get the secure checkout link
#     payment_data = await initialize_paystack_transaction(
#         email=current_user.email,
#         amount=total_user_charge,
#         trip_id=str(new_trip.id)
#     )
    
#     if not payment_data:
#         # Rollback and clean up the trip entry if Paystack initialization fails
#         await session.delete(new_trip)
#         await session.commit()
#         raise HTTPException(
#             status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
#             detail="Payment gateway is currently unavailable. Please try again."
#         )
        
#     # 5. Save the unique Paystack reference to the trip for webhook lookup verification
#     new_trip.paystack_reference = payment_data["reference"]
#     session.add(new_trip)
#     await session.commit()

#     # 6. Return the URL so the mobile app can open the secure checkout overlay
#     return APIResponse(
#         success=True,
#         message="Trip requested. Proceed to payment.",
#         data={
#             "trip_id": str(new_trip.id),
#             "authorization_url": payment_data["authorization_url"],
#             "total_charge": str(total_user_charge)
#         }
#     )

@router.post("/estimate", response_model=APIResponse)
async def get_trip_estimate(
    trip_in: TripCreateSchema,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Step 1: Calculates cost and creates a DRAFT trip in the database.
    Returns the trip_id for the frontend to use in Step 2.
    """
    calculated_base_cost = calculate_tow_cost(
        pickup_lat=trip_in.pickup_lat, pickup_lng=trip_in.pickup_lng,
        dropoff_lat=trip_in.dropoff_lat, dropoff_lng=trip_in.dropoff_lng,
        vehicle_type=trip_in.vehicle_type, truck_type=trip_in.truck_type
    )
    
    # Calculate all fees
    user_fee = round(calculated_base_cost * Decimal(str(settings.USER_FEE_PERCENTAGE)), 2)
    total_user_charge = round(calculated_base_cost + user_fee, 2)
    company_payout = round(calculated_base_cost * Decimal(str(settings.COMPANY_PAYOUT_PERCENTAGE)), 2)
    platform_fee = round((calculated_base_cost * Decimal(str(settings.PLATFORM_CUT_PERCENTAGE))) + user_fee, 2)

    # Save the drafted trip to the database
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
        status=TripStatus.PENDING_PAYMENT  # Use a pending payment here!
    )
    
    session.add(new_trip)
    await session.commit()
    await session.refresh(new_trip)

    return APIResponse(
        success=True,
        message="Estimate calculated and drafted successfully.",
        data={
            "trip_id": str(new_trip.id),
            "total_charge": str(total_user_charge),
            "currency": "NGN"
        }
    )


# @router.post("/confirm", response_model=APIResponse)
# async def confirm_and_pay_trip(
#     trip_in: TripCreateSchema,
#     background_tasks: BackgroundTasks, # Injected to handle notifications without slowing the response
#     session: AsyncSession = Depends(get_session),
#     current_user: User = Depends(get_current_user)
# ) -> Any:
#     """
#     Step 2: Recalculates cost, creates the DB record, initializes Paystack Escrow, 
#     and triggers driver notification.
#     """
#     # 1. Recalculate everything securely on the backend
#     calculated_base_cost = calculate_tow_cost(
#         pickup_lat=trip_in.pickup_lat, pickup_lng=trip_in.pickup_lng,
#         dropoff_lat=trip_in.dropoff_lat, dropoff_lng=trip_in.dropoff_lng,
#         vehicle_type=trip_in.vehicle_type, truck_type=trip_in.truck_type
#     )
    
#     # Round all financials to 2 decimal places for clean Paystack & DB integration
#     user_fee = round(calculated_base_cost * Decimal(str(settings.USER_FEE_PERCENTAGE)), 2)
#     total_user_charge = round(calculated_base_cost + user_fee, 2)
#     company_payout = round(calculated_base_cost * Decimal(str(settings.COMPANY_PAYOUT_PERCENTAGE)), 2)
#     platform_fee = round((calculated_base_cost * Decimal(str(settings.PLATFORM_CUT_PERCENTAGE))) + user_fee, 2)

#     # 2. Create the Trip in the database
#     new_trip = Trip(
#         user_id=current_user.id,
#         pickup_address=trip_in.pickup_address,
#         pickup_lat=trip_in.pickup_lat,
#         pickup_lng=trip_in.pickup_lng,
#         dropoff_address=trip_in.dropoff_address,
#         dropoff_lat=trip_in.dropoff_lat,
#         dropoff_lng=trip_in.dropoff_lng,
#         vehicle_details=trip_in.vehicle_details,
#         total_cost=total_user_charge,
#         platform_fee=platform_fee,
#         company_payout=company_payout,
#         status=TripStatus.SEARCHING
#     )
    
#     session.add(new_trip)
#     await session.commit()
#     await session.refresh(new_trip)

#     # 3. Call Paystack for Escrow checkout link
#     payment_data = await initialize_paystack_transaction(
#         email=current_user.email,
#         amount=total_user_charge,
#         trip_id=str(new_trip.id)
#     )
    
#     if not payment_data:
#         await session.delete(new_trip)
#         await session.commit()
#         raise HTTPException(
#             status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
#             detail="Payment gateway is currently unavailable. Please try again."
#         )
        
#     # 4. Save Paystack reference
#     new_trip.paystack_reference = payment_data["reference"]
#     session.add(new_trip)
#     await session.commit()

#     # 5. Trigger the driver notification in the background
#     # (Consider moving this to your Paystack Webhook in the future!)
#     background_tasks.add_task(
#         notify_drivers_in_area, 
#         trip_id=new_trip.id, 
#         lat=new_trip.pickup_lat, 
#         lng=new_trip.pickup_lng
#     )

#     # 6. Return the URL to the mobile app
#     return APIResponse(
#         success=True,
#         message="Trip confirmed. Proceed to secure Escrow payment.",
#         data={
#             "trip_id": str(new_trip.id),
#             "authorization_url": payment_data["authorization_url"],
#             "total_charge": str(total_user_charge) # Now cleanly rounded!
#         }
#     )


@router.post("/confirm", response_model=APIResponse)
async def confirm_and_pay_trip(
    payload: TripConfirmSchema,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Step 2: Takes the drafted trip_id, fetches the locked-in price, 
    and generates the Paystack checkout URL.
    """
    # 1. Fetch the drafted trip
    statement = select(Trip).where(
        Trip.id == payload.trip_id, 
        Trip.user_id == current_user.id # Security check: Ensure they own this trip!
    )
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip estimate not found.")
        
    if trip.status != TripStatus.PENDING_PAYMENT:
        raise HTTPException(status_code=400, detail="This trip has already been processed.")

    # 2. Call Paystack for Escrow checkout link using the saved cost
    payment_data = await initialize_paystack_transaction(
        email=current_user.email,
        amount=trip.total_cost,
        trip_id=str(trip.id)
    )
    
    if not payment_data:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment gateway is currently unavailable. Please try again."
        )
        
    # 3. Update the trip with Paystack reference and new status
    trip.paystack_reference = payment_data["reference"]
    trip.status = TripStatus.SEARCHING # Or leave as DRAFT until Webhook confirms payment
    session.add(trip)
    await session.commit()

    # 4. Trigger the driver notification
    background_tasks.add_task(
        notify_drivers_in_area, 
        trip_id=trip.id, 
        lat=trip.pickup_lat, 
        lng=trip.pickup_lng
    )

    return APIResponse(
        success=True,
        message="Trip confirmed. Proceed to secure Escrow payment.",
        data={
            "trip_id": str(trip.id),
            "authorization_url": payment_data["authorization_url"],
            "total_charge": str(trip.total_cost)
        }
    )


# driver accepts a trip
@router.post("/{trip_id}/driver/accept", response_model=APIResponse)
async def accept_trip(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
) -> Any:
    """
    Driver accepts a pending tow request.
    Locks the trip to their driver_id and company_id, and updates status to EN_ROUTE.
    """
    # 1. Ensure the driver is actually linked to a company
    if not current_driver.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be assigned to a registered fleet/company to accept trips."
        )

    # 2. Fetch the trip
    statement = select(Trip).where(Trip.id == trip_id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    # 3. CRITICAL SECURITY: The Concurrency Check
    if trip.status == TripStatus.SEARCHING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot accept. The user has not completed their Escrow payment yet."
        )
        
    if trip.status != TripStatus.FUNDS_ESCROWED:
        # If it's already EN_ROUTE, another driver beat them to it!
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This trip is no longer available. Another driver has already accepted it."
        )

    # 4. Assign the trip and update status
    trip.driver_id = current_driver.id
    trip.company_id = current_driver.company_id
    trip.status = TripStatus.EN_ROUTE

    session.add(trip)
    await session.commit()
    await session.refresh(trip)

    # Note: Here you would typically trigger a Push Notification to the User's app:
    # "Driver {current_driver.first_name} from {company.name} is on the way!"

    return APIResponse(
        success=True,
        message="Trip accepted successfully. Please proceed to the pickup location.",
        data={
            "trip_id": str(trip.id),
            "status": trip.status,
            "pickup_address": trip.pickup_address,
            "pickup_lat": trip.pickup_lat,
            "pickup_lng": trip.pickup_lng
        }
    )

# ==========================================
# PAYSTACK TRANSFER SERVICE
# ==========================================

class PaystackPayoutService:
    @staticmethod
    async def create_transfer_recipient(
        account_name: str, 
        account_number: str, 
        bank_code: str
    ) -> Optional[str]:
        """
        Creates a transfer recipient on Paystack to generate a recipient_code.
        """
        url = "https://api.paystack.co/transferrecipient"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "type": "nuban",
            "name": account_name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": "NGN"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=10.0)
                if response.status_code in (200, 201):
                    return response.json()["data"]["recipient_code"]
                logger.error(f"Paystack Recipient Creation Failed: {response.text}")
        except Exception as e:
            logger.error(f"Error calling Paystack recipient API: {str(e)}")
        return None

    @staticmethod
    async def initiate_transfer(
        amount: Decimal, 
        recipient_code: str, 
        reference: str
    ) -> Optional[str]:
        """
        Fires the actual bank payout transfer on Paystack.
        Note: Paystack requires amounts in KOBO.
        """
        url = "https://api.paystack.co/transfer"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "source": "balance",
            "amount": int(amount * 100), # Decimal NGN to Integer Kobo
            "recipient": recipient_code,
            "reason": f"Towing App Dispatch Payout - Ref: {reference}",
            "reference": reference
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=10.0)
                if response.status_code in (200, 201):
                    return response.json()["data"]["transfer_code"]
                logger.error(f"Paystack Transfer Failed: {response.text}")
        except Exception as e:
            logger.error(f"Error calling Paystack transfer API: {str(e)}")
        return None


# ==========================================
# ESCROW RELEASE LOGIC (THE HEART OF DISPATCH)
# ==========================================

async def execute_escrow_release(trip_id: UUID, session: AsyncSession) -> bool:
    """
    Core function that resolves payout splits, generates Paystack payout to 
    the company, and records transactions in the system financial ledger.
    """
    # 1. Fetch the trip, including company details
    trip = await session.get(Trip, trip_id)
    if not trip or trip.status != TripStatus.ARRIVED:
        return False # Trip has already been processed, cancelled, or disputed.

    # 2. Get the Company's Verified Payment Account
    statement = select(PaymentAccount).where(PaymentAccount.company_id == trip.company_id)
    result = await session.execute(statement)
    payment_account = result.scalar_one_or_none()

    if not payment_account or not payment_account.is_verified:
        logger.error(f"Payout failed for Trip {trip.id}: Company {trip.company_id} has no verified payout account.")
        # Switch trip to disputed or flag for admin intervention
        trip.status = TripStatus.DISPUTED
        session.add(trip)
        await session.commit()
        return False

    # 3. Create Paystack Transfer Recipient dynamically if it does not exist
    recipient_code = await PaystackPayoutService.create_transfer_recipient(
        account_name=payment_account.account_name,
        account_number=payment_account.account_number,
        bank_code=payment_account.bank_code
    )

    if not recipient_code:
        logger.error(f"Could not resolve Paystack transfer recipient for Company {trip.company_id}")
        return False

    # 4. Fire the Paystack Payout Transfer
    # We generate a unique gateway transfer reference: e.g., payout_trip-uuid
    payout_reference = f"payout_{str(trip.id)[:20]}"
    transfer_code = await PaystackPayoutService.initiate_transfer(
        amount=trip.company_payout,
        recipient_code=recipient_code,
        reference=payout_reference
    )

    if not transfer_code:
        logger.error(f"Paystack transfer request failed for Trip {trip.id}")
        return False

    # 5. Lock in Status & write to Ledger
    trip.status = TripStatus.COMPLETED
    trip.completed_at = datetime.now(timezone.utc)
    session.add(trip)

    # Record Company Payout to Ledger
    company_tx = Transaction(
        trip_id=trip.id,
        type=TransactionType.COMPANY_PAYOUT,
        amount=trip.company_payout,
        gateway_reference=payout_reference,
        status="success"
    )
    session.add(company_tx)

    # Record Platform Commission to Ledger (Your remaining 13% cut)
    platform_tx = Transaction(
        trip_id=trip.id,
        type=TransactionType.PLATFORM_FEE,
        amount=trip.platform_fee,
        gateway_reference=f"fee_{str(trip.id)[:20]}",
        status="success"
    )
    session.add(platform_tx)

    await session.commit()
    logger.info(f"Escrow successfully released to Company {trip.company_id} for Trip {trip.id}")
    return True


# ==========================================
# 2-MINUTE BACKGROUND TIMER WORKER
# ==========================================

async def wait_and_auto_release_escrow(trip_id: UUID, session_factory):
    """
    FastAPI Background Task: Waits 2 minutes, then releases funds 
    if the user has not confirmed or raised a dispute.
    """
    logger.info(f"Starting 2-minute escrow timer for Trip {trip_id}")
    
    # Wait exactly 2 minutes (120 seconds)
    # Change to a lower number (like 10 seconds) during manual local testing!
    await asyncio.sleep(120)

    # Create a fresh database session to prevent lifecycle expiration bugs in background tasks
    async with session_factory() as session:
        # Refetch trip state
        trip = await session.get(Trip, trip_id)
        if not trip:
            logger.error(f"Trip {trip_id} not found during auto-release evaluation.")
            return

        # Double check status before releasing
        if trip.status == TripStatus.ARRIVED:
            logger.info(f"Auto-release timer expired. No user action detected. Releasing Trip {trip.id} escrow...")
            await execute_escrow_release(trip_id=trip.id, session=session)
        else:
            logger.info(f"Auto-release aborted for Trip {trip_id}. Current status is: {trip.status}")


# ==========================================
# ENDPOINTS
# ==========================================

@router.post("/{trip_id}/arrive", response_model=APIResponse)
async def driver_arrive_at_destination(
    trip_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
) -> Any:
    """
    Driver endpoint: Signals arrival at drop-off. Starts the 2-minute user confirmation window.
    """
    # Fetch the trip and verify driver owns it
    statement = select(Trip).where(Trip.id == trip_id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    if trip.driver_id != current_driver.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to manage this trip."
        )

    if trip.status != TripStatus.TOWING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot mark arrival. Trip is currently in '{trip.status}' status."
        )

    # Update state to ARRIVED & start timer
    trip.status = TripStatus.ARRIVED
    trip.arrived_at = datetime.now(timezone.utc)
    
    session.add(trip)
    await session.commit()
    await session.refresh(trip)

    # Spawn the 2-Minute Background worker
    # We pass the session engine dependency factory so the task can spin up its own safe database session
    from app.db.session import async_session_factory
    background_tasks.add_task(
        wait_and_auto_release_escrow, 
        trip.id, 
        async_session_factory
    )

    return APIResponse(
        success=True,
        message="Arrival confirmed. The user has 2 minutes to confirm or flag a dispute before automated payout.",
        data={
            "trip_id": str(trip.id),
            "status": trip.status,
            "arrived_at": trip.arrived_at
        }
    )

# user confirms trip completion (immediate payout)
@router.post("/{trip_id}/confirm", response_model=APIResponse)
async def user_confirm_completion(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    User endpoint: Explicitly confirms trip is complete, triggering immediate payout.
    """
    statement = select(Trip).where(Trip.id == trip_id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    if trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to confirm this trip."
        )

    if trip.status != TripStatus.ARRIVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trip cannot be completed from state: '{trip.status}'."
        )

    # Execute dynamic split payout & save status
    success = await execute_escrow_release(trip_id=trip.id, session=session)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Escrow transfer failed. Please try again or contact support."
        )

    return APIResponse(
        success=True,
        message="Thank you! Payment released to the towing provider, and trip marked as completed.",
        data={
            "trip_id": str(trip.id),
            "status": TripStatus.COMPLETED
        }
    )

# user disputes a trip (freezes escrow)
@router.post("/{trip_id}/dispute", response_model=APIResponse)
async def user_dispute_trip(
    trip_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    User endpoint: Flags an issue with the tow. Freezes funds in escrow for admin arbitration.
    """
    statement = select(Trip).where(Trip.id == trip_id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    if trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to dispute this trip."
        )

    if trip.status != TripStatus.ARRIVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can only raise disputes during active arrival validation windows."
        )

    # Shift status to DISPUTED to lock out auto-release worker
    trip.status = TripStatus.DISPUTED
    session.add(trip)
    await session.commit()
    await session.refresh(trip)

    # Note: Fire admin notification here to alert management of a disputed transaction

    return APIResponse(
        success=True,
        message="Dispute registered. Escrow funds have been successfully frozen. Our team will contact you shortly.",
        data={
            "trip_id": str(trip.id),
            "status": trip.status
        }
    )