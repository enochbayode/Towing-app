import secrets
import string
import bcrypt 

def get_password_hash(password: str) -> str:
    """
    Hashes the password using the direct bcrypt engine.
    Truncates to 72 bytes to prevent Python 3.14 crashes.
    """
    # 1. Truncate and encode to bytes
    password_bytes = password.encode('utf-8')[:72]
    
    # 2. Generate salt and hash
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    
    # 3. Return as a decoded string for the database
    return hashed.decode('utf-8')

def generate_random_password(length: int = 12) -> str:
    """
    Generates a secure temporary password.
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for i in range(length))

def generate_invite_token() -> str:
    """
    Generates a high-entropy URL-safe token for manager invites.
    """
    return secrets.token_urlsafe(32)