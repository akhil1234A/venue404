"""Analytics event handler subscribing to domain and behavioral events.

Captures all lifecycle and tracking events into the append-only `analytics_events` table.
Strictly append-only write path for CQRS architecture.
"""

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.events.dispatcher import subscribe
from app.events.registry import (
    AdvancePaymentConfirmedEvent,
    BalancePaidEvent,
    BookingAcceptedEvent,
    BookingCancelledEvent,
    BookingCompletedEvent,
    BookingRejectedEvent,
    BookingRequestedEvent,
    RefundIssuedEvent,
    SearchExecutedEvent,
    VenueViewedEvent,
)
from app.modules.analytics.models import AnalyticsEvent
from app.modules.booking.models import Booking

logger = logging.getLogger(__name__)


def _record_event(
    db: Session,
    event_name: str,
    event_id: UUID | None = None,
    user_id: UUID | None = None,
    venue_id: UUID | None = None,
    booking_id: UUID | None = None,
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> AnalyticsEvent:
    """Helper to append an event into analytics_events."""
    row = AnalyticsEvent(
        event_name=event_name,
        event_id=event_id,
        user_id=user_id,
        venue_id=venue_id,
        booking_id=booking_id,
        payload=payload or {},
        occurred_at=occurred_at or datetime.now(),
    )
    db.add(row)
    db.flush()
    try:
        # Commit event write immediately so read-only HTTP GET endpoints (e.g. search, venue view)
        # do not discard analytics telemetry on session rollback at request teardown.
        db.commit()
    except Exception:
        pass
    return row


@subscribe(BookingRequestedEvent)
def on_booking_requested(event: BookingRequestedEvent, db: Session) -> None:
    _record_event(
        db,
        event_name="booking.requested",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=event.venue_id,
        booking_id=event.booking_id,
        payload={
            "venue_name": event.venue_name,
            "owner_id": str(event.owner_id),
        },
        occurred_at=event.occurred_at,
    )


@subscribe(BookingAcceptedEvent)
def on_booking_accepted(event: BookingAcceptedEvent, db: Session) -> None:
    response_time_seconds = None
    try:
        booking = db.query(Booking).filter(Booking.id == event.booking_id).first()
        if booking and booking.created_at:
            created_at_dt = booking.created_at
            if created_at_dt.tzinfo is None and event.occurred_at.tzinfo is not None:
                created_at_dt = created_at_dt.replace(tzinfo=event.occurred_at.tzinfo)
            diff = (event.occurred_at - created_at_dt).total_seconds()
            response_time_seconds = max(0, int(diff))
    except Exception:
        logger.warning(
            "Could not calculate response time for accepted booking %s", event.booking_id
        )

    payload = {
        "venue_name": event.venue_name,
        "owner_id": str(event.owner_id),
    }
    if response_time_seconds is not None:
        payload["response_time_seconds"] = response_time_seconds

    _record_event(
        db,
        event_name="booking.accepted",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=event.venue_id,
        booking_id=event.booking_id,
        payload=payload,
        occurred_at=event.occurred_at,
    )


@subscribe(BookingRejectedEvent)
def on_booking_rejected(event: BookingRejectedEvent, db: Session) -> None:
    response_time_seconds = None
    try:
        booking = db.query(Booking).filter(Booking.id == event.booking_id).first()
        if booking and booking.created_at:
            created_at_dt = booking.created_at
            if created_at_dt.tzinfo is None and event.occurred_at.tzinfo is not None:
                created_at_dt = created_at_dt.replace(tzinfo=event.occurred_at.tzinfo)
            diff = (event.occurred_at - created_at_dt).total_seconds()
            response_time_seconds = max(0, int(diff))
    except Exception:
        logger.warning(
            "Could not calculate response time for rejected booking %s", event.booking_id
        )

    payload = {
        "venue_name": event.venue_name,
        "owner_id": str(event.owner_id),
        "reason": event.reason,
    }
    if response_time_seconds is not None:
        payload["response_time_seconds"] = response_time_seconds

    _record_event(
        db,
        event_name="booking.rejected",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=event.venue_id,
        booking_id=event.booking_id,
        payload=payload,
        occurred_at=event.occurred_at,
    )


@subscribe(BookingCancelledEvent)
def on_booking_cancelled(event: BookingCancelledEvent, db: Session) -> None:
    venue_id = None
    try:
        booking = db.query(Booking).filter(Booking.id == event.booking_id).first()
        if booking:
            venue_id = booking.venue_id
    except Exception:
        pass

    _record_event(
        db,
        event_name="booking.cancelled",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=venue_id,
        booking_id=event.booking_id,
        payload={
            "venue_name": event.venue_name,
            "reason": event.reason,
            "cancelled_by": str(event.cancelled_by) if event.cancelled_by else None,
        },
        occurred_at=event.occurred_at,
    )


@subscribe(BookingCompletedEvent)
def on_booking_completed(event: BookingCompletedEvent, db: Session) -> None:
    venue_id = None
    try:
        booking = db.query(Booking).filter(Booking.id == event.booking_id).first()
        if booking:
            venue_id = booking.venue_id
    except Exception:
        pass

    _record_event(
        db,
        event_name="booking.completed",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=venue_id,
        booking_id=event.booking_id,
        payload={
            "venue_name": event.venue_name,
        },
        occurred_at=event.occurred_at,
    )


@subscribe(AdvancePaymentConfirmedEvent)
def on_payment_confirmed(event: AdvancePaymentConfirmedEvent, db: Session) -> None:
    # Captures both confirmed booking and payment transaction
    gross_paise = 0
    platform_fee_paise = 0
    try:
        booking = db.query(Booking).filter(Booking.id == event.booking_id).first()
        if booking:
            gross_paise = getattr(booking, "quoted_price_paise", 0) or 0
            # Platform fee paide default to 10% (or standard take rate) if not in booking
            platform_fee_paise = int(gross_paise * 0.10)
    except Exception:
        pass

    _record_event(
        db,
        event_name="booking.confirmed",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=event.venue_id,
        booking_id=event.booking_id,
        payload={
            "venue_name": event.venue_name,
            "owner_id": str(event.owner_id) if event.owner_id else None,
            "gross_amount_paise": gross_paise,
            "platform_fee_paise": platform_fee_paise,
        },
        occurred_at=event.occurred_at,
    )


@subscribe(BalancePaidEvent)
def on_balance_paid(event: BalancePaidEvent, db: Session) -> None:
    _record_event(
        db,
        event_name="payment.balance_paid",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=event.venue_id,
        booking_id=event.booking_id,
        payload={
            "venue_name": event.venue_name,
            "owner_id": str(event.owner_id) if event.owner_id else None,
        },
        occurred_at=event.occurred_at,
    )


@subscribe(RefundIssuedEvent)
def on_refund_issued(event: RefundIssuedEvent, db: Session) -> None:
    venue_id = None
    try:
        booking = db.query(Booking).filter(Booking.id == event.booking_id).first()
        if booking:
            venue_id = booking.venue_id
    except Exception:
        pass

    _record_event(
        db,
        event_name="payment.refund",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=venue_id,
        booking_id=event.booking_id,
        payload={
            "amount_rupees": event.amount_rupees,
            "amount_paise": event.amount_rupees * 100,
            "venue_name": event.venue_name,
        },
        occurred_at=event.occurred_at,
    )


@subscribe(SearchExecutedEvent)
def on_search_executed(event: SearchExecutedEvent, db: Session) -> None:
    _record_event(
        db,
        event_name="search.executed",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=None,
        booking_id=None,
        payload={
            "query": event.query,
            "city": event.city,
            "venue_type": event.venue_type,
            "result_count": event.result_count,
        },
        occurred_at=event.occurred_at,
    )


@subscribe(VenueViewedEvent)
def on_venue_viewed(event: VenueViewedEvent, db: Session) -> None:
    _record_event(
        db,
        event_name="venue.viewed",
        event_id=event.event_id,
        user_id=event.user_id,
        venue_id=event.venue_id,
        booking_id=None,
        payload={
            "venue_name": event.venue_name,
            "owner_id": str(event.owner_id) if event.owner_id else None,
        },
        occurred_at=event.occurred_at,
    )
