# app/services/kyc.py
import httpx
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

async def verify_cac_registration(rc_number: str, company_name: str) -> bool:
    """
    Calls Dojah's KYB (Know Your Business) endpoint to verify the CAC number.
    Returns True if the company is active and the names match.
    """
    if not rc_number:
        return False

    url = "https://api.dojah.io/api/v1/kyb/cac"
    headers = {
        "Authorization": settings.DOJAH_API_KEY,
        "AppId": settings.DOJAH_APP_ID,
        "Accept": "application/json"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, 
                headers=headers, 
                params={"rc_number": rc_number},
                timeout=15.0 # Don't hang forever
            )
            
            if response.status_code == 200:
                data = response.json()
                entity = data.get("entity", {})
                
                # Check 1: Is the company legally active?
                status = entity.get("status", "").lower()
                if status not in ["active", "registered"]:
                    return False
                    
                # Check 2: Does the name roughly match? 
                # (CAC names often include "LTD" or "NIGERIA", so we check if the provided name is inside the official name)
                api_company_name = entity.get("company_name", "").lower()
                clean_input_name = company_name.lower().replace(" ltd", "").replace(" limited", "")
                
                if clean_input_name in api_company_name:
                    return True
                    
    except Exception as e:
        logger.error(f"Dojah CAC Verification failed for {rc_number}: {str(e)}")
        
    return False