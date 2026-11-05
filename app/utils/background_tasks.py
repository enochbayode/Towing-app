import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import async_session_factory
from app.models.company import Company, VerificationStatus
from app.services.kyc import verify_nin, verify_cac, DojahNetworkError
from app.utils.email import send_company_status_email

logger = logging.getLogger(__name__)

async def process_company_verification(
    company_id: str,
    nin_number: str,
    rc_number: str,
    company_name: str,
    admin_email: str
):
    """
    1. Sends the 'received' confirmation email to the company admin.
    2. Runs automated verification against NIMC (NIN) and CAC via Dojah.
    3. Updates database status and dispatches appropriate final email.
    """
    # 1. Send immediate receipt notification
    try:
        await send_company_status_email(admin_email, company_name, "received")
    except Exception as e:
        logger.warning(f"Failed to send verification receipt email to {admin_email}: {e}") 

    # 2. Perform automated Dojah verifications
    nin_valid = False
    cac_valid = False
    is_network_failure = False 

    try:
        # Verify both Director NIN and Company CAC
        nin_valid = await verify_nin(nin_number)
        cac_valid = await verify_cac(rc_number)

    except DojahNetworkError as e:
        logger.error(f"Dojah network/server outage during verification for {company_id}: {e}")
        is_network_failure = True
    except Exception as e:
        logger.error(f"Unexpected error running Dojah verification for {company_id}: {e}")
        is_network_failure = True

    # 3. Update database & send outcome notifications
    async with async_session_factory() as session:
        company = await session.get(Company, company_id)
        if not company:
            logger.error(f"Company {company_id} not found during background verification.")
            return

        # Case A: External service failed or timed out -> Escalated to Manual Review
        if is_network_failure:
            company.verification_status = VerificationStatus.PENDING_REVIEW
            company.rejection_reason = "Automated verification temporarily unavailable. Queued for manual review."
            await session.commit()
            
            await send_company_status_email(
                admin_email, 
                company_name, 
                status="manual_review", 
                reason="Verification servers were momentarily unreachable. Our compliance team is reviewing it manually."
            )
            return

        # Case B: Both NIN and CAC passed -> Verified
        if nin_valid and cac_valid:
            company.nin_number = nin_number
            company.cac_rc_number = rc_number
            company.verification_status = VerificationStatus.VERIFIED
            company.rejection_reason = None
            if hasattr(company, "is_vetted"):
                company.is_vetted = True

            await session.commit()
            await send_company_status_email(admin_email, company_name, status="verified")
            return

        # Case C: Verification failed (Invalid credentials) -> Rejected
        rejection_reasons = []
        if not nin_valid:
            rejection_reasons.append("Director NIN could not be validated with NIMC records.")
        if not cac_valid:
            rejection_reasons.append("Company CAC RC number could not be validated.")

        failure_summary = " ".join(rejection_reasons)

        company.verification_status = VerificationStatus.REJECTED
        company.rejection_reason = failure_summary
        if hasattr(company, "is_vetted"):
            company.is_vetted = False

        await session.commit()

        await send_company_status_email(
            admin_email,
            company_name,
            status="rejected",
            reason=failure_summary
        )