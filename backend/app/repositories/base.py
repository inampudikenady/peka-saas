from typing import Generic, Optional, TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.base import Entity


ModelType = TypeVar("ModelType", bound=Entity)


class BaseRepository(Generic[ModelType]):
    def __init__(self, db: Session, model: type[ModelType]) -> None:
        self.db = db
        self.model = model

    def get_by_id(self, entity_id: UUID) -> Optional[ModelType]:
        return self.db.get(self.model, entity_id)

    def add(self, entity: ModelType) -> ModelType:
        self.db.add(entity)
        self.db.flush()
        self.db.refresh(entity)
        return entity

    def delete(self, entity: ModelType) -> None:
        self.db.delete(entity)
        self.db.flush()

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
