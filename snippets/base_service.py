from __future__ import annotations

from typing import Any, Generic, Optional, Type, TypeVar, Union
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.base import Base
from app.repositories.base import BaseRepository

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType")
UpdateSchemaType = TypeVar("UpdateSchemaType")


class BaseService(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """Domain-service base that delegates CRUD to an owned BaseRepository instance.

    Services hold business logic; the repository handles all DB access.
    Subclasses may override any method to add domain logic; all others
    delegate transparently to self.repo.
    """

    def __init__(self, model: Type[ModelType]):
        self.model = model
        self.repo: BaseRepository[ModelType, CreateSchemaType, UpdateSchemaType] = (
            BaseRepository(model)
        )

    def get(self, db: Session, id: Any) -> Optional[ModelType]:
        return self.repo.get(db, id)

    def get_by(self, db: Session, **kwargs: Any) -> Optional[ModelType]:
        return self.repo.get_by(db, **kwargs)

    def get_multi(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        **filters: Any,
    ) -> list[ModelType]:
        return self.repo.get_multi(db, skip=skip, limit=limit, **filters)

    def count(self, db: Session, **filters: Any) -> int:
        return self.repo.count(db, **filters)

    def exists(self, db: Session, id: Any) -> bool:
        return self.repo.exists(db, id)

    def create(
        self,
        db: Session,
        *,
        obj_in: CreateSchemaType,
        user_id: Optional[UUID] = None,
    ) -> ModelType:
        return self.repo.create(db, obj_in=obj_in, user_id=user_id)

    def create_multi(
        self,
        db: Session,
        *,
        objs_in: list[CreateSchemaType],
        user_id: Optional[UUID] = None,
    ) -> list[ModelType]:
        return self.repo.create_multi(db, objs_in=objs_in, user_id=user_id)

    def update(
        self,
        db: Session,
        *,
        db_obj: ModelType,
        obj_in: Union[UpdateSchemaType, dict[str, Any]],
        user_id: Optional[UUID] = None,
    ) -> ModelType:
        return self.repo.update(db, db_obj=db_obj, obj_in=obj_in, user_id=user_id)

    def update_by_id(
        self,
        db: Session,
        *,
        id: Any,
        obj_in: Union[UpdateSchemaType, dict[str, Any]],
        user_id: Optional[UUID] = None,
    ) -> Optional[ModelType]:
        return self.repo.update_by_id(db, id=id, obj_in=obj_in, user_id=user_id)

    def remove(
        self,
        db: Session,
        *,
        id: Any,
        user_id: Optional[UUID] = None,
    ) -> Optional[ModelType]:
        return self.repo.remove(db, id=id, user_id=user_id)

    def force_delete(
        self,
        db: Session,
        *,
        id: Any,
        user_id: Optional[UUID] = None,
    ) -> Optional[ModelType]:
        return self.repo.force_delete(db, id=id, user_id=user_id)

    def remove_multi(
        self,
        db: Session,
        *,
        ids: list[Any],
        user_id: Optional[UUID] = None,
    ) -> int:
        return self.repo.remove_multi(db, ids=ids, user_id=user_id)

    def log_operation(
        self,
        operation: str,
        model_name: str,
        record_id: Any,
        user_id: Optional[UUID] = None,
    ) -> None:
        self.repo._log_operation(operation, model_name, record_id, user_id)
