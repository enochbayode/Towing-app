from uuid import UUID
from decimal import Decimal
from sqlalchemy import func
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.trip import CompanyLedger

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