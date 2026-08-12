"""Object-storage boundary used by document ingestion."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256: str


class ObjectStorage(Protocol):
    def put_stream(
        self, key: str, stream: BinaryIO, max_bytes: int
    ) -> StoredObject: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def verify_hash(self, key: str, expected_sha256: str) -> bool: ...
    def health_check(self) -> bool: ...


class ObjectTooLargeError(ValueError):
    pass


class LocalFilesystemObjectStorage:
    """Atomic filesystem storage for development and single-node deployments."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        pure = PurePosixPath(key)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError("Invalid object key")
        path = (self.root / Path(*pure.parts)).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid object key")
        return path

    def put_stream(self, key: str, stream: BinaryIO, max_bytes: int) -> StoredObject:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, delete=False
            ) as temporary:
                temporary_name = temporary.name
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ObjectTooLargeError(f"Upload exceeds {max_bytes} bytes")
                    digest.update(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
        return StoredObject(
            key=key, size_bytes=size, sha256=f"sha256:{digest.hexdigest()}"
        )

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def verify_hash(self, key: str, expected_sha256: str) -> bool:
        digest = hashlib.sha256()
        with self.open(key) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}" == expected_sha256.lower()

    def health_check(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            return self.root.is_dir() and os.access(self.root, os.R_OK | os.W_OK)
        except OSError:
            return False
