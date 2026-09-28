import httpx
from typing import Optional, Dict, Any
from sqlmodel.ext.asyncio.session import AsyncSession
from firebase_admin import credentials, messaging

from app.models.user import User
from app.core.config import settings

import logging
logger = logging.getLogger(__name__)

class NotificationService:
    async def send_user_push(
        self,
        user_id: str,
        title: str,
        body: str,
        data: Optional[Dict[str, str]] = None, # FCM v1 requires data values to be strings
        session: Optional[AsyncSession] = None
    ) -> bool:
        """
        Fetches the user's push token and dispatches a mobile push notification via Firebase Admin.
        """
        if not session:
            logger.warning(f"No DB session provided to fetch push token for user {user_id}.")
            return False

        # 1. Fetch User and verify FCM Token
        user = await session.get(User, user_id)
        if not user or not getattr(user, "fcm_token", None):
            logger.warning(f"Cannot send push notification: User {user_id} has no valid fcm_token.")
            return False

        # 2. Build Modern FCM Message
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            token=user.fcm_token,
        )

        # 3. Dispatch
        try:
            # send() is synchronous in the SDK, so we run it in a thread if strictly async is needed, 
            # or just use it directly as it's very fast.
            response = messaging.send(message)
            logger.info(f"Successfully sent push notification to {user_id}. Message ID: {response}")
            return True
        except Exception as e:
            logger.error(f"FCM Push API failed for user {user_id}: {str(e)}")
            return False

# Global Singleton Instance
notification_service = NotificationService()