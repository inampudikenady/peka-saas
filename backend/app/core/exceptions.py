class PEKAError(Exception):
    """Base application exception."""


class TenantAlreadyExistsError(PEKAError):
    pass


class TenantDomainAlreadyExistsError(PEKAError):
    pass


class TenantNotFoundError(PEKAError):
    pass
