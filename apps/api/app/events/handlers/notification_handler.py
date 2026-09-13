"""Notification handler subscribing to all domain events.

Bridges business events across modules (booking, payment, admin, chat, jobs)
to the notification service, creating in-app notifications and queueing deferred emails.
"""

from sqlalchemy.orm import Session

from app.events.dispatcher import subscribe
from app.events.registry import (
    AdminPasswordResetRequestedEvent,
    AdvancePaymentConfirmedEvent,
    BalanceOverdueFlaggedEvent,
    BalancePaidEvent,
    BookingAcceptedEvent,
    BookingCancelledEvent,
    BookingCompletedEvent,
    BookingDeadlineExtendedEvent,
    BookingHoldExpiredEvent,
    BookingRejectedEvent,
    BookingRequestedEvent,
    BookingRequestExpiredEvent,
    ChatMessageOfflineEvent,
    ConflictCancelledEvent,
    PaymentReminderEvent,
    RefundIssuedEvent,
    UserReactivatedEvent,
    UserSuspendedEvent,
    VenueApprovedEvent,
    VenueReactivatedEvent,
    VenueRejectedEvent,
    VenueSuspendedEvent,
)
from app.modules.notification import service as notifications
from app.modules.notification.types import NotificationType

# ---------------------------------------------------------------------------
# Booking Events
# ---------------------------------------------------------------------------


@subscribe(BookingRequestedEvent)
def on_booking_requested(event: BookingRequestedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.owner_id,
        NotificationType.NEW_REQUEST_OWNER,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )
    notifications.notify(
        db,
        event.user_id,
        NotificationType.REQUEST_RECEIVED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )


@subscribe(BookingAcceptedEvent)
def on_booking_accepted(event: BookingAcceptedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.REQUEST_ACCEPTED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )


@subscribe(BookingRejectedEvent)
def on_booking_rejected(event: BookingRejectedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.BOOKING_REJECTED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )


@subscribe(BookingDeadlineExtendedEvent)
def on_booking_deadline_extended(event: BookingDeadlineExtendedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.BALANCE_DEADLINE_EXTENDED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )


@subscribe(BookingCancelledEvent)
def on_booking_cancelled(event: BookingCancelledEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.recipient_id,
        NotificationType.BOOKING_CANCELED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )


@subscribe(BookingRequestExpiredEvent)
def on_booking_request_expired(event: BookingRequestExpiredEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.REQUEST_EXPIRED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )


@subscribe(BookingHoldExpiredEvent)
def on_booking_hold_expired(event: BookingHoldExpiredEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.HOLD_EXPIRED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )


@subscribe(BookingCompletedEvent)
def on_booking_completed(event: BookingCompletedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.BOOKING_COMPLETED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )


# ---------------------------------------------------------------------------
# Payment Events
# ---------------------------------------------------------------------------


@subscribe(AdvancePaymentConfirmedEvent)
def on_advance_payment_confirmed(event: AdvancePaymentConfirmedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.PAYMENT_CONFIRMED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
        skip_email=True,
    )
    if event.owner_id:
        notifications.notify(
            db,
            event.owner_id,
            NotificationType.PAYMENT_CONFIRMED,
            context={"venue_name": event.venue_name},
            booking_id=event.booking_id,
        )


@subscribe(BalancePaidEvent)
def on_balance_paid(event: BalancePaidEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.BALANCE_PAID,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
        skip_email=True,
    )
    if event.owner_id:
        notifications.notify(
            db,
            event.owner_id,
            NotificationType.BALANCE_PAID,
            context={"venue_name": event.venue_name},
            booking_id=event.booking_id,
        )


@subscribe(PaymentReminderEvent)
def on_payment_reminder(event: PaymentReminderEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.PAYMENT_REMINDER,
        context={"venue_name": event.venue_name, "hours_left": event.hours_left},
        booking_id=event.booking_id,
    )


@subscribe(BalanceOverdueFlaggedEvent)
def on_balance_overdue_flagged(event: BalanceOverdueFlaggedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.BALANCE_OVERDUE,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )
    if event.owner_id:
        notifications.notify(
            db,
            event.owner_id,
            NotificationType.BALANCE_OVERDUE,
            context={"venue_name": event.venue_name},
            booking_id=event.booking_id,
        )


@subscribe(RefundIssuedEvent)
def on_refund_issued(event: RefundIssuedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.REFUND_ISSUED,
        context={"venue_name": event.venue_name, "amount_rupees": event.amount_rupees},
        booking_id=event.booking_id,
    )


@subscribe(ConflictCancelledEvent)
def on_conflict_cancelled(event: ConflictCancelledEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.CONFLICT_CANCELED,
        context={"venue_name": event.venue_name},
        booking_id=event.booking_id,
    )


# ---------------------------------------------------------------------------
# Admin Venue Events
# ---------------------------------------------------------------------------


@subscribe(VenueApprovedEvent)
def on_venue_approved(event: VenueApprovedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.owner_id,
        NotificationType.VENUE_APPROVED,
        context={"venue_name": event.venue_name},
    )


@subscribe(VenueRejectedEvent)
def on_venue_rejected(event: VenueRejectedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.owner_id,
        NotificationType.VENUE_REJECTED,
        context={"venue_name": event.venue_name, "reason": event.reason or "No reason provided."},
    )


@subscribe(VenueSuspendedEvent)
def on_venue_suspended(event: VenueSuspendedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.owner_id,
        NotificationType.VENUE_SUSPENDED,
        context={"venue_name": event.venue_name, "reason": event.reason},
    )


@subscribe(VenueReactivatedEvent)
def on_venue_reactivated(event: VenueReactivatedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.owner_id,
        NotificationType.VENUE_REACTIVATED,
        context={"venue_name": event.venue_name},
    )


# ---------------------------------------------------------------------------
# Admin User & Auth Events
# ---------------------------------------------------------------------------


@subscribe(UserSuspendedEvent)
def on_user_suspended(event: UserSuspendedEvent, db: Session) -> None:
    notifications.notify(
        db,
        event.user_id,
        NotificationType.USER_SUSPENDED,
        context={"reason": event.reason},
    )


@subscribe(UserReactivatedEvent)
def on_user_reactivated(event: UserReactivatedEvent, db: Session) -> None:
    notifications.notify(db, event.user_id, NotificationType.USER_REACTIVATED)


@subscribe(AdminPasswordResetRequestedEvent)
def on_admin_password_reset_requested(
    event: AdminPasswordResetRequestedEvent, db: Session
) -> None:
    notifications.notify(
        db,
        event.admin_user_id,
        NotificationType.ADMIN_PASSWORD_RESET_REQUESTED,
        context={"target_email": event.target_email},
    )


# ---------------------------------------------------------------------------
# Chat Events
# ---------------------------------------------------------------------------


@subscribe(ChatMessageOfflineEvent)
def on_chat_message_offline(event: ChatMessageOfflineEvent, db: Session) -> None:
    context = {
        "recipient_id": str(event.recipient_id),
        **event.booking_context,
    }
    notifications.notify(
        db,
        user_id=event.recipient_id,
        type="chat_message",
        context=context,
        booking_id=event.booking_id,
    )
