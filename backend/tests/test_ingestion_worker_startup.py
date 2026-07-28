from app.scripts import run_ingestion_worker


def test_worker_startup_heartbeat_is_immediate(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class FakeRepository:
        def __init__(self, _session):
            pass

        def worker_heartbeat(self, worker_id, status):
            calls.append((worker_id, status))

    monkeypatch.setattr(run_ingestion_worker, "SessionLocal", FakeSession)
    monkeypatch.setattr(run_ingestion_worker, "DocumentRepository", FakeRepository)
    run_ingestion_worker.publish_startup_heartbeat("worker-1")
    assert calls == [("worker-1", "STARTING")]
