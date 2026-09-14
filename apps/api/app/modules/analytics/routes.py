from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    AdminAnalyticsOverview,
    AggregationResult,
    OwnerAnalyticsOverview,
)
from app.modules.auth.dependencies import (
    AuthContext,
    require_admin,
    require_owner,
)

admin_analytics_router = APIRouter(prefix="/api/admin/analytics", tags=["admin-analytics"])
owner_analytics_router = APIRouter(prefix="/api/owner/analytics", tags=["owner-analytics"])


# ---------------------------------------------------------------------------
# Admin Analytics Read Endpoints
# ---------------------------------------------------------------------------


@admin_analytics_router.get("/overview", response_model=AdminAnalyticsOverview)
def get_admin_analytics_overview(
    period: str = Query("30d", pattern="^(7d|30d|90d|12m)$"),
    start_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Retrieve comprehensive platform analytics overview: GMV, Funnel, Top Venues, Trends."""
    return service.get_admin_overview(
        db,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )


@admin_analytics_router.get("/export")
def export_admin_analytics(
    period: str = Query("30d", pattern="^(7d|30d|90d|12m)$"),
    _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Export daily analytics data as CSV for reporting and audit."""
    csv_data = service.export_analytics_csv(db, scope="admin", period=period)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=platform_analytics_{period}.csv"},
    )


@admin_analytics_router.post("/aggregate", response_model=AggregationResult)
def trigger_aggregation(
    start_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """On-demand trigger for rollup aggregation job."""
    from datetime import datetime

    s_dt = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    e_dt = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    return service.run_aggregation(db, start_date=s_dt, end_date=e_dt)


@admin_analytics_router.post("/backfill")
def trigger_backfill(
    _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Backfill raw analytics events and rollups from historical bookings."""
    created = service.backfill_historical_data(db)
    return {"status": "ok", "events_created": created}


# ---------------------------------------------------------------------------
# Owner Analytics Read Endpoints
# ---------------------------------------------------------------------------


@owner_analytics_router.get("/overview", response_model=OwnerAnalyticsOverview)
def get_owner_analytics_overview(
    venue_id: UUID | None = Query(None),
    period: str = Query("30d", pattern="^(7d|30d|90d|12m)$"),
    start_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    auth: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Retrieve owner analytics: Revenue, Occupancy, Response Time, Acceptance Rate, Benchmarks."""
    return service.get_owner_overview(
        db,
        owner_id=auth.user_id,
        venue_id=venue_id,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )


@owner_analytics_router.get("/export")
def export_owner_analytics(
    period: str = Query("30d", pattern="^(7d|30d|90d|12m)$"),
    auth: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Export owner venue analytics as CSV."""
    csv_data = service.export_analytics_csv(db, scope="owner", owner_id=auth.user_id, period=period)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=owner_analytics_{period}.csv"},
    )
