"""In-process pub/sub event dispatcher for Venue404.

Provides synchronous in-transaction and post-commit event dispatching with
strict exception isolation so handlers never crash event producers.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.events.registry import DomainEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any, Session], None]

_subscribers: dict[type[DomainEvent], list[EventHandler]] = defaultdict(list)
_listener_registered = False


def subscribe[T: DomainEvent](
    event_type: type[T],
) -> Callable[[Callable[[T, Session], None]], Callable[[T, Session], None]]:
    """Decorator to register an event handler for a specific DomainEvent type."""

    def decorator(func: Callable[[T, Session], None]) -> Callable[[T, Session], None]:
        _subscribers[event_type].append(func)
        return func

    return decorator


def emit(event: DomainEvent, db: Session) -> None:
    """Synchronously dispatch an event to all registered subscribers.

    Each subscriber is executed within a try-except block so that an error
    in one handler does not abort subsequent handlers or fail the caller's transaction.
    """
    event_cls = type(event)
    for cls in event_cls.__mro__:
        if issubclass(cls, DomainEvent):
            for handler in list(_subscribers.get(cls, [])):
                try:
                    handler(event, db)
                except Exception:
                    logger.exception(
                        "Error executing event handler %s for %s",
                        getattr(handler, "__name__", str(handler)),
                        event_cls.__name__,
                    )


def emit_after_commit(db: Session, event: DomainEvent) -> None:
    """Queue an event to be dispatched after the current transaction commits successfully."""
    _ensure_after_commit_listener()
    pending: list[DomainEvent] = db.info.setdefault("_pending_domain_events", [])
    pending.append(event)


def _dispatch_after_commit(session: Session) -> None:
    """SQLAlchemy after_commit hook: drain and dispatch all pending domain events."""
    pending: list[DomainEvent] | None = session.info.pop("_pending_domain_events", None)
    if not pending:
        return

    with SessionLocal() as fresh_db:
        for event in pending:
            emit(event, fresh_db)


def _ensure_after_commit_listener() -> None:
    global _listener_registered
    if not _listener_registered:
        sa_event.listen(SessionLocal, "after_commit", _dispatch_after_commit)
        _listener_registered = True


def clear_handlers() -> None:
    """Reset all subscribers. Primarily used in testing."""
    _subscribers.clear()
