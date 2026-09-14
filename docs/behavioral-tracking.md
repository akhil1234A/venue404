# Behavioral Tracking & User Signals Documentation

**Status:** Shipped — verified against code and test suite, 2026-09-14.

---

## 1. Overview & Architecture

Behavioral Tracking & User Signals extends Venue404's event-driven CQRS analytics pipeline to measure pre-booking customer intent, user interest, and post-booking engagement. 

### Why Behavioral Signals?
Standard transaction metrics (GMV, bookings, cancellations) only show downstream outcomes. Behavioral telemetry reveals:
- **Wishlist Activity:** High-intent signals indicating venues users love or save for later.
- **Availability & Pricing Checks:** How many users actively explore dates and pricing quotes before dropping off or converting.
- **Review Submissions:** Feedback velocity and ratings health across venues.
- **Booking Detail Inspects:** User and venue owner engagement with pending/active bookings.

### End-to-End Flow
```
1. User Interaction (Wishlist toggle, Pricing preview, Calendar check, Review submit, Booking view)
                           │
                           ▼
2. Domain Event Emitted (WishlistToggledEvent, PricingPreviewedEvent, etc.)
                           │
                           ▼
3. Analytics Handler (@subscribe in analytics_handler.py)
                           │
                           ▼ (Append-only write path)
4. PostgreSQL raw log: analytics_events (event_name: 'engagement.*')
                           │
                           ▼
5. Daily Aggregator Job: analytics_aggregator.py (_aggregate_day_engagement)
                           │
                           ▼ (ON CONFLICT DO UPDATE upsert)
6. Materialized table: daily_engagement_stats (per-venue & platform-wide)
                           │
                           ▼
7. Hybrid Read Path: _build_engagement_kpis() in analytics/service.py
                           │
                           ▼
8. Admin & Owner Dashboards (EngagementKpis included in /overview endpoints)
```

---

## 2. Summary of Changes

### 2.1. Domain Events (`app/events/registry.py` & `app/events/__init__.py`)
Added 5 typed domain events inheriting from `DomainEvent`:
- `WishlistToggledEvent`: `venue_id: UUID`, `user_id: UUID`, `action: str` (`"add"` or `"remove"`), `venue_name: str`
- `ReviewSubmittedEvent`: `venue_id: UUID`, `user_id: UUID`, `booking_id: UUID`, `rating: int`
- `AvailabilityCheckedEvent`: `venue_id: UUID`, `user_id: UUID | None`, `booking_date: str`, `booking_type: str`
- `PricingPreviewedEvent`: `venue_id: UUID`, `user_id: UUID | None`, `booking_type: str`
- `BookingDetailViewedEvent`: `booking_id: UUID`, `user_id: UUID`

### 2.2. Event Ingestion (`app/events/handlers/analytics_handler.py`)
Registered 5 subscriber handlers logging raw telemetry to `analytics_events`:
- `engagement.wishlist_toggled`
- `engagement.review_submitted`
- `engagement.availability_checked`
- `engagement.pricing_previewed`
- `engagement.booking_detail_viewed`

- **`apps/api/app/modules/venue/routes.py`**:
  - `POST /venues/{venue_id}/like` → Emits `WishlistToggledEvent` (`action="add"` or `"remove"`).
  - `GET /venues/{venue_id}/pricing-preview` → Emits `PricingPreviewedEvent`.
- **`apps/api/app/modules/availability/routes.py`**:
  - `GET /venues/{venue_id}/quote` → Emits `PricingPreviewedEvent` (used by slot & hourly pricing quotes).
  - `GET /venues/{venue_id}/calendar` → Emits `AvailabilityCheckedEvent`.
  - `GET /venues/{venue_id}/date/{booking_date}` → Emits `AvailabilityCheckedEvent`.
  - `GET /venues/{venue_id}/availability` → Emits `AvailabilityCheckedEvent`.
- **`apps/api/app/modules/review/service.py`**:
  - `create_review()` → Emits `ReviewSubmittedEvent` upon committing review.
- **`apps/api/app/modules/booking/routes.py`**:
  - `GET /bookings/{booking_id}` → Emits `BookingDetailViewedEvent`.

### 2.4. Database Model & Migration (`apps/api/app/modules/analytics/models.py`)
Added `DailyEngagementStats` model:
- Primary key: `id` (UUID)
- Dimensions: `date` (Date), `venue_id` (UUID, nullable for platform-wide rollup)
- Metrics:
  - `wishlist_adds`: integer
  - `wishlist_removes`: integer
  - `reviews_submitted`: integer
  - `avg_review_rating`: float
  - `availability_checks`: integer
  - `pricing_previews`: integer
  - `booking_detail_views`: integer
  - `unique_engaged_users`: integer
- Unique constraint: `uq_daily_engagement_stats_date_venue` on `(date, coalesce(venue_id, '00000000-0000-0000-0000-000000000000'::uuid))`
- Migration: `alembic/versions/e9ecc0d19b2f_add_daily_engagement_stats_table.py`

### 2.5. Aggregation Logic & Dashboards (`apps/api/app/modules/analytics/service.py`)
- `_aggregate_day_engagement(db, target_date, d_start, d_end)`: Rolls up all 5 engagement event types into `DailyEngagementStats` using PostgreSQL `ON CONFLICT DO UPDATE`.
- `_build_engagement_kpis(db, start_date, end_date, venue_ids)`: Queries materialized rollups to compute net wishlist adds, total views, checks, previews, reviews, and average rating.
- Integrated into:
  - `run_aggregation()`: Aggregates daily engagement along with bookings, revenue, and search.
  - `get_admin_overview()`: Returns platform-wide `EngagementKpis`.
  - `get_owner_overview()`: Returns venue-scoped `EngagementKpis`.

### 2.6. API Schema & Frontend Types
- `EngagementKpis` schema added in `apps/api/app/modules/analytics/schemas.py`.
- Exported in TypeScript client: `packages/api-client/src/endpoints/analytics.ts`.

---

## 3. How to Test: Automated Testing

### 3.1. Run Dedicated CQRS & Behavioral Unit Tests
Execute the test suite via Docker:
```bash
docker compose exec api pytest tests/test_analytics_cqrs.py -v
```
Or locally inside `apps/api`:
```powershell
cd apps/api
pytest tests/test_analytics_cqrs.py -v
```
**Expected Result:**
```text
tests/test_analytics_cqrs.py::test_analytics_handler_wishlist_toggled PASSED
tests/test_analytics_cqrs.py::test_analytics_handler_review_submitted PASSED
tests/test_analytics_cqrs.py::test_analytics_handler_availability_checked PASSED
tests/test_analytics_cqrs.py::test_analytics_handler_pricing_previewed PASSED
tests/test_analytics_cqrs.py::test_analytics_handler_booking_detail_viewed PASSED
tests/test_analytics_cqrs.py::test_build_engagement_kpis PASSED
======================== 13 passed in 0.70s ========================
```

### 3.2. Run Linter & Style Checks
```bash
docker compose exec api ruff check app tests/test_analytics_cqrs.py
```
**Expected Result:**
```text
All checks passed!
```

### 3.3. Run Frontend Typecheck
Verify that all web apps compile with the updated API client types:
```bash
pnpm typecheck
```
**Expected Result:**
```text
apps/admin-panel typecheck: Done
apps/owner-portal typecheck: Done
apps/user-web typecheck: Done
```

---

## 4. How to Test: Manual End-to-End Testing

Follow these steps to generate user interactions, verify write-path telemetry in PostgreSQL, execute the aggregation job, and observe metrics in the API response.

### Prerequisites
- API running at `http://localhost:8000` (`docker compose up` or `pnpm dev:api`).
- PostgreSQL container running.
- A valid customer JWT access token and a venue UUID.

---

### Step 1: Trigger Behavioral Actions

#### Action A: Toggle Wishlist (Save Venue)
```bash
curl -X POST "http://localhost:8000/api/venues/<VENUE_ID>/like" \
  -H "Authorization: Bearer <CUSTOMER_TOKEN>" \
  -H "Content-Type: application/json"
```
**Expected response:** `{"liked": true, "likes_count": 1}`

#### Action B: Check Venue Calendar Availability
```bash
curl -X GET "http://localhost:8000/api/availability/venues/<VENUE_ID>/calendar?start_date=2026-08-31&end_date=2026-09-29&booking_type=full_day" \
  -H "Authorization: Bearer <CUSTOMER_TOKEN>"
```
**Expected response:** Calendar response JSON with `days`, `operating_window`, etc.

#### Action C: Check Dynamic Pricing Preview (Quote)
```bash
curl -X GET "http://localhost:8000/api/availability/venues/<VENUE_ID>/quote?starts_at=2026-09-19T06:30:00.000Z&ends_at=2026-09-19T07:30:00.000Z&booking_type=time_slot" \
  -H "Authorization: Bearer <CUSTOMER_TOKEN>"
```
Or via the venue router:
```bash
curl -X GET "http://localhost:8000/api/venues/<VENUE_ID>/pricing-preview?booking_type=hourly&start_time=10:00&end_time=14:00&event_date=2026-10-01" \
  -H "Authorization: Bearer <CUSTOMER_TOKEN>"
```
**Expected response:** Pricing quote JSON with `quoted_price_paise`, breakdown, etc.

#### Action D: View Booking Details
```bash
curl -X GET "http://localhost:8000/api/bookings/<BOOKING_ID>" \
  -H "Authorization: Bearer <CUSTOMER_TOKEN>"
```
**Expected response:** Booking object JSON.

---

### Step 2: Inspect Raw Events Table (Write Path)

Verify that events were persisted into `analytics_events`:
```bash
docker compose exec db psql -U postgres -d venue404 -c "
SELECT event_name, venue_id, user_id, payload, created_at 
FROM analytics_events 
WHERE event_name LIKE 'engagement.%' 
ORDER BY created_at DESC 
LIMIT 5;
"
```
**Expected output:**
You should see rows with:
- `engagement.wishlist_toggled` (payload: `{"action": "add", ...}`)
- `engagement.availability_checked`
- `engagement.pricing_previewed`
- `engagement.booking_detail_viewed`

---

### Step 3: Run the Rollup Aggregation Job

Trigger the aggregation job manually:

**Method 1: via Docker CLI**
```bash
docker compose exec api python scripts/run_job.py analytics_aggregator
```

**Method 2: via Python one-liner**
```bash
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.modules.analytics.service import run_aggregation
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
with SessionLocal() as db:
    res = run_aggregation(db, now - timedelta(days=2), now + timedelta(days=1))
    print('Engagement rows upserted:', res.engagement_rows_upserted)
"
```
**Expected output:**
```text
Aggregation complete: ... 2 engagement rows upserted
```

---

### Step 4: Verify Materialized Rollup Table

Query `daily_engagement_stats` in PostgreSQL:
```bash
docker compose exec db psql -U postgres -d venue404 -c "
SELECT date, venue_id, wishlist_adds, wishlist_removes, availability_checks, pricing_previews, booking_detail_views, unique_engaged_users
FROM daily_engagement_stats
ORDER BY date DESC
LIMIT 5;
"
```
**Expected output:**
Rollup rows showing non-zero values for `wishlist_adds`, `availability_checks`, `pricing_previews`, etc.

---

### Step 5: Verify Read Path (Overview Endpoints)

#### Admin Analytics Overview:
```bash
curl -X GET "http://localhost:8000/api/admin/analytics/overview?period=30d" \
  -H "Authorization: Bearer <ADMIN_TOKEN>"
```
**Response inspection:** Look for the `"engagement"` field in the JSON response:
```json
{
  "kpis": { ... },
  "funnel": [ ... ],
  "engagement": {
    "wishlist_adds": 1,
    "wishlist_removes": 0,
    "reviews_submitted": 0,
    "avg_review_rating": 0.0,
    "availability_checks": 1,
    "pricing_previews": 1,
    "booking_detail_views": 1,
    "unique_engaged_users": 1
  },
  "top_venues": [ ... ],
  "trends": [ ... ],
  "period": { ... }
}
```

#### Owner Analytics Overview:
```bash
curl -X GET "http://localhost:8000/api/owner/analytics/overview?period=30d" \
  -H "Authorization: Bearer <OWNER_TOKEN>"
```
**Response inspection:** Verify that `"engagement"` reflects the stats scoped specifically to the owner's venues.

---

## 5. Troubleshooting & FAQ

| Symptom | Cause | Solution |
|---|---|---|
| `engagement` field is all zeros in dashboard | Aggregation has not run yet, or dates requested are outside the range. | Trigger `scripts/run_job.py analytics_aggregator` or test with `period=30d`. |
| `alembic upgrade head` error on `uq_daily_engagement_stats_date_venue` | Older migration version out of sync. | Run `docker compose exec api alembic current` to verify head is `e9ecc0d19b2f`. |
| Wishlist toggle does not emit event | Endpoint returned 401 Unauthorized or 404 Venue Not Found. | Verify valid Customer Bearer token and existing active venue UUID. |
