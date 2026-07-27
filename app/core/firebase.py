# app/core/firebase.py
import firebase_admin
from firebase_admin import credentials
import logging

logger = logging.getLogger(__name__)

def initialize_firebase():
    """
    Initializes the Firebase Admin SDK. 
    Prevents crashing if called multiple times during hot-reloads.
    """
    try:
        if not firebase_admin._apps:
            # Point this to the path of your downloaded Firebase JSON key
            cred = credentials.Certificate("path/to/your/firebase-service-account.json")
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin initialized successfully.")
            
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")