import logging
from datetime import UTC, datetime, timedelta

from app.core.database import with_session
from app.modules.analytics.service import run_aggregation

logger = logging.getLogger(__name__)


def run() -> int:
    """Scheduled job: compute daily rollups for the previous day and today.

    Runs periodically (e.g. hourly / nightly) to keep materialized aggregate
    tables up to date without placing heavy ad-hoc load on transactional tables.
    """
    now = datetime.now(UTC).date()
    yesterday = now - timedelta(days=1)
    logger.info("Starting analytics rollup aggregation for %s to %s", yesterday, now)

    try:
        with with_session() as db:
            result = run_aggregation(db, start_date=yesterday, end_date=now)
            logger.info(
                "Aggregation complete: %d bookings, %d revenue, %d search rows upserted",
                result.booking_rows_upserted,
                result.revenue_rows_upserted,
                result.search_rows_upserted,
            )
            return (
                result.booking_rows_upserted
                + result.revenue_rows_upserted
                + result.search_rows_upserted
            )
    except Exception:
        logger.exception("Error executing analytics rollup aggregation job")
        return 0
