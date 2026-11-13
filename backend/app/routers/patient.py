"""Patient-side API (phone + code login, health wallet, sharing) and the doctor's share view."""
import json
from collections import OrderedDict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import recalls as recall_service
from .. import whatsapp
from ..audit import audit
from ..catalog import TEST_CATALOG
from ..config import get_settings
from ..db import get_db
from ..deps import PATIENT_COOKIE, current_phone_account
from ..messaging import render, send_sms
from ..models import (Consent, Lab, Message, OtpCode, PatientSession, Patient, PhoneAccount, Recall, Report,
                      Share, utcnow)
from ..security import (hash_otp, hash_token, mask_phone, new_otp, new_token, normalize_bd_phone,
                        otp_matches)
from ..storage import get_storage

router = APIRouter(tags=["patient"])
BD_OFFSET = timedelta(hours=6)


# ---------- the SMS link ----------

@router.get("/api/public/r/{link_token}")
def open_link(link_token: str, db: Session = Depends(get_db)):
    r = db.scalar(select(Report).where(Report.link_token == link_token, Report.status == "sent"))
    if not r:
        raise HTTPException(404, "This link is not valid")
    return {"lab": {"id": r.lab.id, "name": r.lab.name, "name_bn": r.lab.name_bn},
            "masked_phone": mask_phone(r.patient.phone_account.phone),
            "language": r.patient.phone_account.language}


# ---------- login with a one-time code ----------

class OtpRequestIn(BaseModel):
    phone: str | None = None
    link_token: str | None = None


def _resolve(db: Session, phone: str | None, link_token: str | None) -> tuple[str, Lab | None]:
    """Phone number to log in, and the lab whose link was used (it pays for the code SMS)."""
    if link_token:
        r = db.scalar(select(Report).where(Report.link_token == link_token, Report.status == "sent"))
        if not r:
            raise HTTPException(404, "This link is not valid")
        return r.patient.phone_account.phone, r.lab
    try:
        return normalize_bd_phone(phone or ""), None
    except ValueError as e:
        raise HTTPException(422, str(e))


def _resolve_phone(db: Session, phone: str | None, link_token: str | None) -> str:
    return _resolve(db, phone, link_token)[0]


@router.post("/api/patient/otp/request")
def request_otp(body: OtpRequestIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    phone, lab = _resolve(db, body.phone, body.link_token)
    recent = db.scalar(select(func.count(OtpCode.id)).where(OtpCode.phone == phone,
                                                             OtpCode.created_at >= utcnow() - timedelta(minutes=15)))
    if recent >= s.otp_max_requests_per_15_min:
        raise HTTPException(429, "Too many codes requested. Please wait 15 minutes.")
    acct = db.scalar(select(PhoneAccount).where(PhoneAccount.phone == phone))
    # Same answer whether or not the number is known, and no SMS cost for unknown numbers.
    if acct:
        code = new_otp()
        db.add(OtpCode(phone=phone, code_hash=hash_otp(phone, code),
                       expires_at=utcnow() + timedelta(minutes=s.otp_ttl_minutes)))
        send_sms(db, phone=phone, kind="otp", text=render("otp", acct.language, code=code), lab=lab)
        db.commit()
    return {"sent": True, "masked_phone": mask_phone(phone), "expires_in_seconds": s.otp_ttl_minutes * 60}


class OtpVerifyIn(OtpRequestIn):
    code: str


@router.post("/api/patient/otp/verify")
def verify_otp(body: OtpVerifyIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    phone = _resolve_phone(db, body.phone, body.link_token)
    otp = db.scalar(select(OtpCode).where(OtpCode.phone == phone, OtpCode.used_at.is_(None))
                    .order_by(OtpCode.id.desc()))
    if not otp or otp.expires_at < utcnow():
        raise HTTPException(400, "Code expired. Please ask for a new one.")
    if otp.attempts >= s.otp_max_attempts:
        raise HTTPException(429, "Too many wrong tries. Please ask for a new code.")
    if not otp_matches(phone, body.code.strip(), otp.code_hash):
        otp.attempts += 1
        db.commit()
        raise HTTPException(400, "Wrong code")
    otp.used_at = utcnow()
    acct = db.scalar(select(PhoneAccount).where(PhoneAccount.phone == phone))
    token = new_token()
    db.add(PatientSession(token_hash=hash_token(token), phone_account_id=acct.id,
                          expires_at=utcnow() + timedelta(days=s.patient_session_days)))
    audit(db, request, actor_type="patient", actor_id=acct.id, action="login", entity="phone_account",
          entity_id=acct.id)
    db.commit()
    response.set_cookie(PATIENT_COOKIE, token, max_age=s.patient_session_days * 86400, httponly=True,
                        secure=s.cookie_secure, samesite="lax", path="/")
    return {"token": token}


@router.post("/api/patient/logout")
def patient_logout(request: Request, response: Response, acct: PhoneAccount = Depends(current_phone_account),
                   db: Session = Depends(get_db)):
    token = request.cookies.get(PATIENT_COOKIE) or request.headers.get("authorization", "").split(" ")[-1]
    db.execute(delete(PatientSession).where(PatientSession.token_hash == hash_token(token)))
    db.commit()
    response.delete_cookie(PATIENT_COOKIE, path="/")
    return {"signed_out": True}


# ---------- wallet ----------

def _wallet_consent(db: Session, acct: PhoneAccount) -> bool:
    return bool(db.scalar(select(Consent).where(Consent.phone_account_id == acct.id, Consent.scope == "wallet",
                                                Consent.status == "active")))


def _person_key(p: Patient) -> str:
    return f"{' '.join(p.name.lower().split())}|{p.birth_year or ''}"


@router.get("/api/patient/me")
def patient_me(acct: PhoneAccount = Depends(current_phone_account), db: Session = Depends(get_db)):
    patients = db.scalars(select(Patient).where(Patient.phone_account_id == acct.id).order_by(Patient.id)).all()
    people: "OrderedDict[str, dict]" = OrderedDict()
    for p in patients:
        person = people.setdefault(_person_key(p), {"key": _person_key(p), "name": p.name, "sex": p.sex,
                                                    "birth_year": p.birth_year, "patient_ids": []})
        person["patient_ids"].append(p.id)
    return {"masked_phone": mask_phone(acct.phone), "language": acct.language,
            "wallet_consent": _wallet_consent(db, acct), "people": list(people.values()),
            "whatsapp_available": whatsapp.is_enabled(), "whatsapp_opt_in": acct.whatsapp_opt_in}


class PatientPrefsIn(BaseModel):
    language: str | None = None
    whatsapp_opt_in: bool | None = None


@router.patch("/api/patient/me")
def update_prefs(body: PatientPrefsIn, request: Request, acct: PhoneAccount = Depends(current_phone_account),
                 db: Session = Depends(get_db)):
    if body.language is not None:
        if body.language not in ("bn", "en"):
            raise HTTPException(422, "language must be bn or en")
        acct.language = body.language
    if body.whatsapp_opt_in is not None:
        if body.whatsapp_opt_in and not whatsapp.is_enabled():
            raise HTTPException(409, "WhatsApp delivery is not available yet")
        acct.whatsapp_opt_in = body.whatsapp_opt_in
        audit(db, request, actor_type="patient", actor_id=acct.id,
              action="whatsapp.opt_in" if body.whatsapp_opt_in else "whatsapp.opt_out", entity="phone_account",
              entity_id=acct.id)
    db.commit()
    return {"language": acct.language, "whatsapp_opt_in": acct.whatsapp_opt_in}


class WalletConsentIn(BaseModel):
    give: bool


@router.post("/api/patient/consents/wallet")
def wallet_consent(body: WalletConsentIn, request: Request, acct: PhoneAccount = Depends(current_phone_account),
                   db: Session = Depends(get_db)):
    active = db.scalars(select(Consent).where(Consent.phone_account_id == acct.id, Consent.scope == "wallet",
                                              Consent.status == "active")).all()
    if body.give and not active:
        db.add(Consent(scope="wallet", phone_account_id=acct.id, method="otp_in_app"))
    if not body.give:
        for c in active:
            c.status, c.revoked_at = "revoked", utcnow()
    audit(db, request, actor_type="patient", actor_id=acct.id,
          action="consent.wallet.give" if body.give else "consent.wallet.revoke", entity="phone_account",
          entity_id=acct.id)
    db.commit()
    return {"wallet_consent": body.give}


def _lab_name(lab: Lab, lang: str) -> str:
    return lab.name_bn if lang == "bn" and lab.name_bn else lab.name


def _bd_date(dt) -> str | None:
    """A stored UTC time as a Bangladesh calendar date."""
    return (dt + BD_OFFSET).date().isoformat() if dt else None


def _report_card(r: Report, lang: str) -> dict:
    names = [TEST_CATALOG[c]["name_bn" if lang == "bn" else "name"] for c in r.test_codes]
    return {"id": r.id, "title": ", ".join(names) or r.title, "test_codes": r.test_codes,
            "lab": {"id": r.lab.id, "name": _lab_name(r.lab, lang)},
            "date": _bd_date(r.sent_at), "is_new": r.first_opened_at is None,
            "person_key": _person_key(r.patient), "sensitive": r.sensitive}


@router.get("/api/patient/reports")
def my_reports(lab_id: int | None = None, acct: PhoneAccount = Depends(current_phone_account),
               db: Session = Depends(get_db)):
    reports = db.scalars(select(Report).join(Patient, Report.patient_id == Patient.id)
                         .where(Patient.phone_account_id == acct.id, Report.status == "sent")
                         .order_by(Report.sent_at.desc())).all()
    consent = _wallet_consent(db, acct)
    hidden = 0
    if not consent and reports:
        # Without wallet consent, show one lab only: the lab from the link, else the latest lab.
        show_lab = lab_id or reports[0].lab_id
        hidden = len({r.lab_id for r in reports} - {show_lab})
        reports = [r for r in reports if r.lab_id == show_lab]
    patient_ids = {r.patient_id for r in reports}
    upcoming = db.scalars(select(Recall).where(Recall.patient_id.in_(patient_ids), Recall.status == "scheduled")
                          .order_by(Recall.due_date)).all() if patient_ids else []
    return {
        "wallet_consent": consent, "other_labs_hidden": hidden,
        "reports": [_report_card(r, acct.language) for r in reports],
        "reminders": [{"test": TEST_CATALOG[x.test_code]["name_bn" if acct.language == "bn" else "name"],
                       "due_date": x.due_date.isoformat(), "person_key": _person_key(x.patient),
                       "lab": _lab_name(db.get(Lab, x.lab_id), acct.language)} for x in upcoming],
    }


def _pdf_response(r: Report) -> Response:
    data = get_storage().load(r.file_key)
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="report-{r.id}.pdf"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def _own_report(db: Session, acct: PhoneAccount, report_id: int) -> Report:
    r = db.get(Report, report_id)
    if not r or r.status != "sent" or r.patient.phone_account_id != acct.id:
        raise HTTPException(404, "Report not found")
    return r


@router.get("/api/patient/reports/{report_id}/pdf")
def my_report_pdf(report_id: int, request: Request, acct: PhoneAccount = Depends(current_phone_account),
                  db: Session = Depends(get_db)):
    r = _own_report(db, acct, report_id)
    if not r.first_opened_at:
        r.first_opened_at = utcnow()
    audit(db, request, actor_type="patient", actor_id=acct.id, action="report.view", entity="report",
          entity_id=r.id, lab_id=r.lab_id)
    db.commit()
    return _pdf_response(r)


# ---------- privacy controls (the patient's rights under the data protection law) ----------

def _my_patients(db: Session, acct: PhoneAccount) -> list[Patient]:
    return db.scalars(select(Patient).where(Patient.phone_account_id == acct.id).order_by(Patient.id)).all()


@router.get("/api/patient/labs")
def my_labs(acct: PhoneAccount = Depends(current_phone_account), db: Session = Depends(get_db)):
    """Each lab that holds records for this phone, and whether it may still send reports here."""
    out: "OrderedDict[int, dict]" = OrderedDict()
    for p in _my_patients(db, acct):
        lab = out.setdefault(p.lab_id, {"id": p.lab_id, "name": _lab_name(p.lab, acct.language),
                                        "people": [], "receiving": False})
        lab["people"].append(p.name)
        if recall_service.has_delivery_consent(db, p.id):
            lab["receiving"] = True
    return list(out.values())


@router.post("/api/patient/labs/{lab_id}/stop")
def stop_lab(lab_id: int, request: Request, acct: PhoneAccount = Depends(current_phone_account),
             db: Session = Depends(get_db)):
    """Withdraw consent: this lab can no longer send reports or reminders to this phone,
    until the patient agrees again at the lab's counter."""
    patients = [p for p in _my_patients(db, acct) if p.lab_id == lab_id]
    if not patients:
        raise HTTPException(404, "Lab not found")
    ids = [p.id for p in patients]
    for c in db.scalars(select(Consent).where(Consent.patient_id.in_(ids), Consent.scope == "lab_delivery",
                                              Consent.status == "active")):
        c.status, c.revoked_at = "revoked", utcnow()
    cancelled = recall_service.cancel_for_patients(db, ids)
    audit(db, request, actor_type="patient", actor_id=acct.id, action="consent.lab_delivery.revoke",
          entity="phone_account", entity_id=acct.id, lab_id=lab_id, detail={"reminders_cancelled": cancelled})
    db.commit()
    return {"stopped": True, "reminders_cancelled": cancelled}


@router.get("/api/patient/export")
def export_my_data(request: Request, acct: PhoneAccount = Depends(current_phone_account),
                   db: Session = Depends(get_db)):
    """Everything ReportBox holds about this phone, as a file (the right of access and portability).
    The report PDFs themselves are downloaded one by one from the wallet."""
    patients = _my_patients(db, acct)
    ids = [p.id for p in patients]

    def iso(dt):
        return dt.isoformat() + "Z" if dt else None

    data = {
        "exported_at": iso(utcnow()),
        "phone": "+" + acct.phone, "language": acct.language, "whatsapp_opt_in": acct.whatsapp_opt_in,
        "people_at_labs": [{
            "lab": p.lab.name, "name": p.name, "sex": p.sex, "birth_year": p.birth_year,
            "registered_at": iso(p.created_at),
            "consents": [{"scope": c.scope, "status": c.status, "method": c.method, "guardian": c.guardian_name,
                          "given_at": iso(c.created_at), "withdrawn_at": iso(c.revoked_at)}
                         for c in db.scalars(select(Consent).where(Consent.patient_id == p.id))],
            "reports": [{"title": r.title, "tests": r.test_codes, "sent_at": iso(r.sent_at),
                         "first_opened_at": iso(r.first_opened_at), "sha256": r.sha256}
                        for r in db.scalars(select(Report).where(Report.patient_id == p.id, Report.status == "sent"))],
            "reminders": [{"test": x.test_code, "due_date": x.due_date.isoformat(), "status": x.status}
                          for x in db.scalars(select(Recall).where(Recall.patient_id == p.id))],
        } for p in patients],
        "wallet_consents": [{"status": c.status, "given_at": iso(c.created_at), "withdrawn_at": iso(c.revoked_at)}
                            for c in db.scalars(select(Consent).where(Consent.phone_account_id == acct.id))],
        "doctor_shares": [{"reports": len(s.report_ids), "created_at": iso(s.created_at), "expires_at": iso(s.expires_at),
                           "views": s.access_count, "stopped_at": iso(s.revoked_at)}
                          for s in db.scalars(select(Share).where(Share.phone_account_id == acct.id))],
        # Message texts are left out: login codes must not be stored in a file.
        "messages": [{"kind": m.kind, "channel": m.channel, "status": m.status, "sent_at": iso(m.created_at)}
                     for m in db.scalars(select(Message).where(Message.phone == acct.phone).order_by(Message.id))],
    }
    audit(db, request, actor_type="patient", actor_id=acct.id, action="data.export", entity="phone_account",
          entity_id=acct.id)
    db.commit()
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="my-reportbox-data.json"',
                             "Cache-Control": "no-store"})


@router.post("/api/patient/close")
def close_wallet(request: Request, response: Response, acct: PhoneAccount = Depends(current_phone_account),
                 db: Session = Depends(get_db)):
    """Turn the wallet off: withdraw the all-labs permission, stop every doctor link, turn off WhatsApp,
    and sign out on every phone. The labs keep their own medical records; ask a lab to delete those."""
    now = utcnow()
    for c in db.scalars(select(Consent).where(Consent.phone_account_id == acct.id, Consent.scope == "wallet",
                                              Consent.status == "active")):
        c.status, c.revoked_at = "revoked", now
    stopped_links = 0
    for s in db.scalars(select(Share).where(Share.phone_account_id == acct.id, Share.revoked_at.is_(None),
                                            Share.expires_at > now)):
        s.revoked_at = now
        stopped_links += 1
    acct.whatsapp_opt_in = False
    db.execute(delete(PatientSession).where(PatientSession.phone_account_id == acct.id))
    audit(db, request, actor_type="patient", actor_id=acct.id, action="wallet.close", entity="phone_account",
          entity_id=acct.id, detail={"links_stopped": stopped_links})
    db.commit()
    response.delete_cookie(PATIENT_COOKIE, path="/")
    return {"closed": True, "links_stopped": stopped_links}


# ---------- sharing with a doctor ----------

class ShareIn(BaseModel):
    report_ids: list[int]


@router.post("/api/patient/shares", status_code=201)
def create_share(body: ShareIn, request: Request, acct: PhoneAccount = Depends(current_phone_account),
                 db: Session = Depends(get_db)):
    if not body.report_ids:
        raise HTTPException(422, "Choose at least one report")
    reports = [_own_report(db, acct, rid) for rid in dict.fromkeys(body.report_ids)]
    if len({_person_key(r.patient) for r in reports}) > 1:
        raise HTTPException(422, "Share one person's reports at a time")
    token = new_token()
    s = Share(token_hash=hash_token(token), phone_account_id=acct.id, patient_id=reports[0].patient_id,
              report_ids=[r.id for r in reports],
              expires_at=utcnow() + timedelta(hours=get_settings().share_ttl_hours))
    db.add(s)
    db.flush()
    audit(db, request, actor_type="patient", actor_id=acct.id, action="share.create", entity="share", entity_id=s.id)
    db.commit()
    return {"id": s.id, "url": f"{get_settings().public_base_url.rstrip('/')}/d/{token}",
            "expires_at": s.expires_at.isoformat() + "Z"}


@router.get("/api/patient/shares")
def my_shares(acct: PhoneAccount = Depends(current_phone_account), db: Session = Depends(get_db)):
    rows = db.scalars(select(Share).where(Share.phone_account_id == acct.id).order_by(Share.id.desc())).all()
    now = utcnow()
    return [{"id": s.id, "report_ids": s.report_ids, "expires_at": s.expires_at.isoformat() + "Z",
             "active": s.revoked_at is None and s.expires_at > now, "views": s.access_count,
             "last_viewed_at": s.last_accessed_at.isoformat() + "Z" if s.last_accessed_at else None} for s in rows]


@router.delete("/api/patient/shares/{share_id}")
def revoke_share(share_id: int, acct: PhoneAccount = Depends(current_phone_account), db: Session = Depends(get_db)):
    s = db.get(Share, share_id)
    if not s or s.phone_account_id != acct.id:
        raise HTTPException(404, "Share not found")
    s.revoked_at = utcnow()
    db.commit()
    return {"revoked": True}


def _active_share(db: Session, token: str) -> Share:
    s = db.scalar(select(Share).where(Share.token_hash == hash_token(token)))
    if not s or s.revoked_at or s.expires_at < utcnow():
        raise HTTPException(410, "This link has expired. Ask the patient to share again.")
    return s


@router.get("/api/public/share/{token}")
def doctor_view(token: str, request: Request, db: Session = Depends(get_db)):
    s = _active_share(db, token)
    s.access_count += 1
    s.last_accessed_at = utcnow()
    audit(db, request, actor_type="doctor", actor_id=None, action="share.view", entity="share", entity_id=s.id)
    db.commit()
    p = s.patient
    reports = [db.get(Report, rid) for rid in s.report_ids]
    return {
        "patient": {"name": p.name, "sex": p.sex,
                    "age": ((utcnow() + BD_OFFSET).year - p.birth_year) if p.birth_year else None},
        "expires_at": s.expires_at.isoformat() + "Z",
        "reports": [{"id": r.id, "title": ", ".join(TEST_CATALOG[c]["name"] for c in r.test_codes) or r.title,
                     "lab": r.lab.name, "date": _bd_date(r.sent_at)} for r in reports if r],
    }


@router.get("/api/public/share/{token}/reports/{report_id}/pdf")
def doctor_pdf(token: str, report_id: int, request: Request, db: Session = Depends(get_db)):
    s = _active_share(db, token)
    if report_id not in s.report_ids:
        raise HTTPException(404, "Report not in this share")
    r = db.get(Report, report_id)
    audit(db, request, actor_type="doctor", actor_id=None, action="share.pdf", entity="report",
          entity_id=r.id, lab_id=r.lab_id, detail={"share_id": s.id})
    db.commit()
    return _pdf_response(r)
