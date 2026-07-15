import logging
from typing import Any, NamedTuple, Optional, Tuple, Type, Union
from uuid import UUID

from sqlalchemy import Select, delete, func, literal, select, union_all, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.exceptions import DatabaseError, SettlementError
from app.models.enums import PlatformType
from app.models.settlement import SettlementBolt, SettlementFreeNow, SettlementUber

logger = logging.getLogger(__name__)

_AnySettlement = Union[SettlementUber, SettlementBolt, SettlementFreeNow]
_SettlementModel = Type[_AnySettlement]


class _PlatformEntry(NamedTuple):
    model: _SettlementModel
    amount_col: InstrumentedAttribute


PLATFORM_SETTLEMENT_MAP: dict[PlatformType, _PlatformEntry] = {
    PlatformType.UBER: _PlatformEntry(SettlementUber, SettlementUber.payout_total),
    PlatformType.BOLT: _PlatformEntry(SettlementBolt, SettlementBolt.net_earnings),
    PlatformType.FREENOW: _PlatformEntry(
        SettlementFreeNow, SettlementFreeNow.receivable_amount
    ),
}


class SettlementRepository:
    def _build_platform_subquery(
        self,
        model: _SettlementModel,
        amount_col: InstrumentedAttribute,
        pt: PlatformType,
        driver_id: Optional[UUID],
        year: Optional[int],
        week: Optional[int],
        is_processed: Optional[bool],
    ) -> Select:
        q = select(
            model.id,
            model.driver_id,
            literal(pt.value).label("platform"),
            model.week_number,
            model.year,
            model.start_date,
            model.end_date,
            amount_col.label("net_amount"),
            model.is_processed,
            model.created_at,
        )
        if driver_id is not None:
            q = q.where(model.driver_id == driver_id)
        if year is not None:
            q = q.where(model.year == year)
        if week is not None:
            q = q.where(model.week_number == week)
        if is_processed is not None:
            q = q.where(model.is_processed == is_processed)
        return q

    def _mark_processed(
        self,
        db: Session,
        model: _SettlementModel,
        driver_id: UUID,
        year: int,
        week: int,
        payout_id: UUID,
    ) -> int:
        # Bulk UPDATE — already-processed records are skipped via is_processed filter
        result = db.execute(
            update(model)
            .where(
                model.driver_id == driver_id,
                model.year == year,
                model.week_number == week,
                model.is_processed.is_(False),
            )
            .values(is_processed=True, weekly_payout_id=payout_id)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount

    def get_unprocessed(
        self,
        db: Session,
        model: _SettlementModel,
        driver_id: UUID,
        year: int,
        week: int,
    ) -> list[_AnySettlement]:
        try:
            stmt = select(model).where(
                model.driver_id == driver_id,
                model.year == year,

    # ... (get_all_for_payout_period, mark_processed_for_payout follow the same pattern)
