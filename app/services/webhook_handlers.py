import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.trip import Trip, TripStatus, PaymentStatus, CompanyLedger, LedgerEntryType
from app.models.trip import Transaction, TransactionType

logger = logging.getLogger(__name__)

async def process_debt_settlement(data: dict, session: AsyncSession) -> dict:
    """Handles companies paying off their negative cash commission debt."""
    metadata = data.get("metadata", {})
    company_id_str = metadata.get("company_id")
    gateway_reference = data.get("reference")
    amount_in_ngn = data.get("amount", 0) / 100 

    if not company_id_str:
        logger.error(f"Debt settlement success but no company_id found for ref {gateway_reference}")
        return {"status": "ignored", "reason": "missing company_id"}

    # Insert positive entry to clear their negative balance
    settlement_entry = CompanyLedger(
        company_id=UUID(company_id_str),
        entry_type=LedgerEntryType.MANUAL_SETTLEMENT,
        amount=amount_in_ngn, 
        description=f"Debt settlement via Paystack (Ref: {gateway_reference})"
    )
    
    session.add(settlement_entry)
    await session.commit()
    logger.info(f"Debt settlement of {amount_in_ngn} NGN secured for Company {company_id_str}.")
    return {"status": "success"}


async def process_trip_card_payment(data: dict, session: AsyncSession) -> dict:
    """Handles customers paying for a trip via card (Split Payment)."""
    metadata = data.get("metadata", {})
    trip_id_str = metadata.get("trip_id")
    gateway_reference = data.get("reference")
    amount_in_ngn = data.get("amount", 0) / 100 

    if not trip_id_str:
        logger.error(f"Charge successful but no trip_id found for ref {gateway_reference}")
        return {"status": "ignored", "reason": "missing trip_id"}

    trip_id = UUID(trip_id_str)

    statement = select(Trip).where(Trip.id == trip_id)
    result = await session.execute(statement)
    trip = result.scalar_one_or_none()

    if not trip:
        logger.error(f"Trip {trip_id} not found for successful charge {gateway_reference}")
        return {"status": "error", "reason": "trip not found"}

    if trip.payment_status == PaymentStatus.PAID:
        return {"status": "success", "message": "Already processed"}

    # 1. Update Trip
    trip.payment_status = PaymentStatus.PAID
    trip.status = TripStatus.COMPLETED
    session.add(trip)
    
    # 2. Record Transaction Receipt
    new_transaction = Transaction(
        trip_id=trip.id,
        type=TransactionType.CARD_PAYMENT,
        amount=amount_in_ngn,
        gateway_reference=gateway_reference,
        status="success"
    )
    session.add(new_transaction)
    
    # Notice: NO LEDGER UPDATE HERE! Paystack split the money automatically.
    # The platform got its cut, the fleet got theirs. No internal debt was created.
    
    await session.commit()
    logger.info(f"Card payment secured for Trip {trip.id}. Trip COMPLETED.")
    return {"status": "success"}