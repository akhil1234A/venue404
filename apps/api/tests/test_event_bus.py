"""Unit tests for the in-process event bus and notification handlers."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.events.dispatcher import emit, emit_after_commit, subscribe
from app.events.handlers import notification_handler  # noqa: F401
from app.events.registry import (
    AdminPasswordResetRequestedEvent,
    AdvancePaymentConfirmedEvent,
    BalanceOverdueFlaggedEvent,
    BalancePaidEvent,
    BookingAcceptedEvent,
    BookingCancelledEvent,
    BookingCompletedEvent,
    BookingHoldExpiredEvent,
    BookingRejectedEvent,
    BookingRequestedEvent,
    BookingRequestExpiredEvent,
    ChatMessageOfflineEvent,
    ConflictCancelledEvent,
    DomainEvent,
    PaymentReminderEvent,
    RefundIssuedEvent,
    UserReactivatedEvent,
    UserSuspendedEvent,
    VenueApprovedEvent,
    VenueReactivatedEvent,
    VenueRejectedEvent,
    VenueSuspendedEvent,
)
from app.modules.notification.types import NotificationType


class CustomTestEvent(DomainEvent):
    message: str


def test_subscribe_and_emit():
    mock_handler = MagicMock()
    mock_db = MagicMock()

    @subscribe(CustomTestEvent)
    def handle_test(event: CustomTestEvent, db):
        mock_handler(event.message, db)

    event = CustomTestEvent(message="hello event bus")
    emit(event, mock_db)

    mock_handler.assert_called_once_with("hello event bus", mock_db)


def test_multiple_subscribers():
    results = []
    mock_db = MagicMock()

    @subscribe(CustomTestEvent)
    def handler_one(event: CustomTestEvent, db):
        results.append("one")

    @subscribe(CustomTestEvent)
    def handler_two(event: CustomTestEvent, db):
        results.append("two")

    emit(CustomTestEvent(message="test"), mock_db)

    assert "one" in results
    assert "two" in results


def test_exception_isolation():
    mock_db = MagicMock()
    results = []

    @subscribe(CustomTestEvent)
    def failing_handler(event: CustomTestEvent, db):
        raise RuntimeError("Something failed in handler")

    @subscribe(CustomTestEvent)
    def succeeding_handler(event: CustomTestEvent, db):
        results.append("succeeded")

    # Should not raise exception
    emit(CustomTestEvent(message="test"), mock_db)

    assert results == ["succeeded"]


def test_polymorphic_subscription():
    received = []
    mock_db = MagicMock()

    @subscribe(DomainEvent)
    def catch_all(event: DomainEvent, db):
        received.append(event.event_id)

    event = CustomTestEvent(message="polymorphic test")
    emit(event, mock_db)

    assert received == [event.event_id]


def test_emit_after_commit_queuing():
    mock_db = MagicMock()
    mock_db.info = {}

    event = CustomTestEvent(message="after commit test")
    emit_after_commit(mock_db, event)

    assert "_pending_domain_events" in mock_db.info
    assert mock_db.info["_pending_domain_events"] == [event]


@patch("app.modules.notification.service.notify")
def test_notification_handler_booking_requested(mock_notify):
    mock_db = MagicMock()
    user_id = uuid4()
    owner_id = uuid4()
    booking_id = uuid4()
    venue_id = uuid4()

    event = BookingRequestedEvent(
        booking_id=booking_id,
        user_id=user_id,
        owner_id=owner_id,
        venue_id=venue_id,
        venue_name="Grand Ballroom",
    )
    emit(event, mock_db)

    assert mock_notify.call_count == 2
    mock_notify.assert_any_call(
        mock_db,
        owner_id,
        NotificationType.NEW_REQUEST_OWNER,
        context={"venue_name": "Grand Ballroom"},
        booking_id=booking_id,
    )
    mock_notify.assert_any_call(
        mock_db,
        user_id,
        NotificationType.REQUEST_RECEIVED,
        context={"venue_name": "Grand Ballroom"},
        booking_id=booking_id,
    )


@patch("app.modules.notification.service.notify")
def test_notification_handler_booking_accepted(mock_notify):
    mock_db = MagicMock()
    user_id = uuid4()
    booking_id = uuid4()

    event = BookingAcceptedEvent(
        booking_id=booking_id,
        user_id=user_id,
        owner_id=uuid4(),
        venue_id=uuid4(),
        venue_name="Sunset Palace",
    )
    emit(event, mock_db)

    mock_notify.assert_called_once_with(
        mock_db,
        user_id,
        NotificationType.REQUEST_ACCEPTED,
        context={"venue_name": "Sunset Palace"},
        booking_id=booking_id,
    )


@patch("app.modules.notification.service.notify")
def test_notification_handler_booking_rejected(mock_notify):
    mock_db = MagicMock()
    user_id = uuid4()
    booking_id = uuid4()

    event = BookingRejectedEvent(
        booking_id=booking_id,
        user_id=user_id,
        owner_id=uuid4(),
        venue_id=uuid4(),
        venue_name="Sunset Palace",
        reason="Fully booked",
    )
    emit(event, mock_db)

    mock_notify.assert_called_once_with(
        mock_db,
        user_id,
        NotificationType.BOOKING_REJECTED,
        context={"venue_name": "Sunset Palace"},
        booking_id=booking_id,
    )


@patch("app.modules.notification.service.notify")
def test_notification_handler_booking_cancelled(mock_notify):
    mock_db = MagicMock()
    recipient_id = uuid4()
    booking_id = uuid4()

    event = BookingCancelledEvent(
        booking_id=booking_id,
        user_id=uuid4(),
        recipient_id=recipient_id,
        venue_name="Palace View",
    )
    emit(event, mock_db)

    mock_notify.assert_called_once_with(
        mock_db,
        recipient_id,
        NotificationType.BOOKING_CANCELED,
        context={"venue_name": "Palace View"},
        booking_id=booking_id,
    )


@patch("app.modules.notification.service.notify")
def test_notification_handler_payment_events(mock_notify):
    mock_db = MagicMock()
    user_id = uuid4()
    owner_id = uuid4()
    booking_id = uuid4()

    # Advance payment confirmed
    advance_event = AdvancePaymentConfirmedEvent(
        booking_id=booking_id,
        user_id=user_id,
        venue_id=uuid4(),
        venue_name="Garden Hall",
        owner_id=owner_id,
    )
    emit(advance_event, mock_db)

    mock_notify.assert_any_call(
        mock_db,
        user_id,
        NotificationType.PAYMENT_CONFIRMED,
        context={"venue_name": "Garden Hall"},
        booking_id=booking_id,
        skip_email=True,
    )
    mock_notify.assert_any_call(
        mock_db,
        owner_id,
        NotificationType.PAYMENT_CONFIRMED,
        context={"venue_name": "Garden Hall"},
        booking_id=booking_id,
    )

    mock_notify.reset_mock()

    # Balance paid
    balance_event = BalancePaidEvent(
        booking_id=booking_id,
        user_id=user_id,
        venue_id=uuid4(),
        venue_name="Garden Hall",
        owner_id=owner_id,
    )
    emit(balance_event, mock_db)

    mock_notify.assert_any_call(
        mock_db,
        user_id,
        NotificationType.BALANCE_PAID,
        context={"venue_name": "Garden Hall"},
        booking_id=booking_id,
        skip_email=True,
    )
    mock_notify.assert_any_call(
        mock_db,
        owner_id,
        NotificationType.BALANCE_PAID,
        context={"venue_name": "Garden Hall"},
        booking_id=booking_id,
    )

    mock_notify.reset_mock()

    # Refund issued
    refund_event = RefundIssuedEvent(
        booking_id=booking_id,
        user_id=user_id,
        venue_name="Garden Hall",
        amount_rupees=2500,
    )
    emit(refund_event, mock_db)
    mock_notify.assert_called_once_with(
        mock_db,
        user_id,
        NotificationType.REFUND_ISSUED,
        context={"venue_name": "Garden Hall", "amount_rupees": 2500},
        booking_id=booking_id,
    )

    mock_notify.reset_mock()

    # Conflict cancelled
    conflict_event = ConflictCancelledEvent(
        booking_id=booking_id,
        user_id=user_id,
        venue_name="Garden Hall",
    )
    emit(conflict_event, mock_db)
    mock_notify.assert_called_once_with(
        mock_db,
        user_id,
        NotificationType.CONFLICT_CANCELED,
        context={"venue_name": "Garden Hall"},
        booking_id=booking_id,
    )


@patch("app.modules.notification.service.notify")
def test_notification_handler_admin_and_auth_events(mock_notify):
    mock_db = MagicMock()
    owner_id = uuid4()
    user_id = uuid4()
    venue_id = uuid4()

    emit(VenueApprovedEvent(venue_id=venue_id, owner_id=owner_id, venue_name="V1"), mock_db)
    mock_notify.assert_called_with(
        mock_db,
        owner_id,
        NotificationType.VENUE_APPROVED,
        context={"venue_name": "V1"},
    )

    emit(
        VenueRejectedEvent(
            venue_id=venue_id, owner_id=owner_id, venue_name="V1", reason="Incomplete"
        ),
        mock_db,
    )
    mock_notify.assert_called_with(
        mock_db,
        owner_id,
        NotificationType.VENUE_REJECTED,
        context={"venue_name": "V1", "reason": "Incomplete"},
    )

    emit(
        VenueSuspendedEvent(
            venue_id=venue_id, owner_id=owner_id, venue_name="V1", reason="Violation"
        ),
        mock_db,
    )
    mock_notify.assert_called_with(
        mock_db,
        owner_id,
        NotificationType.VENUE_SUSPENDED,
        context={"venue_name": "V1", "reason": "Violation"},
    )

    emit(VenueReactivatedEvent(venue_id=venue_id, owner_id=owner_id, venue_name="V1"), mock_db)
    mock_notify.assert_called_with(
        mock_db,
        owner_id,
        NotificationType.VENUE_REACTIVATED,
        context={"venue_name": "V1"},
    )

    emit(UserSuspendedEvent(user_id=user_id, reason="Spam"), mock_db)
    mock_notify.assert_called_with(
        mock_db,
        user_id,
        NotificationType.USER_SUSPENDED,
        context={"reason": "Spam"},
    )

    emit(UserReactivatedEvent(user_id=user_id), mock_db)
    mock_notify.assert_called_with(mock_db, user_id, NotificationType.USER_REACTIVATED)

    admin_id = uuid4()
    emit(
        AdminPasswordResetRequestedEvent(target_email="admin@test.com", admin_user_id=admin_id),
        mock_db,
    )
    mock_notify.assert_called_with(
        mock_db,
        admin_id,
        NotificationType.ADMIN_PASSWORD_RESET_REQUESTED,
        context={"target_email": "admin@test.com"},
    )


@patch("app.modules.notification.service.notify")
def test_notification_handler_chat_and_jobs(mock_notify):
    mock_db = MagicMock()
    user_id = uuid4()
    owner_id = uuid4()
    booking_id = uuid4()

    # Chat offline
    emit(
        ChatMessageOfflineEvent(
            booking_id=booking_id,
            recipient_id=user_id,
            booking_context={"venue_name": "V1"},
        ),
        mock_db,
    )
    mock_notify.assert_called_with(
        mock_db,
        user_id=user_id,
        type="chat_message",
        context={"recipient_id": str(user_id), "venue_name": "V1"},
        booking_id=booking_id,
    )

    # Stale request expired
    emit(
        BookingRequestExpiredEvent(booking_id=booking_id, user_id=user_id, venue_name="V1"), mock_db
    )
    mock_notify.assert_called_with(
        mock_db,
        user_id,
        NotificationType.REQUEST_EXPIRED,
        context={"venue_name": "V1"},
        booking_id=booking_id,
    )

    # Payment reminder
    emit(
        PaymentReminderEvent(booking_id=booking_id, user_id=user_id, venue_name="V1", hours_left=6),
        mock_db,
    )
    mock_notify.assert_called_with(
        mock_db,
        user_id,
        NotificationType.PAYMENT_REMINDER,
        context={"venue_name": "V1", "hours_left": 6},
        booking_id=booking_id,
    )

    # Hold expired
    emit(BookingHoldExpiredEvent(booking_id=booking_id, user_id=user_id, venue_name="V1"), mock_db)
    mock_notify.assert_called_with(
        mock_db,
        user_id,
        NotificationType.HOLD_EXPIRED,
        context={"venue_name": "V1"},
        booking_id=booking_id,
    )

    # Booking completed
    emit(BookingCompletedEvent(booking_id=booking_id, user_id=user_id, venue_name="V1"), mock_db)
    mock_notify.assert_called_with(
        mock_db,
        user_id,
        NotificationType.BOOKING_COMPLETED,
        context={"venue_name": "V1"},
        booking_id=booking_id,
    )

    # Balance overdue flagged
    mock_notify.reset_mock()
    emit(
        BalanceOverdueFlaggedEvent(
            booking_id=booking_id,
            user_id=user_id,
            venue_name="V1",
            owner_id=owner_id,
        ),
        mock_db,
    )
    mock_notify.assert_any_call(
        mock_db,
        user_id,
        NotificationType.BALANCE_OVERDUE,
        context={"venue_name": "V1"},
        booking_id=booking_id,
    )
    mock_notify.assert_any_call(
        mock_db,
        owner_id,
        NotificationType.BALANCE_OVERDUE,
        context={"venue_name": "V1"},
        booking_id=booking_id,
    )
