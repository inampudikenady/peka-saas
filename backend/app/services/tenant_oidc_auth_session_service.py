import hashlib
import secrets
import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.exceptions import OIDCAuthSessionError
from app.models.tenant_oidc_auth_session import TenantOIDCAuthSession
from app.repositories.tenant_oidc_auth_session_repository import (
    TenantOIDCAuthSessionRepository,
)


class TenantOIDCAuthSessionService:
    def __init__(
        self,
        repository: TenantOIDCAuthSessionRepository,
    ) -> None:
        self.repository = repository

    def create(
        self,
        tenant_id: UUID,
        redirect_uri: str,
    ) -> tuple[TenantOIDCAuthSession, str]:
        raw_state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)

        session = TenantOIDCAuthSession(
            tenant_id=tenant_id,
            state_hash=self.hash_state(raw_state),
            nonce=nonce,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

        created_session = self.repository.add(session)
        self.repository.commit()
        self.repository.refresh(created_session)

        return created_session, raw_state

    @staticmethod
    def code_challenge(code_verifier: str) -> str:
        digest = hashlib.sha256(code_verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def validate(
        self,
        raw_state: str,
        tenant_id: UUID,
    ) -> TenantOIDCAuthSession:
        state_hash = self.hash_state(raw_state)
        session = self.repository.get_by_state_hash(state_hash)

        if session is None or session.tenant_id != tenant_id:
            raise OIDCAuthSessionError("Invalid OIDC state.")

        if session.used_at is not None:
            raise OIDCAuthSessionError("OIDC state has already been used.")

        if session.expires_at < datetime.now(UTC):
            raise OIDCAuthSessionError("OIDC state has expired.")

        return session

    def consume(
        self,
        session: TenantOIDCAuthSession,
    ) -> None:
        session.used_at = datetime.now(UTC)
        self.repository.commit()


    @staticmethod
    def hash_state(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()
