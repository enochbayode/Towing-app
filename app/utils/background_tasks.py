# app/utils/background_tasks.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import async_session_factory
from app.models.company import Company
from app.services.kyc import verify_cac_registration
from app.utils.email import send_company_status_email

async def process_company_verification(company_id: str, rc_number: str, company_name: str, admin_email: str):
    """
    1. Sends the 'Received' email instantly.
    2. Calls Dojah API.
    3. Updates database & sends final status email.
    """
    # 1. Send initial confirmation immediately
    send_company_status_email(admin_email, company_name, "received")
    
    # 2. Run the external API check
    is_valid = await verify_cac_registration(rc_number, company_name)
    
    # 3. Open a fresh DB connection for the background update
    async with async_session_factory() as session:
        company = await session.get(Company, company_id)
        if not company:
            return
            
        if is_valid:
            company.is_vetted = True
            await session.commit()
            send_company_status_email(admin_email, company_name, "verified")
        else:
            # Leave is_vetted = False for manual intervention
            send_company_status_email(admin_email, company_name, "manual_review")