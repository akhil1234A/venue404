import { createClient } from '../client'

export type FunnelStage = {
  stage: string
  label: string
  count: number
  dropoff_rate: number
  conversion_rate: number
}

export type AdminKpis = {
  gmv_paise: number
  gmv_change_pct: number | null
  platform_revenue_paise: number
  platform_revenue_change_pct: number | null
  confirmed_bookings: number
  bookings_change_pct: number | null
  conversion_rate_pct: number
}

export type TopVenuePerformance = {
  venue_id: string
  venue_name: string
  city: string | null
  gmv_paise: number
  confirmed_bookings: number
  views_count: number
}

export type DailyTrendPoint = {
  date: string
  gmv_paise: number
  platform_fee_paise: number
  requests_count: number
  confirmed_count: number
  searches_count: number
  views_count: number
}

export type EngagementKpis = {
  wishlist_adds: number
  wishlist_removes: number
  reviews_submitted: number
  avg_review_rating: number
  availability_checks: number
  pricing_previews: number
  booking_detail_views: number
  unique_engaged_users: number
}

export type AdminAnalyticsOverview = {
  kpis: AdminKpis
  funnel: FunnelStage[]
  top_venues: TopVenuePerformance[]
  trends: DailyTrendPoint[]
  engagement: EngagementKpis
  period: string
  start_date: string
  end_date: string
}

export type OwnerKpis = {
  gross_revenue_paise: number
  net_revenue_paise: number
  platform_fee_paise: number
  occupancy_rate_pct: number
  avg_response_time_seconds: number
  avg_response_time_human: string
  acceptance_rate_pct: number
  total_requests: number
  confirmed_bookings: number
}

export type OwnerBenchmarks = {
  acceptance_rate_pct: number
  platform_acceptance_rate_pct: number
  avg_response_time_seconds: number
  platform_avg_response_time_seconds: number
  conversion_rate_pct: number
  platform_conversion_rate_pct: number
}

export type OwnerAnalyticsOverview = {
  kpis: OwnerKpis
  funnel: FunnelStage[]
  trends: DailyTrendPoint[]
  benchmarks: OwnerBenchmarks
  engagement: EngagementKpis
  period: string
  start_date: string
  end_date: string
}

export const adminAnalyticsEndpoints = (client: ReturnType<typeof createClient>) => ({
  getOverview: (period = '30d'): Promise<AdminAnalyticsOverview> =>
    client.get<AdminAnalyticsOverview>(`/api/admin/analytics/overview?period=${encodeURIComponent(period)}`),

  triggerAggregate: (): Promise<{ status: string }> =>
    client.post<{ status: string }>('/api/admin/analytics/aggregate', {}),

  triggerBackfill: (): Promise<{ status: string; events_created: number }> =>
    client.post<{ status: string; events_created: number }>('/api/admin/analytics/backfill', {}),
})

export const ownerAnalyticsEndpoints = (client: ReturnType<typeof createClient>) => ({
  getOverview: (params: { period?: string; venue_id?: string } = {}): Promise<OwnerAnalyticsOverview> => {
    const qs = new URLSearchParams()
    if (params.period) qs.set('period', params.period)
    if (params.venue_id) qs.set('venue_id', params.venue_id)
    const q = qs.toString()
    return client.get<OwnerAnalyticsOverview>(`/api/owner/analytics/overview${q ? `?${q}` : ''}`)
  },
})

