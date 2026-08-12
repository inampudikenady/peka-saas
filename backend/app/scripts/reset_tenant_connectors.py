"""Delete all connector-domain data for one tenant in development.

Usage:
    python -m app.scripts.reset_tenant_connectors --tenant vitwo --yes
"""

import argparse
from dataclasses import dataclass
from typing import Any, Callable, Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.connector import (
    ConnectorCapability,
    ConnectorEvent,
    ConnectorHeartbeat,
    ConnectorRegistrationToken,
    ManagedConnector,
)
from app.models.tenant import Tenant


PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})


@dataclass(frozen=True)
class ConnectorDataCounts:
    managed_connectors: int
    heartbeats: int
    capabilities: int
    connector_events: int
    registration_tokens: int

    def all_zero(self) -> bool:
        return all(value == 0 for value in self.__dict__.values())


def resolve_tenant(db: Session, tenant_slug: str) -> Tenant | None:
    return db.scalar(select(Tenant).where(Tenant.slug == tenant_slug))


def connector_data_counts(db: Session, tenant_id: UUID) -> ConnectorDataCounts:
    def count(model: Any) -> int:
        return (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.tenant_id == tenant_id)
            )
            or 0
        )

    return ConnectorDataCounts(
        managed_connectors=count(ManagedConnector),
        heartbeats=count(ConnectorHeartbeat),
        capabilities=count(ConnectorCapability),
        connector_events=count(ConnectorEvent),
        registration_tokens=count(ConnectorRegistrationToken),
    )


def delete_connector_data(db: Session, tenant_id: UUID) -> ConnectorDataCounts:
    """Delete only connector-domain records, verifying zero rows before commit."""
    try:
        for model in (
            ConnectorEvent,
            ConnectorHeartbeat,
            ConnectorCapability,
            ManagedConnector,
            ConnectorRegistrationToken,
        ):
            db.execute(delete(model).where(model.tenant_id == tenant_id))
        db.flush()
        remaining = connector_data_counts(db, tenant_id)
        if not remaining.all_zero():
            raise RuntimeError(f"Connector cleanup verification failed: {remaining}")
        db.commit()
        return remaining
    except (RuntimeError, SQLAlchemyError):
        db.rollback()
        raise


def _print_counts(label: str, counts: ConnectorDataCounts) -> None:
    print(label)
    print(f"  managed connectors:   {counts.managed_connectors}")
    print(f"  heartbeats:           {counts.heartbeats}")
    print(f"  capabilities:         {counts.capabilities}")
    print(f"  connector events:     {counts.connector_events}")
    print(f"  registration tokens:  {counts.registration_tokens}")


def _confirmed(tenant_slug: str, input_fn: Callable[[str], str] = input) -> bool:
    answer = input_fn(
        f"Type DELETE {tenant_slug} to permanently remove this tenant's connector data: "
    )
    return answer == f"DELETE {tenant_slug}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete all connector data for one tenant without deleting the tenant."
    )
    parser.add_argument("--tenant", required=True, help="Exact tenant slug")
    parser.add_argument(
        "--yes", action="store_true", help="Skip the interactive confirmation"
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Additional explicit override required in production",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environment = settings.environment.strip().lower()
    if environment in PRODUCTION_ENVIRONMENTS and not args.allow_production:
        print("Refusing connector cleanup in production without --allow-production.")
        return 2

    db = SessionLocal()
    try:
        tenant = resolve_tenant(db, args.tenant)
        if tenant is None:
            print(f"Tenant slug '{args.tenant}' was not found; nothing was deleted.")
            return 1

        print(f"Resolved tenant: slug={tenant.slug} tenant_id={tenant.id}")
        before = connector_data_counts(db, tenant.id)
        _print_counts("Before deletion:", before)

        if not args.yes and not _confirmed(tenant.slug):
            print("Cleanup cancelled; nothing was deleted.")
            return 3

        after = delete_connector_data(db, tenant.id)
        _print_counts("After deletion:", after)
        print("Connector cleanup completed and verified.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
