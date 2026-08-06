import hmac
import hashlib
import json
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_session
from app.core.config import settings
from app.services.webhook_handlers import process_debt_settlement, process_trip_card_payment

router = APIRouter()

@router.post("/paystack")
async def paystack_webhook(
    request: Request,
    x_paystack_signature: str = Header(None),
    session: AsyncSession = Depends(get_session)
):
    """
    Traffic cop for Paystack events. 
    Verifies security, then routes to the appropriate handler function.
    """
    payload = await request.body()
    
    # 1. Security check
    if not x_paystack_signature:
        raise HTTPException(status_code=400, detail="Missing signature header")

    expected_signature = hmac.new(
        key=settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
        msg=payload,
        digestmod=hashlib.sha512
    ).hexdigest()

    if expected_signature != x_paystack_signature:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. Parse Payload
    try:
        event_data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event_data.get("event")
    data = event_data.get("data", {})
    metadata = data.get("metadata", {})

    # 3. Route to the correct handler based on transaction_type
    if event_type == "charge.success":
        transaction_type = metadata.get("transaction_type")
        
        if transaction_type == "DEBT_SETTLEMENT":
            return await process_debt_settlement(data, session)
            
        else:
            # Default to trip payment if no specific transaction_type is set
            return await process_trip_card_payment(data, session)

    # Always return 200 OK fast so Paystack knows you received it
    return {"status": "success"}