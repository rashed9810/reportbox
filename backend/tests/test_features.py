"""Checks for lab settings, WhatsApp, privacy controls, two-step sign-in and billing."""
import hashlib
import hmac
import json
import re
import time
from datetime import date, timedelta

import httpx
import pyotp
import pytest
from conftest import PDF, staff_headers

from app import billing, plans, worker
from app.config import get_settings
from app.db import SessionLocal
from app.models import Invoice, Lab, Message, Recall, Report, Staff, utcnow
from app.whatsapp import CloudApiProvider
from test_flow import PHONE, patient_login, register, send_and_get_link, upload


def _send(client, h, patient_id, codes="hba1c,lipid", recall=True):
    rep = upload(client, h, patient_id, codes=codes, recall=recall).json()
    return client.post(f"/api/staff/reports/{rep['id']}/send", headers=h).json()


# ---------- lab settings ----------

def test_lab_settings_and_reminder_rules(client):
    admin = staff_headers(client, "owner@a.test", "pw-a")
    rec = staff_headers(client, "rec@a.test", "pw-a2")
    assert client.get("/api/staff/lab", headers=rec).status_code == 403
    lab = client.get("/api/staff/lab", headers=admin).json()
    assert lab["plan"] == "growth" and {r["test_code"] for r in lab["recall_rules"]} >= {"hba1c", "cbc"}

    r = client.patch("/api/staff/lab", headers=admin, json={"name_bn": " নতুন নাম ", "address": "Road 2"})
    assert r.json()["name_bn"] == "নতুন নাম" and r.json()["address"] == "Road 2"
    assert client.patch("/api/staff/lab", headers=admin, json={"name": "  "}).status_code == 422

    assert client.put("/api/staff/lab/recall-rules", headers=admin,
                      json=[{"test_code": "lipid", "enabled": True, "days": 3}]).status_code == 422
    rules = client.put("/api/staff/lab/recall-rules", headers=admin, json=[
        {"test_code": "hba1c", "enabled": False},
        {"test_code": "lipid", "enabled": True, "days": 30},
        {"test_code": "cbc", "enabled": True, "days": 60},
    ]).json()
    by = {x["test_code"]: x for x in rules}
    assert not by["hba1c"]["enabled"] and by["lipid"]["days"] == 30 and by["cbc"]["enabled"]
    cat = {t["code"]: t["recall_days"] for t in client.get("/api/staff/catalog", headers=rec).json()}
    assert cat["hba1c"] is None and cat["lipid"] == 30 and cat["cbc"] == 60

    p = register(client, rec)
    _send(client, rec, p["id"], codes="hba1c,lipid,cbc")
    db = SessionLocal()
    recalls = {r.test_code: r for r in db.query(Recall).all()}
    db.close()
    assert set(recalls) == {"lipid", "cbc"}  # HbA1c reminders are off for this lab
    sent_day = recalls["lipid"].due_date - timedelta(days=30)
    assert recalls["cbc"].due_date == sent_day + timedelta(days=60)

    # another lab still uses the defaults
    hb = staff_headers(client, "rec@b.test", "pw-b")
    cat_b = {t["code"]: t["recall_days"] for t in client.get("/api/staff/catalog", headers=hb).json()}
    assert cat_b["hba1c"] == 90 and cat_b["cbc"] is None


# ---------- WhatsApp ----------

def _enable_whatsapp():
    s = get_settings()
    s.whatsapp_enabled = True
    s.wa_app_secret = "app-secret"
    s.wa_verify_token = "verify-me"


def test_whatsapp_needs_opt_in_and_server_switch(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h)
    token = send_and_get_link(client, h, upload(client, h, p["id"]).json()["id"])
    ph = patient_login(client, link_token=token)
    me = client.get("/api/patient/me", headers=ph).json()
    assert me["whatsapp_available"] is False
    assert client.patch("/api/patient/me", headers=ph, json={"whatsapp_opt_in": True}).status_code == 409

    _enable_whatsapp()
    # switched on at the server, but the patient has not chosen it: still SMS
    before = len(client.outbox)
    assert _send(client, h, p["id"])["channel"] == "sms"
    assert len(client.outbox) == before + 1 and client.wa.outbox == []

    assert client.patch("/api/patient/me", headers=ph, json={"whatsapp_opt_in": True}).json()["whatsapp_opt_in"]
    before = len(client.outbox)
    out = _send(client, h, p["id"])
    assert out["channel"] == "whatsapp" and out["message_status"] == "sent"
    assert len(client.outbox) == before  # no SMS
    sent = client.wa.outbox[-1]
    db = SessionLocal()
    link_token = db.get(Report, out["id"]).link_token
    db.close()
    assert sent["to"] == "8801712334821" and sent["template"] == "report_ready" and sent["lang"] == "bn"
    assert sent["body"] == ["সিটি ডায়াগনস্টিক", "Rahima Begum"] and sent["url_suffix"] == link_token

    # WhatsApp refuses: the report goes by SMS instead, and only the SMS is billed
    client.wa.fail_with = "WhatsApp 131026: Message undeliverable"
    before = len(client.outbox)
    out = _send(client, h, p["id"])
    assert out["channel"] == "sms" and out["message_status"] == "sent"
    assert len(client.outbox) == before + 1 and "/r/" in client.outbox[-1]["text"]
    db = SessionLocal()
    msgs = db.query(Message).filter(Message.report_id == out["id"]).order_by(Message.id).all()
    db.close()
    assert [(m.channel, m.status) for m in msgs] == [("whatsapp", "failed"), ("sms", "sent")]


def _signed(body: dict, secret="app-secret"):
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


def test_whatsapp_webhook_fallback(client):
    _enable_whatsapp()
    assert client.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                        "hub.challenge": "1234"}).text == "1234"
    assert client.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                                        "hub.challenge": "1"}).status_code == 403
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h)
    token = send_and_get_link(client, h, upload(client, h, p["id"]).json()["id"])
    ph = patient_login(client, link_token=token)
    client.patch("/api/patient/me", headers=ph, json={"whatsapp_opt_in": True})
    out = _send(client, h, p["id"])
    wamid = client.wa.outbox[-1]["ref"]

    update = {"entry": [{"changes": [{"value": {"statuses": [
        {"id": wamid, "status": "failed", "errors": [{"code": 131026, "title": "Message undeliverable"}]}]}}]}]}
    raw, headers = _signed(update, secret="wrong")
    assert client.post("/api/webhooks/whatsapp", content=raw, headers=headers).status_code == 403
    before = len(client.outbox)
    raw, headers = _signed(update)
    assert client.post("/api/webhooks/whatsapp", content=raw, headers=headers).json()["sms_fallbacks"] == 1
    assert len(client.outbox) == before + 1
    # the same update again does not send a second SMS
    assert client.post("/api/webhooks/whatsapp", content=raw, headers=headers).json()["sms_fallbacks"] == 0
    today = client.get("/api/staff/reports", headers=h).json()
    assert next(r for r in today if r["id"] == out["id"])["channel"] == "sms"


def test_cloud_api_request_shape():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.ABC"}]})

    p = CloudApiProvider("12345", "TOKEN", "v23.0", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert p.send_template("8801712334821", "report_ready", "bn", ["Lab", "Rahima"], "tok123") == "wamid.ABC"
    assert seen["url"] == "https://graph.facebook.com/v23.0/12345/messages" and seen["auth"] == "Bearer TOKEN"
    t = seen["json"]["template"]
    assert seen["json"]["to"] == "8801712334821" and t["name"] == "report_ready" and t["language"] == {"code": "bn"}
    assert t["components"][0] == {"type": "body", "parameters": [{"type": "text", "text": "Lab"},
                                                                 {"type": "text", "text": "Rahima"}]}
    assert t["components"][1] == {"type": "button", "sub_type": "url", "index": "0",
                                  "parameters": [{"type": "text", "text": "tok123"}]}

    bad = CloudApiProvider("1", "T", "v23.0", client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"error": {"code": 132001, "message": "Template name does not exist"}}))))
    with pytest.raises(Exception, match="132001"):
        bad.send_template("8801712334821", "x", "bn", [], "t")


# ---------- privacy controls ----------

def test_stop_lab_export_and_close(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h)
    rep_id = upload(client, h, p["id"], codes="hba1c").json()["id"]
    token = send_and_get_link(client, h, rep_id)
    ph = patient_login(client, link_token=token)

    labs = client.get("/api/patient/labs", headers=ph).json()
    assert labs == [{"id": labs[0]["id"], "name": "সিটি ডায়াগনস্টিক", "people": ["Rahima Begum"], "receiving": True}]

    export = client.get("/api/patient/export", headers=ph)
    assert "attachment" in export.headers["content-disposition"]
    data = export.json()
    assert data["phone"] == "+8801712334821"
    assert data["people_at_labs"][0]["reports"][0]["tests"] == ["hba1c"]
    assert any(m["kind"] == "otp" for m in data["messages"])
    assert "body" not in export.text and "কোড:" not in export.text  # no login codes in the file

    share = client.post("/api/patient/shares", headers=ph, json={"report_ids": [rep_id]}).json()
    dtoken = share["url"].rsplit("/", 1)[1]

    # stop this lab: no more sending, reminders cancelled, reception sees it
    assert client.post(f"/api/patient/labs/{labs[0]['id']}/stop", headers=ph).json()["reminders_cancelled"] == 1
    assert client.get("/api/patient/labs", headers=ph).json()[0]["receiving"] is False
    assert client.post(f"/api/staff/reports/{rep_id}/send", headers=h).status_code == 409
    found = client.get("/api/staff/patients", params={"phone": PHONE}, headers=h).json()[0]
    assert found["consent"] is False and found["consent_withdrawn"] is True
    # past reports stay visible to the patient
    assert len(client.get("/api/patient/reports", headers=ph).json()["reports"]) == 1
    assert client.post("/api/patient/labs/99999/stop", headers=ph).status_code == 404

    # close the wallet: doctor links stop, signed out everywhere
    assert client.post("/api/patient/close", headers=ph).json()["links_stopped"] == 1
    assert client.get(f"/api/public/share/{dtoken}").status_code == 410
    assert client.get("/api/patient/me", headers=ph).status_code == 401


def test_reminder_not_sent_after_consent_withdrawn(client):
    from app import recalls
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h)
    token = send_and_get_link(client, h, upload(client, h, p["id"], codes="hba1c").json()["id"])
    ph = patient_login(client, link_token=token)
    # withdraw directly in the database, leaving the reminder scheduled, to test the safety check
    db = SessionLocal()
    from app.models import Consent
    for c in db.query(Consent).all():
        c.status = "revoked"
    db.commit()
    assert recalls.send_due(db, today=recalls.bd_today() + timedelta(days=200)) == 0
    assert db.query(Recall).one().status == "cancelled"
    db.close()
    assert ph  # patient session unaffected


# ---------- two-step sign-in ----------

def test_two_factor_sign_in(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    setup = client.post("/api/staff/me/2fa/setup", headers=h).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/ReportBox:rec%40a.test")
    totp = pyotp.TOTP(setup["secret"])
    db = SessionLocal()
    stored = db.query(Staff).filter_by(email="rec@a.test").one().totp_secret_enc
    db.close()
    assert setup["secret"] not in stored  # kept encrypted

    assert client.post("/api/staff/me/2fa/enable", headers=h, json={"code": "000000"}).status_code == 400
    assert client.post("/api/staff/me/2fa/enable", headers=h, json={"code": totp.now()}).json()["two_factor"]
    assert client.post("/api/staff/me/2fa/setup", headers=h).status_code == 409

    body = {"email": "rec@a.test", "password": "pw-a2"}
    r = client.post("/api/staff/login", json=body)
    assert r.status_code == 401 and r.json()["detail"] == "two_factor_required"
    assert client.post("/api/staff/login", json={**body, "code": "123456"}).status_code == 401
    future = totp.at(time.time() + 30)  # next code: the one used to turn it on cannot be reused
    assert client.post("/api/staff/login", json={**body, "code": future}).status_code == 200
    assert client.post("/api/staff/login", json={**body, "code": future}).status_code == 401  # replay blocked
    assert client.post("/api/staff/login", json={"email": "rec@a.test", "password": "wrong", "code": future}).status_code == 401

    # the admin resets it for a lost phone; the person can sign in with the password again
    admin = staff_headers(client, "owner@a.test", "pw-a")
    staff_list = client.get("/api/staff/staff", headers=admin).json()
    rec = next(s for s in staff_list if s["email"] == "rec@a.test")
    assert rec["two_factor"] is True
    client.patch(f"/api/staff/staff/{rec['id']}", headers=admin, json={"reset_two_factor": True})
    assert client.post("/api/staff/login", json=body).status_code == 200


def test_two_factor_disable_needs_password_and_code(client):
    h = staff_headers(client, "owner@a.test", "pw-a")
    secret = client.post("/api/staff/me/2fa/setup", headers=h).json()["secret"]
    totp = pyotp.TOTP(secret)
    client.post("/api/staff/me/2fa/enable", headers=h, json={"code": totp.now()})
    nxt = totp.at(time.time() + 30)
    assert client.post("/api/staff/me/2fa/disable", headers=h, json={"password": "bad", "code": nxt}).status_code == 400
    assert client.post("/api/staff/me/2fa/disable", headers=h, json={"password": "pw-a", "code": nxt}).json()["two_factor"] is False
    assert client.post("/api/staff/login", json={"email": "owner@a.test", "password": "pw-a"}).status_code == 200


# ---------- billing ----------

def _move_to_last_month(db):
    """Pretend everything so far happened in the middle of last month."""
    last = billing.previous_period()
    start, _ = billing.period_bounds_utc(last)
    mid = start + timedelta(days=10)
    for model in (Report, Message):
        for row in db.query(model).all():
            row.created_at = mid
    for lab in db.query(Lab).all():
        lab.created_at = start
    db.commit()
    return last


def test_invoice_calculation_and_payment(client, monkeypatch):
    monkeypatch.setitem(plans.PLANS, "starter", {"name": "Starter", "price_bdt": 2500, "reports": 1, "messages": 2})
    h = staff_headers(client, "rec@a.test", "pw-a2")
    admin = staff_headers(client, "owner@a.test", "pw-a")
    p = register(client, h)
    for _ in range(3):  # 3 reports, 3 report SMS; then a login code SMS = 4 messages
        _send(client, h, p["id"], codes="cbc", recall=False)
    link = re.search(r"/r/(\S+)", client.outbox[-1]["text"]).group(1)
    patient_login(client, link_token=link)  # a code asked for from the lab's link is billed to that lab
    db = SessionLocal()
    lab = db.query(Lab).filter_by(name="City Diagnostic Centre").one()
    lab.plan, lab.discount_percent = "starter", 50
    lab.discount_until = date.today() + timedelta(days=200)
    db.commit()
    period = _move_to_last_month(db)
    get_settings().vat_percent = 5.0

    with pytest.raises(ValueError):
        billing.generate_for_period(db, billing.period_of(billing.bd_now()))  # this month is not finished
    created = billing.generate_for_period(db, period)
    assert len(created) == 2  # both labs
    assert billing.generate_for_period(db, period) == []  # running again changes nothing
    inv = db.query(Invoice).filter_by(lab_id=lab.id).one()
    # 2500 - 50% = 1250; overage: 2 extra reports x 1.00 + 2 extra messages x 0.60 = 3.20; VAT 5%
    assert (inv.base_paisa, inv.discount_paisa) == (250000, 125000)
    assert (inv.reports_used, inv.messages_used) == (3, 4)
    assert inv.overage_paisa == 2 * 100 + 2 * 60
    assert inv.vat_paisa == round((125000 + 320) * 0.05)
    assert inv.total_paisa == 125000 + 320 + inv.vat_paisa
    assert inv.due_date.day == 15
    other = db.query(Invoice).filter(Invoice.lab_id != lab.id).one()
    assert other.discount_paisa == 0 and other.total_paisa == round(450000 * 1.05)
    inv_id, other_id = inv.id, other.id
    db.close()

    assert client.get("/api/staff/billing", headers=h).status_code == 403
    b = client.get("/api/staff/billing", headers=admin).json()
    assert b["plan"] == "starter" and b["invoices"][0]["id"] == inv_id
    assert b["invoices"][0]["number"].startswith("RB-")
    dash = client.get("/api/staff/dashboard", headers=admin).json()
    assert dash["unpaid_invoice"]["id"] == inv_id

    pay = {"method": "bkash", "reference": "9ab3xk2lq"}
    assert client.post(f"/api/staff/billing/invoices/{other_id}/payment", headers=admin, json=pay).status_code == 404
    r = client.post(f"/api/staff/billing/invoices/{inv_id}/payment", headers=admin, json=pay).json()
    assert r["status"] == "verifying" and r["payment_ref"] == "9AB3XK2LQ"

    from app import cli
    cli.confirm_payment(["--invoice", str(inv_id)])
    assert client.get("/api/staff/billing", headers=admin).json()["invoices"][0]["status"] == "paid"
    assert client.post(f"/api/staff/billing/invoices/{inv_id}/payment", headers=admin, json=pay).status_code == 409


def test_overdue_and_discount_expiry(client, monkeypatch):
    db = SessionLocal()
    lab = db.query(Lab).first()
    lab.discount_percent, lab.discount_until = 50, date(2020, 1, 31)  # long expired
    period = _move_to_last_month(db)
    inv = billing.generate_for_period(db, period)[0]
    assert inv.discount_paisa == 0
    monkeypatch.setattr(billing, "bd_now", lambda: utcnow() + timedelta(days=60))
    assert billing.invoice_out(inv)["status"] == "overdue"
    db.close()


def test_worker_bills_on_first_days_only(client, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(billing, "bd_now", lambda: datetime(2031, 1, 20, 12, 0))
    assert worker.bill_once() == 0
    monkeypatch.setattr(billing, "bd_now", lambda: datetime(2031, 1, 2, 12, 0))
    assert worker.bill_once() == 2  # both labs billed for December 2030
    assert worker.bill_once() == 0
    db = SessionLocal()
    assert {i.period for i in db.query(Invoice).all()} == {"2030-12"}
    db.close()
