"""Checks for the pilot-readiness features: cookies, login limits, staff accounts, real SMS, resend."""
import re

import httpx
from conftest import PDF, staff_headers

from app import messaging, worker
from app.messaging import BulkSmsBdProvider
from app.models import utcnow
from test_flow import register, upload

CSRF = {"X-RB-CSRF": "1"}


def test_cookie_login_and_csrf(client):
    r = client.post("/api/staff/login", json={"email": "rec@a.test", "password": "pw-a2"})
    assert "rb_staff" in r.cookies and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/staff/me").json()["name"] == "Shirin"  # cookie only, no header
    body = {"phone": "01712334821", "name": "A", "sex": "F", "consent_given": True}
    assert client.post("/api/staff/patients", json=body).status_code == 403  # no CSRF header
    assert client.post("/api/staff/patients", json=body, headers=CSRF).status_code == 201
    assert client.post("/api/staff/logout", headers=CSRF).status_code == 200
    client.cookies.clear()
    assert client.get("/api/staff/me").status_code == 401


def test_logout_kills_session(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    client.cookies.clear()
    assert client.post("/api/staff/logout", headers=h).status_code == 200
    assert client.get("/api/staff/me", headers=h).status_code == 401


def test_login_lockout(client):
    for _ in range(5):
        assert client.post("/api/staff/login", json={"email": "rec@a.test", "password": "nope"}).status_code == 401
    r = client.post("/api/staff/login", json={"email": "rec@a.test", "password": "pw-a2"})
    assert r.status_code == 429


def test_patient_cookie_and_logout(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h)
    rep = upload(client, h, p["id"]).json()
    client.post(f"/api/staff/reports/{rep['id']}/send", headers=h)
    token = re.search(r"/r/(\S+)", client.outbox[-1]["text"]).group(1)
    client.cookies.clear()
    client.post("/api/patient/otp/request", json={"link_token": token})
    code = re.search(r"\d{6}", client.outbox[-1]["text"]).group(0)
    r = client.post("/api/patient/otp/verify", json={"link_token": token, "code": code})
    assert "rb_patient" in r.cookies
    assert len(client.get("/api/patient/reports").json()["reports"]) == 1
    assert client.post("/api/patient/logout", headers=CSRF).status_code == 200
    client.cookies.clear()
    assert client.get("/api/patient/reports").status_code == 401


def test_staff_management(client):
    admin = staff_headers(client, "owner@a.test", "pw-a")
    rec = staff_headers(client, "rec@a.test", "pw-a2")
    assert client.get("/api/staff/staff", headers=rec).status_code == 403
    assert client.post("/api/staff/staff", headers=admin, json={"name": "New", "email": "new@a.test", "password": "short"}).status_code == 422
    new = client.post("/api/staff/staff", headers=admin, json={"name": "New", "email": "New@a.test", "password": "long-enough-pw"}).json()
    assert new["email"] == "new@a.test" and new["role"] == "reception"
    nh = staff_headers(client, "new@a.test", "long-enough-pw")
    client.patch(f"/api/staff/staff/{new['id']}", headers=admin, json={"active": False})
    assert client.get("/api/staff/me", headers=nh).status_code == 401  # signed out at once
    me = client.get("/api/staff/me", headers=admin).json()
    assert client.patch(f"/api/staff/staff/{me['id']}", headers=admin, json={"active": False}).status_code == 400
    # other labs' staff are invisible
    b = staff_headers(client, "rec@b.test", "pw-b")
    assert all(s["email"].endswith("a.test") for s in client.get("/api/staff/staff", headers=admin).json())
    assert client.patch(f"/api/staff/staff/{new['id']}", headers=b, json={"active": True}).status_code == 403
    # change own password
    assert client.post("/api/staff/me/password", headers=rec, json={"current_password": "pw-a2", "new_password": "a-new-password"}).status_code == 200
    staff_headers(client, "rec@a.test", "a-new-password")


def test_bulksmsbd_provider():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"response_code": 202, "message_id": 991, "success_message": "SMS Submitted Successfully"})

    p = BulkSmsBdProvider("KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert p.send("8801712334821", "hello", sender_id="CITYDIAG") == "991"
    assert seen["url"] == "https://bulksmsbd.net/api/smsapi"
    for part in ["api_key=KEY", "type=text", "number=8801712334821", "senderid=CITYDIAG"]:
        assert part in seen["body"]

    bad = BulkSmsBdProvider("KEY", client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"response_code": 1007, "error_message": "Balance Insufficient"}))))
    try:
        bad.send("8801712334821", "x")
        assert False
    except messaging.SmsError as e:
        assert "1007" in str(e) and "Balance" in str(e)


def test_failed_sms_shows_and_resends(client):
    class Flaky(messaging.ConsoleProvider):
        fail = True

        def send(self, phone, text, sender_id=None):
            if self.fail:
                raise messaging.SmsError("BulkSMSBD 1007: Balance insufficient")
            return super().send(phone, text, sender_id)

    flaky = Flaky()
    messaging.set_provider(flaky)
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h)
    rep = upload(client, h, p["id"]).json()
    r = client.post(f"/api/staff/reports/{rep['id']}/send", headers=h).json()
    assert r["message_status"] == "failed" and "Balance" in r["message_error"]
    assert client.get("/api/staff/reports", headers=h).json()[0]["status"] == "sms_failed"
    flaky.fail = False
    r = client.post(f"/api/staff/reports/{rep['id']}/send", headers=h).json()
    assert r["message_status"] == "sent" and r["status"] == "sent"
    assert flaky.outbox[-1]["sender_id"] == "CITYDIAG"  # lab's own sender ID


def test_worker_respects_daytime(monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(worker, "utcnow", lambda: datetime(2026, 11, 1, 18, 0))  # 00:00 in Dhaka
    assert worker.run_once() == 0
