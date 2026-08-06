# app/services/payment.py
import httpx
import logging
from app.core.config import settings
from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime, timezone

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



# initialize_paystack_transaction and create_paystack_subaccount functions are defined below
async def initialize_paystack_transaction(
    email: str, 
    total_cost_ngn: float, 
    platform_fee_ngn: float,
    trip_id: str,
    company_subaccount_code: str  # Routes the money directly to the company
) -> Optional[Dict[str, Any]]:
    """
    Calls Paystack to initialize a split-payment transaction using Subaccounts.
    Returns the authorization URL and transaction reference.
    """
    url = "https://api.paystack.co/transaction/initialize"
    
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    # Paystack expects amounts in Kobo (lowest denomination)
    amount_kobo = int(total_cost_ngn * 100)
    flat_fee_kobo = int(platform_fee_ngn * 100)
    
    # Append a timestamp to ensure the reference is unique on every retry
    unique_reference = f"trip_{trip_id}_{int(datetime.now(timezone.utc).timestamp())}"
    
    payload = {
        "email": email,
        "amount": str(amount_kobo),
        "reference": unique_reference,
        "subaccount": company_subaccount_code, 
        "transaction_charge": flat_fee_kobo,   
        "bearer": "account",                   
        "metadata": {
            "trip_id": str(trip_id)
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
            else:
                logger.error(f"Paystack Init Error {response.status_code}: {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Failed to connect to Paystack: {str(e)}")
        return None


async def create_paystack_subaccount(
    business_name: str, 
    bank_code: str, 
    account_number: str
) -> Optional[str]:
    """
    Creates a Paystack Subaccount for a fleet company.
    Returns the subaccount_code (e.g., 'SUB_vsyte...') used for split payments.
    """
    url = "https://api.paystack.co/subaccount"
    
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "business_name": business_name,
        "settlement_bank": bank_code,
        "account_number": account_number,
        # We set percentage to 0 because we override it dynamically with 
        # 'transaction_charge' during the actual trip checkout
        "percentage_charge": 0.0  # 
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=10.0)
            
            if response.status_code in (200, 201):
                data = response.json()["data"]
                return data["subaccount_code"]
            else:
                logger.error(f"Paystack Subaccount Creation Error: {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Failed to connect to Paystack Subaccount API: {str(e)}")
        return None


# This function is used to initialize a debt settlement transaction for a fleet company to pay off their commission debt. 
# The money goes directly to the platform's main account.
async def initialize_debt_settlement(
    email: str, 
    amount_ngn: float, 
    company_id: str
) -> Optional[Dict[str, Any]]:
    """
    Initializes a standard Paystack transaction for a fleet to pay off their commission debt.
    The money goes directly to the platform's main account.
    """
    url = "https://api.paystack.co/transaction/initialize"
    
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    # Paystack requires the amount in Kobo
    amount_kobo = int(amount_ngn * 100)
    
    # Generate a unique reference prefix to easily identify it in the webhook
    unique_reference = f"settlement_{company_id}_{int(datetime.now(timezone.utc).timestamp())}"
    
    payload = {
        "email": email,
        "amount": str(amount_kobo),
        "reference": unique_reference,
        "metadata": {
            "transaction_type": "DEBT_SETTLEMENT",
            "company_id": str(company_id)
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
            else:
                logger.error(f"Paystack Settlement Init Error: {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Failed to connect to Paystack: {str(e)}")
        return None