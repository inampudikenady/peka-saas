import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.exceptions import OIDCConfigurationError


SECRET_PREFIX = "fernet:v1:"


class OIDCSecretCipher:
    def __init__(self, key_material: str | None = None) -> None:
        material = (
            key_material
            or settings.tenant_sso_encryption_key
            or settings.platform_admin_jwt_secret
        )
        key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
        self.fernet = Fernet(key)

    def encrypt(self, secret: str) -> str:
        token = self.fernet.encrypt(secret.encode()).decode()
        return f"{SECRET_PREFIX}{token}"

    @staticmethod
    def is_encrypted(stored_secret: str) -> bool:
        return stored_secret.startswith(SECRET_PREFIX)

    def decrypt(self, stored_secret: str) -> str:
        if not stored_secret.startswith(SECRET_PREFIX):
            # Compatibility for configurations created before at-rest encryption.
            return stored_secret
        try:
            return self.fernet.decrypt(
                stored_secret.removeprefix(SECRET_PREFIX).encode()
            ).decode()
        except InvalidToken as exc:
            raise OIDCConfigurationError(
                "The stored OIDC client secret could not be decrypted."
            ) from exc
