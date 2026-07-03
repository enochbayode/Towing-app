# app/api/v1/endpoints/company.py
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import Any

from app.schemas.company import (
    CompanyCreate, 
    CompanyResponse, 
    PaymentAccountCreate, 
    PaymentAccountResponse,
    CompanyUpdate
)

from app.models.company import Company, PaymentAccount
from app.services.payment import resolve_account_name 
from app.models.admin import Admin
from app.db.session import get_session
from app.api.deps import get_current_admin
from app.utils.background_tasks import process_company_verification
from app.schemas.user import APIResponse


router = APIRouter()

@router.post("/admin/register", response_model=APIResponse[CompanyResponse])
async def register_company(
    company_in: CompanyCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin) # Ensures they are logged in
) -> Any:
    
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
) -> Any:
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

@router.patch("/me", response_model=APIResponse[CompanyResponse])
async def update_my_company(
    company_update: CompanyUpdate,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
) -> Any:
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
) -> Any:
    
    if not current_admin.company_id:
        raise HTTPException(status_code=400, detail="Register a company profile first.")

    statement = select(PaymentAccount).where(PaymentAccount.company_id == current_admin.company_id)
    result = await session.execute(statement)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Your company already has a payout account.")

    # --- THE VERIFICATION STEP ---
    verified_account_name = await resolve_account_name(
        account_number=account_in.account_number,
        bank_code=account_in.bank_code
    )
    
    if not verified_account_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not verify this bank account. Please check the account number and bank."
        )

    # --- SAVE THE VERIFIED DATA ---
    new_account = PaymentAccount(
        bank_name=account_in.bank_name,
        bank_code=account_in.bank_code,
        account_number=account_in.account_number,
        account_name=verified_account_name, # Use the official name from the bank!
        company_id=current_admin.company_id,
        is_verified=True # Instantly set to True because Paystack confirmed it
    )
    
    session.add(new_account)
    await session.commit()
    await session.refresh(new_account)

    return APIResponse(
        success=True,
        message=f"Account linked successfully for {verified_account_name}.",
        data=new_account
    )

# PATCH /payment-account
@router.patch("/payment-account", response_model=APIResponse[PaymentAccountResponse])
async def update_payment_account(
    account_in: PaymentAccountCreate,
    session: AsyncSession = Depends(get_session),
    current_admin: Admin = Depends(get_current_admin)
) -> Any:
    """
    Updates an existing payment account.
    Requires full bank details to re-verify the account name.
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

    # 3. Update the existing record with the verified data
    existing_account.bank_name = account_in.bank_name
    existing_account.bank_code = account_in.bank_code
    existing_account.account_number = account_in.account_number
    existing_account.account_name = verified_account_name
    existing_account.is_verified = True
    
    session.add(existing_account)
    await session.commit()
    await session.refresh(existing_account)

    return APIResponse(
        success=True,
        message=f"Payment account successfully updated to {verified_account_name}.",
        data=existing_account
    )