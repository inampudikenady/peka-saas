from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.schemas.token import PlatformTokenPayload


password_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
)


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return password_context.verify(plain_password, password_hash)


def create_access_token(
    subject: UUID,
    username: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    expires_at = datetime.utcnow() + (
        expires_delta
        or timedelta(minutes=settings.platform_admin_access_token_minutes)
    )

    payload = {
        "sub": str(subject),
        "username": username,
        "type": "platform_admin",
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.platform_admin_jwt_secret,
        algorithm=settings.platform_admin_jwt_algorithm,
    )


def create_tenant_access_token(
    subject: UUID,
    username: str,
    tenant_id: UUID,
    expires_delta: Optional[timedelta] = None,
) -> str:
    expires_at = datetime.utcnow() + (
        expires_delta
        or timedelta(minutes=settings.platform_admin_access_token_minutes)
    )

    payload = {
        "sub": str(subject),
        "username": username,
        "tenant_id": str(tenant_id),
        "type": "tenant_user",
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.platform_admin_jwt_secret,
        algorithm=settings.platform_admin_jwt_algorithm,
    )


def decode_access_token(token: str) -> PlatformTokenPayload:
    try:
        payload = jwt.decode(
            token,
            settings.platform_admin_jwt_secret,
            algorithms=[settings.platform_admin_jwt_algorithm],
        )
        return PlatformTokenPayload.model_validate(payload)
    except JWTError as exc:
        raise ValueError("Invalid access token") from exc
