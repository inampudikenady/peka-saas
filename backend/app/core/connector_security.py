import hashlib
import secrets

from app.core.security import hash_password, verify_password


REGISTRATION_TOKEN_PREFIX = "peka_reg_"
CONNECTOR_SECRET_PREFIX = "peka_cs_"


def generate_registration_token() -> str:
    return REGISTRATION_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_registration_token(token: str) -> str:
    # Tokens contain 256 bits of entropy, making deterministic SHA-256 safe for lookup.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_connector_secret() -> str:
    return CONNECTOR_SECRET_PREFIX + secrets.token_urlsafe(48)


def hash_connector_secret(secret: str) -> str:
    return hash_password(secret)


def verify_connector_secret(secret: str, secret_hash: str) -> bool:
    try:
        return verify_password(secret, secret_hash)
    except (ValueError, TypeError):
        return False
