"""Qdrant boundary with mandatory server-side tenant filters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx


REQUIRED_PAYLOAD_INDEXES = (
    "tenant_id",
    "connector_id",
    "source_id",
    "document_id",
    "version_id",
    "lifecycle_status",
)


@dataclass(frozen=True)
class VectorPoint:
    id: UUID
    vector: list[float]
    payload: dict[str, Any]


@dataclass(frozen=True)
class VectorHit:
    id: UUID
    score: float
    payload: dict[str, Any]


class VectorStore(Protocol):
    def ensure_collection(self, dimension: int) -> None: ...
    def upsert(self, points: list[VectorPoint]) -> None: ...
    def delete_version(self, tenant_id: UUID, version_id: UUID) -> None: ...
    def delete_document(self, tenant_id: UUID, document_id: UUID) -> None: ...
    def count_points(
        self,
        tenant_id: UUID,
        document_id: UUID | None = None,
        version_id: UUID | None = None,
    ) -> int: ...
    def count_all_points(self) -> int: ...
    def health_check(self) -> bool: ...
    def search(
        self, tenant_id: UUID, vector: list[float], limit: int, filters: dict[str, str]
    ) -> list[VectorHit]: ...


class InMemoryVectorStore:
    """Deterministic test-only vector store."""

    def __init__(self) -> None:
        self.points: dict[UUID, VectorPoint] = {}

    def upsert(self, points: list[VectorPoint]) -> None:
        self.points.update({point.id: point for point in points})

    def ensure_collection(self, dimension: int) -> None:
        self.dimension = dimension

    def delete_version(self, tenant_id: UUID, version_id: UUID) -> None:
        self.points = {
            key: point
            for key, point in self.points.items()
            if point.payload.get("tenant_id") != str(tenant_id)
            or point.payload.get("version_id") != str(version_id)
        }

    def health_check(self) -> bool:
        return True

    def count_points(
        self,
        tenant_id: UUID,
        document_id: UUID | None = None,
        version_id: UUID | None = None,
    ) -> int:
        return sum(
            1
            for point in self.points.values()
            if point.payload.get("tenant_id") == str(tenant_id)
            and (
                document_id is None
                or point.payload.get("document_id") == str(document_id)
            )
            and (
                version_id is None or point.payload.get("version_id") == str(version_id)
            )
        )

    def count_all_points(self) -> int:
        return len(self.points)

    def delete_document(self, tenant_id: UUID, document_id: UUID) -> None:
        self.points = {
            key: point
            for key, point in self.points.items()
            if point.payload.get("tenant_id") != str(tenant_id)
            or point.payload.get("document_id") != str(document_id)
        }

    def search(
        self, tenant_id: UUID, vector: list[float], limit: int, filters: dict[str, str]
    ) -> list[VectorHit]:
        hits: list[VectorHit] = []
        for point in self.points.values():
            if point.payload.get("tenant_id") != str(tenant_id):
                continue
            if any(
                point.payload.get(key) != value
                for key, value in filters.items()
                if value
            ):
                continue
            score = sum(
                left * right for left, right in zip(vector, point.vector, strict=True)
            )
            hits.append(VectorHit(point.id, score, point.payload))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


class DisabledVectorStore:
    def ensure_collection(self, dimension: int) -> None:
        return None

    def upsert(self, points: list[VectorPoint]) -> None:
        raise RuntimeError("Qdrant is not configured")

    def delete_version(self, tenant_id: UUID, version_id: UUID) -> None:
        raise RuntimeError("Qdrant is not configured")

    def delete_document(self, tenant_id: UUID, document_id: UUID) -> None:
        raise RuntimeError("Qdrant is not configured")

    def count_points(
        self,
        tenant_id: UUID,
        document_id: UUID | None = None,
        version_id: UUID | None = None,
    ) -> int:
        raise RuntimeError("Qdrant is not configured")

    def count_all_points(self) -> int:
        raise RuntimeError("Qdrant is not configured")

    def search(
        self, tenant_id: UUID, vector: list[float], limit: int, filters: dict[str, str]
    ) -> list[VectorHit]:
        raise RuntimeError("Qdrant is not configured")

    def health_check(self) -> bool:
        return False


class QdrantVectorStore:
    def __init__(
        self,
        url: str,
        collection: str,
        api_key: str | None = None,
        timeout: float = 30,
        tls_verify: bool = True,
    ) -> None:
        self.url = url.rstrip("/")
        self.collection = collection
        self.headers = {"api-key": api_key} if api_key else {}
        self.client = httpx.Client(
            timeout=timeout, verify=tls_verify, headers=self.headers
        )

    def ensure_collection(self, dimension: int) -> None:
        response = self.client.get(f"{self.url}/collections/{self.collection}")
        if response.status_code == 404:
            response = self.client.put(
                f"{self.url}/collections/{self.collection}",
                json={"vectors": {"size": dimension, "distance": "Cosine"}},
            )
            response.raise_for_status()
            response = self.client.get(f"{self.url}/collections/{self.collection}")
        response.raise_for_status()
        collection = response.json()["result"]
        vectors = collection["config"]["params"]["vectors"]
        if not isinstance(vectors, dict) or vectors.get("size") != dimension:
            raise RuntimeError(
                "Qdrant collection vector dimension does not match configuration"
            )
        for field in REQUIRED_PAYLOAD_INDEXES:
            index_response = self.client.put(
                f"{self.url}/collections/{self.collection}/index?wait=true",
                json={"field_name": field, "field_schema": "keyword"},
            )
            if index_response.status_code not in {200, 409}:
                index_response.raise_for_status()
        verified = self.client.get(f"{self.url}/collections/{self.collection}")
        verified.raise_for_status()
        payload_schema = verified.json()["result"].get("payload_schema") or {}
        missing = [
            field for field in REQUIRED_PAYLOAD_INDEXES if field not in payload_schema
        ]
        if missing:
            raise RuntimeError("Qdrant collection is missing required payload indexes")

    def upsert(self, points: list[VectorPoint]) -> None:
        response = self.client.put(
            f"{self.url}/collections/{self.collection}/points?wait=true",
            json={
                "points": [
                    {
                        "id": str(point.id),
                        "vector": point.vector,
                        "payload": point.payload,
                    }
                    for point in points
                ]
            },
        )
        response.raise_for_status()

    def delete_version(self, tenant_id: UUID, version_id: UUID) -> None:
        response = self.client.post(
            f"{self.url}/collections/{self.collection}/points/delete?wait=true",
            json={"filter": self._filter(tenant_id, {"version_id": str(version_id)})},
        )
        response.raise_for_status()

    @staticmethod
    def _filter(tenant_id: UUID, filters: dict[str, str]) -> dict[str, Any]:
        must = [{"key": "tenant_id", "match": {"value": str(tenant_id)}}]
        must.extend(
            {"key": key, "match": {"value": value}}
            for key, value in filters.items()
            if value
        )
        return {"must": must}

    def delete_document(self, tenant_id: UUID, document_id: UUID) -> None:
        response = self.client.post(
            f"{self.url}/collections/{self.collection}/points/delete?wait=true",
            json={"filter": self._filter(tenant_id, {"document_id": str(document_id)})},
        )
        response.raise_for_status()

    def count_points(
        self,
        tenant_id: UUID,
        document_id: UUID | None = None,
        version_id: UUID | None = None,
    ) -> int:
        filters = {
            "document_id": str(document_id) if document_id else "",
            "version_id": str(version_id) if version_id else "",
        }
        response = self.client.post(
            f"{self.url}/collections/{self.collection}/points/count",
            json={"filter": self._filter(tenant_id, filters), "exact": True},
        )
        response.raise_for_status()
        return int(response.json()["result"]["count"])

    def count_all_points(self) -> int:
        response = self.client.get(f"{self.url}/collections/{self.collection}")
        response.raise_for_status()
        return int(response.json()["result"].get("points_count") or 0)

    def search(
        self, tenant_id: UUID, vector: list[float], limit: int, filters: dict[str, str]
    ) -> list[VectorHit]:
        response = self.client.post(
            f"{self.url}/collections/{self.collection}/points/search",
            json={
                "vector": vector,
                "limit": limit,
                "with_payload": True,
                "filter": self._filter(tenant_id, filters),
            },
        )
        response.raise_for_status()
        return [
            VectorHit(
                UUID(str(item["id"])), float(item["score"]), item.get("payload") or {}
            )
            for item in response.json()["result"]
        ]

    def health_check(self) -> bool:
        try:
            return self.client.get(
                "/healthz" if self.url == "" else f"{self.url}/healthz"
            ).is_success
        except httpx.HTTPError:
            return False
