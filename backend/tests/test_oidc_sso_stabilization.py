from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

from app.core.exceptions import OIDCAuthenticationError, OIDCConfigurationError
from app.core.exceptions import OIDCUserAuthorizationError
from app.models.tenant_sso_config import SSOProvider
from app.schemas.tenant_sso import TenantSSOConfigUpdate
from app.services.oidc_authentication_service import (
    OIDCAuthenticationService,
    OIDCUserIdentity,
)
from app.services.oidc_authorization_service import OIDCAuthorizationService
from app.services.oidc_discovery_service import (
    OIDCDiscoveryService,
    entra_issuer_url,
    entra_tenant_id_from_issuer,
    normalize_entra_tenant_id,
    normalize_issuer_url,
)
from app.services.oidc_secret_cipher import OIDCSecretCipher, SECRET_PREFIX
from app.services.tenant_oidc_auth_session_service import (
    TenantOIDCAuthSessionService,
)
from app.services.tenant_sso_service import (
    OIDCRuntimeConfiguration,
    TenantSSOService,
)
from app.services.oidc_user_service import OIDCUserService


TENANT_ID = "11111111-1111-4111-8111-111111111111"
ISSUER = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"


class Response:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://provider.example")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("provider error", request=request, response=response)


def runtime(**overrides):
    values = {
        "tenant_id": uuid4(),
        "provider": SSOProvider.MICROSOFT_ENTRA,
        "issuer_url": ISSUER,
        "client_id": "client-id",
        "client_secret": "client-secret",
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/keys",
        "redirect_uri": "https://tenant.example/api/v1/tenant/auth/callback",
        "scopes": "openid profile email",
        "enabled": True,
    }
    values.update(overrides)
    return OIDCRuntimeConfiguration(**values)


def test_entra_tenant_id_and_issuer_are_normalized_consistently():
    assert normalize_entra_tenant_id(TENANT_ID.upper()) == TENANT_ID
    assert entra_issuer_url(TENANT_ID.upper()) == ISSUER
    assert entra_tenant_id_from_issuer(f"{ISSUER}/") == TENANT_ID
    for invalid in (" common ", "not-a-uuid", f"{TENANT_ID} "):
        with pytest.raises(OIDCConfigurationError):
            normalize_entra_tenant_id(invalid)


def test_generic_issuer_normalization_and_validation():
    assert normalize_issuer_url("https://IdP.Example/realms/acme///") == (
        "https://idp.example/realms/acme"
    )
    for invalid in (
        " http://idp.example",
        "http://idp.example",
        "https://user:secret@idp.example",
        "https://idp.example?tenant=acme",
    ):
        with pytest.raises(OIDCConfigurationError):
            normalize_issuer_url(invalid)


def test_discovery_requires_matching_issuer_and_reports_safe_failure(monkeypatch):
    monkeypatch.setattr(
        "app.services.oidc_discovery_service.httpx.get",
        lambda *args, **kwargs: Response({
            "issuer": "https://idp.example",
            "authorization_endpoint": "https://idp.example/authorize",
            "token_endpoint": "https://idp.example/token",
            "jwks_uri": "https://idp.example/keys",
        }),
    )
    assert OIDCDiscoveryService().discover("https://idp.example/").issuer == (
        "https://idp.example"
    )
    monkeypatch.setattr(
        "app.services.oidc_discovery_service.httpx.get",
        lambda *args, **kwargs: Response({}, status_code=503),
    )
    with pytest.raises(OIDCConfigurationError, match="discovery failed"):
        OIDCDiscoveryService().discover("https://idp.example")


def test_existing_microsoft_issuer_in_generic_mode_stays_generic():
    config = SimpleNamespace(
        provider=SSOProvider.GENERIC_OIDC,
        entra_tenant_id=None,
        issuer_url=f"{ISSUER}/",
        client_id="old-client",
        client_secret_encrypted="enc:existing",
        authorization_endpoint="old-authorize",
        token_endpoint="old-token",
        jwks_uri="old-keys",
        redirect_uri="old-callback",
        scopes="openid profile email",
        enabled=True,
    )
    repository = SimpleNamespace(
        get_by_tenant_id=lambda tenant_id: config,
        commit=lambda: None,
        refresh=lambda value: None,
        rollback=lambda: None,
    )
    tenant = SimpleNamespace(
        slug="acme",
        subdomain="acme.example",
        tenant_url="https://acme.example",
    )
    discovery = SimpleNamespace(
        discover=lambda issuer: SimpleNamespace(
            issuer=issuer.rstrip("/"),
            authorization_endpoint=f"{issuer.rstrip('/')}/authorize",
            token_endpoint=f"{issuer.rstrip('/')}/token",
            jwks_uri=f"{issuer.rstrip('/')}/keys",
        )
    )
    cipher = SimpleNamespace(
        encrypt=lambda secret: f"enc:{secret}",
        decrypt=lambda secret: secret.removeprefix("enc:"),
        is_encrypted=lambda secret: secret.startswith("enc:"),
    )
    service = TenantSSOService(
        repository,
        SimpleNamespace(get_by_id=lambda tenant_id: tenant),
        discovery,
        cipher,
    )
    result = service.upsert(
        uuid4(),
        TenantSSOConfigUpdate(
            provider=SSOProvider.GENERIC_OIDC,
            issuer_url=f"{ISSUER}/",
            client_id="client-id",
            enabled=True,
        ),
    )
    assert result.provider == SSOProvider.GENERIC_OIDC
    assert result.entra_tenant_id is None
    assert result.issuer_url == ISSUER
    assert result.client_secret_encrypted == "enc:existing"


def test_seeded_placeholder_accepts_first_secret_without_discovery():
    config = SimpleNamespace(
        provider=SSOProvider.GENERIC_OIDC,
        entra_tenant_id=None,
        issuer_url=None,
        client_id=None,
        client_secret_encrypted=None,
        authorization_endpoint=None,
        token_endpoint=None,
        jwks_uri=None,
        redirect_uri=None,
        scopes="openid profile email",
        enabled=False,
    )
    repository = SimpleNamespace(
        get_by_tenant_id=lambda tenant_id: config,
        commit=lambda: None,
        refresh=lambda value: None,
        rollback=lambda: None,
    )
    tenant = SimpleNamespace(
        slug="acme",
        subdomain="acme.example",
        tenant_url="https://acme.example",
    )
    service = TenantSSOService(
        repository,
        SimpleNamespace(get_by_id=lambda tenant_id: tenant),
        SimpleNamespace(
            discover=lambda issuer: (_ for _ in ()).throw(
                AssertionError("save must not perform discovery")
            )
        ),
        SimpleNamespace(
            encrypt=lambda secret: f"enc:{secret}",
            decrypt=lambda secret: secret.removeprefix("enc:"),
            is_encrypted=lambda secret: secret.startswith("enc:"),
        ),
    )
    result = service.upsert(
        uuid4(),
        TenantSSOConfigUpdate(
            provider=SSOProvider.MICROSOFT_ENTRA,
            entra_tenant_id=TENANT_ID,
            client_id="client",
            client_secret="new-secret",
            enabled=True,
        ),
    )
    assert result.client_secret_encrypted == "enc:new-secret"
    assert result.authorization_endpoint is None


def test_reading_legacy_entra_config_encrypts_secret_and_derives_tenant_id():
    config = SimpleNamespace(
        provider=SSOProvider.MICROSOFT_ENTRA,
        entra_tenant_id=None,
        issuer_url=ISSUER,
        client_secret_encrypted="legacy-secret",
        redirect_uri=None,
    )
    commits = []
    repository = SimpleNamespace(
        get_by_tenant_id=lambda tenant_id: config,
        commit=lambda: commits.append(True),
        refresh=lambda value: None,
    )
    cipher = SimpleNamespace(
        encrypt=lambda secret: f"enc:{secret}",
        decrypt=lambda secret: secret.removeprefix("enc:"),
        is_encrypted=lambda secret: secret.startswith("enc:"),
    )
    service = TenantSSOService(
        repository,
        SimpleNamespace(
            get_by_id=lambda tenant_id: SimpleNamespace(
                slug="acme",
                subdomain="acme.example",
                tenant_url="https://acme.example",
            )
        ),
        SimpleNamespace(),
        cipher,
    )
    assert service.get(uuid4()) is config
    assert config.client_secret_encrypted == "enc:legacy-secret"
    assert config.entra_tenant_id == TENANT_ID
    assert config.redirect_uri == (
        "https://acme.example/api/v1/tenant/auth/callback"
    )
    assert commits == [True]


def test_authorization_url_contains_state_nonce_and_pkce():
    url = OIDCAuthorizationService().build_authorization_url(
        runtime(),
        state="state",
        nonce="nonce",
        code_challenge="challenge",
    )
    query = parse_qs(urlsplit(url).query)
    assert query["state"] == ["state"]
    assert query["nonce"] == ["nonce"]
    assert query["code_challenge"] == ["challenge"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [
        "https://tenant.example/api/v1/tenant/auth/callback"
    ]


def test_state_is_tenant_bound_expiring_one_use_and_has_pkce():
    stored = []
    repository = SimpleNamespace(
        add=lambda session: stored.append(session) or session,
        commit=lambda: None,
        refresh=lambda session: None,
        get_by_state_hash=lambda state_hash: next(
            (item for item in stored if item.state_hash == state_hash), None
        ),
    )
    service = TenantOIDCAuthSessionService(repository)
    tenant_id = uuid4()
    session, raw_state = service.create(
        tenant_id,
        "https://tenant.example/api/v1/tenant/auth/callback",
    )
    assert session.code_verifier
    assert service.code_challenge(session.code_verifier)
    assert service.validate(raw_state, tenant_id) is session
    with pytest.raises(Exception, match="Invalid OIDC state"):
        service.validate(raw_state, uuid4())
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(Exception, match="expired"):
        service.validate(raw_state, tenant_id)
    session.expires_at = datetime.now(UTC) + timedelta(minutes=1)
    service.consume(session)
    with pytest.raises(Exception, match="already been used"):
        service.validate(raw_state, tenant_id)


def signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_jwk = jwk.construct(public_pem, "RS256").to_dict()
    public_jwk["kid"] = "signing-key"
    return private_pem, public_jwk


def authenticate(monkeypatch, *, audience="client-id", issuer=ISSUER, nonce="nonce"):
    private_key, public_jwk = signing_material()
    claims = {
        "iss": issuer,
        "aud": audience,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "iat": datetime.now(UTC),
        "nonce": nonce,
        "sub": "subject",
        "oid": "stable-object-id",
        "email": "User@Example.com",
    }
    id_token = jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "signing-key"},
    )
    requests = []

    def post(url, data, timeout):
        requests.append(data)
        return Response({"id_token": id_token})

    monkeypatch.setattr("app.services.oidc_authentication_service.httpx.post", post)
    monkeypatch.setattr(
        "app.services.oidc_authentication_service.httpx.get",
        lambda *args, **kwargs: Response({"keys": [public_jwk]}),
    )
    identity = OIDCAuthenticationService().authenticate(
        runtime(),
        code="authorization-code",
        expected_nonce="nonce",
        redirect_uri="https://tenant.example/api/v1/tenant/auth/callback",
        code_verifier="verifier",
    )
    return identity, requests


def test_callback_validation_uses_oid_and_exact_redirect_with_pkce(monkeypatch):
    identity, requests = authenticate(monkeypatch)
    assert identity.subject == "stable-object-id"
    assert identity.email == "user@example.com"
    assert requests[0]["redirect_uri"] == (
        "https://tenant.example/api/v1/tenant/auth/callback"
    )
    assert requests[0]["code_verifier"] == "verifier"


@pytest.mark.parametrize(
    ("audience", "issuer", "nonce"),
    [
        ("another-client", ISSUER, "nonce"),
        ("client-id", "https://other.example", "nonce"),
        ("client-id", ISSUER, "wrong-nonce"),
    ],
)
def test_callback_rejects_audience_issuer_and_nonce(
    monkeypatch, audience, issuer, nonce
):
    with pytest.raises(OIDCAuthenticationError):
        authenticate(
            monkeypatch,
            audience=audience,
            issuer=issuer,
            nonce=nonce,
        )


def test_client_secrets_are_encrypted_and_legacy_values_remain_readable():
    cipher = OIDCSecretCipher("unit-test-key")
    encrypted = cipher.encrypt("client-secret")
    assert encrypted.startswith(SECRET_PREFIX)
    assert "client-secret" not in encrypted
    assert cipher.decrypt(encrypted) == "client-secret"
    assert cipher.decrypt("legacy-plaintext") == "legacy-plaintext"


def test_disabled_or_conflicting_tenant_user_is_not_authorized():
    tenant_id = uuid4()
    inactive = SimpleNamespace(
        is_active=False,
        external_subject="subject",
    )
    repository = SimpleNamespace(
        get_by_tenant_and_external_subject=lambda scoped_tenant, subject: (
            inactive if scoped_tenant == tenant_id else None
        ),
        get_by_tenant_and_email=lambda scoped_tenant, email: None,
    )
    identity = OIDCUserIdentity(
        subject="subject",
        email="user@example.com",
    )
    with pytest.raises(OIDCUserAuthorizationError):
        OIDCUserService(repository).provision(tenant_id, identity)
