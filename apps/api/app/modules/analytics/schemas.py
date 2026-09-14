from uuid import UUID

from pydantic import BaseModel, Field


class FunnelStage(BaseModel):
    stage: str
    label: str
    count: int
    dropoff_rate: float = Field(
        ..., description="Percentage dropped off from previous stage (0-100)"
    )
    conversion_rate: float = Field(
        ..., description="Percentage converted from initial stage (0-100)"
    )


class AdminKpis(BaseModel):
    gmv_paise: int
    gmv_change_pct: float | None = None
    platform_revenue_paise: int
    platform_revenue_change_pct: float | None = None
    confirmed_bookings: int
    bookings_change_pct: float | None = None
    conversion_rate_pct: float


class TopVenuePerformance(BaseModel):
    venue_id: UUID
    venue_name: str
    city: str | None = None
    gmv_paise: int
    confirmed_bookings: int
    views_count: int


class DailyTrendPoint(BaseModel):
    date: str
    gmv_paise: int = 0
    platform_fee_paise: int = 0
    requests_count: int = 0
    confirmed_count: int = 0
    searches_count: int = 0
    views_count: int = 0


class AdminAnalyticsOverview(BaseModel):
    kpis: AdminKpis
    funnel: list[FunnelStage]
    top_venues: list[TopVenuePerformance]
    trends: list[DailyTrendPoint]
    period: str
    start_date: str
    end_date: str


class OwnerKpis(BaseModel):
    gross_revenue_paise: int
    net_revenue_paise: int
    platform_fee_paise: int
    occupancy_rate_pct: float
    avg_response_time_seconds: int
    avg_response_time_human: str
    acceptance_rate_pct: float
    total_requests: int
    confirmed_bookings: int


class OwnerBenchmarks(BaseModel):
    acceptance_rate_pct: float
    platform_acceptance_rate_pct: float
    avg_response_time_seconds: int
    platform_avg_response_time_seconds: int
    conversion_rate_pct: float
    platform_conversion_rate_pct: float


class OwnerAnalyticsOverview(BaseModel):
    kpis: OwnerKpis
    funnel: list[FunnelStage]
    trends: list[DailyTrendPoint]
    benchmarks: OwnerBenchmarks
    period: str
    start_date: str
    end_date: str


class AggregationResult(BaseModel):
    status: str
    dates_aggregated: list[str]
    booking_rows_upserted: int
    revenue_rows_upserted: int
    search_rows_upserted: int
