# app/utils/driver_notification.py
import logging
from firebase_admin import messaging
from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

async def push_trip_to_driver(fcm_token: str, trip_id: str, pickup_address: str, amount: str) -> bool:
    """
    Sends an FCM push notification to a driver without blocking the event loop.
    """
    if not fcm_token:
        logger.warning("Attempted to send FCM, but driver has no token.")
        return False

    message = messaging.Message(
        notification=messaging.Notification(
            title="🚨 New Tow Request!",
            body=f"Pickup at {pickup_address}. Tap to accept."
        ),
        data={
            "type": "NEW_TRIP",
            "trip_id": str(trip_id),
            "amount": str(amount)
        },
        token=fcm_token,
        android=messaging.AndroidConfig(priority='high'),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(aps=messaging.Aps(content_available=True))
        )
    )

    try:
        # We push the blocking Firebase HTTP call into a threadpool
        response = await run_in_threadpool(messaging.send, message)
        logger.info(f"Successfully sent FCM to device. Message ID: {response}")
        return True
    except Exception as e:
        logger.error(f"FCM Push failed: {e}")
        return False