# app/api/v1/endpoints/webhook.py
import hmac
import hashlib
import json
import logging
from fastapi import APIRouter, Request, Header, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

# Adjust imports to match your project structure
from app.db.session import get_session
from app.core.config import settings
from app.models.trip import Trip, TripStatus, Transaction, TransactionType
from app.utils.dispatch_worker import broadcast_trip_to_drivers

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/paystack")
async def paystack_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_paystack_signature: str = Header(None),
    session: AsyncSession = Depends(get_session)
):
    """
    Listens for Paystack events. 
    Catches 'charge.success' to lock funds in Escrow.
    """
    # 1. Read the raw body for cryptographic verification
    payload = await request.body()
    
    # 2. Verify the signature to ensure it's actually Paystack
    if not x_paystack_signature:
        raise HTTPException(status_code=400, detail="Missing signature header")

    expected_signature = hmac.new(
        key=settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
        msg=payload,
        digestmod=hashlib.sha512
    ).hexdigest()

    if expected_signature != x_paystack_signature:
        logger.error("Fake webhook intercepted. Signatures do not match.")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 3. Parse the JSON data
    try:
        event_data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event_data.get("event")
    data = event_data.get("data", {})

    # 4. We only care about successful charges right now
    if event_type == "charge.success":
        gateway_reference = data.get("reference")
        amount_in_kobo = data.get("amount")
        amount_in_ngn = amount_in_kobo / 100  # Convert back to NGN
        
        # Extract the trip_id we hid in the metadata during initialization
        metadata = data.get("metadata", {})
        custom_fields = metadata.get("custom_fields", [])
        
        trip_id = None
        for field in custom_fields:
            if field.get("variable_name") == "trip_id":
                trip_id = field.get("value")
                break
                
        if not trip_id:
            logger.error(f"Charge successful but no trip_id found in metadata for ref {gateway_reference}")
            return {
                "status": "ignored", 
                "reason": "missing trip_id"
            }

        # 5. Find the Trip in the database
        statement = select(Trip).where(Trip.id == trip_id)
        result = await session.execute(statement)
        trip = result.scalar_one_or_none()

        if not trip:
            logger.error(f"Trip {trip_id} not found for successful charge {gateway_reference}")
            return {"status": "error", "reason": "trip not found"}

        # Prevent double-processing if Paystack accidentally sends the webhook twice
        if trip.status != TripStatus.SEARCHING:
            return {"status": "success", "message": "Already processed"}

        # 6. UPDATE TRIP STATUS (The money is now in Escrow!)
        trip.status = TripStatus.FUNDS_ESCROWED
        session.add(trip)
        
        # 7. WRITE TO THE FINANCIAL LEDGER
        new_transaction = Transaction(
            trip_id=trip.id,
            type=TransactionType.ESCROW_DEPOSIT,
            amount=amount_in_ngn,
            gateway_reference=gateway_reference,
            status="success"
        )
        session.add(new_transaction)
        
        await session.commit()
        
        logger.info(f"Escrow secured for Trip {trip.id}. Status updated to FUNDS_ESCROWED.")

        # 9. FIRE THE DISPATCH ENGINE! (The new addition)
        # This triggers the 5km -> 10km -> 15km radar search in the background
        background_tasks.add_task(
            broadcast_trip_to_drivers, 
            str(trip.id)
        )
        
        # NOTE: Right here is where you would trigger a WebSocket message or 
        # Push Notification to the tow companies to say "New Job Available!"

    # Always return a fast 200 OK so Paystack knows you received it
    return {"status": "success"}
