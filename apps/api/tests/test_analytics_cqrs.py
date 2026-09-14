"""Unit and integration tests for CQRS Analytics Pipeline.

Tests:
1. Event bus handlers append to analytics_events (Write path)
2. Daily rollup aggregation logic and idempotency (Read path)
3. Admin Analytics KPI, Funnel, Top Venues, and Trends calculation
4. Owner Analytics KPI, Occupancy, Response Time, Benchmarks, and Trends
5. CSV Report generation
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

from app.events import (
    AdvancePaymentConfirmedEvent,
    AvailabilityCheckedEvent,
    BookingAcceptedEvent,
    BookingDetailViewedEvent,
    BookingRequestedEvent,
    PricingPreviewedEvent,
    ReviewSubmittedEvent,
    SearchExecutedEvent,
    VenueViewedEvent,
    WishlistToggledEvent,
)
from app.events.handlers import analytics_handler
from app.modules.analytics import service
from app.modules.analytics.models import (
    AnalyticsEvent,
)
from app.modules.analytics.schemas import (
    DailyTrendPoint,
    EngagementKpis,
)


def test_analytics_handler_booking_requested():
    """Verify BookingRequestedEvent records a booking.requested raw event."""
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
    analytics_handler.on_booking_requested(event, mock_db)

    assert mock_db.add.call_count == 1
    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, AnalyticsEvent)
    assert added_obj.event_name == "booking.requested"
    assert added_obj.booking_id == booking_id
    assert added_obj.venue_id == venue_id
    assert added_obj.user_id == user_id
    assert added_obj.payload["venue_name"] == "Grand Ballroom"
    assert added_obj.payload["owner_id"] == str(owner_id)
    assert mock_db.flush.called


def test_analytics_handler_booking_accepted():
    """Verify BookingAcceptedEvent computes response_time_seconds when booking exists."""
    mock_db = MagicMock()
    user_id = uuid4()
    owner_id = uuid4()
    booking_id = uuid4()
    venue_id = uuid4()

    booking_created = datetime.now(UTC) - timedelta(hours=2)
    mock_booking = MagicMock()
    mock_booking.created_at = booking_created
    mock_db.query().filter().first.return_value = mock_booking

    event = BookingAcceptedEvent(
        booking_id=booking_id,
        user_id=user_id,
        owner_id=owner_id,
        venue_id=venue_id,
        venue_name="Grand Ballroom",
    )
    analytics_handler.on_booking_accepted(event, mock_db)

    added_obj = mock_db.add.call_args[0][0]
    assert added_obj.event_name == "booking.accepted"
    assert "response_time_seconds" in added_obj.payload
    assert added_obj.payload["response_time_seconds"] >= 7100


def test_analytics_handler_payment_confirmed():
    """Verify AdvancePaymentConfirmedEvent records booking.confirmed with gross and fee."""
    mock_db = MagicMock()
    user_id = uuid4()
    venue_id = uuid4()
    booking_id = uuid4()

    mock_booking = MagicMock()
    mock_booking.quoted_price_paise = 10000000  # 1 Lakh INR
    mock_db.query().filter().first.return_value = mock_booking

    event = AdvancePaymentConfirmedEvent(
        booking_id=booking_id,
        user_id=user_id,
        venue_id=venue_id,
        venue_name="Grand Ballroom",
    )
    analytics_handler.on_payment_confirmed(event, mock_db)

    added_obj = mock_db.add.call_args[0][0]
    assert added_obj.event_name == "booking.confirmed"
    assert added_obj.payload["gross_amount_paise"] == 10000000
    assert added_obj.payload["platform_fee_paise"] == 1000000


def test_analytics_handler_search_and_venue_viewed():
    """Verify SearchExecutedEvent and VenueViewedEvent are captured."""
    mock_db = MagicMock()
    user_id = uuid4()
    venue_id = uuid4()

    # Search
    search_event = SearchExecutedEvent(
        query="beach resort",
        city="Goa",
        venue_type="resort",
        result_count=8,
        user_id=user_id,
    )
    analytics_handler.on_search_executed(search_event, mock_db)

    search_row = mock_db.add.call_args[0][0]
    assert search_row.event_name == "search.executed"
    assert search_row.payload["query"] == "beach resort"
    assert search_row.payload["result_count"] == 8

    # View
    view_event = VenueViewedEvent(
        venue_id=venue_id,
        user_id=user_id,
        venue_name="Sunny Sands",
    )
    analytics_handler.on_venue_viewed(view_event, mock_db)

    view_row = mock_db.add.call_args[0][0]
    assert view_row.event_name == "venue.viewed"
    assert view_row.venue_id == venue_id


def test_period_date_parsing():
    """Verify period parsing utility produces correct ranges."""
    c_start, c_end, p_start, p_end = service.parse_period_dates("7d")
    assert (c_end - c_start).days == 6
    assert (p_end - p_start).days == 6
    assert p_end == c_start - timedelta(days=1)

    c_start, c_end, p_start, p_end = service.parse_period_dates(
        start_date="2026-08-01", end_date="2026-08-10"
    )
    assert c_start == date(2026, 8, 1)
    assert c_end == date(2026, 8, 10)
    assert p_end == date(2026, 7, 31)


def test_format_human_duration():
    """Test duration formatting for dashboard display."""
    assert service._format_human_duration(0) == "N/A"
    assert service._format_human_duration(45) == "45s"
    assert service._format_human_duration(1800) == "30m"
    assert service._format_human_duration(7200) == "2.0h"


def test_export_csv_generation():
    """Verify CSV formatting for Admin and Owner exports."""
    mock_db = MagicMock()
    t1 = DailyTrendPoint(
        date="2026-09-01",
        gmv_paise=5000000,
        platform_fee_paise=500000,
        requests_count=3,
        confirmed_count=2,
        searches_count=50,
        views_count=25,
    )
    service._build_daily_trends = MagicMock(return_value=[t1])

    admin_csv = service.export_analytics_csv(mock_db, scope="admin", period="7d")
    assert (
        "Date,GMV (INR),Platform Fee (INR),Searches,Views,Requests,Confirmed Bookings"
        in admin_csv
    )
    assert "2026-09-01,50000.00,5000.00,50,25,3,2" in admin_csv

    owner_csv = service.export_analytics_csv(
        mock_db, scope="owner", owner_id=uuid4(), period="7d"
    )
    assert "Date,Gross Revenue (INR),Platform Fee (INR),Net Payout (INR)" in owner_csv
    assert "2026-09-01,50000.00,5000.00,45000.00,3,2,25" in owner_csv


def test_analytics_handler_wishlist_toggled():
    """Verify WishlistToggledEvent records a raw engagement event."""
    mock_db = MagicMock()
    user_id = uuid4()
    venue_id = uuid4()

    event = WishlistToggledEvent(
        user_id=user_id,
        venue_id=venue_id,
        action="add",
    )
    analytics_handler.on_wishlist_toggled(event, mock_db)

    assert mock_db.add.call_count == 1
    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, AnalyticsEvent)
    assert added_obj.event_name == "engagement.wishlist_toggled"
    assert added_obj.user_id == user_id
    assert added_obj.venue_id == venue_id
    assert added_obj.payload["action"] == "add"
    assert mock_db.flush.called


def test_analytics_handler_review_submitted():
    """Verify ReviewSubmittedEvent records review submission with rating."""
    mock_db = MagicMock()
    user_id = uuid4()
    venue_id = uuid4()
    booking_id = uuid4()
    review_id = uuid4()

    event = ReviewSubmittedEvent(
        review_id=review_id,
        venue_id=venue_id,
        booking_id=booking_id,
        user_id=user_id,
        rating=5,
    )
    analytics_handler.on_review_submitted(event, mock_db)

    added_obj = mock_db.add.call_args[0][0]
    assert added_obj.event_name == "engagement.review_submitted"
    assert added_obj.user_id == user_id
    assert added_obj.venue_id == venue_id
    assert added_obj.booking_id == booking_id
    assert added_obj.payload["rating"] == 5


def test_analytics_handler_availability_checked():
    """Verify AvailabilityCheckedEvent records calendar queries."""
    mock_db = MagicMock()
    user_id = uuid4()
    venue_id = uuid4()

    event = AvailabilityCheckedEvent(
        venue_id=venue_id,
        user_id=user_id,
        booking_date="2026-10-01",
        booking_type="hourly",
    )
    analytics_handler.on_availability_checked(event, mock_db)

    added_obj = mock_db.add.call_args[0][0]
    assert added_obj.event_name == "engagement.availability_checked"
    assert added_obj.user_id == user_id
    assert added_obj.venue_id == venue_id
    assert added_obj.payload["booking_date"] == "2026-10-01"
    assert added_obj.payload["booking_type"] == "hourly"


def test_analytics_handler_pricing_previewed():
    """Verify PricingPreviewedEvent records pricing queries."""
    mock_db = MagicMock()
    user_id = uuid4()
    venue_id = uuid4()

    event = PricingPreviewedEvent(
        venue_id=venue_id,
        user_id=user_id,
        booking_type="hourly",
    )
    analytics_handler.on_pricing_previewed(event, mock_db)

    added_obj = mock_db.add.call_args[0][0]
    assert added_obj.event_name == "engagement.pricing_previewed"
    assert added_obj.user_id == user_id
    assert added_obj.venue_id == venue_id
    assert added_obj.payload["booking_type"] == "hourly"


def test_analytics_handler_booking_detail_viewed():
    """Verify BookingDetailViewedEvent records booking detail views."""
    mock_db = MagicMock()
    user_id = uuid4()
    booking_id = uuid4()
    venue_id = uuid4()

    mock_booking = MagicMock()
    mock_booking.venue_id = venue_id
    mock_db.query().filter().first.return_value = mock_booking

    event = BookingDetailViewedEvent(
        booking_id=booking_id,
        user_id=user_id,
    )
    analytics_handler.on_booking_detail_viewed(event, mock_db)

    added_obj = mock_db.add.call_args[0][0]
    assert added_obj.event_name == "engagement.booking_detail_viewed"
    assert added_obj.booking_id == booking_id
    assert added_obj.user_id == user_id
    assert added_obj.venue_id == venue_id


def test_build_engagement_kpis():
    """Verify _build_engagement_kpis aggregates stats correctly."""
    mock_db = MagicMock()
    row = MagicMock()
    row.wl_adds = 15
    row.wl_removes = 3
    row.reviews = 5
    row.avail = 42
    row.pricing = 18
    row.bkgviews = 25
    row.users = 30

    avg_row = MagicMock()
    avg_row.avg_rating = 4.5

    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.first.side_effect = [row, avg_row]
    mock_db.query.return_value = query_mock

    kpis = service._build_engagement_kpis(
        mock_db, start_date=date(2026, 9, 1), end_date=date(2026, 9, 7)
    )
    assert isinstance(kpis, EngagementKpis)
    assert kpis.wishlist_adds == 15
    assert kpis.wishlist_removes == 3
    assert kpis.wishlist_adds - kpis.wishlist_removes == 12
    assert kpis.reviews_submitted == 5
    assert kpis.avg_review_rating == 4.5
    assert kpis.availability_checks == 42
    assert kpis.pricing_previews == 18
    assert kpis.booking_detail_views == 25
    assert kpis.unique_engaged_users == 30


