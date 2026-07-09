from fastapi import HTTPException, Request, status

from app.core.tenant_context import TenantContext


def get_current_tenant_context(request: Request) -> TenantContext:
    tenant_context = getattr(request.state, "tenant_context", None)

    if tenant_context is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant could not be resolved.",
        )

    return tenant_context
