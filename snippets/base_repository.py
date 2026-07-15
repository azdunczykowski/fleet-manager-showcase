from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import (
    Any,
    Generic,
    Optional,
    Protocol,
    Type,
    TypeVar,
    Union,
    runtime_checkable,
)
from uuid import UUID

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.inspection import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from app.core.constants import MAX_QUERY_LIMIT
from app.core.exceptions import DatabaseError, DuplicateError
from app.db.base import Base

logger = logging.getLogger(__name__)

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType")
UpdateSchemaType = TypeVar("UpdateSchemaType")


@runtime_checkable
class HasCreateDict(Protocol):
    def create_dict(self) -> dict[str, Any]: ...


@runtime_checkable
class HasUpdateDict(Protocol):
    def update_dict(self, *, exclude_unset: bool = False) -> dict[str, Any]: ...


class BaseRepository(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model
        self._primary_key = self._get_primary_key()

    def _get_primary_key(self) -> str:
        mapper = sqlalchemy_inspect(self.model)
        primary_keys = [key.name for key in mapper.primary_key]
        if not primary_keys:
            raise RuntimeError(f"model {self.model.__name__} has no primary key")
        if len(primary_keys) > 1:
            raise RuntimeError(f"model {self.model.__name__} has composite primary key")
        return primary_keys[0]

    def _log_operation(
        self,
        operation: str,
        model_name: str,
        record_id: Any,
        user_id: Optional[UUID] = None,
    ) -> None:
        log_data = {
            "op": operation,
            "tbl": model_name,
            "id": str(record_id),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if user_id:
            log_data["user"] = str(user_id)
        logger.info("AUDIT: %s", log_data)

    def _serialize_create(self, obj_in: CreateSchemaType) -> dict[str, Any]:
        if isinstance(obj_in, HasCreateDict):
            return obj_in.create_dict()
        return obj_in.model_dump()

    def get(self, db: Session, id: Any) -> Optional[ModelType]:
        try:
            return db.get(self.model, id)
        except SQLAlchemyError as e:
            logger.error("db error in get: %s", e)
            raise DatabaseError("failed to retrieve record") from e

    def get_by(self, db: Session, **kwargs) -> Optional[ModelType]:
        try:
            return db.scalar(select(self.model).filter_by(**kwargs))
        except SQLAlchemyError as e:
            logger.error("db error in get_by: %s", e)
            raise DatabaseError("failed to retrieve record") from e

    def get_multi(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        **filters,
    ) -> list[ModelType]:
        try:
            stmt = select(self.model)
            if filters:
                stmt = stmt.filter_by(**filters)
            limit = min(limit, MAX_QUERY_LIMIT)
            return list(db.scalars(stmt.offset(skip).limit(limit)).all())
        except SQLAlchemyError as e:
            logger.error("db error in get_multi: %s", e)
            raise DatabaseError("failed to retrieve records") from e

    def count(self, db: Session, **filters) -> int:
        try:
            stmt = select(func.count()).select_from(self.model)
            if filters:
                stmt = stmt.filter_by(**filters)
            return db.scalar(stmt) or 0
        except SQLAlchemyError as e:
            logger.error("db error in count: %s", e)
            raise DatabaseError("failed to count records") from e

    def exists(self, db: Session, id: Any) -> bool:
        # SELECT EXISTS is more efficient than loading the full record
        try:
            pk_column = getattr(self.model, self._primary_key)
            return bool(db.scalar(select(exists().where(pk_column == id))))
        except SQLAlchemyError as e:
            logger.error("db error in exists: %s", e)
            raise DatabaseError("failed to check existence") from e

    def create(
        self,
        db: Session,
        *,
        obj_in: CreateSchemaType,
        user_id: Optional[UUID] = None,
    ) -> ModelType:
        try:
            db_obj = self.model(**self._serialize_create(obj_in))
            db.add(db_obj)
            db.flush()
            db.refresh(db_obj)
            record_id = getattr(db_obj, self._primary_key)
            self._log_operation("create", self.model.__name__, record_id, user_id)
            return db_obj
        except IntegrityError as e:
            logger.warning("integrity error: %s", e)
            raise DuplicateError(f"{self.model.__name__.lower()}.already_exists") from e
        except SQLAlchemyError as e:
            logger.error("db error in create: %s", e)
            raise DatabaseError("database_error") from e

    def create_multi(
        self,
        db: Session,
        *,
        objs_in: list[CreateSchemaType],
        user_id: Optional[UUID] = None,
    ) -> list[ModelType]:
        # All records flushed together — a single failure rolls back the batch
        try:
            db_objs = []
            for obj_in in objs_in:
                db_obj = self.model(**self._serialize_create(obj_in))
                db.add(db_obj)
                db_objs.append(db_obj)
            db.flush()
            for db_obj in db_objs:
                db.refresh(db_obj)
                record_id = getattr(db_obj, self._primary_key)
                self._log_operation("create", self.model.__name__, record_id, user_id)
            return db_objs
        except IntegrityError as e:
            raise DuplicateError(f"{self.model.__name__.lower()}.bulk_duplicate") from e
        except SQLAlchemyError as e:
            logger.error("db error in create_multi: %s", e)
            raise DatabaseError("database_error") from e

    def update(
        self,
        db: Session,
        *,
        db_obj: ModelType,
        obj_in: Union[UpdateSchemaType, dict[str, Any]],
        user_id: Optional[UUID] = None,
    ) -> ModelType:
        # Only explicitly set fields are written (exclude_unset)
        try:
            if isinstance(obj_in, dict):
                update_data = obj_in
            elif isinstance(obj_in, HasUpdateDict):
                update_data = obj_in.update_dict(exclude_unset=True)
            else:
                update_data = obj_in.model_dump(exclude_unset=True)
            if not update_data:
                return db_obj
            for field, value in update_data.items():
                if not hasattr(db_obj, field):
                    raise DatabaseError(
                        f"update: field '{field}' not found on {self.model.__name__}"
                    )
                setattr(db_obj, field, value)
            db.add(db_obj)
            db.flush()
            db.refresh(db_obj)
            record_id = getattr(db_obj, self._primary_key)
            self._log_operation("update", self.model.__name__, record_id, user_id)
            return db_obj
        except IntegrityError as e:
            raise DuplicateError(
                f"{self.model.__name__.lower()}.update_conflict"
            ) from e
        except SQLAlchemyError as e:
            logger.error("db error in update: %s", e)
            raise DatabaseError("database_error") from e

    def update_by_id(
        self,
        db: Session,
        *,
        id: Any,
        obj_in: Union[UpdateSchemaType, dict[str, Any]],
        user_id: Optional[UUID] = None,
    ) -> Optional[ModelType]:
        db_obj = self.get(db, id)
        if not db_obj:
            return None
        return self.update(db, db_obj=db_obj, obj_in=obj_in, user_id=user_id)

    def remove(
        self,
        db: Session,
        *,
        id: Any,
        user_id: Optional[UUID] = None,
    ) -> Optional[ModelType]:
        # Soft-deletes if the model has is_active; hard-deletes otherwise
        try:
            obj = self.get(db, id)
            if not obj:
                return None
            if hasattr(obj, "is_active"):
                obj.is_active = False
                db.add(obj)
                delete_type = "soft_delete"
            else:
                db.delete(obj)
                delete_type = "hard_delete"
            db.flush()
            self._log_operation(delete_type, self.model.__name__, id, user_id)
            return obj
        except SQLAlchemyError as e:
            logger.error("db error in remove: %s", e)
            raise DatabaseError("database_error") from e

    def force_delete(
        self,
        db: Session,
        *,
        id: Any,
        user_id: Optional[UUID] = None,
    ) -> Optional[ModelType]:
        try:
            obj = self.get(db, id)
            if not obj:
                return None
            db.delete(obj)
            db.flush()
            self._log_operation("hard_delete", self.model.__name__, id, user_id)
            return obj
        except SQLAlchemyError as e:
            logger.error("db error in force_delete: %s", e)
            raise DatabaseError("database_error") from e

    def remove_multi(
        self,
        db: Session,
        *,
        ids: list[Any],
        user_id: Optional[UUID] = None,
    ) -> int:
        # Bulk UPDATE/DELETE with IN clause — avoids loading each record
        try:
            pk_column = getattr(self.model, self._primary_key)
            if hasattr(self.model, "is_active"):
                result = db.execute(
                    update(self.model)
                    .where(pk_column.in_(ids))
                    .values(is_active=False)
                    .execution_options(synchronize_session=False)
                )
                db.flush()
                for id in ids:
                    self._log_operation("soft_delete", self.model.__name__, id, user_id)
                return result.rowcount
            else:
                result = db.execute(
                    delete(self.model)
                    .where(pk_column.in_(ids))
                    .execution_options(synchronize_session=False)
                )
                db.flush()
                for id in ids:
                    self._log_operation("hard_delete", self.model.__name__, id, user_id)
                return result.rowcount
        except SQLAlchemyError as e:
            logger.error("db error in remove_multi: %s", e)
            raise DatabaseError("database_error") from e
