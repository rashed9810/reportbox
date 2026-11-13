"""Repeat-test reminders: schedule when a report is sent, send when due, mark returned."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog import TEST_CATALOG
from .messaging import render, send_sms
from .models import Consent, Lab, LabRecallRule, Recall, Report, utcnow

RETURN_WINDOW_DAYS = 60  # a new test within this many days of the reminder counts as "came back"
BD_OFFSET = timedelta(hours=6)  # Bangladesh is UTC+6 all year; due dates use the Bangladesh calendar
MIN_DAYS, MAX_DAYS = 7, 730


def bd_today() -> date:
    return (utcnow() + BD_OFFSET).date()


def effective_rules(db: Session, lab_id: int) -> dict[str, int | None]:
    """test code -> reminder interval in days for this lab (None = no reminder)."""
    rules = {c: t["recall_days"] for c, t in TEST_CATALOG.items()}
    for r in db.scalars(select(LabRecallRule).where(LabRecallRule.lab_id == lab_id)):
        if r.test_code in rules:
            rules[r.test_code] = r.days if r.enabled else None
    return rules


def has_delivery_consent(db: Session, patient_id: int) -> bool:
    return bool(db.scalar(select(Consent.id).where(Consent.patient_id == patient_id, Consent.scope == "lab_delivery",
                                                   Consent.status == "active").limit(1)))


def schedule_for_report(db: Session, report: Report) -> list[Recall]:
    created = []
    if not report.recall:
        return created
    rules = effective_rules(db, report.lab_id)
    for code in report.test_codes:
        days = rules.get(code)
        if not days:
            continue
        # one open reminder per patient and test: replace any older scheduled one
        for old in db.scalars(select(Recall).where(Recall.patient_id == report.patient_id,
                                                   Recall.test_code == code, Recall.status == "scheduled")):
            old.status = "cancelled"
        r = Recall(lab_id=report.lab_id, patient_id=report.patient_id, test_code=code,
                   due_date=((report.sent_at or utcnow()) + BD_OFFSET).date() + timedelta(days=days),
                   source_report_id=report.id)
        db.add(r)
        created.append(r)
    return created


def cancel_for_patients(db: Session, patient_ids: list[int]) -> int:
    count = 0
    if not patient_ids:
        return count
    for r in db.scalars(select(Recall).where(Recall.patient_id.in_(patient_ids), Recall.status == "scheduled")):
        r.status = "cancelled"
        count += 1
    return count


def mark_returns(db: Session, report: Report) -> int:
    """Called when a new report is sent: a sent reminder for the same test now counts as returned."""
    cutoff = utcnow() - timedelta(days=RETURN_WINDOW_DAYS)
    count = 0
    for r in db.scalars(select(Recall).where(Recall.patient_id == report.patient_id, Recall.status == "sent",
                                             Recall.test_code.in_(report.test_codes))):
        if r.sent_at and r.sent_at >= cutoff:
            r.status, r.returned_report_id = "returned", report.id
            count += 1
    return count


def send_due(db: Session, today: date | None = None) -> int:
    """Send reminders that are due. Returns how many SMS were sent."""
    today = today or bd_today()
    due = db.scalars(select(Recall).where(Recall.status == "scheduled", Recall.due_date <= today)).all()
    sent = 0
    for r in due:
        # The patient may have stopped messages from this lab since the reminder was scheduled.
        if not has_delivery_consent(db, r.patient_id):
            r.status = "cancelled"
            continue
        lab = db.get(Lab, r.lab_id)
        patient = r.patient
        lang = patient.phone_account.language
        test = TEST_CATALOG[r.test_code]["name_bn" if lang == "bn" else "name"]
        lab_name = (lab.name_bn if lang == "bn" and lab.name_bn else lab.name)
        text = render("recall", lang, lab=lab_name, name=patient.name, test=test)
        # Reminders always go by SMS: WhatsApp would count them as marketing, about 20x the price.
        send_sms(db, phone=patient.phone_account.phone, kind="recall", text=text, lab=lab)
        r.status, r.sent_at = "sent", utcnow()
        sent += 1
    db.commit()
    return sent
