"""Sending SMS.

Providers (choose with SMS_PROVIDER):
- console    prints the message and keeps it in memory. For development and tests.
- bulksmsbd  BulkSMSBD (bulksmsbd.net), a Bangladeshi aggregator. Uses its documented
             `/api/smsapi` endpoint; response_code 202 means "submitted". Confirm the details in
             your BulkSMSBD dashboard before going live, and whitelist the server's IP there
             (error 1032 means the IP is not whitelisted).
- http       a generic adapter: edit HttpSmsProvider.send() to match another aggregator.

Keep Bangla messages short: Unicode SMS fit about 70 characters per part, so long ones cost 2-3x.
"""
import logging

import httpx
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Lab, Message

log = logging.getLogger("reportbox.sms")

TEMPLATES = {
    "report_ready": {
        "bn": "{lab}: {name}-এর রিপোর্ট প্রস্তুত। দেখুন: {url}",
        "en": "{lab}: Report for {name} is ready. View: {url}",
    },
    "otp": {
        "bn": "রিপোর্টবক্স কোড: {code}। ৫ মিনিট বৈধ। কাউকে বলবেন না।",
        "en": "ReportBox code: {code}. Valid 5 minutes. Do not share it.",
    },
    "recall": {
        "bn": "{lab}: {name}, আপনার {test} পরীক্ষার সময় হয়েছে। প্রয়োজনে ডাক্তারের সাথে কথা বলুন।",
        "en": "{lab}: {name}, your {test} test is due. Please talk to your doctor if needed.",
    },
}

BULKSMSBD_ERRORS = {
    1001: "Invalid number", 1002: "Sender ID not correct or disabled", 1007: "Balance insufficient",
    1011: "User ID not found", 1032: "Server IP not whitelisted in BulkSMSBD",
}


class SmsError(Exception):
    pass


class ConsoleProvider:
    def __init__(self):
        self.outbox: list[dict] = []

    def send(self, phone: str, text: str, sender_id: str | None = None) -> str:
        ref = f"console-{len(self.outbox) + 1}"
        self.outbox.append({"phone": phone, "text": text, "ref": ref, "sender_id": sender_id})
        print(f"[SMS to {phone} from {sender_id or '-'}] {text}", flush=True)
        return ref


class BulkSmsBdProvider:
    URL = "https://bulksmsbd.net/api/smsapi"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise RuntimeError("SMS_API_KEY is required for SMS_PROVIDER=bulksmsbd")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=15)

    def send(self, phone: str, text: str, sender_id: str | None = None) -> str:
        params = {"api_key": self.api_key, "type": "text", "number": phone, "message": text}
        if sender_id:
            params["senderid"] = sender_id
        r = self.client.post(self.URL, data=params)
        r.raise_for_status()
        try:
            body = r.json()
        except ValueError:
            raise SmsError(f"Unexpected reply: {r.text[:120]}")
        code = int(body.get("response_code", 0))
        if code != 202:
            raise SmsError(f"BulkSMSBD {code}: {BULKSMSBD_ERRORS.get(code, body.get('error_message', 'error'))}")
        return str(body.get("message_id") or body.get("success_message") or "202")[:100]


class HttpSmsProvider:
    def __init__(self, url: str, api_key: str):
        self.url, self.api_key = url, api_key

    def send(self, phone: str, text: str, sender_id: str | None = None) -> str:
        # Generic shape. Check your aggregator's documentation and adjust.
        params = {"api_key": self.api_key, "number": phone, "message": text}
        if sender_id:
            params["senderid"] = sender_id
        r = httpx.post(self.url, data=params, timeout=15)
        r.raise_for_status()
        return r.text[:100]


_provider = None


def get_provider():
    global _provider
    if _provider is None:
        s = get_settings()
        if s.sms_provider == "bulksmsbd":
            _provider = BulkSmsBdProvider(s.sms_api_key)
        elif s.sms_provider == "http":
            _provider = HttpSmsProvider(s.sms_http_url, s.sms_http_api_key)
        else:
            _provider = ConsoleProvider()
    return _provider


def set_provider(provider) -> None:
    global _provider
    _provider = provider


def render(kind: str, lang: str, **values) -> str:
    templates = TEMPLATES[kind]
    return templates.get(lang, templates["bn"]).format(**values)


def send_sms(db: Session, *, phone: str, kind: str, text: str, lab: Lab | None = None,
             report_id: int | None = None) -> Message:
    msg = Message(lab_id=lab.id if lab else None, report_id=report_id, phone=phone, kind=kind, body=text)
    db.add(msg)
    sender = (lab.sms_sender_id if lab and lab.sms_sender_id else None) or get_settings().sms_sender_id or None
    try:
        msg.provider_ref = get_provider().send(phone, text, sender_id=sender)
        msg.status = "sent"
    except Exception as exc:  # keep going; the message stays visible as failed and can be resent
        msg.status, msg.error = "failed", str(exc)[:300]
        log.exception("SMS failed")
    db.flush()
    return msg
