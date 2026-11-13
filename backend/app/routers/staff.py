"""Lab-side API: reception staff and the lab owner."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import billing
from .. import recalls as recall_service
from .. import twofactor
from ..audit import audit
from ..catalog import TEST_CATALOG, validate_codes
from ..config import get_settings
from ..db import get_db
from ..deps import STAFF_COOKIE, current_admin, current_staff
from ..models import (Consent, Invoice, LabRecallRule, LoginFailure, Message, PhoneAccount, Patient, Recall,
                      Report, Share, Staff, StaffSession, utcnow)
from ..plans import PLANS, get_plan
from ..security import (hash_password, hash_token, new_link_token, new_token, normalize_bd_phone,
                        verify_password)
from ..storage import get_storage
from ..whatsapp import deliver_report

router = APIRouter(prefix="/api/staff", tags=["staff"])

BD_OFFSET = timedelta(hours=6)  # Bangladesh time is UTC+6 all year


def bd_today() -> date:
    return (utcnow() + BD_OFFSET).date()


# ---------- sign in ----------

class LoginIn(BaseModel):
    email: str
    password: str
    code: str | None = None  # two-step sign-in code, when turned on


def _record_failure(db: Session, email: str, request: Request) -> None:
    db.add(LoginFailure(email=email, ip=request.client.host if request.client else None))
    db.commit()


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    email = body.email.lower().strip()
    window = utcnow() - timedelta(minutes=15)
    failures = db.scalar(select(func.count(LoginFailure.id)).where(LoginFailure.email == email,
                                                                    LoginFailure.created_at >= window))
    if failures >= s.staff_login_max_failures:
        raise HTTPException(429, "Too many wrong attempts. Try again in 15 minutes.")
    staff = db.scalar(select(Staff).where(Staff.email == email))
    if not staff or not staff.active or not verify_password(body.password, staff.password_hash):
        _record_failure(db, email, request)
        raise HTTPException(401, "Wrong email or password")
    if staff.totp_enabled:
        if not body.code:
            # Password was right: ask for the code without counting a failure.
            raise HTTPException(401, "two_factor_required")
        step = twofactor.verify(twofactor.decrypt_secret(staff.totp_secret_enc), body.code, staff.totp_last_step)
        if step is None:
            _record_failure(db, email, request)
            raise HTTPException(401, "Wrong or expired code from the authenticator app")
        staff.totp_last_step = step
    db.execute(delete(LoginFailure).where(LoginFailure.email == email))
    token = new_token()
    db.add(StaffSession(token_hash=hash_token(token), staff_id=staff.id,
                        expires_at=utcnow() + timedelta(hours=s.staff_session_hours)))
    audit(db, request, actor_type="staff", actor_id=staff.id, action="login", entity="staff",
          entity_id=staff.id, lab_id=staff.lab_id)
    db.commit()
    response.set_cookie(STAFF_COOKIE, token, max_age=s.staff_session_hours * 3600, httponly=True,
                        secure=s.cookie_secure, samesite="lax", path="/")
    # The token is also returned for programs that use the API directly; the website ignores it.
    return {"token": token, "staff": _staff_out(staff)}


@router.post("/logout")
def logout(request: Request, response: Response, staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    token = request.cookies.get(STAFF_COOKIE) or request.headers.get("authorization", "").split(" ")[-1]
    db.execute(delete(StaffSession).where(StaffSession.token_hash == hash_token(token)))
    db.commit()
    response.delete_cookie(STAFF_COOKIE, path="/")
    return {"signed_out": True}


def _staff_out(s: Staff) -> dict:
    return {"id": s.id, "name": s.name, "role": s.role, "email": s.email, "two_factor": s.totp_enabled,
            "lab": {"id": s.lab.id, "name": s.lab.name, "sms_sender_id": s.lab.sms_sender_id}}


@router.get("/me")
def me(staff: Staff = Depends(current_staff)):
    return _staff_out(staff)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


def _check_password(pw: str) -> None:
    n = get_settings().min_password_length
    if len(pw) < n:
        raise HTTPException(422, f"Password must be at least {n} characters")


@router.post("/me/password")
def change_password(body: PasswordChangeIn, request: Request, staff: Staff = Depends(current_staff),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, staff.password_hash):
        raise HTTPException(400, "Current password is wrong")
    _check_password(body.new_password)
    staff.password_hash = hash_password(body.new_password)
    audit(db, request, actor_type="staff", actor_id=staff.id, action="password.change", entity="staff",
          entity_id=staff.id, lab_id=staff.lab_id)
    db.commit()
    return {"changed": True}


# ---------- two-step sign-in ----------

@router.post("/me/2fa/setup")
def two_factor_setup(staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    """Start setup: a new secret to scan into the authenticator app. Not active until confirmed."""
    if staff.totp_enabled:
        raise HTTPException(409, "Two-step sign-in is already on. Turn it off first to set up a new phone.")
    secret = twofactor.new_secret()
    staff.totp_secret_enc = twofactor.encrypt_secret(secret)
    staff.totp_last_step = None
    db.commit()
    return {"secret": secret, "otpauth_uri": twofactor.provisioning_uri(secret, staff.email)}


class CodeIn(BaseModel):
    code: str


@router.post("/me/2fa/enable")
def two_factor_enable(body: CodeIn, request: Request, staff: Staff = Depends(current_staff),
                      db: Session = Depends(get_db)):
    if staff.totp_enabled:
        raise HTTPException(409, "Two-step sign-in is already on")
    if not staff.totp_secret_enc:
        raise HTTPException(400, "Start the setup first")
    step = twofactor.verify(twofactor.decrypt_secret(staff.totp_secret_enc), body.code, None)
    if step is None:
        raise HTTPException(400, "That code is not right. Check the phone's time is correct and try the newest code.")
    staff.totp_enabled, staff.totp_last_step = True, step
    audit(db, request, actor_type="staff", actor_id=staff.id, action="2fa.enable", entity="staff",
          entity_id=staff.id, lab_id=staff.lab_id)
    db.commit()
    return {"two_factor": True}


class TwoFactorOffIn(BaseModel):
    password: str
    code: str


@router.post("/me/2fa/disable")
def two_factor_disable(body: TwoFactorOffIn, request: Request, staff: Staff = Depends(current_staff),
                       db: Session = Depends(get_db)):
    if not staff.totp_enabled:
        raise HTTPException(409, "Two-step sign-in is not on")
    if not verify_password(body.password, staff.password_hash):
        raise HTTPException(400, "Password is wrong")
    step = twofactor.verify(twofactor.decrypt_secret(staff.totp_secret_enc), body.code, staff.totp_last_step)
    if step is None:
        raise HTTPException(400, "Wrong or expired code")
    staff.totp_enabled, staff.totp_secret_enc, staff.totp_last_step = False, None, None
    audit(db, request, actor_type="staff", actor_id=staff.id, action="2fa.disable", entity="staff",
          entity_id=staff.id, lab_id=staff.lab_id)
    db.commit()
    return {"two_factor": False}


# ---------- staff accounts (lab admin only) ----------

class StaffIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    password: str
    role: str = Field("reception", pattern="^(admin|reception)$")


class StaffUpdate(BaseModel):
    active: bool | None = None
    password: str | None = None
    role: str | None = Field(None, pattern="^(admin|reception)$")
    reset_two_factor: bool = False  # for a lost phone


def _staff_row(s: Staff) -> dict:
    return {"id": s.id, "name": s.name, "email": s.email, "role": s.role, "active": s.active,
            "two_factor": s.totp_enabled}


@router.get("/staff")
def list_staff(admin: Staff = Depends(current_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(Staff).where(Staff.lab_id == admin.lab_id).order_by(Staff.id)).all()
    return [_staff_row(s) for s in rows]


@router.post("/staff", status_code=201)
def add_staff(body: StaffIn, request: Request, admin: Staff = Depends(current_admin), db: Session = Depends(get_db)):
    email = body.email.lower().strip()
    if "@" not in email:
        raise HTTPException(422, "Enter a valid email")
    if db.scalar(select(Staff).where(Staff.email == email)):
        raise HTTPException(409, "This email already has an account")
    _check_password(body.password)
    s = Staff(lab_id=admin.lab_id, name=body.name.strip(), email=email, role=body.role,
              password_hash=hash_password(body.password))
    db.add(s)
    db.flush()
    audit(db, request, actor_type="staff", actor_id=admin.id, action="staff.create", entity="staff",
          entity_id=s.id, lab_id=admin.lab_id)
    db.commit()
    return _staff_row(s)


@router.patch("/staff/{staff_id}")
def update_staff(staff_id: int, body: StaffUpdate, request: Request, admin: Staff = Depends(current_admin),
                 db: Session = Depends(get_db)):
    s = db.get(Staff, staff_id)
    if not s or s.lab_id != admin.lab_id:
        raise HTTPException(404, "Staff not found")
    if s.id == admin.id and (body.active is False or body.role == "reception" or body.reset_two_factor):
        raise HTTPException(400, "You cannot disable, demote or reset two-step sign-in on your own account here")
    if body.active is not None:
        s.active = body.active
        if not body.active:  # sign them out everywhere
            db.execute(delete(StaffSession).where(StaffSession.staff_id == s.id))
    if body.role:
        s.role = body.role
    if body.password:
        _check_password(body.password)
        s.password_hash = hash_password(body.password)
        db.execute(delete(StaffSession).where(StaffSession.staff_id == s.id))
    if body.reset_two_factor:
        s.totp_enabled, s.totp_secret_enc, s.totp_last_step = False, None, None
        db.execute(delete(StaffSession).where(StaffSession.staff_id == s.id))
    audit(db, request, actor_type="staff", actor_id=admin.id, action="staff.update", entity="staff",
          entity_id=s.id, lab_id=admin.lab_id, detail={"active": body.active, "role": body.role,
                                                        "password_reset": bool(body.password),
                                                        "two_factor_reset": body.reset_two_factor})
    db.commit()
    return _staff_row(s)


# ---------- lab settings (admin) ----------

def _rules_out(db: Session, lab_id: int) -> list[dict]:
    effective = recall_service.effective_rules(db, lab_id)
    return [{"test_code": c, "name": t["name"], "name_bn": t["name_bn"], "default_days": t["recall_days"],
             "enabled": effective[c] is not None, "days": effective[c] or t["recall_days"]}
            for c, t in TEST_CATALOG.items()]


@router.get("/catalog")
def catalog(staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    """Tests for the reception screen, with this lab's own reminder intervals."""
    rules = recall_service.effective_rules(db, staff.lab_id)
    return [{"code": k, **v, "recall_days": rules[k]} for k, v in TEST_CATALOG.items()]


@router.get("/lab")
def get_lab(admin: Staff = Depends(current_admin), db: Session = Depends(get_db)):
    lab = admin.lab
    plan = get_plan(lab.plan)
    return {"id": lab.id, "name": lab.name, "name_bn": lab.name_bn, "address": lab.address,
            "dghs_licence": lab.dghs_licence, "sms_sender_id": lab.sms_sender_id,
            "plan": lab.plan, "plan_name": plan["name"], "recall_rules": _rules_out(db, lab.id)}


class LabUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    name_bn: str | None = Field(None, max_length=200)
    address: str | None = Field(None, max_length=300)


@router.patch("/lab")
def update_lab(body: LabUpdate, request: Request, admin: Staff = Depends(current_admin), db: Session = Depends(get_db)):
    """Names and address. The SMS sender ID and plan are set by ReportBox (they need approval/billing)."""
    lab = admin.lab
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        v = v.strip() if isinstance(v, str) else v
        if k == "name":
            if not v or len(v) < 2:
                raise HTTPException(422, "The lab name cannot be empty")
            lab.name = v
        else:
            setattr(lab, k, v or None)
    audit(db, request, actor_type="staff", actor_id=admin.id, action="lab.update", entity="lab", entity_id=lab.id,
          lab_id=lab.id, detail=changes)
    db.commit()
    return get_lab(admin, db)


class RuleIn(BaseModel):
    test_code: str
    enabled: bool
    days: int | None = None


@router.put("/lab/recall-rules")
def set_recall_rules(rules: list[RuleIn], request: Request, admin: Staff = Depends(current_admin),
                     db: Session = Depends(get_db)):
    """Turn reminders on or off per test and set after how many days. Applies to reports sent from now on."""
    for r in rules:
        if r.test_code not in TEST_CATALOG:
            raise HTTPException(422, f"Unknown test: {r.test_code}")
        if r.enabled and not (r.days and recall_service.MIN_DAYS <= r.days <= recall_service.MAX_DAYS):
            raise HTTPException(422, f"{TEST_CATALOG[r.test_code]['name']}: days must be between "
                                     f"{recall_service.MIN_DAYS} and {recall_service.MAX_DAYS}")
    for r in rules:
        row = db.scalar(select(LabRecallRule).where(LabRecallRule.lab_id == admin.lab_id,
                                                    LabRecallRule.test_code == r.test_code))
        if not row:
            row = LabRecallRule(lab_id=admin.lab_id, test_code=r.test_code)
            db.add(row)
        row.enabled, row.days = r.enabled, (r.days if r.enabled else None)
    audit(db, request, actor_type="staff", actor_id=admin.id, action="lab.recall_rules", entity="lab",
          entity_id=admin.lab_id, lab_id=admin.lab_id, detail={"rules": [r.model_dump() for r in rules]})
    db.commit()
    return _rules_out(db, admin.lab_id)


# ---------- patients ----------

def _patient_out(p: Patient, db: Session) -> dict:
    consent = db.scalar(select(Consent).where(Consent.patient_id == p.id, Consent.scope == "lab_delivery",
                                              Consent.status == "active"))
    stopped = db.scalar(select(Consent.id).where(Consent.patient_id == p.id, Consent.scope == "lab_delivery",
                                                 Consent.status == "revoked").limit(1))
    return {"id": p.id, "name": p.name, "sex": p.sex, "birth_year": p.birth_year,
            "age": (bd_today().year - p.birth_year) if p.birth_year else None,
            "phone": p.phone_account.phone, "consent": bool(consent),
            "consent_withdrawn": bool(stopped) and not consent,
            "consent_recorded_at": consent.created_at.isoformat() if consent else None}


@router.get("/patients")
def search_patients(phone: str, staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    try:
        phone = normalize_bd_phone(phone)
    except ValueError as e:
        raise HTTPException(422, str(e))
    acct = db.scalar(select(PhoneAccount).where(PhoneAccount.phone == phone))
    if not acct:
        return []
    # staff only ever see patients registered by their own lab
    patients = db.scalars(select(Patient).where(Patient.phone_account_id == acct.id,
                                                Patient.lab_id == staff.lab_id).order_by(Patient.id)).all()
    return [_patient_out(p, db) for p in patients]


class PatientIn(BaseModel):
    phone: str
    name: str = Field(min_length=1, max_length=120)
    sex: str = Field(pattern="^[FMO]$")
    birth_year: int | None = Field(None, ge=1900, le=2100)
    consent_given: bool
    guardian_name: str | None = None


@router.post("/patients", status_code=201)
def create_patient(body: PatientIn, request: Request, staff: Staff = Depends(current_staff),
                   db: Session = Depends(get_db)):
    try:
        phone = normalize_bd_phone(body.phone)
    except ValueError as e:
        raise HTTPException(422, str(e))
    is_minor = body.birth_year is not None and bd_today().year - body.birth_year < 18
    if body.consent_given and is_minor and not body.guardian_name:
        raise HTTPException(422, "Patients under 18 need a parent or guardian's consent: enter the guardian's name")
    acct = db.scalar(select(PhoneAccount).where(PhoneAccount.phone == phone))
    if not acct:
        acct = PhoneAccount(phone=phone)
        db.add(acct)
        db.flush()
    p = Patient(lab_id=staff.lab_id, phone_account_id=acct.id, name=body.name.strip(), sex=body.sex,
                birth_year=body.birth_year)
    db.add(p)
    db.flush()
    if body.consent_given:
        db.add(Consent(scope="lab_delivery", patient_id=p.id, lab_id=staff.lab_id, method="verbal_at_counter",
                       guardian_name=body.guardian_name if is_minor else None, recorded_by_staff_id=staff.id))
    audit(db, request, actor_type="staff", actor_id=staff.id, action="patient.create", entity="patient",
          entity_id=p.id, lab_id=staff.lab_id)
    db.commit()
    return _patient_out(p, db)


@router.post("/patients/{patient_id}/consent")
def record_consent(patient_id: int, request: Request, guardian_name: str | None = None,
                   staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    p = _own_patient(db, staff, patient_id)
    is_minor = p.birth_year is not None and bd_today().year - p.birth_year < 18
    if is_minor and not guardian_name:
        raise HTTPException(422, "Patients under 18 need a guardian's consent")
    db.add(Consent(scope="lab_delivery", patient_id=p.id, lab_id=staff.lab_id, method="verbal_at_counter",
                   guardian_name=guardian_name if is_minor else None, recorded_by_staff_id=staff.id))
    audit(db, request, actor_type="staff", actor_id=staff.id, action="consent.record", entity="patient",
          entity_id=p.id, lab_id=staff.lab_id)
    db.commit()
    return _patient_out(p, db)


def _own_patient(db: Session, staff: Staff, patient_id: int) -> Patient:
    p = db.get(Patient, patient_id)
    if not p or p.lab_id != staff.lab_id:
        raise HTTPException(404, "Patient not found")
    return p


# ---------- reports ----------

def _report_out(r: Report, last: Message | None = None) -> dict:
    status = "opened" if r.first_opened_at else r.status
    if status == "sent" and last is not None and last.status == "failed":
        status = "sms_failed"
    return {"id": r.id, "title": r.title, "test_codes": r.test_codes, "status": status,
            "channel": last.channel if last is not None and last.status != "failed" else None,
            "patient": {"id": r.patient.id, "name": r.patient.name},
            "created_at": r.created_at.isoformat(), "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "opened_at": r.first_opened_at.isoformat() if r.first_opened_at else None,
            "recall": r.recall, "sensitive": r.sensitive, "file_size": r.file_size}


def _last_message(db: Session, report_id: int) -> Message | None:
    return db.scalar(select(Message).where(Message.report_id == report_id, Message.kind == "report_ready")
                     .order_by(Message.id.desc()).limit(1))


@router.post("/reports", status_code=201)
async def upload_report(request: Request, patient_id: int = Form(...), test_codes: str = Form(""),
                        title: str = Form(""), sensitive: bool = Form(False), recall: bool = Form(False),
                        file: UploadFile = File(...), staff: Staff = Depends(current_staff),
                        db: Session = Depends(get_db)):
    p = _own_patient(db, staff, patient_id)
    codes = [c.strip() for c in test_codes.split(",") if c.strip()]
    try:
        validate_codes(codes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    data = await file.read()
    limit = get_settings().max_pdf_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {get_settings().max_pdf_mb} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(422, "Only PDF reports can be uploaded")
    file_key, digest = get_storage().save(data)
    title = title.strip() or ", ".join(TEST_CATALOG[c]["name"] for c in codes) or "Lab report"
    r = Report(lab_id=staff.lab_id, patient_id=p.id, title=title, test_codes=codes, sensitive=sensitive,
               recall=recall, file_key=file_key, file_size=len(data), sha256=digest,
               created_by_staff_id=staff.id)
    db.add(r)
    db.flush()
    audit(db, request, actor_type="staff", actor_id=staff.id, action="report.upload", entity="report",
          entity_id=r.id, lab_id=staff.lab_id)
    db.commit()
    return _report_out(r)


@router.post("/reports/{report_id}/send")
def send_report(report_id: int, request: Request, staff: Staff = Depends(current_staff),
                db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if not r or r.lab_id != staff.lab_id:
        raise HTTPException(404, "Report not found")
    if not recall_service.has_delivery_consent(db, r.patient_id):
        raise HTTPException(409, "Record the patient's consent before sending")
    if not r.link_token:
        r.link_token = new_link_token()
    first_send = r.status != "sent"
    r.status, r.sent_at = "sent", utcnow()
    msg = deliver_report(db, r)  # WhatsApp if the patient chose it, otherwise SMS
    if first_send:
        recall_service.mark_returns(db, r)
        recall_service.schedule_for_report(db, r)
    audit(db, request, actor_type="staff", actor_id=staff.id, action="report.send", entity="report",
          entity_id=r.id, lab_id=staff.lab_id, detail={"message_status": msg.status, "channel": msg.channel})
    db.commit()
    out = _report_out(r, msg)
    out["message_status"] = msg.status
    out["channel"] = msg.channel
    if msg.status == "failed":
        out["message_error"] = msg.error
    return out


@router.get("/reports")
def list_reports(day: date | None = None, staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    """Reports created on a Bangladesh calendar day (default: today in Bangladesh)."""
    day = day or bd_today()
    start = datetime.combine(day, datetime.min.time()) - BD_OFFSET
    rows = db.scalars(select(Report).where(Report.lab_id == staff.lab_id, Report.created_at >= start,
                                           Report.created_at < start + timedelta(days=1))
                      .order_by(Report.created_at.desc())).all()
    return [_report_out(r, _last_message(db, r.id)) for r in rows]


# ---------- owner dashboard ----------

@router.get("/dashboard")
def dashboard(staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    lab = staff.lab
    period = billing.period_of(billing.bd_now())
    month_start, _ = billing.period_bounds_utc(period)

    def count(stmt):
        return db.scalar(stmt) or 0

    sent = count(select(func.count(Report.id)).where(Report.lab_id == lab.id, Report.sent_at >= month_start))
    opened = count(select(func.count(Report.id)).where(Report.lab_id == lab.id, Report.sent_at >= month_start,
                                                       Report.first_opened_at.is_not(None)))
    reminders_sent = count(select(func.count(Recall.id)).where(Recall.lab_id == lab.id, Recall.sent_at >= month_start))
    returned = count(select(func.count(Recall.id)).where(Recall.lab_id == lab.id, Recall.status == "returned",
                                                         Recall.sent_at >= month_start - timedelta(days=60)))
    shares = count(select(func.count(Share.id)).join(Patient, Share.patient_id == Patient.id)
                   .where(Patient.lab_id == lab.id, Share.created_at >= month_start))
    # Only messages that actually went out count, the same as on the bill.
    by_kind = dict(db.execute(select(Message.kind, func.count(Message.id))
                              .where(Message.lab_id == lab.id, Message.created_at >= month_start,
                                     Message.status.in_(("sent", "delivered")))
                              .group_by(Message.kind)).all())
    by_channel = dict(db.execute(select(Message.channel, func.count(Message.id))
                                 .where(Message.lab_id == lab.id, Message.created_at >= month_start,
                                        Message.status.in_(("sent", "delivered")))
                                 .group_by(Message.channel)).all())
    upcoming = db.execute(select(Recall.test_code, func.count(Recall.id))
                          .where(Recall.lab_id == lab.id, Recall.status == "scheduled",
                                 Recall.due_date <= bd_today() + timedelta(days=7))
                          .group_by(Recall.test_code)).all()
    plan = get_plan(lab.plan)
    open_invoice = db.scalar(select(Invoice).where(Invoice.lab_id == lab.id, Invoice.status == "unpaid")
                             .order_by(Invoice.period.desc()).limit(1))
    return {
        "month": period,
        "reports_sent": sent, "reports_opened": opened,
        "open_rate": round(opened / sent, 3) if sent else None,
        "reminders_sent": reminders_sent, "patients_returned": returned, "doctor_shares": shares,
        "messages": {"used": sum(by_kind.values()), "quota": plan["messages"], "by_kind": by_kind,
                     "by_channel": by_channel},
        "reports_quota": plan["reports"], "plan_name": plan["name"],
        "upcoming_reminders": [{"test_code": c, "name": TEST_CATALOG[c]["name"], "count": n} for c, n in upcoming],
        "unpaid_invoice": billing.invoice_out(open_invoice) if open_invoice else None,
    }


@router.post("/recalls/run")
def run_recalls(staff: Staff = Depends(current_admin), db: Session = Depends(get_db)):
    """Send reminders that are due now. The worker also does this automatically during the day."""
    return {"sent": recall_service.send_due(db)}


# ---------- billing (admin) ----------

@router.get("/billing")
def billing_overview(admin: Staff = Depends(current_admin), db: Session = Depends(get_db)):
    lab = admin.lab
    s = get_settings()
    period = billing.period_of(billing.bd_now())
    invoices = db.scalars(select(Invoice).where(Invoice.lab_id == lab.id).order_by(Invoice.period.desc())).all()
    return {
        "plan": lab.plan, "plans": PLANS,
        "discount_percent": lab.discount_percent,
        "discount_until": lab.discount_until.isoformat() if lab.discount_until else None,
        "this_month": {"period": period, **billing.calculate(db, lab, period)},
        "vat_percent": s.vat_percent,
        "pay_to": {"bkash": s.payment_bkash_number or None, "nagad": s.payment_nagad_number or None},
        "invoices": [billing.invoice_out(i) for i in invoices],
    }


class PaymentIn(BaseModel):
    method: str = Field(pattern="^(bkash|nagad|bank|cash)$")
    reference: str = Field(min_length=4, max_length=60)


@router.post("/billing/invoices/{invoice_id}/payment")
def submit_payment(invoice_id: int, body: PaymentIn, request: Request, admin: Staff = Depends(current_admin),
                   db: Session = Depends(get_db)):
    """The owner tells us they paid, with the transaction ID. ReportBox confirms after checking."""
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.lab_id != admin.lab_id:
        raise HTTPException(404, "Invoice not found")
    if inv.status not in ("unpaid", "verifying"):
        raise HTTPException(409, f"This invoice is already {inv.status}")
    inv.status, inv.payment_method = "verifying", body.method
    inv.payment_ref = body.reference.strip().upper()
    inv.payment_submitted_at = utcnow()
    audit(db, request, actor_type="staff", actor_id=admin.id, action="invoice.payment_submitted", entity="invoice",
          entity_id=inv.id, lab_id=inv.lab_id, detail={"method": body.method, "reference": inv.payment_ref})
    db.commit()
    return billing.invoice_out(inv)
