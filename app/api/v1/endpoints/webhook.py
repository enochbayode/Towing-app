# app/api/v1/endpoints/webhook.py
import hmac
import hashlib
import json
import logging
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.db.session import get_session
from app.core.config import settings
from app.models.trip import Trip, TripStatus, PaymentStatus, Transaction, TransactionType

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/paystack")
async def paystack_webhook(
    request: Request,
    x_paystack_signature: str = Header(None),
    session: AsyncSession = Depends(get_session)
):
    """
    Listens for Paystack events. 
    Catches 'charge.success' when a user pays via card AT THE LOCATION.
    """
    payload = await request.body()
    
    # 1. Cryptographic Signature Verification
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

    # 2. Parse JSON Payload
    try:
        event_data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event_data.get("event")
    data = event_data.get("data", {})

    # 3. Process Successful Charges at the Location
    if event_type == "charge.success":
        gateway_reference = data.get("reference")
        amount_in_ngn = data.get("amount", 0) / 100 
        
        # Extract the trip_id hidden in metadata
        metadata = data.get("metadata", {})
        trip_id = metadata.get("trip_id")
                
        if not trip_id:
            logger.error(f"Charge successful but no trip_id found in metadata for ref {gateway_reference}")
            return {"status": "ignored", "reason": "missing trip_id"}

        # 4. Fetch Trip
        statement = select(Trip).where(Trip.id == trip_id)
        result = await session.execute(statement)
        trip = result.scalar_one_or_none()

        if not trip:
            logger.error(f"Trip {trip_id} not found for successful charge {gateway_reference}")
            return {"status": "error", "reason": "trip not found"}

        # 5. Prevent Double-Processing
        if trip.payment_status == PaymentStatus.PAID:
            return {"status": "success", "message": "Already processed"}

        # 6. Mark Trip as Paid and Completed!
        trip.payment_status = PaymentStatus.PAID
        trip.status = TripStatus.COMPLETED  # The driver can now be released!
        session.add(trip)
        
        # 7. Log the transaction
        new_transaction = Transaction(
            trip_id=trip.id,
            type=TransactionType.CARD_PAYMENT,
            amount=amount_in_ngn,
            gateway_reference=gateway_reference,
            status="success"
        )
        session.add(new_transaction)
        await session.commit()
        
        logger.info(f"Card payment secured for Towing app Trip {trip.id}. Trip COMPLETED.")

        # NOTE: Here you would trigger a WebSocket or FCM push to the Driver's app
        # saying: "Payment Received! Trip is complete."

    return {"status": "success"}