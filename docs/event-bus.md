# In-Process Event-Driven Architecture (Event Bus)

**Status:** Shipped — verified against code, 2026-09-13

A lightweight, in-process, typed pub/sub event bus for the Venue404 FastAPI backend. Replaces tight cross-module couplings and direct notification calls with domain events.

---

## 1. Why: Motivation & Architectural Problems Solved

Before this implementation, modules across the backend had direct, hard dependencies on one another—most notably on `app.modules.notification.service.notify()`. Across **11 files in 6 modules and background jobs**, direct cross-module calls created several architectural problems:

### 1.1. Tight Coupling & Domain Boundary Erosion
Core business domains like **Payment** and **Booking** were forced to manage notification side-effects directly:
- `payment/service.py` had to know who gets notified, which email templates are sent, what parameters are required in context dictionaries, and whether emails should be skipped (`skip_email=True`).
- If notification requirements changed, engineers had to modify and risk breaking mission-critical financial transaction flows.

### 1.2. Circular Import Workarounds
Because `admin` and `auth` modules depended on `notification`, and `notification` depended on `profile` and `booking`, python circular dependencies emerged. This forced developers to write hacky inline imports inside function bodies:
```python
# Before: ugly workaround repeated across admin/service.py and auth/service.py
def suspend_venue(db: Session, ...):
    ...
    from app.modules.notification import service as notifications
    from app.modules.notification.types import NotificationType
    notifications.notify(...)
```

### 1.3. Violation of the Open/Closed Principle
Every time a new side effect was needed when an action occurred (e.g. auditing, CQRS analytics, re-indexing search, sending Webhooks), developers had to modify the originating service function.
With the Event Bus:
- The originating service only **announces what happened** (`emit(AdvancePaymentConfirmedEvent(...), db)`).
- Any number of listeners (notifications, analytics, search indexers) can react without modifying a single line of booking or payment code.

### 1.4. Fragile Error Boundaries
Direct function calls meant that if a downstream side-effect (e.g. preparing an email or creating a notification record) failed or threw an unhandled exception, it could bubble up and roll back the primary database transaction (such as a Stripe payment confirmation).

### 1.5. Lack of Type Safety
Direct calls relied on magic strings (e.g. `"payment_confirmed"`, `"hold_expired"`) and arbitrary `dict[str, Any]` contexts. Renaming an event or omitting a required context key went undetected until runtime.

---

## 2. What: Architecture & Core Mechanics

The event bus is implemented in `apps/api/app/events/` as a pure Python + Pydantic in-process pub/sub system with zero external service dependencies.

```
                    ┌──────────────────────────────┐
                    │       Domain Producer        │
                    │  (booking, payment, admin)   │
                    └──────────────┬───────────────┘
                                   │ emit(event, db)
                                   ▼
                    ┌──────────────────────────────┐
                    │          Event Bus           │
                    │   (app/events/dispatcher)    │
                    └──────┬───────────────┬───────┘
                           │               │
         isolated try/catch│               │isolated try/catch
                           ▼               ▼
            ┌────────────────────┐   ┌────────────────────┐
            │Notification Handler│   │ Analytics Handler  │
            │(in-app rows/email) │   │    (CQRS read DB)  │
            └────────────────────┘   └────────────────────┘
```

### 2.1. Core Components

| Component | Path | Responsibility |
|---|---|---|
| **Base & Registry** | [`app/events/registry.py`](../apps/api/app/events/registry.py) | Strongly typed Pydantic models for all system domain events, inheriting from `DomainEvent`. |
| **Dispatcher** | [`app/events/dispatcher.py`](../apps/api/app/events/dispatcher.py) | Handler registry (`_subscribers`), `@subscribe` decorator, and `emit` / `emit_after_commit` dispatchers. |
| **Public Exports** | [`app/events/__init__.py`](../apps/api/app/events/__init__.py) | Clean public interface (`emit`, `emit_after_commit`, `subscribe`, domain events). |
| **Handlers** | [`app/events/handlers/`](../apps/api/app/events/handlers/) | Subscriber packages (e.g. `notification_handler.py`, `analytics_handler.py`). |
| **App Startup** | [`app/main.py`](../apps/api/app/main.py) | Imports `app.events.handlers` during application lifespan to register subscribers. |

### 2.2. Base Domain Event

Every event inherits from `DomainEvent`, which automatically stamps each event with an immutable UUID and a UTC timestamp:

```python
class DomainEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

### 2.3. Two Emission Modes

The dispatcher provides two dispatch modes depending on whether side-effects belong inside the database transaction or after commit:

1. **`emit(event: DomainEvent, db: Session) -> None` (In-Transaction)**
   - Executes synchronously within the caller's active database transaction.
   - Ideal for handlers that write database rows that must commit or roll back together with the main business action (e.g., writing an `in_app_notifications` row or an append-only analytics event).
   - **Exception Isolation**: Every subscriber runs inside an isolated `try...except` block. A failure in one handler is logged to Sentry/logger and never aborts other subscribers or the caller's transaction.

2. **`emit_after_commit(db: Session, event: DomainEvent) -> None` (Post-Commit)**
   - Stashes events in `db.info["_pending_domain_events"]`.
   - Uses an SQLAlchemy `after_commit` listener on `SessionLocal`.
   - Fires only after the transaction has successfully committed to the database.
   - Ideal for third-party network I/O, webhooks, or asynchronous task enqueueing that should never run if the database rolls back.

### 2.4. Polymorphic Subscriptions
The dispatcher walks the event class's MRO (Method Resolution Order). A subscriber listening to `DomainEvent` will receive *all* emitted events in the application, making audit loggers and event monitors trivial to attach.

---

## 3. Before vs. After: Code Diff & Side-by-Side

### 3.1. Payment Confirmation (`payment/service.py`)

#### Before
```python
# Tightly coupled: Payment service decides who gets notified and email rules
venue_name = venue.name if venue else "your venue"
notifications.notify(
    db,
    booking.user_id,
    "payment_confirmed",
    context={"venue_name": venue_name},
    booking_id=booking.id,
    skip_email=True,
)
if venue:
    notifications.notify(
        db,
        venue.owner_id,
        "payment_confirmed",
        context={"venue_name": venue_name},
        booking_id=booking.id,
    )
```

#### After
```python
# Decoupled: Payment service simply states the business fact
venue_name = venue.name if venue else "your venue"
emit(
    AdvancePaymentConfirmedEvent(
        booking_id=booking.id,
        user_id=booking.user_id,
        venue_id=booking.venue_id,
        venue_name=venue_name,
        owner_id=venue.owner_id if venue else None,
    ),
    db,
)
```

The notification logic now lives completely in [`app/events/handlers/notification_handler.py`](../apps/api/app/events/handlers/notification_handler.py):
```python
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
```

---

### 3.2. Admin Action (`admin/service.py`)

#### Before
```python
# Had to use lazy inline imports to avoid circular import crashes
from app.modules.notification import service as notifications
from app.modules.notification.types import NotificationType

notifications.notify(
    db,
    venue.owner_id,
    NotificationType.VENUE_APPROVED,
    context={"venue_name": venue.name},
)
```

#### After
```python
# Clean, top-level imported domain event
emit(
    VenueApprovedEvent(
        venue_id=venue_id,
        owner_id=venue.owner_id,
        venue_name=venue.name,
    ),
    db,
)
```

---

## 4. Complete Domain Event Catalog

| Domain | Event Class | Key Payload Fields | Emitted When |
|---|---|---|---|
| **Booking** | `BookingRequestedEvent` | `booking_id`, `user_id`, `owner_id`, `venue_id`, `venue_name` | User submits a manual booking request or instant booking entry |
| **Booking** | `BookingAcceptedEvent` | `booking_id`, `user_id`, `owner_id`, `venue_id`, `venue_name` | Venue owner accepts a booking request |
| **Booking** | `BookingRejectedEvent` | `booking_id`, `user_id`, `owner_id`, `venue_id`, `venue_name`, `reason` | Venue owner rejects a booking request |
| **Booking** | `BookingCancelledEvent` | `booking_id`, `user_id`, `recipient_id`, `venue_name`, `cancelled_by`, `reason` | Booking cancelled by user, owner, or balance overdue autocancel job |
| **Booking** | `BookingDeadlineExtendedEvent` | `booking_id`, `user_id`, `venue_id`, `venue_name`, `new_due_date` | Owner extends overdue balance payment deadline |
| **Booking (Jobs)** | `BookingRequestExpiredEvent` | `booking_id`, `user_id`, `venue_name` | Stale booking request auto-expired by background job |
| **Booking (Jobs)** | `BookingHoldExpiredEvent` | `booking_id`, `user_id`, `venue_name` | Payment hold window (24h or 15m instant) expires without payment |
| **Booking (Jobs)** | `BookingCompletedEvent` | `booking_id`, `user_id`, `venue_name` | Event date passes for fully paid booking |
| **Payment** | `AdvancePaymentConfirmedEvent` | `booking_id`, `user_id`, `venue_id`, `venue_name`, `owner_id` | Stripe advance payment intent captured & slot confirmed |
| **Payment** | `BalancePaidEvent` | `booking_id`, `user_id`, `venue_id`, `venue_name`, `owner_id` | Remaining balance payment successfully captured |
| **Payment** | `PaymentReminderEvent` | `booking_id`, `user_id`, `venue_name`, `hours_left` | Job flags hold expiring within reminder window |
| **Payment** | `BalanceOverdueFlaggedEvent` | `booking_id`, `user_id`, `venue_name`, `owner_id` | Balance overdue job flags unpaid balance past due date |
| **Payment** | `RefundIssuedEvent` | `booking_id`, `user_id`, `venue_name`, `amount_rupees` | Stripe refund captured on cancellation |
| **Payment** | `ConflictCancelledEvent` | `booking_id`, `user_id`, `venue_name` | Losing competitor booking auto-cancelled and refunded |
| **Admin** | `VenueApprovedEvent` | `venue_id`, `owner_id`, `venue_name` | Super admin approves pending venue |
| **Admin** | `VenueRejectedEvent` | `venue_id`, `owner_id`, `venue_name`, `reason` | Super admin rejects pending venue |
| **Admin** | `VenueSuspendedEvent` | `venue_id`, `owner_id`, `venue_name`, `reason` | Admin suspends approved venue |
| **Admin** | `VenueReactivatedEvent` | `venue_id`, `owner_id`, `venue_name` | Admin reactivates suspended venue |
| **Admin** | `UserSuspendedEvent` | `user_id`, `reason` | Admin suspends user account |
| **Admin** | `UserReactivatedEvent` | `user_id` | Admin reactivates user account |
| **Auth** | `AdminPasswordResetRequestedEvent` | `target_email`, `admin_user_id` | Password reset requested for super admin account |
| **Chat** | `ChatMessageOfflineEvent` | `booking_id`, `recipient_id`, `booking_context` | Message sent to offline chat participant |
| **Behavioral** | `SearchExecutedEvent` | `query`, `city`, `venue_type`, `result_count`, `user_id` | User performs venue search |
| **Behavioral** | `VenueViewedEvent` | `venue_id`, `user_id`, `owner_id`, `venue_name` | User views venue detail page |
| **Behavioral** | `WishlistToggledEvent` | `venue_id`, `user_id`, `action`, `venue_name` | User adds or removes venue from saved/wishlist |
| **Behavioral** | `ReviewSubmittedEvent` | `venue_id`, `user_id`, `booking_id`, `rating` | Customer submits review and star rating for completed booking |
| **Behavioral** | `AvailabilityCheckedEvent` | `venue_id`, `user_id`, `booking_date`, `booking_type` | User inspects venue calendar availability |
| **Behavioral** | `PricingPreviewedEvent` | `venue_id`, `user_id`, `booking_type` | User previews dynamic pricing breakdown or quote |
| **Behavioral** | `BookingDetailViewedEvent` | `booking_id`, `user_id` | User or owner views booking details modal/page |

---

## 5. Developer Guide: How to Work With Events

### 5.1. How to Emit an Existing Event
Import `emit` and the event from `app.events`:
```python
from app.events import BookingCompletedEvent, emit

# Inside your service function:
emit(
    BookingCompletedEvent(
        booking_id=booking.id,
        user_id=booking.user_id,
        venue_name=venue.name,
    ),
    db,
)
```

### 5.2. How to Add a New Domain Event
1. Add the Pydantic model to [`app/events/registry.py`](../apps/api/app/events/registry.py):
   ```python
   class VenueReviewSubmittedEvent(DomainEvent):
       review_id: UUID
       venue_id: UUID
       user_id: UUID
       rating: int
   ```
2. Re-export it in [`app/events/__init__.py`](../apps/api/app/events/__init__.py).

### 5.3. How to Create a New Listener / Handler
1. Decorate a function with `@subscribe(EventClass)`:
   ```python
   from app.events import VenueReviewSubmittedEvent, subscribe
   from sqlalchemy.orm import Session

   @subscribe(VenueReviewSubmittedEvent)
   def on_review_submitted(event: VenueReviewSubmittedEvent, db: Session) -> None:
       # Run your side effect here (e.g. recalculate venue rating average)
       ...
   ```
2. Ensure your handler module is imported in [`app/events/handlers/__init__.py`](../apps/api/app/events/handlers/__init__.py) so that it is registered when FastAPI starts.

---

## 6. Testing & Quality Assurance

The event bus was engineered with high testability:
- Pure unit tests run in **< 0.2 seconds** without needing a live PostgreSQL or Redis instance.
- Handler failures can be tested in isolation using mock exceptions.

### 6.1. Running the Event Bus Test Suite
```powershell
cd apps/api
uv run pytest tests/test_event_bus.py
```

### 6.2. Test Suite Coverage (`tests/test_event_bus.py`)
1. **`test_subscribe_and_emit`**: Validates registration and parameter dispatch to subscribers.
2. **`test_multiple_subscribers`**: Verifies that fan-out works across multiple independent handlers for the same event.
3. **`test_exception_isolation`**: Proves that an unhandled error in handler A does not prevent handler B from running and does not raise an exception to the caller.
4. **`test_polymorphic_subscription`**: Confirms that subscribers to `DomainEvent` receive all subclass events.
5. **`test_emit_after_commit_queuing`**: Verifies post-commit event queueing in `db.info`.
6. **Notification Integration Tests**: Confirms that all domain events accurately trigger the intended `notifications.notify()` calls with exact payloads, titles, and recipient IDs.
