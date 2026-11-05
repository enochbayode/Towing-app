import asyncio
from arq import Retry
from arq.connections import RedisSettings
from sqlmodel.ext.asyncio.session import AsyncSession
from urllib.parse import urlparse

# Import your database engine and models
from app.db.session import engine
from app.models.company import Company, VerificationStatus
from app.services.kyc import verify_nin, verify_cac, DojahNetworkError
from app.core.config import settings

async def process_company_verification(ctx, company_id: str, nin: str, cac: str):
    job_try = ctx.get("job_try", 1)
    max_tries = ctx.get("max_tries", 5)
    
    try:
        # 1. Attempt the Dojah API calls
        nin_valid = await verify_nin(nin)
        cac_valid = await verify_cac(cac)
        
    except DojahNetworkError as e:
        # 2. Trigger Exponential Backoff Retry (e.g., 15s, 30s, 60s, 120s...)
        if job_try >= max_tries:
            # If we hit max_tries, we catch the failure below and reject the application.
            nin_valid, cac_valid = False, False 
            rejection_reason = "System verification unavailable. Please contact support."
        else:
            defer_time = 15 * (2 ** (job_try - 1))
            raise Retry(defer=defer_time) # Safely suspends the job and requeues it

    # 3. Update the Database based on the final result
    async with AsyncSession(engine) as session:
        company = await session.get(Company, company_id)
        if not company:
            return # Company deleted before job processed
            
        if nin_valid and cac_valid:
            company.nin_number = nin
            company.cac_rc_number = cac
            company.verification_status = VerificationStatus.VERIFIED
            company.rejection_reason = None
        else:
            company.verification_status = VerificationStatus.REJECTED
            company.rejection_reason = locals().get('rejection_reason', "Automated check failed: Invalid NIN or CAC.")
            
        session.add(company)
        await session.commit()

# 1. Parse the URL manually
parsed_url = urlparse(settings.REDIS_URL)

# 2. Force SSL to True
redis_settings = RedisSettings(
    host=parsed_url.hostname,
    port=parsed_url.port or 6379,
    password=parsed_url.password,
    ssl=True
)

# 3. Bypass Windows certificate check
redis_settings.ssl_cert_reqs = "none"

class WorkerSettings:
    functions = [process_company_verification]
    redis_settings = redis_settings
    max_tries = 5




# redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

# # ADD THIS: Bypass the strict Windows SSL check
# redis_settings.ssl_cert_reqs = "none"

# class WorkerSettings:
#     functions = [process_company_verification]
#     redis_settings = redis_settings
#     max_tries = 5

# class WorkerSettings:
#     functions = [process_company_verification]
    
#     # Replaces the default RedisSettings() with your secure cloud URL
#     redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    
#     max_tries = 5


# redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
# redis_settings.ssl_ca_certs = "/path/to/provider/ca-certificate.crt" # Use this instead of "none"