"""Monthly invoices for labs.

How a bill is worked out for one Bangladesh calendar month:
  plan price - founding discount + overage (extra reports and messages beyond the plan) + VAT

Payment: the lab owner pays by bKash/Nagad to the numbers in the settings and types the
transaction ID on the Billing page. The invoice then shows "checking" until you confirm it with
`python -m app.cli confirm-payment --invoice N` (after you see the money arrive).
"""
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Invoice, Lab, Message, Report, utcnow
from .plans import OVERAGE_PAISA_PER_MESSAGE, OVERAGE_PAISA_PER_REPORT, PAYMENT_DUE_DAY, get_plan

BD_OFFSET = timedelta(hours=6)


def bd_now() -> datetime:
    return utcnow() + BD_OFFSET


def period_of(d: date | datetime) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def previous_period(today: date | None = None) -> str:
    today = today or bd_now().date()
    first = today.replace(day=1)
    return period_of(first - timedelta(days=1))


def period_bounds_utc(period: str) -> tuple[datetime, datetime]:
    """Start and end of a Bangladesh calendar month, as naive UTC times (how the database stores them)."""
    y, m = (int(x) for x in period.split("-"))
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12), m % 12 + 1, 1)
    return start - BD_OFFSET, end - BD_OFFSET


def usage(db: Session, lab_id: int, period: str) -> dict:
    start, end = period_bounds_utc(period)
    reports = db.scalar(select(func.count(Report.id)).where(
        Report.lab_id == lab_id, Report.status == "sent", Report.created_at >= start, Report.created_at < end)) or 0
    messages = db.scalar(select(func.count(Message.id)).where(
        Message.lab_id == lab_id, Message.status.in_(("sent", "delivered")),
        Message.created_at >= start, Message.created_at < end)) or 0
    return {"reports": reports, "messages": messages}


def calculate(db: Session, lab: Lab, period: str) -> dict:
    plan = get_plan(lab.plan)
    u = usage(db, lab.id, period)
    base = plan["price_bdt"] * 100
    first_day = date.fromisoformat(f"{period}-01")
    discount = 0
    if lab.discount_percent and lab.discount_until and first_day <= lab.discount_until:
        discount = base * min(max(lab.discount_percent, 0), 100) // 100
    extra_reports = max(0, u["reports"] - plan["reports"])
    extra_messages = max(0, u["messages"] - plan["messages"])
    overage = extra_reports * OVERAGE_PAISA_PER_REPORT + extra_messages * OVERAGE_PAISA_PER_MESSAGE
    subtotal = base - discount + overage
    vat = round(subtotal * get_settings().vat_percent / 100)
    return {"plan": lab.plan, "plan_name": plan["name"], "base_paisa": base, "discount_paisa": discount,
            "reports_used": u["reports"], "reports_included": plan["reports"],
            "messages_used": u["messages"], "messages_included": plan["messages"],
            "extra_reports": extra_reports, "extra_messages": extra_messages,
            "overage_paisa": overage, "vat_paisa": vat, "total_paisa": subtotal + vat}


def due_date_for(period: str) -> date:
    y, m = (int(x) for x in period.split("-"))
    return date(y + (m == 12), m % 12 + 1, PAYMENT_DUE_DAY)


def generate_for_period(db: Session, period: str) -> list[Invoice]:
    """Create invoices for every lab for a finished month. Safe to run again: labs that already have
    an invoice for that month are skipped."""
    if period >= period_of(bd_now()):
        raise ValueError("Only finished months can be billed")
    _, end = period_bounds_utc(period)
    created = []
    for lab in db.scalars(select(Lab).where(Lab.created_at < end)).all():
        if db.scalar(select(Invoice.id).where(Invoice.lab_id == lab.id, Invoice.period == period)):
            continue
        c = calculate(db, lab, period)
        inv = Invoice(lab_id=lab.id, period=period, plan=c["plan"], base_paisa=c["base_paisa"],
                      discount_paisa=c["discount_paisa"], reports_used=c["reports_used"],
                      reports_included=c["reports_included"], messages_used=c["messages_used"],
                      messages_included=c["messages_included"], overage_paisa=c["overage_paisa"],
                      vat_paisa=c["vat_paisa"], total_paisa=c["total_paisa"], due_date=due_date_for(period))
        db.add(inv)
        created.append(inv)
    db.commit()
    return created


def invoice_out(inv: Invoice) -> dict:
    overdue = inv.status in ("unpaid",) and bd_now().date() > inv.due_date
    return {"id": inv.id, "number": f"RB-{inv.period.replace('-', '')}-{inv.lab_id:04d}", "period": inv.period,
            "plan": inv.plan, "plan_name": get_plan(inv.plan)["name"],
            "base_paisa": inv.base_paisa, "discount_paisa": inv.discount_paisa,
            "reports_used": inv.reports_used, "reports_included": inv.reports_included,
            "messages_used": inv.messages_used, "messages_included": inv.messages_included,
            "overage_paisa": inv.overage_paisa, "vat_paisa": inv.vat_paisa, "total_paisa": inv.total_paisa,
            "status": "overdue" if overdue else inv.status, "due_date": inv.due_date.isoformat(),
            "payment_method": inv.payment_method, "payment_ref": inv.payment_ref,
            "paid_at": inv.paid_at.isoformat() if inv.paid_at else None, "note": inv.note}
