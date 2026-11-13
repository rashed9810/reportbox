"""Database tables. Each maps to an HL7 FHIR resource where one fits (see app/fhir.py)."""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (works the same on SQLite and Postgres)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Lab(Base):  # FHIR Organization
    __tablename__ = "labs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    name_bn: Mapped[str | None] = mapped_column(String(200))
    sms_sender_id: Mapped[str | None] = mapped_column(String(11))  # masking ID, max 11 chars
    dghs_licence: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(300))
    plan: Mapped[str] = mapped_column(String(20), default="growth")  # see app/plans.py
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)  # e.g. 50 for founding labs
    discount_until: Mapped[date | None] = mapped_column(Date)  # last day the discount applies
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LabRecallRule(Base):
    """A lab's own reminder setting for one test. No row = the default from app/catalog.py."""
    __tablename__ = "lab_recall_rules"
    __table_args__ = (UniqueConstraint("lab_id", "test_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True)
    test_code: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    days: Mapped[int | None] = mapped_column(Integer)


class Staff(Base):  # FHIR Practitioner / PractitionerRole
    __tablename__ = "staff"
    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="reception")  # admin | reception
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Two-step sign-in (authenticator app). The secret is stored encrypted.
    totp_secret_enc: Mapped[str | None] = mapped_column(String(300))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_last_step: Mapped[int | None] = mapped_column(Integer)  # blocks reusing the same code
    lab: Mapped[Lab] = relationship()


class StaffSession(Base):
    __tablename__ = "staff_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class PhoneAccount(Base):
    """One verified phone number. A household key, not a person: it can hold many patients."""
    __tablename__ = "phone_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(13), unique=True, index=True)  # 8801XXXXXXXXX
    language: Mapped[str] = mapped_column(String(2), default="bn")
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)  # chosen by the patient in the app
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Patient(Base):  # FHIR Patient. Owned by the lab that registered them.
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True)
    phone_account_id: Mapped[int] = mapped_column(ForeignKey("phone_accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    sex: Mapped[str] = mapped_column(String(1))  # F | M | O
    birth_year: Mapped[int | None] = mapped_column(Integer)
    lab_mrn: Mapped[str | None] = mapped_column(String(50))  # the lab's own patient number
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    phone_account: Mapped[PhoneAccount] = relationship()
    lab: Mapped[Lab] = relationship()


class Consent(Base):  # FHIR Consent
    """Two separate scopes, never bundled:
    - lab_delivery: patient agreed this lab may send their reports digitally (recorded by staff)
    - wallet: phone owner agreed to see reports from all labs in one place (given in the app)
    """
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | revoked
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), index=True)
    phone_account_id: Mapped[int | None] = mapped_column(ForeignKey("phone_accounts.id"), index=True)
    lab_id: Mapped[int | None] = mapped_column(ForeignKey("labs.id"))
    method: Mapped[str] = mapped_column(String(20))  # verbal_at_counter | otp_in_app
    guardian_name: Mapped[str | None] = mapped_column(String(120))  # under-18 patients
    recorded_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class Report(Base):  # FHIR DiagnosticReport (PDF = presentedForm)
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    test_codes: Mapped[list] = mapped_column(JSON, default=list)  # keys of TEST_CATALOG
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    file_key: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    recall: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | sent
    link_token: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by_staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    patient: Mapped[Patient] = relationship()
    lab: Mapped[Lab] = relationship()


class Recall(Base):  # FHIR ServiceRequest (status=draft) for the repeat test
    __tablename__ = "recalls"
    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    test_code: Mapped[str] = mapped_column(String(30))
    due_date: Mapped[datetime] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="scheduled")  # scheduled | sent | returned | cancelled
    source_report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    returned_report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"))
    patient: Mapped[Patient] = relationship()


class Share(Base):  # FHIR Consent with a time-limited provision
    __tablename__ = "shares"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    phone_account_id: Mapped[int] = mapped_column(ForeignKey("phone_accounts.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    report_ids: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    patient: Mapped[Patient] = relationship()


class OtpCode(Base):
    __tablename__ = "otp_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(13), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PatientSession(Base):
    __tablename__ = "patient_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    phone_account_id: Mapped[int] = mapped_column(ForeignKey("phone_accounts.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Message(Base):
    """Every SMS or WhatsApp message sent. Used for billing and delivery status."""
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int | None] = mapped_column(ForeignKey("labs.id"), index=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), index=True)
    phone: Mapped[str] = mapped_column(String(13))
    channel: Mapped[str] = mapped_column(String(10), default="sms")  # sms | whatsapp
    kind: Mapped[str] = mapped_column(String(20))  # report_ready | otp | recall
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | sent | failed
    provider_ref: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Invoice(Base):
    """One lab's bill for one Bangladesh calendar month. Amounts are in paisa (100 paisa = 1 taka)
    so overage like BDT 0.60 per message adds up exactly."""
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("lab_id", "period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    plan: Mapped[str] = mapped_column(String(20))
    base_paisa: Mapped[int] = mapped_column(Integer)
    discount_paisa: Mapped[int] = mapped_column(Integer, default=0)
    reports_used: Mapped[int] = mapped_column(Integer)
    reports_included: Mapped[int] = mapped_column(Integer)
    messages_used: Mapped[int] = mapped_column(Integer)
    messages_included: Mapped[int] = mapped_column(Integer)
    overage_paisa: Mapped[int] = mapped_column(Integer, default=0)
    vat_paisa: Mapped[int] = mapped_column(Integer, default=0)
    total_paisa: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="unpaid")  # unpaid | verifying | paid | void
    due_date: Mapped[date] = mapped_column(Date)
    payment_method: Mapped[str | None] = mapped_column(String(10))  # bkash | nagad | bank | cash
    payment_ref: Mapped[str | None] = mapped_column(String(60))  # the bKash/Nagad TrxID
    payment_submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    lab: Mapped[Lab] = relationship()


class LoginFailure(Base):
    """Wrong staff passwords, to lock an email out for 15 minutes after too many tries."""
    __tablename__ = "login_failures"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), index=True)
    ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditEvent(Base):  # FHIR AuditEvent
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(10))  # staff | patient | doctor | system
    actor_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    lab_id: Mapped[int | None] = mapped_column(Integer, index=True)
    ip: Mapped[str | None] = mapped_column(String(45))
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
