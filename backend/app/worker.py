"""Background worker. Every 15 minutes it:
  - sends due repeat-test reminders, only during daytime hours in Bangladesh;
  - on the first days of each month, makes last month's invoices (skips labs already billed).

Run with `python -m app.worker`. Both jobs are safe to repeat.
"""
import logging
import time
from datetime import timedelta

from . import billing, recalls
from .config import get_settings
from .db import SessionLocal
from .models import utcnow

log = logging.getLogger("reportbox.worker")
CHECK_EVERY_SECONDS = 15 * 60


def run_once() -> int:
    """Send due reminders if it is daytime in Bangladesh. Returns how many were sent."""
    s = get_settings()
    bd_hour = (utcnow() + timedelta(hours=6)).hour
    if not (s.reminder_start_hour <= bd_hour < s.reminder_end_hour):
        return 0  # no reminder SMS at night
    db = SessionLocal()
    try:
        return recalls.send_due(db, today=recalls.bd_today())
    finally:
        db.close()


def bill_once() -> int:
    """On days 1-3 of the month, bill last month. Returns how many invoices were made."""
    today = billing.bd_now().date()
    if today.day > 3:
        return 0
    db = SessionLocal()
    try:
        return len(billing.generate_for_period(db, billing.previous_period(today)))
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("Worker started")
    while True:
        for name, job in (("reminders", run_once), ("invoices", bill_once)):
            try:
                n = job()
                if n:
                    log.info("%s: %s done", name, n)
            except Exception:
                log.exception("%s run failed; will retry", name)
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
