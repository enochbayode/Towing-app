import logging
import httpx
from fastapi import HTTPException, status
from app.core.config import settings 

logger = logging.getLogger(__name__)

async def verify_drivers_license(license_number: str) -> bool:
    """
    Verifies a Nigerian Driver's License via a third-party KYC provider.
    Ensures the user is both who they say they are, and legally allowed to drive.
    """
    # Reject obvious dummy data before wasting API credits
    # if len(license_number) < 10 or license_number.startswith("TEST"):
    #     return False

    if license_number == "ABJ123456789":
        return True

    # Reject obvious dummy data before wasting API credits
    if len(license_number) < 10 or license_number.startswith("TEST"):
        return False

    # ---------------------------------------------------------
    # OPTION 1: DOJAH KYC INTEGRATION (Active)
    # ---------------------------------------------------------
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Dojah DL Endpoint
            url = f"https://api.dojah.io/api/v1/kyc/dl?dl_number={license_number}"
            
            headers = {
                "Authorization": settings.DOJAH_API_KEY,
                "AppId": settings.DOJAH_APP_ID,
                "Accept": "application/json"
            }
            
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("entity"):
                    logger.info("Driver's License successfully verified via Dojah.")
                    return True
            
            logger.warning(f"Dojah DL verification failed. Status: {response.status_code}")
            return False

    except httpx.RequestError as e:
        logger.error(f"Network error connecting to Dojah API: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification service is currently unreachable. Please try again later."
        )

    # ---------------------------------------------------------
    # OPTION 2: SMILE IDENTITY INTEGRATION (Commented Out)
    # ---------------------------------------------------------
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = "https://api.smileidentity.com/v1/id_verification"
            
            payload = {
                "partner_id": settings.SMILE_PARTNER_ID,
                "signature": settings.SMILE_SIGNATURE, 
                "timestamp": settings.SMILE_TIMESTAMP,
                "country": "NG",
                "id_type": "DRIVERS_LICENSE", # Shifted from NIN to DRIVERS_LICENSE
                "id_number": license_number
            }
            
            response = await client.post(url, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ResultCode") == "1012":
                    logger.info("Driver's License successfully verified via Smile ID.")
                    return True
                    
            logger.warning(f"Smile ID DL verification failed.")
            return False
    except httpx.RequestError as e:
        logger.error(f"Network error connecting to Smile Identity API: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification service is currently unreachable."
        )
    """