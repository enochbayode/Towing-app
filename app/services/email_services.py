from app.core.config import settings
import resend
import logging

# Set the API key directly for the Resend SDK
# Ideally, pull this from your core/config.py settings
FROM_EMAIL = settings.RESEND_FROM_EMAIL

logger = logging.getLogger(__name__)

def send_otp(email: str, full_name: str, otp_code: str, role: str) -> None:
    """
    Sends a 6-digit OTP verification email via Resend.
    Adapts the email subject and messaging based on the recipient's role.
    
    Args:
        email: The recipient's email address.
        name: The recipient's full name.
        otp_code: The 6-digit verification code.
        role: "user", "admin", or "driver".
    """
    try:
        resend.api_key = settings.RESEND_API_KEY
        
        # 1. Determine email context based on role
        if role == "user":
            subject = "Verify Your Towing App Account"
            greeting = f"Welcome to the platform, {full_name}!"
            context = "Use the code below to verify your rider account and access on-demand roadside assistance."
        elif role == "driver":
            subject = "Tow Fleet Onboarding - Verification Code"
            greeting = f"Welcome Operator {full_name},"
            context = "Use the code below to verify your driver profile and start receiving dispatch requests."
        else: # admin
            subject = "Admin Portal Verification"
            greeting = f"Hello {full_name},"
            context = "Your admin access verification code is:"

        # 2. Build the Resend parameters
        params = {
            "from": FROM_EMAIL,
            "to": [email],
            "subject": subject,
            "html": f"""
            <div style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #2d3748;">
                <h2 style="color: #1a365d; border-bottom: 2px solid #edf2f7; padding-bottom: 10px;">{subject}</h2>
                <p>{greeting}</p>
                <p>{context}</p>
                
                <div style="background-color: #f7fafc; padding: 24px; text-align: center; border-radius: 8px; border-left: 4px solid #dd6b20; margin: 24px 0;">
                    <h1 style="letter-spacing: 8px; color: #dd6b20; margin: 0; font-size: 32px;">{otp_code}</h1>
                </div>
                
                <p style="font-size: 13px; color: #718096; line-height: 1.5;">
                    This code will expire in 15 minutes. For your security, do not share this code with anyone, including our support team. If you did not request this verification, please ignore this email.
                </p>
            </div>
            """
        }
        
        # 3. Dispatch the email
        response = resend.Emails.send(params)
        logger.info(f"---->> OTP email sent successfully to {email}. Resend ID: {response.get('id')}")
        
    except Exception as e:
        # TEMPORARY DEBUG PRINT (Remove after fixing!)
        print(f"DEBUG: My API key is exactly -> '{settings.RESEND_API_KEY}'")
        logger.error(f"---> Failed to send OTP email to {email}: {str(e)}")
        # Optionally re-raise the exception if you want the API endpoint to fail 
        # when the email fails to send:
        # raise Exception("Email dispatch failed") from e