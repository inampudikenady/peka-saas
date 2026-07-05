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
