from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    # bcrypt solo usa 72 bytes de input; si te pasas, passlib/bcrypt puede lanzar ValueError
    try:
        if password and len(password.encode("utf-8")) > 72:
            return False
        return pwd_context.verify(password, hashed)
    except ValueError:
        return False

def get_password_hash(password: str) -> str:
    # opcional: impedir registrar passwords >72 bytes si usas bcrypt
    if password and len(password.encode("utf-8")) > 72:
        raise ValueError("Password too long for bcrypt (max 72 bytes).")
    return pwd_context.hash(password)

def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": subject, "exp": expire}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
