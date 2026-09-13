"""Event handlers package.

Importing this package ensures all event listeners are registered.
"""

from app.events.handlers import notification_handler  # noqa: F401

__all__ = ["notification_handler"]
