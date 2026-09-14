# Analytics Pipeline & CQRS

**Status:** Shipped — verified against code and test suite, 2026-09-14.

Covers the `analytics` module, event ingestion via the event bus, write/read path separation (CQRS), materialized aggregation rollups, manual job execution, historical backfill, and administrative & owner dashboards.

---

## 1. System Architecture & CQRS Pattern

Venue404 uses a lightweight Command Query Responsibility Segregation (CQRS) and Lambda-style architecture to isolate transactional writes from heavy analytical reads.

```
                    COMMAND (WRITE) PATH
User / Owner Actions (Search, View Venue, Book, Pay)
                     │
                     ▼
           Application Routers
                     │
                     ▼
           In-Memory Event Bus (publish)
                     │
                     ▼
        Analytics Handler (analytics_handler.py)
                     │
                     ▼ (append-only INSERT)
             analytics_events (PostgreSQL)

─────────────────────────────────────────────────────────
                  AGGREGATION / ROLLUP (CRON / JOBS)
   APScheduler / CLI (run_job.py) / POST /internal/run-jobs
                     │
                     ▼
         analytics_aggregator.py
                     │
                     ▼ (INSERT ... ON CONFLICT DO UPDATE)
  ┌───────────────────────┬───────────────────────┬──────────────────────┐
  │  daily_booking_stats  │  daily_revenue_stats  │  daily_search_stats  │
  └───────────────────────┴───────────────────────┴──────────────────────┘

─────────────────────────────────────────────────────────
                     QUERY (READ) PATH
          Admin Panel & Owner Portal Dashboards
                     │
                     ▼
  GET /api/admin/analytics/*  |  GET /api/owner/analytics/*
                     │
                     ▼
             analytics/service.py
    (Historical Rollups + Today's Live Events Union)
```

### Why CQRS for Analytics?
1. **Zero Transactional Lock Contention**: User search, booking creation, and payment webhooks do not perform expensive aggregations, index scans, or table locks. Events are appended directly to `analytics_events`.
2. **Immutable Audit Trail**: The `analytics_events` table is append-only (no updates, no deletes).
3. **Sub-millisecond Dashboard Reads**: Dashboards query pre-aggregated rollups (`daily_booking_stats`, `daily_revenue_stats`, `daily_search_stats`) for historical periods, combined with a fast index scan on `analytics_events` for today's live activity (Lambda architecture).

---

## 2. Data Models & Database Schema

Defined in [`apps/api/app/modules/analytics/models.py`](file:///c:/Users/Akhil%20Anwar/projects/Personal/venue/myVenue/apps/api/app/modules/analytics/models.py):

| Table | Nature | Key Columns & Indexes | Purpose |
|---|---|---|---|
| `analytics_events` | Append-only write log | `id` (UUID PK), `event_type`, `venue_id` (FK index), `user_id` (FK), `session_id`, `metadata_json`, `created_at` (index) | Captures granular telemetry from user interactions and lifecycle events. |
| `daily_booking_stats` | Materialized rollup | `date`, `venue_id` (Composite Unique Index: `date, venue_id`), `total_requests`, `total_accepted`, `total_rejected`, `total_cancelled`, `total_completed`, `avg_response_time_seconds` | Precomputed booking funnel & operational speed metrics. |
| `daily_revenue_stats` | Materialized rollup | `date`, `venue_id` (Composite Unique Index: `date, venue_id`), `gmv_paise`, `platform_fee_paise`, `owner_payout_paise`, `refunds_paise`, `transaction_count` | Precomputed gross merchandise value and revenue splits. |
| `daily_search_stats` | Materialized rollup | `date`, `city` (Composite Unique Index: `date, city`), `total_searches`, `unique_users`, `avg_results_count` | Precomputed demand and search discovery metrics. |

All financial numbers are strictly stored in integer **paise** (`BigInteger`), avoiding floating-point inaccuracies.

---

## 3. How It Works Normally (Lifecycle & Ingestion)

### Step 1: Event Ingestion (Write Side)
When actions happen across the application, domain events are dispatched onto the in-memory event bus:
- `SearchExecutedEvent`: Emitted from [`search/routes.py`](file:///c:/Users/Akhil%20Anwar/projects/Personal/venue/myVenue/apps/api/app/modules/search/routes.py) whenever a user executes a venue search query or filter.
- `VenueViewedEvent`: Emitted from [`venue/routes.py`](file:///c:/Users/Akhil%20Anwar/projects/Personal/venue/myVenue/apps/api/app/modules/venue/routes.py) when a public venue detail page is viewed.
- `BookingRequestedEvent`: Emitted upon new booking creation (`PENDING_OWNER`).
- `BookingAcceptedEvent` / `BookingRejectedEvent`: Emitted upon owner acceptance or rejection.
- `BookingCancelledEvent`: Emitted when a customer or owner cancels.
- `PaymentSucceededEvent` / `RefundProcessedEvent`: Emitted when Stripe webhooks complete.

[`analytics_handler.py`](file:///c:/Users/Akhil%20Anwar/projects/Personal/venue/myVenue/apps/api/app/events/handlers/analytics_handler.py) subscribes to each of these events and appends a corresponding record into `analytics_events`.

### Step 2: Rollup Aggregation (Scheduled Cron)
- In local development and monolithic deployments, the in-process **APScheduler** in [`app/jobs/scheduler.py`](file:///c:/Users/Akhil%20Anwar/projects/Personal/venue/myVenue/apps/api/app/jobs/scheduler.py) schedules `analytics_aggregator` to run **hourly** (`0 * * * *`).
- In production, serverless crons or GitHub Actions trigger `POST /api/internal/run-jobs?jobs=analytics_aggregator`.
- The aggregator queries `analytics_events` for past days and upserts rows into `daily_booking_stats`, `daily_revenue_stats`, and `daily_search_stats` with `ON CONFLICT DO UPDATE`.

### Step 3: Serving Dashboards (Hybrid Read Side)
When Admin or Owner dashboards request metrics via `/api/admin/analytics/overview` or `/api/owner/analytics/overview`:
1. Historical data between `start_date` and `yesterday` is read from `daily_*_stats` tables (instant index lookups).
2. Today's live events are queried directly from `analytics_events` where `created_at >= CURRENT_DATE`.
3. The query aggregates and sums both streams into a unified response containing:
   - **Admin:** GMV, Net Revenue, Take-Rate, 4-Stage Conversion Funnel (`Search → Venue View → Request → Confirmed`), and Top Venues ranking with CSV export.
   - **Owner:** Venue GMV, Net Payout, Occupancy Rate, Booking Acceptance Rate, Avg Response Time, and Platform Benchmarks comparison.

---

## 4. How to Manually Run the Job

You can manually trigger the aggregation job without waiting for the hourly scheduler.

### Method 1: Using the Project's Job Runner CLI (Recommended)
From the repository root or the `apps/api` folder:

```powershell
# Windows (PowerShell)
cd apps/api
.venv\Scripts\python.exe scripts/run_job.py analytics_aggregator

# Linux / macOS
cd apps/api
source .venv/bin/activate
python scripts/run_job.py analytics_aggregator
```

**Output example:**
```text
=== Running Job: analytics_aggregator ===
Starting analytics aggregation rollup...
Aggregated 12 booking stats, 10 revenue stats, 5 search stats rollup records.
Analytics aggregation complete. Total records updated: 27
Job 'analytics_aggregator' completed successfully in 0.05s.
```

### Method 2: One-Liner Python CLI
```powershell
cd apps/api
.venv\Scripts\python.exe -c "import app.models; from app.jobs.runner import run_job; print('Records updated:', run_job('analytics_aggregator'))"
```

### Method 3: HTTP API Trigger (Admin)
Send a POST request with an admin Bearer token:
```http
POST /api/admin/analytics/aggregate
Authorization: Bearer <ADMIN_ACCESS_TOKEN>
```
**Response (200 OK):**
```json
{
  "message": "Aggregation completed successfully.",
  "records_updated": 27
}
```

### Method 4: Internal Machine-to-Machine Runner Endpoint
```http
POST /api/internal/run-jobs?jobs=analytics_aggregator
```

---

## 5. Historical Backfill Procedure

If you have existing booking and payment records in the database that were created before the analytics pipeline was introduced, or if you reset the `analytics_events` table, run the built-in backfill utility.

### Running the Backfill
```powershell
cd apps/api
.venv\Scripts\python.exe -c "import app.models; from app.core.database import SessionLocal; from app.modules.analytics.service import backfill_historical_data; db = SessionLocal(); print('Events backfilled:', backfill_historical_data(db)); db.close()"
```

### What Backfill Does:
1. Scans existing `bookings` from the last 60 days.
2. Checks whether each booking already has corresponding events in `analytics_events` to avoid duplicate insertion.
3. Generates the synthetic write lifecycle for missing records:
   - `booking.requested` with creation timestamp
   - `booking.accepted` or `booking.rejected`
   - `booking.confirmed` with payment details
   - `booking.cancelled` if cancelled
4. Once completed, re-run the aggregation job (`scripts/run_job.py analytics_aggregator`) to materialize the backfilled data into daily rollups.

---

## 6. Testing & Quality Verification

### 1. Automated Test Suite
Run the dedicated CQRS integration and event bus test suites:

```powershell
cd apps/api
.venv\Scripts\python.exe -m pytest tests/test_analytics_cqrs.py tests/test_event_bus.py -v
```

This verifies:
- Event handlers subscribing and appending events to `analytics_events`.
- Ingestion of search, view, booking request, confirmed, cancelled, and payment events.
- Mathematical precision of rollup aggregation into daily tables.
- Hybrid querying (historical rollups + live today events).
- Top venues calculation and funnel conversion metrics.

### 2. Linting & Formatting Check
```powershell
cd apps/api
.venv\Scripts\python.exe -m ruff check app tests
```

### 3. Frontend Compilation Check
To verify that both web dashboards compile cleanly against the typed API client:

```powershell
pnpm --filter admin-panel build
pnpm --filter owner-portal build
```

---

## 7. Manual Testing Walkthrough

Follow this cycle to manually verify the entire loop end-to-end:

1. **Emit a Search Event**:
   - Navigate to user web application or perform a search request:
   ```http
   GET http://localhost:8000/api/search?city=Mumbai
   ```
2. **Emit a Venue View Event**:
   - Open a venue detail page or request:
   ```http
   GET http://localhost:8000/api/venues/<VENUE_ID>
   ```
3. **Verify Raw Events Table**:
   - Query PostgreSQL:
   ```sql
   SELECT event_type, venue_id, created_at FROM analytics_events ORDER BY created_at DESC LIMIT 5;
   ```
   You should see `search.executed` and `venue.viewed` recorded.
4. **Trigger Aggregation**:
   - Run:
   ```powershell
   cd apps/api
   .venv\Scripts\python.exe scripts/run_job.py analytics_aggregator
   ```
5. **Verify Dashboards**:
   - **Admin Panel** (`http://localhost:5174/`): Check the conversion funnel bar (Search → View → Request → Confirmed), GMV, and Top Venues table.
   - **Owner Portal** (`http://localhost:5173/`): Check venue occupancy rate, acceptance rate, response time, and comparison against platform benchmarks.
