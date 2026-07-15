from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy import Enum as DBEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.encryption import EncryptedString
from app.core.exceptions import DomainValidationError
from app.db.base import Base, TimestampMixin
from app.models.enums import DriverStatus

if TYPE_CHECKING:
    from app.models.car_assignment import CarAssignment
    from app.models.contract import Contract
    from app.models.driver_document import DriverDocument
    from app.models.fee_adjustment import FeeAdjustment
    from app.models.invoice import Invoice
    from app.models.odometer_entry import OdometerEntry
    from app.models.payout import WeeklyPayout
    from app.models.platform_account import PlatformAccount
    from app.models.recurring_fee import RecurringFee
    from app.models.settlement import (
        SettlementBolt,
        SettlementFreeNow,
        SettlementUber,
    )
    from app.models.user import User


class Driver(Base, TimestampMixin):
    """
    Represents a driver in the fleet management system.

    A Driver is always linked to a User account (1-to-1). It extends the user
    with driver-specific data: personal info, status, documents, platform
    accounts, assignments, settlements, invoices, payouts and fees.

    Attributes:
        user_id: PK and FK to users.id — driver shares identity with user.
        first_name: Driver's first name, title-cased on write.
        last_name: Driver's last name, title-cased on write.
        status: Current lifecycle status (PENDING, ACTIVE, INACTIVE, etc.).
        user: Resolved User object for authentication and contact data.
        documents: All documents uploaded by this driver.
        platform_accounts: Uber/Bolt/FreeNow account links.
        invoices: All invoices issued for this driver.
        settlements_bolt: Bolt platform settlement records.
        settlements_uber: Uber platform settlement records.
        settlements_freenow: FreeNow platform settlement records.
        weekly_payouts: Weekly payout records for this driver.
        car_assignments: All vehicle assignments, active and historical.
        fee_adjustments: Manual fee corrections applied to this driver.
        recurring_fees: Recurring charges configured for this driver.
        odometer_entries: Daily odometer readings logged by this driver.
    """

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        doc=(
            "PK and FK to users.id. Driver identity is shared with User — "
            "deleting a user removes the driver profile."
        ),
    )

    first_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Driver's first name. Title-cased on write, min 2 chars.",
    )

    last_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Driver's last name. Title-cased on write, min 2 chars.",
    )

    status: Mapped[DriverStatus] = mapped_column(
        DBEnum(
            DriverStatus,
            name="driver_status_enum",
            native_enum=True,
        ),
        default=DriverStatus.PENDING,
        nullable=False,
        index=True,
        doc="Driver lifecycle status. Defaults to PENDING on registration.",
    )

    status_reason: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="Reason for the last status change (suspend/block). Cleared on activate.",
    )

    phone_number: Mapped[Optional[str]] = mapped_column(
        String(15),
        nullable=True,
        doc="Driver's contact phone number.",
    )

    iban: Mapped[Optional[str]] = mapped_column(
        EncryptedString(),
        nullable=True,
        doc="Driver's IBAN for payouts. Stored encrypted at rest. Set by admin only.",
    )

    address: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Driver's street address.",
    )

    city: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="Driver's city of residence.",
    )

    postal_code: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        doc="Driver's postal code in Polish format (DD-DDD).",
    )

    has_own_car: Mapped[Optional[bool]] = mapped_column(
        nullable=True,
        doc="Whether the driver owns their own vehicle. Collected during registration.",
    )

    work_city: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="City where the driver wants to work. Selected from predefined list.",
    )

    is_student: Mapped[Optional[bool]] = mapped_column(
        nullable=True,
        doc="Whether the driver is a student under 26. Collected during registration.",
    )

    is_employed: Mapped[Optional[bool]] = mapped_column(
        nullable=True,
        doc=(
            "Whether the driver is employed elsewhere. "
            "Only relevant when is_student is False."
        ),
    )

    user: Mapped[User] = relationship(
        "User",
        back_populates="driver",
        lazy="selectin",
        doc=(
            "Resolved User object. Loaded automatically via SELECT IN. "
            "Provides access to phone_number, email, and auth data."
        ),
    )

    # ... (remaining relationships: invoices, settlements, payouts, car
    # assignments, fee adjustments, recurring fees, odometer entries — same pattern)
