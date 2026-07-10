class PEKAError(Exception):
    """Base exception for all domain-level PEKA errors."""


class TenantError(PEKAError):
    """Base exception for tenant-related operations."""


class TenantAlreadyExistsError(TenantError):
    """Raised when attempting to create a tenant with an existing slug."""


class TenantDomainAlreadyExistsError(TenantError):
    """Raised when a tenant primary domain is already assigned."""


class TenantNotFoundError(TenantError):
    """Raised when the requested tenant cannot be found."""


class TenantInviteError(PEKAError):
    """Base exception for tenant invite operations."""


class InvalidTenantInviteTokenError(TenantInviteError):
    """Raised when a tenant invite token is invalid."""


class TenantInviteAlreadyUsedError(TenantInviteError):
    """Raised when a tenant invite token has already been used."""


class TenantInviteExpiredError(TenantInviteError):
    """Raised when a tenant invite token has expired."""


class TenantUserAlreadyExistsError(TenantInviteError):
    """Raised when a tenant user already exists for the invite."""


class TenantUsernameAlreadyExistsError(TenantInviteError):
    """Raised when a generated tenant username already exists."""


class OIDCError(PEKAError):
    """Base exception for safe, domain-level OIDC failures."""


class OIDCAuthSessionError(OIDCError):
    """Raised when an OIDC state session cannot be validated."""


class OIDCConfigurationError(OIDCError):
    """Raised when the tenant OIDC configuration is incomplete."""


class OIDCAuthenticationError(OIDCError):
    """Raised when the provider response or ID token cannot be authenticated."""
