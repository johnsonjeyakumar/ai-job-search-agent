"""One-shot Phase 5 backfill: compute match + opportunity for every stored job.

Idempotent: rows are created or refreshed in place. Run from ``backend/``::

    python -m app.scripts.phase5_backfill

The scores reflect the user's current profile/preferences (or the application
defaults when none are stored) evaluated against each job posting.
"""
from __future__ import annotations

import logging

from app.database.session import SessionLocal
from app.services import matches_service

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with SessionLocal() as db:
        recomputed = matches_service.recalculate_all(db)
        summary = matches_service.stats_summary(db)
        logging.info("Phase 5 backfill complete: %d job(s) updated", recomputed)
        logging.info(
            "Avg match %s / avg opportunity %s, evaluated jobs %s",
            summary.get("average_match_score"),
            summary.get("average_opportunity_score"),
            summary.get("evaluated_jobs"),
        )
        counts = summary.get("recommendation_counts", {})
        for band, count in sorted(counts.items()):
            logging.info("  %-12s %s", band, count)


if __name__ == "__main__":
    main()
