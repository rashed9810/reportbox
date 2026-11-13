"""Command-line helpers for running ReportBox (you, the operator, not the labs).

  Labs
    python -m app.cli seed
        Create a demo lab with two staff accounts (local testing only).
    python -m app.cli create-lab --name "City Diagnostic Centre" --name-bn "সিটি ডায়াগনস্টিক" \
        --sender CITYDIAG --plan growth --discount-percent 50 --discount-until 2027-05-31 \
        --admin-name "Owner" --admin-email owner@lab.com
        Create a real lab and its admin account. Prints a one-time password to change at first sign-in.
    python -m app.cli update-lab --lab-id 1 [--sender CITYDIAG] [--plan pro] [--licence X]
        [--discount-percent 50 --discount-until 2027-05-31]
        Change what only ReportBox may set: the approved SMS sender ID, the plan, the discount.
    python -m app.cli list-labs

  Reminders
    python -m app.cli send-recalls
        Send repeat-test reminders that are due now (the worker does this automatically).

  Billing
    python -m app.cli generate-invoices [--period 2026-10]
        Bill every lab for a finished month (default: last month). Safe to run twice.
    python -m app.cli list-invoices [--status verifying]
    python -m app.cli confirm-payment --invoice 12 [--method bkash --ref TRX123]
        Mark an invoice paid once you have seen the money arrive.
    python -m app.cli reject-payment --invoice 12 --reason "TrxID not found"
"""
import argparse
import secrets
import sys
from datetime import date

from sqlalchemy import select

from . import billing, recalls
from .db import Base, SessionLocal, engine
from .models import Invoice, Lab, Staff, utcnow
from .plans import PLANS, taka
from .security import hash_password


def _with_db(fn):
    """Give the command a database session and always close it, even when it stops with an error."""
    def run(argv: list[str] | None = None):
        db = SessionLocal()
        try:
            return fn(db, argv or [])
        finally:
            db.close()
    run.__name__ = fn.__name__
    return run


@_with_db
def seed(db, argv: list[str]) -> None:
    Base.metadata.create_all(engine)
    if db.scalar(select(Lab).where(Lab.name == "City Diagnostic Centre")):
        print("Demo lab already exists.")
        return
    lab = Lab(name="City Diagnostic Centre", name_bn="সিটি ডায়াগনস্টিক", sms_sender_id="CITYDIAG",
              address="Mirpur 10, Dhaka", dghs_licence="[DGHS LICENCE NO]", plan="growth")
    db.add(lab)
    db.flush()
    db.add_all([
        Staff(lab_id=lab.id, name="Lab Owner", email="owner@citydiag.test",
              password_hash=hash_password("owner-demo-123"), role="admin"),
        Staff(lab_id=lab.id, name="Shirin", email="reception@citydiag.test",
              password_hash=hash_password("reception-demo-123"), role="reception"),
    ])
    db.commit()
    print("Created demo lab.\n  owner@citydiag.test / owner-demo-123\n  reception@citydiag.test / reception-demo-123")


def _lab_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sender", help="Approved SMS sender ID (max 11 characters)")
    p.add_argument("--licence", help="DGHS licence number")
    p.add_argument("--plan", choices=list(PLANS))
    p.add_argument("--discount-percent", type=int)
    p.add_argument("--discount-until", type=date.fromisoformat, help="YYYY-MM-DD, last day of the discount")


def _apply_lab_options(lab: Lab, a) -> None:
    if a.sender is not None:
        if len(a.sender) > 11:
            sys.exit("Sender ID must be 11 characters or fewer")
        lab.sms_sender_id = a.sender or None
    if a.licence is not None:
        lab.dghs_licence = a.licence or None
    if a.plan:
        lab.plan = a.plan
    if a.discount_percent is not None:
        if not 0 <= a.discount_percent <= 100:
            sys.exit("Discount must be 0 to 100 percent")
        lab.discount_percent = a.discount_percent
    if a.discount_until is not None:
        lab.discount_until = a.discount_until
    if lab.discount_percent and not lab.discount_until:
        sys.exit("Give --discount-until with a discount")


@_with_db
def create_lab(db, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="create-lab")
    p.add_argument("--name", required=True)
    p.add_argument("--name-bn")
    p.add_argument("--address")
    p.add_argument("--admin-name", required=True)
    p.add_argument("--admin-email", required=True)
    _lab_options(p)
    a = p.parse_args(argv)
    email = a.admin_email.lower().strip()
    if db.scalar(select(Staff).where(Staff.email == email)):
        sys.exit(f"{email} already has an account")
    lab = Lab(name=a.name, name_bn=a.name_bn, address=a.address, plan="growth", discount_percent=0)
    _apply_lab_options(lab, a)
    db.add(lab)
    db.flush()
    password = secrets.token_urlsafe(9)
    db.add(Staff(lab_id=lab.id, name=a.admin_name, email=email, password_hash=hash_password(password), role="admin"))
    db.commit()
    print(f"Created lab #{lab.id} {a.name} on the {PLANS[lab.plan]['name']} plan\n  admin: {email}\n"
          f"  one-time password: {password}\n  Ask the owner to change it at first sign-in (Account & staff page).")


@_with_db
def update_lab(db, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="update-lab")
    p.add_argument("--lab-id", type=int, required=True)
    _lab_options(p)
    a = p.parse_args(argv)
    lab = db.get(Lab, a.lab_id)
    if not lab:
        sys.exit("No such lab")
    _apply_lab_options(lab, a)
    db.commit()
    print(f"Lab #{lab.id} {lab.name}: plan={lab.plan} sender={lab.sms_sender_id} "
          f"discount={lab.discount_percent}% until {lab.discount_until}")


@_with_db
def list_labs(db, argv: list[str]) -> None:
    for lab in db.scalars(select(Lab).order_by(Lab.id)):
        print(f"#{lab.id:<4} {lab.name:<34} plan={lab.plan:<8} sender={lab.sms_sender_id or '-':<11} "
              f"discount={lab.discount_percent}%{' until ' + str(lab.discount_until) if lab.discount_until else ''}")


@_with_db
def generate_invoices(db, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="generate-invoices")
    p.add_argument("--period", help="YYYY-MM (default: last month)")
    a = p.parse_args(argv)
    period = a.period or billing.previous_period()
    try:
        created = billing.generate_for_period(db, period)
    except ValueError as e:
        sys.exit(str(e))
    for inv in created:
        print(f"Invoice #{inv.id} {inv.lab.name} {period}: BDT {taka(inv.total_paisa)} due {inv.due_date}")
    print(f"{len(created)} new invoice(s) for {period}")


@_with_db
def list_invoices(db, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="list-invoices")
    p.add_argument("--status", choices=["unpaid", "verifying", "paid", "void"])
    a = p.parse_args(argv)
    q = select(Invoice).order_by(Invoice.period.desc(), Invoice.id)
    if a.status:
        q = q.where(Invoice.status == a.status)
    for inv in db.scalars(q):
        ref = f" {inv.payment_method} {inv.payment_ref}" if inv.payment_ref else ""
        print(f"#{inv.id:<5} {inv.period} {inv.lab.name:<30} BDT {taka(inv.total_paisa):>10}  {inv.status}{ref}")


@_with_db
def confirm_payment(db, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="confirm-payment")
    p.add_argument("--invoice", type=int, required=True)
    p.add_argument("--method", choices=["bkash", "nagad", "bank", "cash"])
    p.add_argument("--ref")
    a = p.parse_args(argv)
    inv = db.get(Invoice, a.invoice)
    if not inv:
        sys.exit("No such invoice")
    if inv.status == "paid":
        sys.exit("Already paid")
    inv.status, inv.paid_at = "paid", utcnow()
    inv.payment_method = a.method or inv.payment_method
    inv.payment_ref = a.ref or inv.payment_ref
    inv.note = None
    db.commit()
    print(f"Invoice #{inv.id} ({inv.lab.name}, {inv.period}) marked paid: {inv.payment_method} {inv.payment_ref}")


@_with_db
def reject_payment(db, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="reject-payment")
    p.add_argument("--invoice", type=int, required=True)
    p.add_argument("--reason", required=True)
    a = p.parse_args(argv)
    inv = db.get(Invoice, a.invoice)
    if not inv or inv.status != "verifying":
        sys.exit("Only an invoice waiting for checking can be rejected")
    inv.status, inv.note = "unpaid", a.reason[:300]
    db.commit()
    print(f"Invoice #{inv.id} back to unpaid: {a.reason}")


COMMANDS = {
    "create-lab": create_lab, "update-lab": update_lab, "generate-invoices": generate_invoices,
    "list-invoices": list_invoices, "confirm-payment": confirm_payment, "reject-payment": reject_payment,
}


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "seed":
        seed()
    elif cmd == "list-labs":
        list_labs()
    elif cmd == "send-recalls":
        _with_db(lambda db, argv: print(f"Sent {recalls.send_due(db)} reminders"))()
    elif cmd in COMMANDS:
        COMMANDS[cmd](sys.argv[2:])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
