import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin


class AnalyticsEvent(Base):
    """Append-only raw domain & behavioral event store.

    CRITICAL: This table is strictly append-only (never updated, never deleted).
    It acts as the single write path event log for the CQRS analytics pipeline.
    """

    __tablename__ = "analytics_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )

    __table_args__ = (
        Index("ix_analytics_events_name_time", "event_name", "occurred_at"),
        Index("ix_analytics_events_venue_time", "venue_id", "occurred_at"),
    )


class DailyBookingStats(Base, TimestampMixin):
    """Materialized daily booking rollup table (CQRS Read side).

    venue_id IS NULL represents platform-wide stats.
    """

    __tablename__ = "daily_booking_stats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    total_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_bookings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_bookings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_bookings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    total_response_time_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    slot_hours_booked: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        Index(
            "uq_daily_booking_stats_date_venue",
            "date",
            text("COALESCE(venue_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )


class DailyRevenueStats(Base, TimestampMixin):
    """Materialized daily revenue rollup table (CQRS Read side).

    venue_id IS NULL represents platform-wide stats.
    Amounts are stored in paise (1 INR = 100 paise).
    """

    __tablename__ = "daily_revenue_stats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    gross_merchandise_value_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    platform_fee_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    owner_payout_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refunds_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index(
            "uq_daily_revenue_stats_date_venue",
            "date",
            text("COALESCE(venue_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )


class DailySearchStats(Base, TimestampMixin):
    """Materialized daily search & venue page view rollup table (CQRS Read side).

    venue_id IS NULL represents global search queries;
    populated venue_id represents venue detail page views.
    """

    __tablename__ = "daily_search_stats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    total_searches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_venue_views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_users: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index(
            "uq_daily_search_stats_date_venue",
            "date",
            text("COALESCE(venue_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )
