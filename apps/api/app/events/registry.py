"""Typed domain event models for Venue404.

All domain events inherit from DomainEvent and represent state transitions or
notable occurrences across business domains (booking, payment, admin, chat, jobs).
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    """Base class for all domain events in the system."""

    event_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Booking Events
# ---------------------------------------------------------------------------


class BookingRequestedEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    owner_id: UUID
    venue_id: UUID
    venue_name: str


class BookingAcceptedEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    owner_id: UUID
    venue_id: UUID
    venue_name: str


class BookingRejectedEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    owner_id: UUID
    venue_id: UUID
    venue_name: str
    reason: str = ""


class BookingCancelledEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    recipient_id: UUID
    venue_name: str
    reason: str | None = None
    cancelled_by: UUID | None = None


class BookingDeadlineExtendedEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_id: UUID
    venue_name: str
    new_due_date: date


class BookingRequestExpiredEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_name: str


class BookingHoldExpiredEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_name: str


class BookingCompletedEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_name: str


# ---------------------------------------------------------------------------
# Payment Events
# ---------------------------------------------------------------------------


class AdvancePaymentConfirmedEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_id: UUID
    venue_name: str
    owner_id: UUID | None = None


class BalancePaidEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_id: UUID
    venue_name: str
    owner_id: UUID | None = None


class PaymentReminderEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_name: str
    hours_left: int


class BalanceOverdueFlaggedEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_name: str
    owner_id: UUID | None = None


class RefundIssuedEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_name: str
    amount_rupees: int


class ConflictCancelledEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
    venue_name: str


# ---------------------------------------------------------------------------
# Admin Venue Events
# ---------------------------------------------------------------------------


class VenueApprovedEvent(DomainEvent):
    venue_id: UUID
    owner_id: UUID
    venue_name: str


class VenueRejectedEvent(DomainEvent):
    venue_id: UUID
    owner_id: UUID
    venue_name: str
    reason: str = ""


class VenueSuspendedEvent(DomainEvent):
    venue_id: UUID
    owner_id: UUID
    venue_name: str
    reason: str = ""


class VenueReactivatedEvent(DomainEvent):
    venue_id: UUID
    owner_id: UUID
    venue_name: str


# ---------------------------------------------------------------------------
# Admin User & Auth Events
# ---------------------------------------------------------------------------


class UserSuspendedEvent(DomainEvent):
    user_id: UUID
    reason: str = ""


class UserReactivatedEvent(DomainEvent):
    user_id: UUID


class AdminPasswordResetRequestedEvent(DomainEvent):
    target_email: str
    admin_user_id: UUID


# ---------------------------------------------------------------------------
# Chat Events
# ---------------------------------------------------------------------------


class ChatMessageOfflineEvent(DomainEvent):
    booking_id: UUID
    recipient_id: UUID
    booking_context: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Search and Behavioral Events
# ---------------------------------------------------------------------------


class SearchExecutedEvent(DomainEvent):
    query: str = ""
    city: str = ""
    venue_type: str | None = None
    result_count: int = 0
    user_id: UUID | None = None


class VenueViewedEvent(DomainEvent):
    venue_id: UUID
    user_id: UUID | None = None
    owner_id: UUID | None = None
    venue_name: str = ""


# ---------------------------------------------------------------------------
# Behavioral & Engagement Events
# ---------------------------------------------------------------------------


class WishlistToggledEvent(DomainEvent):
    venue_id: UUID
    user_id: UUID
    action: str  # "add" or "remove"
    venue_name: str = ""


class ReviewSubmittedEvent(DomainEvent):
    venue_id: UUID
    user_id: UUID
    booking_id: UUID
    rating: int


class AvailabilityCheckedEvent(DomainEvent):
    venue_id: UUID
    user_id: UUID | None = None
    booking_date: str = ""
    booking_type: str = ""


class PricingPreviewedEvent(DomainEvent):
    venue_id: UUID
    user_id: UUID | None = None
    booking_type: str = ""


class BookingDetailViewedEvent(DomainEvent):
    booking_id: UUID
    user_id: UUID
