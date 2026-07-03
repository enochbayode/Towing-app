# app/services/payment.py
import httpx
import logging
from typing import Optional, Dict
from app.core.config import settings
from decimal import Decimal

logger = logging.getLogger(__name__)

async def resolve_account_name(account_number: str, bank_code: str) -> Optional[str]:
    """
    Calls Paystack's Account Resolution API.
    Returns the official account name registered with the bank if valid.
    Returns None if the account is invalid or the API fails.
    """
    url = f"https://api.paystack.co/bank/resolve"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    params = {
        "account_number": account_number,
        "bank_code": bank_code
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") is True:
                    # Return the exact, verified name from the bank
                    return data["data"]["account_name"]
                    
            elif response.status_code in [400, 422]:
                logger.warning(f"Invalid account number/bank code: {account_number} / {bank_code}")
                return None
                
    except Exception as e:
        logger.error(f"Paystack resolution failed: {str(e)}")
        
    return None


async def initialize_paystack_transaction(email: str, amount: Decimal, trip_id: str) -> Optional[Dict]:
    """
    Initializes a Paystack payment and returns the checkout URL and reference.
    Note: Paystack requires the amount in KOBO (multiply NGN by 100).
    """
    url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    amount_in_kobo = int(amount * 100)
    
    payload = {
        "email": email,
        "amount": amount_in_kobo,
        # We pass the trip_id as metadata so the webhook knows exactly which trip this is for!
        "metadata": {
            "custom_fields": [
                {"display_name": "Trip ID", "variable_name": "trip_id", "value": trip_id}
            ]
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=10.0)
            if response.status_code == 200:
                data = response.json()["data"]
                return {
                    "authorization_url": data["authorization_url"],
                    "reference": data["reference"]
                }
    except Exception as e:
        logger.error(f"Failed to initialize Paystack: {str(e)}")
        
    return None