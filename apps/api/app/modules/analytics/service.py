import csv
import io
import logging
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.modules.analytics.models import (
    AnalyticsEvent,
    DailyBookingStats,
    DailyRevenueStats,
    DailySearchStats,
)
from app.modules.analytics.schemas import (
    AdminAnalyticsOverview,
    AdminKpis,
    AggregationResult,
    DailyTrendPoint,
    FunnelStage,
    OwnerAnalyticsOverview,
    OwnerBenchmarks,
    OwnerKpis,
    TopVenuePerformance,
)
from app.modules.booking.models import Booking, BookingStatus
from app.modules.venue.models import Venue, VenueStatus

logger = logging.getLogger(__name__)

SENTINEL_NULL_UUID = "00000000-0000-0000-0000-000000000000"


def record_raw_event(
    db: Session,
    event_name: str,
    event_id: UUID | None = None,
    user_id: UUID | None = None,
    venue_id: UUID | None = None,
    booking_id: UUID | None = None,
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> AnalyticsEvent:
    """Record an append-only event into analytics_events."""
    event = AnalyticsEvent(
        id=uuid4(),
        event_name=event_name,
        event_id=event_id,
        user_id=user_id,
        venue_id=venue_id,
        booking_id=booking_id,
        payload=payload or {},
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db.add(event)
    db.flush()
    return event


def _format_human_duration(seconds: int) -> str:
    if seconds <= 0:
        return "N/A"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = seconds / 3600.0
    return f"{hours:.1f}h"


def parse_period_dates(
    period: str = "30d",
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[date, date, date, date]:
    """Calculate (current_start, current_end, previous_start, previous_end) dates."""
    today = datetime.now(UTC).date()

    if start_date and end_date:
        c_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        c_end = datetime.strptime(end_date, "%Y-%m-%d").date()
        num_days = (c_end - c_start).days + 1
        p_end = c_start - timedelta(days=1)
        p_start = p_end - timedelta(days=num_days - 1)
        return c_start, c_end, p_start, p_end

    period_map = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "12m": 365,
    }
    days = period_map.get(period.lower(), 30)
    c_end = today
    c_start = today - timedelta(days=days - 1)
    p_end = c_start - timedelta(days=1)
    p_start = p_end - timedelta(days=days - 1)
    return c_start, c_end, p_start, p_end


# ---------------------------------------------------------------------------
# Aggregator (Rollup Materializer)
# ---------------------------------------------------------------------------


def run_aggregation(
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
) -> AggregationResult:
    """Compute daily rollups from analytics_events into materialized stats tables.

    Idempotent upserts ensure re-runs overwrite and correct data without duplicates.
    """
    if not end_date:
        end_date = datetime.now(UTC).date()
    if not start_date:
        start_date = end_date - timedelta(days=1)

    curr = start_date
    dates_aggregated = []
    total_booking_rows = 0
    total_revenue_rows = 0
    total_search_rows = 0

    while curr <= end_date:
        d_start = datetime.combine(curr, time.min, tzinfo=UTC)
        d_end = datetime.combine(curr, time.max, tzinfo=UTC)

        b_rows = _aggregate_day_bookings(db, curr, d_start, d_end)
        r_rows = _aggregate_day_revenue(db, curr, d_start, d_end)
        s_rows = _aggregate_day_search(db, curr, d_start, d_end)

        dates_aggregated.append(curr.isoformat())
        total_booking_rows += b_rows
        total_revenue_rows += r_rows
        total_search_rows += s_rows
        curr += timedelta(days=1)

    db.commit()

    return AggregationResult(
        status="ok",
        dates_aggregated=dates_aggregated,
        booking_rows_upserted=total_booking_rows,
        revenue_rows_upserted=total_revenue_rows,
        search_rows_upserted=total_search_rows,
    )


def _aggregate_day_bookings(
    db: Session, target_date: date, d_start: datetime, d_end: datetime
) -> int:
    """Aggregate booking events for a day by venue and platform-wide."""
    events = (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.occurred_at >= d_start,
            AnalyticsEvent.occurred_at <= d_end,
            AnalyticsEvent.event_name.in_(
                [
                    "booking.requested",
                    "booking.accepted",
                    "booking.rejected",
                    "booking.confirmed",
                    "booking.completed",
                    "booking.cancelled",
                ]
            ),
        )
        .all()
    )

    # venue_key -> dict of stats; None key represents platform-wide
    venue_map: dict[UUID | None, dict] = {}

    def _ensure_entry(v_id: UUID | None):
        if v_id not in venue_map:
            venue_map[v_id] = {
                "total_requests": 0,
                "accepted_requests": 0,
                "rejected_requests": 0,
                "confirmed_bookings": 0,
                "completed_bookings": 0,
                "cancelled_bookings": 0,
                "total_response_time_seconds": 0,
                "response_count": 0,
                "slot_hours_booked": 0.0,
            }
        return venue_map[v_id]

    _ensure_entry(None)

    for ev in events:
        v_entry = _ensure_entry(ev.venue_id) if ev.venue_id else None
        p_entry = venue_map[None]

        resp_time = ev.payload.get("response_time_seconds")
        resp_sec = int(resp_time) if resp_time is not None else None

        if ev.event_name == "booking.requested":
            p_entry["total_requests"] += 1
            if v_entry:
                v_entry["total_requests"] += 1
        elif ev.event_name == "booking.accepted":
            p_entry["accepted_requests"] += 1
            if v_entry:
                v_entry["accepted_requests"] += 1
            if resp_sec is not None:
                p_entry["total_response_time_seconds"] += resp_sec
                p_entry["response_count"] += 1
                if v_entry:
                    v_entry["total_response_time_seconds"] += resp_sec
                    v_entry["response_count"] += 1
        elif ev.event_name == "booking.rejected":
            p_entry["rejected_requests"] += 1
            if v_entry:
                v_entry["rejected_requests"] += 1
            if resp_sec is not None:
                p_entry["total_response_time_seconds"] += resp_sec
                p_entry["response_count"] += 1
                if v_entry:
                    v_entry["total_response_time_seconds"] += resp_sec
                    v_entry["response_count"] += 1
        elif ev.event_name == "booking.confirmed":
            p_entry["confirmed_bookings"] += 1
            if v_entry:
                v_entry["confirmed_bookings"] += 1
        elif ev.event_name == "booking.completed":
            p_entry["completed_bookings"] += 1
            if v_entry:
                v_entry["completed_bookings"] += 1
        elif ev.event_name == "booking.cancelled":
            p_entry["cancelled_bookings"] += 1
            if v_entry:
                v_entry["cancelled_bookings"] += 1

    upserted_count = 0
    for v_id, stats in venue_map.items():
        existing = (
            db.query(DailyBookingStats)
            .filter(
                DailyBookingStats.date == target_date,
                DailyBookingStats.venue_id == v_id
                if v_id is not None
                else DailyBookingStats.venue_id.is_(None),
            )
            .first()
        )
        if existing:
            for k, v in stats.items():
                setattr(existing, k, v)
        else:
            new_row = DailyBookingStats(
                id=uuid4(),
                date=target_date,
                venue_id=v_id,
                **stats,
            )
            db.add(new_row)
        upserted_count += 1

    db.flush()
    return upserted_count


def _aggregate_day_revenue(
    db: Session, target_date: date, d_start: datetime, d_end: datetime
) -> int:
    """Aggregate financial & revenue stats for a day."""
    events = (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.occurred_at >= d_start,
            AnalyticsEvent.occurred_at <= d_end,
            AnalyticsEvent.event_name.in_(
                [
                    "booking.confirmed",
                    "payment.balance_paid",
                    "payment.refund",
                ]
            ),
        )
        .all()
    )

    venue_map: dict[UUID | None, dict] = {}

    def _ensure_entry(v_id: UUID | None):
        if v_id not in venue_map:
            venue_map[v_id] = {
                "gross_merchandise_value_paise": 0,
                "platform_fee_paise": 0,
                "owner_payout_paise": 0,
                "refunds_paise": 0,
                "transaction_count": 0,
            }
        return venue_map[v_id]

    _ensure_entry(None)

    for ev in events:
        v_entry = _ensure_entry(ev.venue_id) if ev.venue_id else None
        p_entry = venue_map[None]

        if ev.event_name == "booking.confirmed":
            gross = int(ev.payload.get("gross_amount_paise", 0))
            fee = int(ev.payload.get("platform_fee_paise", 0))
            p_entry["gross_merchandise_value_paise"] += gross
            p_entry["platform_fee_paise"] += fee
            p_entry["owner_payout_paise"] += max(0, gross - fee)
            p_entry["transaction_count"] += 1
            if v_entry:
                v_entry["gross_merchandise_value_paise"] += gross
                v_entry["platform_fee_paise"] += fee
                v_entry["owner_payout_paise"] += max(0, gross - fee)
                v_entry["transaction_count"] += 1
        elif ev.event_name == "payment.refund":
            ref = int(ev.payload.get("amount_paise", 0))
            p_entry["refunds_paise"] += ref
            p_entry["transaction_count"] += 1
            if v_entry:
                v_entry["refunds_paise"] += ref
                v_entry["transaction_count"] += 1

    upserted_count = 0
    for v_id, stats in venue_map.items():
        existing = (
            db.query(DailyRevenueStats)
            .filter(
                DailyRevenueStats.date == target_date,
                DailyRevenueStats.venue_id == v_id
                if v_id is not None
                else DailyRevenueStats.venue_id.is_(None),
            )
            .first()
        )
        if existing:
            for k, v in stats.items():
                setattr(existing, k, v)
        else:
            new_row = DailyRevenueStats(
                id=uuid4(),
                date=target_date,
                venue_id=v_id,
                **stats,
            )
            db.add(new_row)
        upserted_count += 1

    db.flush()
    return upserted_count


def _aggregate_day_search(
    db: Session, target_date: date, d_start: datetime, d_end: datetime
) -> int:
    """Aggregate search and venue view stats for a day."""
    events = (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.occurred_at >= d_start,
            AnalyticsEvent.occurred_at <= d_end,
            AnalyticsEvent.event_name.in_(["search.executed", "venue.viewed"]),
        )
        .all()
    )

    venue_map: dict[UUID | None, dict] = {}
    users_by_venue: dict[UUID | None, set[UUID]] = {}

    def _ensure_entry(v_id: UUID | None):
        if v_id not in venue_map:
            venue_map[v_id] = {
                "total_searches": 0,
                "total_venue_views": 0,
                "unique_users": 0,
            }
            users_by_venue[v_id] = set()
        return venue_map[v_id]

    _ensure_entry(None)

    for ev in events:
        if ev.event_name == "search.executed":
            p_entry = venue_map[None]
            p_entry["total_searches"] += 1
            if ev.user_id:
                users_by_venue[None].add(ev.user_id)
        elif ev.event_name == "venue.viewed":
            p_entry = venue_map[None]
            p_entry["total_venue_views"] += 1
            if ev.user_id:
                users_by_venue[None].add(ev.user_id)

            if ev.venue_id:
                v_entry = _ensure_entry(ev.venue_id)
                v_entry["total_venue_views"] += 1
                if ev.user_id:
                    users_by_venue[ev.venue_id].add(ev.user_id)

    for v_id, u_set in users_by_venue.items():
        venue_map[v_id]["unique_users"] = len(u_set)

    upserted_count = 0
    for v_id, stats in venue_map.items():
        existing = (
            db.query(DailySearchStats)
            .filter(
                DailySearchStats.date == target_date,
                DailySearchStats.venue_id == v_id
                if v_id is not None
                else DailySearchStats.venue_id.is_(None),
            )
            .first()
        )
        if existing:
            for k, v in stats.items():
                setattr(existing, k, v)
        else:
            new_row = DailySearchStats(
                id=uuid4(),
                date=target_date,
                venue_id=v_id,
                **stats,
            )
            db.add(new_row)
        upserted_count += 1

    db.flush()
    return upserted_count


# ---------------------------------------------------------------------------
# Hybrid Read Path (CQRS Dashboards)
# ---------------------------------------------------------------------------


def get_admin_overview(
    db: Session,
    period: str = "30d",
    start_date: str | None = None,
    end_date: str | None = None,
) -> AdminAnalyticsOverview:
    """Read path for Admin Dashboard: GMV, Funnel, Top Venues, Daily Trends."""
    c_start, c_end, p_start, p_end = parse_period_dates(period, start_date, end_date)
    today = datetime.now(UTC).date()

    # Query historical rollups for current and previous period
    curr_rev = (
        db.query(
            func.coalesce(func.sum(DailyRevenueStats.gross_merchandise_value_paise), 0).label(
                "gmv"
            ),
            func.coalesce(func.sum(DailyRevenueStats.platform_fee_paise), 0).label("fee"),
        )
        .filter(
            DailyRevenueStats.venue_id.is_(None),
            DailyRevenueStats.date >= c_start,
            DailyRevenueStats.date <= c_end,
        )
        .first()
    )

    prev_rev = (
        db.query(
            func.coalesce(func.sum(DailyRevenueStats.gross_merchandise_value_paise), 0).label(
                "gmv"
            ),
            func.coalesce(func.sum(DailyRevenueStats.platform_fee_paise), 0).label("fee"),
        )
        .filter(
            DailyRevenueStats.venue_id.is_(None),
            DailyRevenueStats.date >= p_start,
            DailyRevenueStats.date <= p_end,
        )
        .first()
    )

    curr_bkg = (
        db.query(
            func.coalesce(func.sum(DailyBookingStats.total_requests), 0).label("requests"),
            func.coalesce(func.sum(DailyBookingStats.confirmed_bookings), 0).label("confirmed"),
        )
        .filter(
            DailyBookingStats.venue_id.is_(None),
            DailyBookingStats.date >= c_start,
            DailyBookingStats.date <= c_end,
        )
        .first()
    )

    prev_bkg = (
        db.query(
            func.coalesce(func.sum(DailyBookingStats.confirmed_bookings), 0).label("confirmed"),
        )
        .filter(
            DailyBookingStats.venue_id.is_(None),
            DailyBookingStats.date >= p_start,
            DailyBookingStats.date <= p_end,
        )
        .first()
    )

    curr_search = (
        db.query(
            func.coalesce(func.sum(DailySearchStats.total_searches), 0).label("searches"),
            func.coalesce(func.sum(DailySearchStats.total_venue_views), 0).label("views"),
        )
        .filter(
            DailySearchStats.venue_id.is_(None),
            DailySearchStats.date >= c_start,
            DailySearchStats.date <= c_end,
        )
        .first()
    )

    # Hybrid live update: if today is in the requested range, fetch live events for today
    gmv_today = 0
    fee_today = 0
    req_today = 0
    conf_today = 0
    searches_today = 0
    views_today = 0

    if c_start <= today <= c_end:
        t_start = datetime.combine(today, time.min, tzinfo=UTC)
        today_events = db.query(AnalyticsEvent).filter(AnalyticsEvent.occurred_at >= t_start).all()
        for ev in today_events:
            if ev.event_name == "booking.confirmed":
                gmv_today += int(ev.payload.get("gross_amount_paise", 0))
                fee_today += int(ev.payload.get("platform_fee_paise", 0))
                conf_today += 1
            elif ev.event_name == "booking.requested":
                req_today += 1
            elif ev.event_name == "search.executed":
                searches_today += 1
            elif ev.event_name == "venue.viewed":
                views_today += 1

    total_gmv = int(curr_rev.gmv if curr_rev else 0) + gmv_today
    total_fee = int(curr_rev.fee if curr_rev else 0) + fee_today
    prev_gmv = int(prev_rev.gmv if prev_rev else 0)
    prev_fee = int(prev_rev.fee if prev_rev else 0)

    total_confirmed = int(curr_bkg.confirmed if curr_bkg else 0) + conf_today
    prev_confirmed = int(prev_bkg.confirmed if prev_bkg else 0)
    total_requests = int(curr_bkg.requests if curr_bkg else 0) + req_today

    total_searches = int(curr_search.searches if curr_search else 0) + searches_today
    total_views = int(curr_search.views if curr_search else 0) + views_today

    # Calculate percentage deltas
    def _pct_change(curr: int, prev: int) -> float | None:
        if prev <= 0:
            return None if curr == 0 else 100.0
        return round(((curr - prev) / prev) * 100.0, 1)

    gmv_change = _pct_change(total_gmv, prev_gmv)
    fee_change = _pct_change(total_fee, prev_fee)
    bkg_change = _pct_change(total_confirmed, prev_confirmed)

    # Conversion Rate
    conv_rate = round((total_confirmed / max(1, total_searches)) * 100.0, 2)

    kpis = AdminKpis(
        gmv_paise=total_gmv,
        gmv_change_pct=gmv_change,
        platform_revenue_paise=total_fee,
        platform_revenue_change_pct=fee_change,
        confirmed_bookings=total_confirmed,
        bookings_change_pct=bkg_change,
        conversion_rate_pct=conv_rate,
    )

    # Conversion Funnel: Search -> View -> Request -> Confirmed
    s1 = total_searches
    s2 = total_views
    s3 = total_requests
    s4 = total_confirmed

    funnel = [
        FunnelStage(
            stage="search",
            label="Searches Executed",
            count=s1,
            dropoff_rate=0.0,
            conversion_rate=100.0 if s1 > 0 else 0.0,
        ),
        FunnelStage(
            stage="view",
            label="Venue Views",
            count=s2,
            dropoff_rate=round(max(0.0, ((s1 - s2) / max(1, s1)) * 100.0), 1),
            conversion_rate=round((s2 / max(1, s1)) * 100.0, 1),
        ),
        FunnelStage(
            stage="request",
            label="Booking Requests",
            count=s3,
            dropoff_rate=round(max(0.0, ((s2 - s3) / max(1, s2)) * 100.0), 1),
            conversion_rate=round((s3 / max(1, s1)) * 100.0, 1),
        ),
        FunnelStage(
            stage="confirmed",
            label="Confirmed Bookings",
            count=s4,
            dropoff_rate=round(max(0.0, ((s3 - s4) / max(1, s3)) * 100.0), 1),
            conversion_rate=round((s4 / max(1, s1)) * 100.0, 1),
        ),
    ]

    # Top Venues
    top_venues_query = (
        db.query(
            DailyRevenueStats.venue_id,
            func.sum(DailyRevenueStats.gross_merchandise_value_paise).label("gmv"),
        )
        .filter(
            DailyRevenueStats.venue_id.is_not(None),
            DailyRevenueStats.date >= c_start,
            DailyRevenueStats.date <= c_end,
        )
        .group_by(DailyRevenueStats.venue_id)
        .order_by(text("gmv DESC"))
        .limit(5)
        .all()
    )

    top_venues = []
    for row in top_venues_query:
        venue = db.query(Venue).filter(Venue.id == row.venue_id).first()
        v_name = venue.name if venue else "Unknown Venue"
        v_city = venue.city if venue else None

        # Count bookings and views
        b_cnt = (
            db.query(func.sum(DailyBookingStats.confirmed_bookings))
            .filter(
                DailyBookingStats.venue_id == row.venue_id,
                DailyBookingStats.date >= c_start,
                DailyBookingStats.date <= c_end,
            )
            .scalar()
            or 0
        )
        v_cnt = (
            db.query(func.sum(DailySearchStats.total_venue_views))
            .filter(
                DailySearchStats.venue_id == row.venue_id,
                DailySearchStats.date >= c_start,
                DailySearchStats.date <= c_end,
            )
            .scalar()
            or 0
        )
        top_venues.append(
            TopVenuePerformance(
                venue_id=row.venue_id,
                venue_name=v_name,
                city=v_city,
                gmv_paise=int(row.gmv or 0),
                confirmed_bookings=int(b_cnt),
                views_count=int(v_cnt),
            )
        )

    # Daily Timeseries Trends
    trends = _build_daily_trends(db, c_start, c_end, venue_id=None)

    return AdminAnalyticsOverview(
        kpis=kpis,
        funnel=funnel,
        top_venues=top_venues,
        trends=trends,
        period=period,
        start_date=c_start.isoformat(),
        end_date=c_end.isoformat(),
    )


def get_owner_overview(
    db: Session,
    owner_id: UUID,
    venue_id: UUID | None = None,
    period: str = "30d",
    start_date: str | None = None,
    end_date: str | None = None,
) -> OwnerAnalyticsOverview:
    """Read path for Owner Dashboard: Revenue, Occupancy, Response Time, Benchmarks."""
    c_start, c_end, _, _ = parse_period_dates(period, start_date, end_date)

    # Fetch owner's venue IDs
    v_query = db.query(Venue.id).filter(
        Venue.owner_id == owner_id,
        Venue.status == VenueStatus.approved,
        Venue.deleted_at.is_(None),
    )
    if venue_id:
        v_query = v_query.filter(Venue.id == venue_id)
    venue_ids = [r[0] for r in v_query.all()]

    if not venue_ids:
        # Return blank stats for owners with no active venues
        zero_kpis = OwnerKpis(
            gross_revenue_paise=0,
            net_revenue_paise=0,
            platform_fee_paise=0,
            occupancy_rate_pct=0.0,
            avg_response_time_seconds=0,
            avg_response_time_human="N/A",
            acceptance_rate_pct=0.0,
            total_requests=0,
            confirmed_bookings=0,
        )
        return OwnerAnalyticsOverview(
            kpis=zero_kpis,
            funnel=[],
            trends=[],
            benchmarks=OwnerBenchmarks(
                acceptance_rate_pct=0.0,
                platform_acceptance_rate_pct=0.0,
                avg_response_time_seconds=0,
                platform_avg_response_time_seconds=0,
                conversion_rate_pct=0.0,
                platform_conversion_rate_pct=0.0,
            ),
            period=period,
            start_date=c_start.isoformat(),
            end_date=c_end.isoformat(),
        )

    # 1. Financial stats
    rev_row = (
        db.query(
            func.coalesce(func.sum(DailyRevenueStats.gross_merchandise_value_paise), 0).label(
                "gmv"
            ),
            func.coalesce(func.sum(DailyRevenueStats.platform_fee_paise), 0).label("fee"),
            func.coalesce(func.sum(DailyRevenueStats.owner_payout_paise), 0).label("payout"),
        )
        .filter(
            DailyRevenueStats.venue_id.in_(venue_ids),
            DailyRevenueStats.date >= c_start,
            DailyRevenueStats.date <= c_end,
        )
        .first()
    )

    gross_rev = int(rev_row.gmv if rev_row else 0)
    plat_fee = int(rev_row.fee if rev_row else 0)
    net_rev = int(rev_row.payout if rev_row else 0)

    # 2. Booking stats
    bkg_row = (
        db.query(
            func.coalesce(func.sum(DailyBookingStats.total_requests), 0).label("requests"),
            func.coalesce(func.sum(DailyBookingStats.accepted_requests), 0).label("accepted"),
            func.coalesce(func.sum(DailyBookingStats.rejected_requests), 0).label("rejected"),
            func.coalesce(func.sum(DailyBookingStats.confirmed_bookings), 0).label("confirmed"),
            func.coalesce(func.sum(DailyBookingStats.total_response_time_seconds), 0).label(
                "resp_time"
            ),
            func.coalesce(func.sum(DailyBookingStats.response_count), 0).label("resp_count"),
        )
        .filter(
            DailyBookingStats.venue_id.in_(venue_ids),
            DailyBookingStats.date >= c_start,
            DailyBookingStats.date <= c_end,
        )
        .first()
    )

    requests = int(bkg_row.requests if bkg_row else 0)
    accepted = int(bkg_row.accepted if bkg_row else 0)
    rejected = int(bkg_row.rejected if bkg_row else 0)
    confirmed = int(bkg_row.confirmed if bkg_row else 0)
    tot_resp_time = int(bkg_row.resp_time if bkg_row else 0)
    resp_cnt = int(bkg_row.resp_count if bkg_row else 0)

    # Views
    views = (
        db.query(func.coalesce(func.sum(DailySearchStats.total_venue_views), 0))
        .filter(
            DailySearchStats.venue_id.in_(venue_ids),
            DailySearchStats.date >= c_start,
            DailySearchStats.date <= c_end,
        )
        .scalar()
        or 0
    )

    # Acceptance Rate = Accepted / (Accepted + Rejected)
    total_decided = accepted + rejected
    acceptance_rate = round((accepted / total_decided) * 100.0, 1) if total_decided > 0 else 100.0

    # Avg Response Time
    avg_resp_sec = int(tot_resp_time / max(1, resp_cnt)) if resp_cnt > 0 else 0

    # Occupancy Rate: ratio of confirmed booking days to total days * active venues
    num_days = max(1, (c_end - c_start).days + 1)
    total_capacity_slots = len(venue_ids) * num_days
    occupancy_rate = min(100.0, round((confirmed / max(1, total_capacity_slots)) * 100.0, 1))

    kpis = OwnerKpis(
        gross_revenue_paise=gross_rev,
        net_revenue_paise=net_rev,
        platform_fee_paise=plat_fee,
        occupancy_rate_pct=occupancy_rate,
        avg_response_time_seconds=avg_resp_sec,
        avg_response_time_human=_format_human_duration(avg_resp_sec),
        acceptance_rate_pct=acceptance_rate,
        total_requests=requests,
        confirmed_bookings=confirmed,
    )

    # Owner Funnel: Views -> Requests -> Accepted -> Confirmed
    f1 = views
    f2 = requests
    f3 = accepted
    f4 = confirmed

    funnel = [
        FunnelStage(
            stage="views",
            label="Venue Views",
            count=f1,
            dropoff_rate=0.0,
            conversion_rate=100.0 if f1 > 0 else 0.0,
        ),
        FunnelStage(
            stage="requests",
            label="Booking Requests",
            count=f2,
            dropoff_rate=round(max(0.0, ((f1 - f2) / max(1, f1)) * 100.0), 1),
            conversion_rate=round((f2 / max(1, f1)) * 100.0, 1),
        ),
        FunnelStage(
            stage="accepted",
            label="Accepted Requests",
            count=f3,
            dropoff_rate=round(max(0.0, ((f2 - f3) / max(1, f2)) * 100.0), 1),
            conversion_rate=round((f3 / max(1, f1)) * 100.0, 1),
        ),
        FunnelStage(
            stage="confirmed",
            label="Confirmed Bookings",
            count=f4,
            dropoff_rate=round(max(0.0, ((f3 - f4) / max(1, f3)) * 100.0), 1),
            conversion_rate=round((f4 / max(1, f1)) * 100.0, 1),
        ),
    ]

    # Benchmarks against Platform Average
    plat_bkg = (
        db.query(
            func.coalesce(func.sum(DailyBookingStats.accepted_requests), 0).label("accepted"),
            func.coalesce(func.sum(DailyBookingStats.rejected_requests), 0).label("rejected"),
            func.coalesce(func.sum(DailyBookingStats.total_response_time_seconds), 0).label(
                "resp_time"
            ),
            func.coalesce(func.sum(DailyBookingStats.response_count), 0).label("resp_count"),
            func.coalesce(func.sum(DailyBookingStats.confirmed_bookings), 0).label("confirmed"),
        )
        .filter(
            DailyBookingStats.venue_id.is_(None),
            DailyBookingStats.date >= c_start,
            DailyBookingStats.date <= c_end,
        )
        .first()
    )

    plat_accepted = int(plat_bkg.accepted if plat_bkg else 0)
    plat_rejected = int(plat_bkg.rejected if plat_bkg else 0)
    plat_resp_time = int(plat_bkg.resp_time if plat_bkg else 0)
    plat_resp_cnt = int(plat_bkg.resp_count if plat_bkg else 0)
    plat_decided = plat_accepted + plat_rejected

    plat_acceptance_rate = (
        round((plat_accepted / plat_decided) * 100.0, 1) if plat_decided > 0 else 85.0
    )
    plat_avg_resp_sec = int(plat_resp_time / max(1, plat_resp_cnt)) if plat_resp_cnt > 0 else 7200
    plat_conv_rate = 5.0  # standard baseline

    benchmarks = OwnerBenchmarks(
        acceptance_rate_pct=acceptance_rate,
        platform_acceptance_rate_pct=plat_acceptance_rate,
        avg_response_time_seconds=avg_resp_sec,
        platform_avg_response_time_seconds=plat_avg_resp_sec,
        conversion_rate_pct=round((confirmed / max(1, views)) * 100.0, 1),
        platform_conversion_rate_pct=plat_conv_rate,
    )

    # Trends for owner venues
    trends = _build_daily_trends(db, c_start, c_end, venue_ids=venue_ids)

    return OwnerAnalyticsOverview(
        kpis=kpis,
        funnel=funnel,
        trends=trends,
        benchmarks=benchmarks,
        period=period,
        start_date=c_start.isoformat(),
        end_date=c_end.isoformat(),
    )


def _build_daily_trends(
    db: Session,
    start_date: date,
    end_date: date,
    venue_id: UUID | None = None,
    venue_ids: list[UUID] | None = None,
) -> list[DailyTrendPoint]:
    """Assemble chronological daily points for charting."""
    curr = start_date
    date_keys = []
    trend_map = {}

    while curr <= end_date:
        d_str = curr.isoformat()
        date_keys.append(d_str)
        trend_map[d_str] = DailyTrendPoint(date=d_str)
        curr += timedelta(days=1)

    # Rev query
    rev_q = db.query(
        DailyRevenueStats.date,
        func.sum(DailyRevenueStats.gross_merchandise_value_paise).label("gmv"),
        func.sum(DailyRevenueStats.platform_fee_paise).label("fee"),
    ).filter(
        DailyRevenueStats.date >= start_date,
        DailyRevenueStats.date <= end_date,
    )
    if venue_ids is not None:
        rev_q = rev_q.filter(DailyRevenueStats.venue_id.in_(venue_ids))
    elif venue_id is not None:
        rev_q = rev_q.filter(DailyRevenueStats.venue_id == venue_id)
    else:
        rev_q = rev_q.filter(DailyRevenueStats.venue_id.is_(None))

    for row in rev_q.group_by(DailyRevenueStats.date).all():
        d_str = row.date.isoformat()
        if d_str in trend_map:
            trend_map[d_str].gmv_paise = int(row.gmv or 0)
            trend_map[d_str].platform_fee_paise = int(row.fee or 0)

    # Bkg query
    bkg_q = db.query(
        DailyBookingStats.date,
        func.sum(DailyBookingStats.total_requests).label("requests"),
        func.sum(DailyBookingStats.confirmed_bookings).label("confirmed"),
    ).filter(
        DailyBookingStats.date >= start_date,
        DailyBookingStats.date <= end_date,
    )
    if venue_ids is not None:
        bkg_q = bkg_q.filter(DailyBookingStats.venue_id.in_(venue_ids))
    elif venue_id is not None:
        bkg_q = bkg_q.filter(DailyBookingStats.venue_id == venue_id)
    else:
        bkg_q = bkg_q.filter(DailyBookingStats.venue_id.is_(None))

    for row in bkg_q.group_by(DailyBookingStats.date).all():
        d_str = row.date.isoformat()
        if d_str in trend_map:
            trend_map[d_str].requests_count = int(row.requests or 0)
            trend_map[d_str].confirmed_count = int(row.confirmed or 0)

    # Search query
    search_q = db.query(
        DailySearchStats.date,
        func.sum(DailySearchStats.total_searches).label("searches"),
        func.sum(DailySearchStats.total_venue_views).label("views"),
    ).filter(
        DailySearchStats.date >= start_date,
        DailySearchStats.date <= end_date,
    )
    if venue_ids is not None:
        search_q = search_q.filter(DailySearchStats.venue_id.in_(venue_ids))
    elif venue_id is not None:
        search_q = search_q.filter(DailySearchStats.venue_id == venue_id)
    else:
        search_q = search_q.filter(DailySearchStats.venue_id.is_(None))

    for row in search_q.group_by(DailySearchStats.date).all():
        d_str = row.date.isoformat()
        if d_str in trend_map:
            trend_map[d_str].searches_count = int(row.searches or 0)
            trend_map[d_str].views_count = int(row.views or 0)

    return [trend_map[k] for k in date_keys]


def export_analytics_csv(
    db: Session,
    scope: str = "admin",
    owner_id: UUID | None = None,
    period: str = "30d",
) -> str:
    """Generate a CSV report for analytics."""
    c_start, c_end, _, _ = parse_period_dates(period)
    output = io.StringIO()
    writer = csv.writer(output)

    if scope == "owner" and owner_id:
        v_ids = [r[0] for r in db.query(Venue.id).filter(Venue.owner_id == owner_id).all()]
        trends = _build_daily_trends(db, c_start, c_end, venue_ids=v_ids)
        writer.writerow(
            [
                "Date",
                "Gross Revenue (INR)",
                "Platform Fee (INR)",
                "Net Payout (INR)",
                "Requests",
                "Confirmed Bookings",
                "Views",
            ]
        )
        for p in trends:
            writer.writerow(
                [
                    p.date,
                    f"{p.gmv_paise / 100:.2f}",
                    f"{p.platform_fee_paise / 100:.2f}",
                    f"{(p.gmv_paise - p.platform_fee_paise) / 100:.2f}",
                    p.requests_count,
                    p.confirmed_count,
                    p.views_count,
                ]
            )
    else:
        trends = _build_daily_trends(db, c_start, c_end, venue_id=None)
        writer.writerow(
            [
                "Date",
                "GMV (INR)",
                "Platform Fee (INR)",
                "Searches",
                "Views",
                "Requests",
                "Confirmed Bookings",
            ]
        )
        for p in trends:
            writer.writerow(
                [
                    p.date,
                    f"{p.gmv_paise / 100:.2f}",
                    f"{p.platform_fee_paise / 100:.2f}",
                    p.searches_count,
                    p.views_count,
                    p.requests_count,
                    p.confirmed_count,
                ]
            )

    return output.getvalue()


def backfill_historical_data(db: Session) -> int:
    """Backfill analytics_events from existing operational bookings and ledger entries.

    Ensures existing databases immediately have analytics data.
    """
    bookings = db.query(Booking).all()
    events_created = 0

    for bkg in bookings:
        # Check if booking.requested exists
        existing_req = (
            db.query(AnalyticsEvent)
            .filter(
                AnalyticsEvent.booking_id == bkg.id,
                AnalyticsEvent.event_name == "booking.requested",
            )
            .first()
        )
        if not existing_req:
            record_raw_event(
                db,
                event_name="booking.requested",
                booking_id=bkg.id,
                user_id=bkg.user_id,
                venue_id=bkg.venue_id,
                payload={"venue_name": getattr(bkg.venue, "name", "") if bkg.venue else ""},
                occurred_at=bkg.created_at,
            )
            events_created += 1

        if bkg.status in (BookingStatus.confirmed, BookingStatus.completed):
            existing_conf = (
                db.query(AnalyticsEvent)
                .filter(
                    AnalyticsEvent.booking_id == bkg.id,
                    AnalyticsEvent.event_name == "booking.confirmed",
                )
                .first()
            )
            if not existing_conf:
                gross = bkg.quoted_price_paise or 0
                fee = int(gross * 0.10)
                record_raw_event(
                    db,
                    event_name="booking.confirmed",
                    booking_id=bkg.id,
                    user_id=bkg.user_id,
                    venue_id=bkg.venue_id,
                    payload={
                        "venue_name": getattr(bkg.venue, "name", "") if bkg.venue else "",
                        "gross_amount_paise": gross,
                        "platform_fee_paise": fee,
                    },
                    occurred_at=bkg.updated_at or bkg.created_at,
                )
                events_created += 1

    db.commit()

    # Trigger aggregation over the past 30 days
    if events_created > 0:
        run_aggregation(db, start_date=datetime.now(UTC).date() - timedelta(days=60))

    return events_created
