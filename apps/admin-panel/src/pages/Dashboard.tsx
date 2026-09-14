import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../lib/AuthContext'
import {
  MetricCard, ActivityItem,
  SectionHeader, StatusBadge, EmptyState,
  type DashboardMetric,
} from '@venue404/ui'
import {
  Building2, UserCheck,
  CalendarDays, ClipboardList,
  CheckCircle2, XCircle, Clock,
  RefreshCw, TrendingUp, IndianRupee,
  Filter, Download, Heart, Calculator, Star,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { AdminLayout } from '../components/AdminLayout'
import { createClient, ApiError } from '@venue404/api-client'
import {
  adminActionEndpoints,
  adminUserEndpoints,
  adminBookingEndpoints,
  adminVenueEndpoints,
  adminAnalyticsEndpoints,
} from '@venue404/api-client'
import { GrowthChart } from '../components/GrowthChart'

const client = createClient()
const actionsApi = adminActionEndpoints(client)
const usersApi = adminUserEndpoints(client)
const bookingsApi = adminBookingEndpoints(client)
const venuesApi = adminVenueEndpoints(client)
const analyticsApi = adminAnalyticsEndpoints(client)

const METRIC_TEMPLATES: DashboardMetric[] = [
  {
    label: 'Pending Approvals',
    value: '—',
    description: 'Venues awaiting approval',
    icon: <Building2 className="h-4 w-4" />,
    accent: 'amber',
  },
  {
    label: 'Active Bookings',
    value: '—',
    description: 'Confirmed this month',
    icon: <CalendarDays className="h-4 w-4" />,
    accent: 'brand',
  },
  {
    label: 'Venue Owners',
    value: '—',
    description: 'Registered on platform',
    icon: <UserCheck className="h-4 w-4" />,
    accent: 'emerald',
  },
  {
    label: 'Open Actions',
    value: '—',
    description: 'Total admin actions logged',
    icon: <ClipboardList className="h-4 w-4" />,
    accent: 'violet',
  },
]

const today = new Date().toLocaleDateString('en-IN', {
  weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
})

function formatCurrency(paise: number): string {
  const rupees = paise / 100
  if (rupees >= 10000000) return `₹${(rupees / 10000000).toFixed(2)} Cr`
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(2)} L`
  if (rupees >= 1000) return `₹${(rupees / 1000).toFixed(1)} K`
  return `₹${rupees.toLocaleString('en-IN')}`
}

function actionLabel(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function actionIcon(type: string) {
  if (type.endsWith('approved') || type.endsWith('reactivated') || type.endsWith('completed'))
    return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
  if (type.endsWith('rejected') || type.endsWith('suspended') || type.endsWith('deleted'))
    return <XCircle className="h-3.5 w-3.5 text-red-400" />
  return <CheckCircle2 className="h-3.5 w-3.5 text-brand-secondary" />
}

function actionBadge(type: string) {
  if (type.includes('suspend')) return <StatusBadge label="Suspended" variant="danger" dot={false} />
  if (type.includes('reactivat')) return <StatusBadge label="Reactivated" variant="success" dot={false} />
  if (type.includes('approved')) return <StatusBadge label="Approved" variant="success" dot={false} />
  if (type.includes('rejected')) return <StatusBadge label="Rejected" variant="warning" dot={false} />
  return null
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function suppressAuthErrors(e: unknown) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) throw e
  return null
}

export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [period, setPeriod] = useState('30d')

  const { data: actionsData, isLoading: actionsLoading } = useQuery({
    queryKey: ['admin', 'dashboard', 'actions'],
    queryFn: () => actionsApi.listActions({ limit: 4 }).catch(suppressAuthErrors),
  })

  const { data: ownerStats } = useQuery({
    queryKey: ['admin', 'dashboard', 'owner-stats'],
    queryFn: () => usersApi.getOwnerStats().catch(suppressAuthErrors),
  })

  const { data: bookingStats } = useQuery({
    queryKey: ['admin', 'dashboard', 'booking-stats'],
    queryFn: () => bookingsApi.getStats().catch(suppressAuthErrors),
  })

  const { data: venueStats } = useQuery({
    queryKey: ['admin', 'dashboard', 'venue-stats'],
    queryFn: () => venuesApi.getVenueStats().catch(suppressAuthErrors),
  })

  // CQRS Analytics Query
  const { data: analyticsData, isLoading: analyticsLoading } = useQuery({
    queryKey: ['admin', 'analytics', 'overview', period],
    queryFn: () => analyticsApi.getOverview(period).catch(suppressAuthErrors),
  })

  const recentActions = actionsData?.items ?? []
  const actionsTotal = actionsData?.total ?? null

  const metrics = METRIC_TEMPLATES.map((m) => {
    if (m.label === 'Pending Approvals') return { ...m, value: venueStats ? String(venueStats.pending_approval) : '—' }
    if (m.label === 'Active Bookings') return { ...m, value: bookingStats ? String(bookingStats.confirmed) : '—' }
    if (m.label === 'Venue Owners') return { ...m, value: ownerStats ? String(ownerStats.total) : '—' }
    if (m.label === 'Open Actions') return { ...m, value: actionsTotal !== null ? String(actionsTotal) : '—' }
    return m
  })

  const firstName = user?.profile.full_name?.split(' ')[0] ?? null

  const handleExport = () => {
    window.open(`/api/admin/analytics/export?period=${period}`, '_blank')
  }

  return (
    <AdminLayout pageTitle="Dashboard" pageSubtitle={today}>
      {/* Welcome */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-zinc-900">
            {firstName ? `Good to see you, ${firstName}` : 'Welcome back'}
          </h2>
          <p className="mt-0.5 text-sm text-zinc-500">
            Platform health, revenue metrics, and booking conversion pipeline.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-lg border border-zinc-200 bg-white p-1 text-xs">
            {['7d', '30d', '90d', '12m'].map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPeriod(p)}
                className={`rounded px-2.5 py-1 font-medium transition-colors ${
                  period === p ? 'bg-zinc-900 text-white shadow-sm' : 'text-zinc-600 hover:text-zinc-900'
                }`}
              >
                {p.toUpperCase()}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={handleExport}
            className="flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 shadow-sm transition-colors hover:bg-zinc-50"
          >
            <Download className="h-3.5 w-3.5 text-zinc-400" />
            CSV
          </button>
        </div>
      </div>

      {/* Operational Metrics */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((m, i) => (
          <div key={m.label} className="card-enter" style={{ '--index': i } as React.CSSProperties}>
            <MetricCard {...m} />
          </div>
        ))}
      </div>

      {/* CQRS Financial & Conversion Funnel Cards */}
      <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">Gross Merchandise Value</span>
            <div className="rounded-lg bg-emerald-50 p-2 text-emerald-600">
              <IndianRupee className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold tracking-tight text-zinc-900">
              {analyticsData ? formatCurrency(analyticsData.kpis.gmv_paise) : '—'}
            </span>
          </div>
          <p className="mt-1 text-xs text-zinc-500">
            Total booking volume processed ({period.toUpperCase()})
          </p>
        </div>

        <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">Platform Take-Rate Revenue</span>
            <div className="rounded-lg bg-indigo-50 p-2 text-indigo-600">
              <TrendingUp className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold tracking-tight text-zinc-900">
              {analyticsData ? formatCurrency(analyticsData.kpis.platform_revenue_paise) : '—'}
            </span>
          </div>
          <p className="mt-1 text-xs text-zinc-500">
            Platform commissions and fees earned
          </p>
        </div>

        <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">Search-to-Booking Conversion</span>
            <div className="rounded-lg bg-amber-50 p-2 text-amber-600">
              <Filter className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold tracking-tight text-zinc-900">
              {analyticsData ? `${analyticsData.kpis.conversion_rate_pct}%` : '—'}
            </span>
          </div>
          <p className="mt-1 text-xs text-zinc-500">
            Search query to confirmed booking completion rate
          </p>
        </div>
      </div>

      {/* Booking Conversion Funnel Visualizer */}
      <div className="mt-5 rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
        <SectionHeader
          title="Booking Conversion Funnel"
          description="Lightweight CQRS read model aggregating search -> view -> request -> confirmed"
          className="mb-4"
        />
        {analyticsLoading ? (
          <div className="flex items-center justify-center py-10">
            <RefreshCw className="h-5 w-5 animate-spin text-zinc-300" />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            {analyticsData?.funnel.map((f, idx) => (
              <div
                key={f.stage}
                className="relative flex flex-col justify-between rounded-lg border border-zinc-100 bg-zinc-50/70 p-4 transition-all hover:bg-zinc-50"
              >
                <div>
                  <div className="flex items-center justify-between text-xs font-medium text-zinc-500">
                    <span>{f.label}</span>
                    <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-[10px] text-zinc-700">
                      Step {idx + 1}
                    </span>
                  </div>
                  <div className="mt-2 text-xl font-bold text-zinc-900">
                    {f.count.toLocaleString('en-IN')}
                  </div>
                </div>
                <div className="mt-3 border-t border-zinc-200/60 pt-2 text-[11px] text-zinc-500">
                  {idx > 0 ? (
                    <div className="flex justify-between">
                      <span>Drop-off:</span>
                      <span className="font-semibold text-rose-500">{f.dropoff_rate}%</span>
                    </div>
                  ) : (
                    <div className="flex justify-between">
                      <span>Initial Pool:</span>
                      <span className="font-semibold text-zinc-700">100%</span>
                    </div>
                  )}
                  <div className="mt-0.5 flex justify-between">
                    <span>Overall rate:</span>
                    <span className="font-semibold text-emerald-600">{f.conversion_rate}%</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Audience Signals & Pre-Booking Intent */}
      {analyticsData?.engagement && (
        <div className="mt-5 rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
          <SectionHeader
            title="Pre-Booking Signals & User Engagement"
            description="Active customer intent, search explorations, quotes, and engagement telemetry"
            className="mb-4"
          />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-lg border border-zinc-100 bg-zinc-50/70 p-4 transition-all hover:bg-zinc-50">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">Wishlist Saves</span>
                <div className="rounded-lg bg-rose-50 p-2 text-rose-600">
                  <Heart className="h-4 w-4" />
                </div>
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-900">
                {analyticsData.engagement.wishlist_adds.toLocaleString('en-IN')}
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                {analyticsData.engagement.wishlist_removes > 0
                  ? `${analyticsData.engagement.wishlist_adds - analyticsData.engagement.wishlist_removes} net saves (${analyticsData.engagement.wishlist_removes} removed)`
                  : 'Customer saved venue intent'}
              </p>
            </div>

            <div className="rounded-lg border border-zinc-100 bg-zinc-50/70 p-4 transition-all hover:bg-zinc-50">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">Calendar Inquiries</span>
                <div className="rounded-lg bg-sky-50 p-2 text-sky-600">
                  <CalendarDays className="h-4 w-4" />
                </div>
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-900">
                {analyticsData.engagement.availability_checks.toLocaleString('en-IN')}
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                Active date availability lookups
              </p>
            </div>

            <div className="rounded-lg border border-zinc-100 bg-zinc-50/70 p-4 transition-all hover:bg-zinc-50">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">Quotes Generated</span>
                <div className="rounded-lg bg-violet-50 p-2 text-violet-600">
                  <Calculator className="h-4 w-4" />
                </div>
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-900">
                {analyticsData.engagement.pricing_previews.toLocaleString('en-IN')}
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                Instant pricing previews calculated
              </p>
            </div>

            <div className="rounded-lg border border-zinc-100 bg-zinc-50/70 p-4 transition-all hover:bg-zinc-50">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">Review Health</span>
                <div className="rounded-lg bg-amber-50 p-2 text-amber-600">
                  <Star className="h-4 w-4" />
                </div>
              </div>
              <div className="mt-2 flex items-baseline gap-1 text-2xl font-bold text-zinc-900">
                <span>{analyticsData.engagement.avg_review_rating > 0 ? analyticsData.engagement.avg_review_rating.toFixed(1) : '—'}</span>
                {analyticsData.engagement.avg_review_rating > 0 && <span className="text-xs font-medium text-amber-500">★</span>}
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                {analyticsData.engagement.reviews_submitted} customer reviews submitted
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Content grid: Top Venues, Actions, and Growth Chart */}
      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-3">

        {/* Top Venues CQRS Widget */}
        <div className="card-enter rounded-xl border border-zinc-200 bg-white shadow-sm">
          <div className="border-b border-zinc-100 px-5 py-4">
            <SectionHeader title="Top Venues by Revenue" description={`Ranked by GMV (${period.toUpperCase()})`} />
          </div>
          <div className="p-4">
            {!analyticsData || analyticsData.top_venues.length === 0 ? (
              <EmptyState
                icon={<Building2 className="h-4 w-4" />}
                title="No venue activity"
                description="Venue performance metrics will appear here."
              />
            ) : (
              <div className="divide-y divide-zinc-100">
                {analyticsData.top_venues.map((tv, rank) => (
                  <div key={tv.venue_id} className="flex items-center justify-between py-3">
                    <div className="flex items-center gap-3">
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-zinc-100 text-xs font-bold text-zinc-600">
                        {rank + 1}
                      </span>
                      <div>
                        <div className="text-xs font-semibold text-zinc-900">{tv.venue_name}</div>
                        <div className="text-[11px] text-zinc-400">
                          {tv.city || 'Location N/A'} • {tv.confirmed_bookings} bookings
                        </div>
                      </div>
                    </div>
                    <div className="text-right text-xs font-bold text-zinc-900">
                      {formatCurrency(tv.gmv_paise)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Recent audit actions */}
        <div className="card-enter rounded-xl border border-zinc-200 bg-white shadow-sm">
          <div className="border-b border-zinc-100 px-5 py-4">
            <SectionHeader
              title="Recent Admin Actions"
              action={
                <button
                  type="button"
                  onClick={() => navigate('/audit-log')}
                  className="press text-xs font-medium text-brand transition-colors hover:text-brand"
                >
                  Full log
                </button>
              }
            />
          </div>

          {actionsLoading && (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="h-4 w-4 animate-spin text-zinc-300" />
            </div>
          )}

          {!actionsLoading && recentActions.length === 0 && (
            <div className="px-5 py-4">
              <EmptyState
                icon={<ClipboardList className="h-4 w-4" />}
                title="No actions yet"
                description="Admin actions will appear here."
              />
            </div>
          )}

          {!actionsLoading && recentActions.length > 0 && (
            <ul className="divide-y divide-zinc-100 px-5">
              {recentActions.map((a) => (
                <li key={a.id}>
                  <ActivityItem
                    title={actionLabel(a.action_type)}
                    description={a.reason ?? a.target_type}
                    timestamp={timeAgo(a.created_at)}
                    icon={actionIcon(a.action_type)}
                    badge={actionBadge(a.action_type) ?? undefined}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Platform growth chart */}
        <div className="card-enter rounded-xl border border-zinc-200 bg-white shadow-sm" style={{ minHeight: 320 }}>
          <GrowthChart />
        </div>
      </div>

      {/* Quick actions */}
      <div className="card-enter mt-5 rounded-xl border border-zinc-200 bg-white px-5 py-4 shadow-sm">
        <SectionHeader title="Quick actions" className="mb-3" />
        <div className="flex flex-wrap gap-2">
          {[
            { label: 'Review pending venues', href: '/venues/pending', icon: <Building2 className="h-3.5 w-3.5" /> },
            { label: 'Manage users', href: '/users', icon: <UserCheck className="h-3.5 w-3.5" /> },
            { label: 'Open audit log', href: '/audit-log', icon: <ClipboardList className="h-3.5 w-3.5" /> },
            { label: 'Active bookings', href: '/bookings', icon: <Clock className="h-3.5 w-3.5" /> },
          ].map((a) => (
            <button
              key={a.href}
              type="button"
              onClick={() => navigate(a.href)}
              className="press flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs font-medium text-zinc-700 transition-colors duration-150 hover:border-zinc-300 hover:bg-zinc-100"
            >
              <span className="text-zinc-400" aria-hidden="true">{a.icon}</span>
              {a.label}
            </button>
          ))}
        </div>
      </div>
    </AdminLayout>
  )
}
