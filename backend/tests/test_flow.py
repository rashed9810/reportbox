"""End-to-end checks of the main ReportBox flow and its privacy rules."""
import re
from datetime import date, timedelta

from conftest import PDF, staff_headers

from app import recalls
from app.db import SessionLocal
from app.models import OtpCode, Recall, Share, utcnow

PHONE = "01712-334821"


def register(client, h, name="Rahima Begum", sex="F", birth_year=1968, consent=True, phone=PHONE, **extra):
    r = client.post("/api/staff/patients", headers=h, json={
        "phone": phone, "name": name, "sex": sex, "birth_year": birth_year, "consent_given": consent, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, h, patient_id, codes="hba1c,lipid", recall=True, data=PDF):
    return client.post("/api/staff/reports", headers=h,
                       data={"patient_id": patient_id, "test_codes": codes, "recall": str(recall).lower()},
                       files={"file": ("r.pdf", data, "application/pdf")})


def last_code(client):
    sms = [m for m in client.outbox if "code" in m["text"].lower() or "কোড" in m["text"]][-1]
    return re.search(r"\d{6}", sms["text"]).group(0)


def patient_login(client, link_token=None, phone=None):
    body = {"link_token": link_token} if link_token else {"phone": phone}
    r = client.post("/api/patient/otp/request", json=body)
    assert r.status_code == 200, r.text
    r = client.post("/api/patient/otp/verify", json={**body, "code": last_code(client)})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def send_and_get_link(client, h, report_id):
    r = client.post(f"/api/staff/reports/{report_id}/send", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["message_status"] == "sent"
    url = re.search(r"http://app\.test/r/(\S+)", client.outbox[-1]["text"]).group(1)
    return url


def test_full_flow(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h)
    assert p["consent"] is True and p["phone"] == "8801712334821"

    rep = upload(client, h, p["id"]).json()
    assert rep["status"] == "draft"
    token = send_and_get_link(client, h, rep["id"])
    sms = client.outbox[-1]["text"]
    assert "রাহিমা" not in sms and "Rahima Begum" in sms  # name as registered
    assert "HbA1c" not in sms  # SMS never names the test

    link = client.get(f"/api/public/r/{token}").json()
    assert link["masked_phone"] == "017••••4821"

    ph = patient_login(client, link_token=token)
    wallet = client.get("/api/patient/reports", headers=ph).json()
    assert len(wallet["reports"]) == 1 and wallet["reports"][0]["is_new"]
    assert {x["test"] for x in wallet["reminders"]} == {"রক্তের সুগার (HbA1c)", "লিপিড প্রোফাইল"}
    assert wallet["reminders"][0]["lab"] == "সিটি ডায়াগনস্টিক"

    pdf = client.get(f"/api/patient/reports/{rep['id']}/pdf", headers=ph)
    assert pdf.status_code == 200 and pdf.content == PDF
    assert pdf.headers["cache-control"] == "no-store"

    today = client.get("/api/staff/reports", headers=h).json()
    assert today[0]["status"] == "opened"

    share = client.post("/api/patient/shares", headers=ph, json={"report_ids": [rep["id"]]}).json()
    dtoken = share["url"].rsplit("/", 1)[1]
    view = client.get(f"/api/public/share/{dtoken}").json()
    assert view["patient"]["name"] == "Rahima Begum" and len(view["reports"]) == 1
    assert client.get(f"/api/public/share/{dtoken}/reports/{rep['id']}/pdf").content == PDF
    assert client.get("/api/patient/shares", headers=ph).json()[0]["views"] == 1

    # the login code sent from this lab's link counts toward this lab's messages
    dash = client.get("/api/staff/dashboard", headers=h).json()
    assert dash["messages"]["by_kind"] == {"report_ready": 1, "otp": 1}


def test_send_requires_consent(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h, consent=False)
    rep = upload(client, h, p["id"]).json()
    r = client.post(f"/api/staff/reports/{rep['id']}/send", headers=h)
    assert r.status_code == 409
    client.post(f"/api/staff/patients/{p['id']}/consent", headers=h)
    assert client.post(f"/api/staff/reports/{rep['id']}/send", headers=h).status_code == 200


def test_minor_needs_guardian(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    r = client.post("/api/staff/patients", headers=h, json={
        "phone": PHONE, "name": "Nusrat", "sex": "F", "birth_year": date.today().year - 14, "consent_given": True})
    assert r.status_code == 422
    register(client, h, name="Nusrat", birth_year=date.today().year - 14, guardian_name="Rahima Begum")


def test_only_pdfs(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h)
    assert upload(client, h, p["id"], data=b"<html>not a pdf").status_code == 422
    assert upload(client, h, p["id"], codes="made-up").status_code == 422


def test_staff_cannot_see_other_labs(client):
    ha = staff_headers(client, "rec@a.test", "pw-a2")
    hb = staff_headers(client, "rec@b.test", "pw-b")
    p = register(client, ha)
    rep = upload(client, ha, p["id"]).json()
    assert client.get("/api/staff/patients", params={"phone": PHONE}, headers=hb).json() == []
    assert client.post(f"/api/staff/reports/{rep['id']}/send", headers=hb).status_code == 404
    assert client.get(f"/fhir/DiagnosticReport/{rep['id']}", headers=hb).status_code == 404
    fhir = client.get(f"/fhir/DiagnosticReport/{rep['id']}", headers=ha).json()
    assert fhir["resourceType"] == "DiagnosticReport"
    assert {c["code"] for c in fhir["code"]["coding"]} == {"4548-4", "24331-1"}


def test_wallet_needs_consent_for_other_labs(client):
    ha = staff_headers(client, "rec@a.test", "pw-a2")
    hb = staff_headers(client, "rec@b.test", "pw-b")
    pa = register(client, ha)
    pb = register(client, hb)
    ta = send_and_get_link(client, ha, upload(client, ha, pa["id"]).json()["id"])
    send_and_get_link(client, hb, upload(client, hb, pb["id"], codes="tsh").json()["id"])

    ph = patient_login(client, link_token=ta)
    me = client.get("/api/patient/me", headers=ph).json()
    assert len(me["people"]) == 1 and len(me["people"][0]["patient_ids"]) == 2  # same person at two labs
    lab_a = client.get(f"/api/public/r/{ta}").json()["lab"]["id"]
    w = client.get("/api/patient/reports", params={"lab_id": lab_a}, headers=ph).json()
    assert len(w["reports"]) == 1 and w["other_labs_hidden"] == 1

    client.post("/api/patient/consents/wallet", headers=ph, json={"give": True})
    w = client.get("/api/patient/reports", headers=ph).json()
    assert len(w["reports"]) == 2 and w["other_labs_hidden"] == 0


def test_otp_limits(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    register(client, h)
    body = {"phone": PHONE}
    client.post("/api/patient/otp/request", json=body)
    for _ in range(5):
        assert client.post("/api/patient/otp/verify", json={**body, "code": "000000"}).status_code in (400,)
    # even the right code is refused after 5 wrong tries
    assert client.post("/api/patient/otp/verify", json={**body, "code": last_code(client)}).status_code == 429
    client.post("/api/patient/otp/request", json=body)
    client.post("/api/patient/otp/request", json=body)
    assert client.post("/api/patient/otp/request", json=body).status_code == 429

    # expired code
    db = SessionLocal()
    otp = db.query(OtpCode).order_by(OtpCode.id.desc()).first()
    otp.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    db.close()
    assert client.post("/api/patient/otp/verify", json={**body, "code": "123456"}).status_code == 400


def test_unknown_phone_gets_no_sms(client):
    before = len(client.outbox)
    r = client.post("/api/patient/otp/request", json={"phone": "01899000000"})
    assert r.status_code == 200 and len(client.outbox) == before


def test_share_expires_and_revokes(client):
    h = staff_headers(client, "rec@a.test", "pw-a2")
    p = register(client, h)
    rep = upload(client, h, p["id"]).json()
    token = send_and_get_link(client, h, rep["id"])
    ph = patient_login(client, link_token=token)
    share = client.post("/api/patient/shares", headers=ph, json={"report_ids": [rep["id"]]}).json()
    dtoken = share["url"].rsplit("/", 1)[1]
    db = SessionLocal()
    s = db.get(Share, share["id"])
    s.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()
    assert client.get(f"/api/public/share/{dtoken}").status_code == 410

    share2 = client.post("/api/patient/shares", headers=ph, json={"report_ids": [rep["id"]]}).json()
    client.delete(f"/api/patient/shares/{share2['id']}", headers=ph)
    assert client.get(f"/api/public/share/{share2['url'].rsplit('/', 1)[1]}").status_code == 410


def test_recall_sent_and_return_counted(client):
    h = staff_headers(client, "owner@a.test", "pw-a")
    p = register(client, h)
    send_and_get_link(client, h, upload(client, h, p["id"], codes="hba1c").json()["id"])

    db = SessionLocal()
    today = recalls.bd_today()
    assert recalls.send_due(db, today=today + timedelta(days=89)) == 0
    assert recalls.send_due(db, today=today + timedelta(days=90)) == 1
    db.close()
    assert "HbA1c" in client.outbox[-1]["text"]

    # patient comes back: the new HbA1c report marks the reminder as returned
    send_and_get_link(client, h, upload(client, h, p["id"], codes="hba1c").json()["id"])
    db = SessionLocal()
    statuses = sorted(r.status for r in db.query(Recall).all())
    db.close()
    assert statuses == ["returned", "scheduled"]
    dash = client.get("/api/staff/dashboard", headers=h).json()
    assert dash["patients_returned"] == 1 and dash["reports_sent"] == 2
    assert dash["messages"]["by_kind"]["recall"] == 1


def test_phone_formats(client):
    from app.security import mask_phone, normalize_bd_phone
    for raw in ["01712334821", "+8801712334821", "8801712334821", "017 1233 4821"]:
        assert normalize_bd_phone(raw) == "8801712334821"
    for bad in ["0171233482", "01212334821", "12345"]:
        try:
            normalize_bd_phone(bad)
            assert False, bad
        except ValueError:
            pass
    assert mask_phone("8801712334821") == "017••••4821"
