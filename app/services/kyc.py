# # app/services/kyc.py
# import httpx
# import logging
# from app.core.config import settings

# logger = logging.getLogger(__name__)

# async def verify_cac_registration(rc_number: str, company_name: str) -> bool:
#     """
#     Calls Dojah's KYB (Know Your Business) endpoint to verify the CAC number.
#     Returns True if the company is active and the names match.
#     """
#     if not rc_number:
#         return False

#     url = "https://api.dojah.io/api/v1/kyb/cac"
#     headers = {
#         "Authorization": settings.DOJAH_API_KEY,
#         "AppId": settings.DOJAH_APP_ID,
#         "Accept": "application/json"
#     }
    
#     try:
#         async with httpx.AsyncClient() as client:
#             response = await client.get(
#                 url, 
#                 headers=headers, 
#                 params={"rc_number": rc_number},
#                 timeout=15.0 # Don't hang forever
#             )
            
#             if response.status_code == 200:
#                 data = response.json()
#                 entity = data.get("entity", {})
                
#                 # Check 1: Is the company legally active?
#                 status = entity.get("status", "").lower()
#                 if status not in ["active", "registered"]:
#                     return False
                    
#                 # Check 2: Does the name roughly match? 
#                 # (CAC names often include "LTD" or "NIGERIA", so we check if the provided name is inside the official name)
#                 api_company_name = entity.get("company_name", "").lower()
#                 clean_input_name = company_name.lower().replace(" ltd", "").replace(" limited", "")
                
#                 if clean_input_name in api_company_name:
#                     return True
                    
#     except Exception as e:
#         logger.error(f"Dojah CAC Verification failed for {rc_number}: {str(e)}")
        
#     return False




# import httpx
# import logging
# from typing import Optional, Dict
# from app.core.config import settings

# logger = logging.getLogger(__name__)

# async def verify_cac_with_prembly(rc_number: str, company_name: str) -> Optional[Dict]:
#     """
#     Calls Prembly (Identitypass) CAC Verification API.
#     Returns the official company details (including directors) if valid.
#     Returns None if the RC number is invalid or the API fails.
#     """
#     # Use the sandbox URL for test mode. Change to api.myidentitypass.com for production.
#     url = "https://sandbox.myidentitypass.com/api/v2/biometrics/merchant/data/verification/cac"
    
#     headers = {
#         "x-api-key": settings.PREMBLY_SECRET_KEY,
#         "Content-Type": "application/json"
#     }
    
#     payload = {
#         "rc_number": rc_number,
#         "company_name": company_name # Prembly often uses this to cross-check the RC number
#     }
    
#     try:
#         async with httpx.AsyncClient() as client:
#             response = await client.post(url, headers=headers, json=payload, timeout=15.0)
            
#             if response.status_code == 200:
#                 data = response.json()
#                 # Prembly returns status: True on successful verification
#                 if data.get("status") is True:
#                     return data.get("vcData", data.get("data")) # Depending on API version
                    
#             elif response.status_code in [400, 404, 422]:
#                 logger.warning(f"Invalid RC Number or mismatch: {rc_number} / {company_name}")
#                 return None
                
#     except Exception as e:
#         logger.error(f"Prembly CAC resolution failed: {str(e)}")
        
#     return None




import httpx
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

DOJAH_BASE_URL = settings.DOJAH_BASE_URL  # Use the base URL from settings

def _get_headers() -> dict:
    """Returns the required headers for Dojah API requests."""
    return {
        "Authorization": settings.DOJAH_AUTHORIZATION,
        "AppId": settings.DOJAH_APP_ID,
        "Accept": "application/json"
    }

class DojahNetworkError(Exception):
    pass

async def verify_nin(nin: str) -> bool:
    url = f"{DOJAH_BASE_URL}/api/v1/kyc/nin"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=_get_headers(), params={"nin": nin}, timeout=15.0)
            
            # If Dojah throws a 500/502/504, raise it to trigger the queue retry
            if response.status_code >= 500:
                raise DojahNetworkError("Dojah server is down.")
                
            response.raise_for_status()
            return bool(response.json().get("entity"))
            
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise DojahNetworkError(f"Network error: {str(e)}")


async def verify_cac(rc_number: str, company_type: str = "COMPANY") -> bool:
    """
    Verifies a business via its CAC Registration (RC) Number.
    """
    url = f"{DOJAH_BASE_URL}/api/v1/kyc/cac/basic"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                url, 
                headers=_get_headers(), 
                params={
                    "rc_number": rc_number,
                    "company_type": company_type
                },
                timeout=15.0
            )
            response.raise_for_status()
            data = response.json()
            
            return bool(data.get("entity"))
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Dojah CAC verification failed: {e.response.text}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Network error during Dojah CAC verification: {str(e)}")
            return False


async def verify_plate_number(plate_number: str) -> bool:
    """
    Verifies a vehicle's insurance status against the NIID via its plate number.
    Note: Verify the exact query parameter name ('vehicle_number' vs 'plate_number') 
    in your Dojah dashboard documentation if the vehicle endpoint updates.
    """
    url = f"{DOJAH_BASE_URL}/api/v1/kyc/vehicle"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                url, 
                headers=_get_headers(), 
                params={"vehicle_number": plate_number}, 
                timeout=15.0
            )
            response.raise_for_status()
            data = response.json()
            
            return bool(data.get("entity"))
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Dojah Vehicle verification failed: {e.response.text}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Network error during Dojah Vehicle verification: {str(e)}")
            return False

# verify_drivers_license function added to verify Nigerian Driver's License via Dojah API
async def verify_drivers_license(license_number: str) -> bool:
    """
    Verifies a Nigerian Driver's License via Dojah API.
    Returns True if valid, False if invalid.
    Raises DojahNetworkError on server failure.
    """
    url = f"{settings.DOJAH_BASE_URL}/api/v1/kyc/dl"
    headers = {
        "Authorization": settings.DOJAH_AUTHORIZATION,
        "AppId": settings.DOJAH_APP_ID,
        "Accept": "application/json"
    }
    params = {"dl_number": license_number}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=15.0)
            
        if response.status_code == 200:
            data = response.json()
            # Dojah returns 'entity' if the license is found and valid
            if data.get("entity"):
                return True
        return False
        
    except httpx.RequestError as e:
        logger.error(f"Dojah network error during DL verification: {e}")
        raise DojahNetworkError(f"Network error: {e}")