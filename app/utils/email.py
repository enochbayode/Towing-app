import os
import resend
import logging
from app.core.config import settings

# Ensure these are set in your environment or core config
resend.api_key = os.getenv("RESEND_API_KEY")
FROM_EMAIL = settings.RESEND_FROM_EMAIL

logger = logging.getLogger(__name__)

def send_driver_invite_email(
    driver_email: str, 
    driver_name: str, 
    temp_password: str, 
    invite_link: str, 
    company_name: str
) -> None:
    """
    Sends an onboarding invitation to a new driver using the Resend SDK.
    Includes both plain text and HTML fallbacks.
    """
    
    # --- PLAIN TEXT VERSION ---
    text_content = f"""Hello {driver_name},

You have been invited by {company_name} to join the SoulsDrive network as a Towing Fleet Operator.

Your account has been provisioned with the following login details:
• Email: {driver_email}
• Temporary Password: {temp_password}

To finalize your account setup, please visit the secure link below to Accept or Decline this invitation:
{invite_link}

Note: You will be asked to enter the email and temporary password provided above to securely process your invitation.
You can only accept or decline this invitation once, and the link will expire after 7 days for security reasons.

Best regards,
The SoulsDrive Team
"""

    # --- HTML VERSION ---
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #dd6b20;">Welcome to SoulsDrive!</h2>
        <p>Hello <strong>{driver_name}</strong>,</p>
        
        <p>You have been invited by <strong>{company_name}</strong> to join the platform as a <strong>Towing Fleet Operator</strong>.</p>
        
        <div style="background-color: #f7fafc; padding: 15px; border-radius: 8px; border-left: 4px solid #dd6b20; margin: 20px 0;">
            <p style="margin-top: 0;"><strong>Your Login Credentials:</strong></p>
            <ul style="margin-bottom: 0; padding-left: 20px;">
                <li><strong>Email:</strong> {driver_email}</li>
                <li><strong>Temporary Password:</strong> <span style="font-family: monospace; background: #e2e8f0; padding: 2px 6px; border-radius: 4px; color: #c05621; font-weight: bold;">{temp_password}</span></li>
            </ul>
        </div>
        
        <p>To finalize your account setup, please click the button below to review and respond to this invitation.</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{invite_link}" style="background-color: #1a365d; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Accept or Decline Invitation</a>
        </div>
        
        <p style="font-size: 0.9em; color: #6b7280;">If the button doesn't work, copy and paste this link into your browser:<br>
        <a href="{invite_link}" style="color: #2b6cb0;">{invite_link}</a></p>
        
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="font-size: 0.85em; color: #718096;">Best regards,<br><strong>The SoulsDrive Team</strong></p>
      </body>
    </html>
    """

    try:
        params = {
            "from": f"<{FROM_EMAIL}>",
            "to": [driver_email],
            "subject": f"Invitation: Join {company_name} on SoulsDrive",
            "text": text_content,
            "html": html_content
        }
        
        response = resend.Emails.send(params)
        logger.info(f"Driver invite email sent successfully to {driver_email}. Resend ID: {response.get('id')}")
        
    except Exception as e:
        logger.error(f"EMAIL ERROR: Failed to send driver invite to {driver_email}: {str(e)}")


def send_company_status_email(email: str, company_name: str, status: str) -> None:
    """
    Sends lifecycle emails for company registration.
    status options: 'received', 'verified', 'manual_review'
    """
    try:
        resend.api_key = settings.RESEND_API_KEY
        
        if status == "received":
            subject = "Registration Received - Awaiting Verification"
            body = f"""
            <h2>Welcome to the Platform, {company_name}!</h2>
            <p>Your fleet registration has been successfully received.</p>
            <p>Our system is currently verifying your Corporate Affairs Commission (CAC) details. This process usually takes a few minutes, but can take up to 72 hours if manual review is required.</p>
            <p>We will notify you the moment your account is vetted and ready for dispatch operations.</p>
            """
        elif status == "verified":
            subject = "Company Verified - Ready for Dispatch"
            body = f"""
            <h2>Verification Successful 🎉</h2>
            <p>Great news! The CAC registration for <strong>{company_name}</strong> has been verified.</p>
            <p>Your fleet is now fully vetted. You can log into your dashboard to add your payout bank accounts and start onboarding drivers.</p>
            """
        else: # manual_review
            subject = "Action Required - Manual Verification"
            body = f"""
            <h2>Registration Update for {company_name}</h2>
            <p>We were unable to automatically verify your CAC registration number.</p>
            <p>Our compliance team has received your file and will review it manually within the next 72 hours. We may reach out to this email if additional documents are required.</p>
            """

        params = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [email],
            "subject": subject,
            "html": f'<div style="font-family: Arial, sans-serif; color: #2d3748;">{body}</div>'
        }
        
        resend.Emails.send(params)
        
    except Exception as e:
        logger.error(f"Failed to send {status} email to {email}: {str(e)}")