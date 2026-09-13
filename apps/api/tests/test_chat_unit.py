import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ForbiddenError, RateLimitError
from app.modules.booking.helpers import TERMINAL_STATUSES
from app.modules.chat import manager
from app.modules.chat.repository import mark_messages_read
from app.modules.chat.service import _validate_and_create_message


# ============================================================================
# Rate Limiting Tests
# ============================================================================
def test_enforce_chat_send_limit_within_limit():
    from app.core.rate_limit import enforce_chat_send_limit

    mock_redis = MagicMock()
    mock_redis.incr.return_value = 5

    with (
        patch("app.core.redis.is_configured", return_value=True),
        patch("app.core.redis.get_redis", return_value=mock_redis),
    ):
        # Should not raise
        enforce_chat_send_limit(uuid.uuid4())
        mock_redis.incr.assert_called_once()


def test_enforce_chat_send_limit_exceeded():
    from app.core.rate_limit import enforce_chat_send_limit

    mock_redis = MagicMock()
    mock_redis.incr.return_value = 31

    with (
        patch("app.core.redis.is_configured", return_value=True),
        patch("app.core.redis.get_redis", return_value=mock_redis),
    ):
        with pytest.raises(RateLimitError, match="sending messages too quickly"):
            enforce_chat_send_limit(uuid.uuid4())


def test_enforce_chat_send_limit_fail_open_on_redis_error():
    from app.core.rate_limit import enforce_chat_send_limit

    mock_redis = MagicMock()
    mock_redis.incr.side_effect = Exception("Upstash unreachable")

    with (
        patch("app.core.redis.is_configured", return_value=True),
        patch("app.core.redis.get_redis", return_value=mock_redis),
    ):
        # Should fail open without raising
        enforce_chat_send_limit(uuid.uuid4())


# ============================================================================
# Manager & Presence Tests
# ============================================================================
def test_manager_register_and_unregister_with_redis():
    booking_id = uuid.uuid4()
    user_id = uuid.uuid4()
    ws_mock = MagicMock()

    mock_redis = MagicMock()

    with (
        patch("app.core.redis.is_configured", return_value=True),
        patch("app.core.redis.get_redis", return_value=mock_redis),
    ):
        manager.register_connection(booking_id, user_id, ws_mock)

        # In-process connection check
        assert manager.is_user_connected(booking_id, user_id) is True
        mock_redis.set.assert_called_once_with(f"chat:online:{booking_id}:{user_id}", "1", ex=120)

        # Unregister
        manager.unregister_connection(booking_id, user_id)
        mock_redis.delete.assert_called_once_with(f"chat:online:{booking_id}:{user_id}")


def test_manager_is_user_connected_cross_instance_redis():
    booking_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_redis = MagicMock()
    mock_redis.get.return_value = "1"

    # Not in local _connections dict
    manager._connections.clear()

    with (
        patch("app.core.redis.is_configured", return_value=True),
        patch("app.core.redis.get_redis", return_value=mock_redis),
    ):
        connected = manager.is_user_connected(booking_id, user_id)
        assert connected is True
        mock_redis.get.assert_called_once_with(f"chat:online:{booking_id}:{user_id}")


@pytest.mark.asyncio
async def test_manager_broadcast_typing():
    booking_id = uuid.uuid4()
    sender_id = uuid.uuid4()
    receiver_id = uuid.uuid4()

    ws_receiver = AsyncMock()
    manager._connections.clear()
    manager.register_connection(booking_id, sender_id, AsyncMock())
    manager.register_connection(booking_id, receiver_id, ws_receiver)

    try:
        await manager.broadcast_typing(booking_id, sender_id, is_typing=True)
        assert ws_receiver.send_text.call_count == 1
        sent_payload = ws_receiver.send_text.call_args[0][0]
        assert '"type": "typing_start"' in sent_payload
        assert str(sender_id) in sent_payload

        await manager.broadcast_typing(booking_id, sender_id, is_typing=False)
        assert ws_receiver.send_text.call_count == 2
        sent_stop = ws_receiver.send_text.call_args[0][0]
        assert '"type": "typing_stop"' in sent_stop
    finally:
        manager._connections.clear()


def test_notify_offline_participant_error_handled():
    booking_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    db_mock = MagicMock()

    # Even if notify raises an unhandled exception, it should be caught and logged
    notify_err = Exception("Notification service down")
    with (
        patch("app.modules.chat.manager.is_user_connected", return_value=False),
        patch("app.modules.chat.manager.notify", side_effect=notify_err),
    ):
        # Should NOT raise
        manager.notify_offline_participant(
            db_mock, booking_id, recipient_id, {"venue_name": "Grand Hall"}
        )


# ============================================================================
# Service Validation & Message Creation Tests
# ============================================================================
def test_validate_and_create_message_empty_or_whitespace():
    db_mock = MagicMock()
    booking_id = uuid.uuid4()
    sender_id = uuid.uuid4()

    # Mock booking
    booking_mock = MagicMock()
    booking_mock.id = booking_id
    booking_mock.user_id = sender_id
    booking_mock.status = "confirmed"

    venue_mock = MagicMock()
    venue_mock.owner_id = uuid.uuid4()
    venue_mock.name = "Test Hall"

    scalars_mock = MagicMock()
    scalars_mock.first.side_effect = [booking_mock, venue_mock, booking_mock, venue_mock]
    db_mock.execute.return_value.scalars.return_value = scalars_mock

    with patch("app.core.rate_limit.enforce_chat_send_limit"):
        with pytest.raises(ValueError, match="Message cannot be empty"):
            _validate_and_create_message(db_mock, booking_id, sender_id, "")

        with pytest.raises(ValueError, match="Message cannot be empty"):
            _validate_and_create_message(db_mock, booking_id, sender_id, "   \n\t  ")


def test_validate_and_create_message_exceeds_length():
    db_mock = MagicMock()
    booking_id = uuid.uuid4()
    sender_id = uuid.uuid4()

    booking_mock = MagicMock()
    booking_mock.id = booking_id
    booking_mock.user_id = sender_id
    booking_mock.status = "confirmed"

    venue_mock = MagicMock()
    venue_mock.owner_id = uuid.uuid4()
    venue_mock.name = "Test Hall"

    scalars_mock = MagicMock()
    scalars_mock.first.side_effect = [booking_mock, venue_mock]
    db_mock.execute.return_value.scalars.return_value = scalars_mock

    with (
        patch("app.core.rate_limit.enforce_chat_send_limit"),
        patch("app.core.config.settings.chat_max_message_length", 2000),
    ):
        long_message = "a" * 2001
        with pytest.raises(ValueError, match="exceeds 2000 characters"):
            _validate_and_create_message(db_mock, booking_id, sender_id, long_message)


def test_validate_and_create_message_terminal_status():
    db_mock = MagicMock()
    booking_id = uuid.uuid4()
    sender_id = uuid.uuid4()

    booking_mock = MagicMock()
    booking_mock.id = booking_id
    booking_mock.user_id = sender_id
    booking_mock.status = list(TERMINAL_STATUSES)[0]

    venue_mock = MagicMock()
    venue_mock.owner_id = uuid.uuid4()

    scalars_mock = MagicMock()
    scalars_mock.first.side_effect = [booking_mock, venue_mock]
    db_mock.execute.return_value.scalars.return_value = scalars_mock

    with patch("app.core.rate_limit.enforce_chat_send_limit"):
        with pytest.raises(ForbiddenError, match="terminal status"):
            _validate_and_create_message(db_mock, booking_id, sender_id, "Hello")


def test_validate_and_create_message_unauthorized():
    db_mock = MagicMock()
    booking_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    unauthorized_id = uuid.uuid4()

    booking_mock = MagicMock()
    booking_mock.id = booking_id
    booking_mock.user_id = customer_id
    booking_mock.status = "confirmed"

    venue_mock = MagicMock()
    venue_mock.owner_id = owner_id

    scalars_mock = MagicMock()
    scalars_mock.first.side_effect = [booking_mock, venue_mock]
    db_mock.execute.return_value.scalars.return_value = scalars_mock

    with patch("app.core.rate_limit.enforce_chat_send_limit"):
        with pytest.raises(ForbiddenError, match="Not authorized"):
            _validate_and_create_message(db_mock, booking_id, unauthorized_id, "Hello")


# ============================================================================
# Repository Bulk Mark Read Test
# ============================================================================
def test_repository_mark_messages_read_bulk():
    db_mock = MagicMock()
    booking_id = uuid.uuid4()
    user_id = uuid.uuid4()

    result_mock = MagicMock()
    result_mock.rowcount = 4
    db_mock.execute.return_value = result_mock

    count = mark_messages_read(db_mock, booking_id, user_id)
    assert count == 4
    db_mock.execute.assert_called_once()
    db_mock.flush.assert_called_once()
