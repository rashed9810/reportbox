import os
import tempfile

from cryptography.fernet import Fernet

_tmp = tempfile.mkdtemp()
# Set TEST_DATABASE_URL to run the tests on Postgres instead of SQLite.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["FILE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["SMS_PROVIDER"] = "console"
os.environ["PUBLIC_BASE_URL"] = "http://app.test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import messaging, whatsapp  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Lab, Staff  # noqa: E402
from app.security import hash_password  # noqa: E402

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    lab_a = Lab(name="City Diagnostic Centre", name_bn="সিটি ডায়াগনস্টিক", sms_sender_id="CITYDIAG")
    lab_b = Lab(name="Sunrise Diagnostic", sms_sender_id="SUNRISE")
    db.add_all([lab_a, lab_b])
    db.flush()
    db.add_all([
        Staff(lab_id=lab_a.id, name="Owner A", email="owner@a.test", password_hash=hash_password("pw-a"), role="admin"),
        Staff(lab_id=lab_a.id, name="Shirin", email="rec@a.test", password_hash=hash_password("pw-a2")),
        Staff(lab_id=lab_b.id, name="Rec B", email="rec@b.test", password_hash=hash_password("pw-b")),
    ])
    db.commit()
    db.close()
    provider = messaging.ConsoleProvider()
    messaging.set_provider(provider)
    wa = whatsapp.FakeWhatsApp()
    whatsapp.set_provider(wa)
    s = get_settings()
    saved = {k: getattr(s, k) for k in ("whatsapp_enabled", "wa_app_secret", "wa_verify_token", "vat_percent")}
    with TestClient(app) as c:
        c.outbox = provider.outbox
        c.wa = wa
        yield c
    for k, v in saved.items():  # tests may change settings; put them back
        setattr(s, k, v)


def staff_headers(client, email, password):
    r = client.post("/api/staff/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
