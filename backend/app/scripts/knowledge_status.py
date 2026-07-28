"""Print safe local knowledge-runtime status from the shared Settings object."""

import json
from datetime import datetime, timezone

from sqlalchemy import func, select, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import IngestionJob, IngestionJobState
from app.repositories.document_repository import DocumentRepository
from app.services.knowledge_runtime_health import embedding_health, qdrant_health
from app.services.provider_factory import object_storage


def main() -> int:
    result: dict[str, object] = {
        "environment": settings.environment,
        "settings_file": str(settings.model_config["env_file"]),
        "embedding_provider": embedding_health(verify=True),
        "qdrant": qdrant_health(),
    }
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        repository = DocumentRepository(db)
        heartbeat = repository.latest_worker_heartbeat()
        queued = db.scalar(
            select(func.count())
            .select_from(IngestionJob)
            .where(
                IngestionJob.state.in_(
                    [
                        IngestionJobState.PENDING,
                        IngestionJobState.FAILED_RETRYABLE,
                        IngestionJobState.RETRY,
                    ]
                )
            )
        ) or 0
        worker: dict[str, object] = {"status": "not_running", "queued_jobs": queued}
        if heartbeat is not None:
            seen = heartbeat.last_seen_at
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            age = round((datetime.now(timezone.utc) - seen).total_seconds())
            worker.update(
                {
                    "status": (
                        "healthy"
                        if age <= settings.peka_ingestion_worker_heartbeat_stale_seconds
                        else "degraded"
                    ),
                    "worker_state": heartbeat.status,
                    "last_heartbeat_seconds_ago": age,
                }
            )
        result["postgresql"] = {"status": "healthy"}
        result["ingestion_worker"] = worker
    except Exception:
        result["postgresql"] = {"status": "unavailable"}
        result["ingestion_worker"] = {"status": "unavailable"}
    finally:
        db.close()
    try:
        result["object_storage"] = {
            "status": "healthy" if object_storage().health_check() else "unavailable"
        }
    except Exception:
        result["object_storage"] = {"status": "unavailable"}
    print(json.dumps(result, indent=2, sort_keys=True))
    statuses = [
        item.get("status")
        for item in result.values()
        if isinstance(item, dict)
    ]
    return 0 if "unavailable" not in statuses else 1


if __name__ == "__main__":
    raise SystemExit(main())
