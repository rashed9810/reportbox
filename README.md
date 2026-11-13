# ReportBox (version 0.3, pilot-ready)

Labs send test reports to patients' phones by SMS or WhatsApp. Patients open a link, enter a 6-digit code, and see all their reports. They can share them with a doctor through a link or QR code that stops working after 24 hours. Labs can turn on repeat-test reminders, which bring patients back, and pay a monthly plan by bKash or Nagad.

Version 0.3 is ready for a small pilot once the legal steps in "Before real patients" are done. **To put it on a server, follow [docs/DEPLOY.md](docs/DEPLOY.md).**

## What's inside

| Folder | What it is |
| --- | --- |
| `backend/` | Python **FastAPI** server: database, logins, PDFs, SMS, reminders, migrations |
| `frontend/` | **Next.js** website: reception, owner dashboard, lab settings, billing, account and staff, patient pages and settings, doctor page |
| `deploy/` | Everything for the live server: Docker setup, HTTPS proxy, nightly encrypted backups |
| `docs/DEPLOY.md` | Step-by-step guide to going live on a server in Bangladesh |
| `docker-compose.yml` | Optional Postgres for your own computer (SQLite also works) |

## Run it on your computer

You need Python 3.11+ and Node.js 20+.

### 1. Start the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and set `FILE_ENCRYPTION_KEY`. Generate one with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then create the demo lab and start the server:

```bash
python -m app.cli seed
uvicorn app.main:app --reload --port 8000
```

API docs open at http://localhost:8000/api/docs.

### 2. Start the frontend (in a second terminal)

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. The website forwards `/api` calls to the backend, so both share one address and the login cookies work.

### 3. Try the whole flow

1. Click **Lab staff sign in**: `reception@citydiag.test` / `reception-demo-123`.
2. Type a phone number like `01712334821`, press **Search**, and add a new family member.
3. Attach any PDF, tick **HbA1c**, tick the consent box, then press **Send to patient**.
4. Look at the **backend terminal**: the "SMS" is printed there with a link like `http://localhost:3000/r/abc123`. Open it (a phone-sized browser window works best).
5. Press **কোড পাঠান** (Send code). The 6-digit code also prints in the backend terminal. Enter it.
6. You're in the patient's health wallet. Tap the report to open the PDF, or **ডাক্তারকে দেখান** (Show to doctor) to make a 24-hour link.
7. Sign in as the owner (`owner@citydiag.test` / `owner-demo-123`): see **Owner dashboard**, add staff and turn on two-step sign-in under **Account & staff**, choose reminder intervals under **Lab settings**, and see the plan under **Billing**.
8. In the patient's wallet, open **সেটিংস ও গোপনীয়তা** (Settings and privacy) to download the data, stop a lab, or close the wallet.

To try **WhatsApp** locally, set `WHATSAPP_ENABLED=true` in `backend/.env` (leave `WA_PHONE_NUMBER_ID` empty). The patient's settings then show the WhatsApp switch, and "sent" WhatsApp messages print in the backend terminal.

To try **billing** locally: `python -m app.cli generate-invoices --period 2026-10` bills last month (only labs that existed then), and `python -m app.cli confirm-payment --invoice 1` marks a payment as received.

### Run the tests

```bash
cd backend
pytest -q
# on Postgres instead of SQLite:
TEST_DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/testdb" pytest -q
```

30 tests cover the full flow and the safety rules:
- consent before sending, and guardian consent for under-18s
- staff only see their own lab
- login-code limits and the staff password lockout
- cookie sign-in with protection against other sites acting for a signed-in user
- two-step sign-in: setup, wrong codes, a code never working twice, and the admin reset for a lost phone
- staff accounts, real-SMS replies and resending failed SMS
- WhatsApp: only after the patient opts in, the exact request Meta expects, SMS fallback when it fails, and signed delivery updates
- each lab's own reminder rules, and no reminder after a patient withdraws consent
- privacy: download my data (without login codes), stop a lab, close the wallet
- billing: discount, extra usage, VAT, running twice safely, payment submission and confirmation, overdue status
- link expiry, the wallet needing permission for other labs, and reminders only in the daytime

## How it works (short version)

- **Patient identity:** a phone number is a *household*, not a person. One phone can hold several family members. Labs only see the patients they registered.
- **Two separate consents:** (1) staff record that the patient agreed to digital delivery from *this lab*; (2) the patient, in the app, agrees to see reports from *all labs* together. Without (2), patients only see one lab's reports.
- **The message never names the test**, so a shared phone does not reveal it.
- **Sign-in** uses httpOnly cookies that page scripts cannot read. Changes need a special header that other websites cannot send. Staff are locked out for 15 minutes after 5 wrong attempts. **Two-step sign-in** (authenticator app codes) can be turned on per person; its secret is stored encrypted.
- **PDFs are encrypted** on disk. Sessions and share links are random tokens, and only their hashes are stored.
- **Login codes:** 6 digits, valid 5 minutes, 5 wrong tries maximum, 3 requests per 15 minutes per phone. Unknown numbers get no SMS (and cost nothing).
- **SMS:** `SMS_PROVIDER=bulksmsbd` sends through BulkSMSBD using each lab's own sender ID. A failed message shows its reason on the reception screen with a **Resend** button.
- **WhatsApp:** patients who switch it on get "report ready" as a WhatsApp *utility* template with a button to their report. If WhatsApp fails, at once or later (reported by Meta's webhook), the report goes by SMS. Codes and reminders always go by SMS.
- **Reminders:** each lab chooses which tests get a reminder and after how many days (defaults: 90 days for sugar tests, 180 for lipid, TSH and creatinine). The worker sends due reminders between 10:00 and 19:00 Bangladesh time, and skips patients who withdrew consent. If the patient repeats the test within 60 days, the dashboard counts them as "came back".
- **Patient rights:** download everything held about them, stop any lab from messaging them, and close the wallet (stops doctor links and WhatsApp, signs out everywhere). Labs keep their own medical records.
- **Billing:** plans and prices live in `backend/app/plans.py`. The worker makes last month's invoices on the 1st. Owners pay by bKash/Nagad and enter the transaction ID; you confirm with `python -m app.cli confirm-payment`. Amounts are stored in paisa, so they add up exactly.
- **Listen button:** reads the page aloud using the phone's own voice. It only appears when the phone has a Bangla (or English) voice installed.
- **Database changes** go through Alembic migrations (`alembic upgrade head`). The server applies them on start.
- **FHIR-ready:** `/fhir/Patient/{id}` and `/fhir/DiagnosticReport/{id}` return standard HL7 FHIR R4 with LOINC codes, for connecting to DGHS's Shared Health Record later.
- **Audit log:** every login, upload, send, view, share, consent change, data download and staff change is recorded in `audit_events`.

## Before real patients (must do)

1. **Lawyer review** of the consent wording, privacy policy, data processing agreement with each lab, and the hosting and backup locations (Personal Data Protection law).
2. **Go live on a Bangladeshi server** following `docs/DEPLOY.md`, including its go-live checklist.
3. **SMS:** BulkSMSBD account, server IP whitelisted, each pilot lab's sender ID approved. Confirm the API details against your BulkSMSBD dashboard.
4. **Accountant:** confirm the VAT rate (and any startup exemption) before charging VAT.
5. **Outside security check** before growing past the pilot labs.

## Not built yet (on purpose)

- **Automatic upload from lab software** ("watch folder" or a direct link to the lab's system): depends on which software your interviews show labs use.
- **Reading results out of PDFs for trend charts:** each lab's report layout is different. It needs real reports from pilot labs.
- **Automatic bKash/Nagad checkout:** needs a merchant account and the gateway's private API documentation. Payments are confirmed by hand for now.
- **Patient-confirmed merging** of the same person across labs. Today one person is matched by name plus birth year on the same phone.
- **Bangla for the staff screens.**
- **Phase 2 (Sugar-Pressure Companion):** planned after about 30 paying labs.
