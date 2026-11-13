"""WhatsApp delivery through Meta's WhatsApp Cloud API.

Only the "report ready" message goes by WhatsApp, as a *utility* template, which is priced like a
branded SMS in Bangladesh. Login codes and reminders stay on SMS (reminders would count as
marketing on WhatsApp, about 20x the price).

The template must be created and approved in WhatsApp Manager first (see docs/DEPLOY.md):
  body:   "{{1}}: {{2}}-এর রিপোর্ট প্রস্তুত। নিচের বোতামে চাপ দিন।"
  button: "Visit website" URL button, URL https://YOUR-DOMAIN/r/{{1}}
"""
import hashlib
import hmac
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .messaging import render, send_sms
from .models import Lab, Message, Report

log = logging.getLogger("reportbox.whatsapp")


class WhatsAppError(Exception):
    pass


class CloudApiProvider:
    def __init__(self, phone_number_id: str, access_token: str, api_version: str, client: httpx.Client | None = None):
        if not phone_number_id or not access_token:
            raise RuntimeError("WA_PHONE_NUMBER_ID and WA_ACCESS_TOKEN are required when WHATSAPP_ENABLED=true")
        self.url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        self.token = access_token
        self.client = client or httpx.Client(timeout=15)

    def send_template(self, to: str, template: str, lang: str, body_params: list[str], url_suffix: str) -> str:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": lang},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": p} for p in body_params]},
                    {"type": "button", "sub_type": "url", "index": "0",
                     "parameters": [{"type": "text", "text": url_suffix}]},
                ],
            },
        }
        r = self.client.post(self.url, json=payload, headers={"Authorization": f"Bearer {self.token}"})
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400 or "error" in body:
            err = body.get("error", {})
            raise WhatsAppError(f"WhatsApp {err.get('code', r.status_code)}: {err.get('message', r.text[:150])}")
        try:
            return body["messages"][0]["id"]
        except (KeyError, IndexError):
            raise WhatsAppError(f"Unexpected WhatsApp reply: {str(body)[:150]}")


class FakeWhatsApp:
    """For tests and local development: records what would be sent."""

    def __init__(self):
        self.outbox: list[dict] = []
        self.fail_with: str | None = None

    def send_template(self, to, template, lang, body_params, url_suffix) -> str:
        if self.fail_with:
            raise WhatsAppError(self.fail_with)
        ref = f"wamid.fake{len(self.outbox) + 1}"
        self.outbox.append({"to": to, "template": template, "lang": lang, "body": body_params,
                            "url_suffix": url_suffix, "ref": ref})
        print(f"[WhatsApp to {to}] {template}/{lang} {body_params} button=/r/{url_suffix}", flush=True)
        return ref


_provider = None


def is_enabled() -> bool:
    return get_settings().whatsapp_enabled


def get_provider():
    global _provider
    if _provider is None:
        s = get_settings()
        _provider = (CloudApiProvider(s.wa_phone_number_id, s.wa_access_token, s.wa_api_version)
                     if s.wa_phone_number_id else FakeWhatsApp())
    return _provider


def set_provider(provider) -> None:
    global _provider
    _provider = provider


def _lab_name(lab: Lab, lang: str) -> str:
    return lab.name_bn if lang == "bn" and lab.name_bn else lab.name


def deliver_report(db: Session, report: Report) -> Message:
    """Tell the patient their report is ready: WhatsApp if they chose it, else (or if it fails) SMS.
    Returns the message that carried it."""
    s = get_settings()
    patient, lab = report.patient, report.lab
    acct = patient.phone_account
    lang = acct.language
    lab_name = _lab_name(lab, lang)

    if is_enabled() and acct.whatsapp_opt_in:
        msg = Message(lab_id=lab.id, report_id=report.id, phone=acct.phone, channel="whatsapp", kind="report_ready",
                      body=f"[template {s.wa_template_report_ready}] {lab_name} | {patient.name} | /r/{report.link_token}")
        db.add(msg)
        try:
            msg.provider_ref = get_provider().send_template(
                acct.phone, s.wa_template_report_ready,
                s.wa_template_lang_bn if lang == "bn" else s.wa_template_lang_en,
                [lab_name, patient.name], report.link_token)
            msg.status = "sent"
            db.flush()
            return msg
        except Exception as exc:
            msg.status, msg.error = "failed", str(exc)[:300]
            log.warning("WhatsApp failed, falling back to SMS: %s", exc)
            db.flush()

    return _send_report_sms(db, report)


def _send_report_sms(db: Session, report: Report) -> Message:
    patient, lab = report.patient, report.lab
    lang = patient.phone_account.language
    url = f"{get_settings().public_base_url.rstrip('/')}/r/{report.link_token}"
    # the message never names the test, so a shared phone does not reveal it
    text = render("report_ready", lang, lab=_lab_name(lab, lang), name=patient.name, url=url)
    return send_sms(db, phone=patient.phone_account.phone, kind="report_ready", text=text, lab=lab,
                    report_id=report.id)


# ---------- delivery updates from Meta (webhook) ----------

def signature_ok(raw_body: bytes, header: str | None) -> bool:
    secret = get_settings().wa_app_secret
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def handle_status_update(db: Session, payload: dict) -> int:
    """When Meta reports a WhatsApp message as failed (e.g. the number has no WhatsApp),
    send the report by SMS instead. Returns how many fallbacks were sent."""
    fallbacks = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for st in change.get("value", {}).get("statuses", []) or []:
                msg = db.scalar(select(Message).where(Message.provider_ref == st.get("id"),
                                                      Message.channel == "whatsapp"))
                if not msg:
                    continue
                status = st.get("status")
                if status in ("delivered", "read"):
                    msg.status = "delivered"
                elif status == "failed" and msg.status != "failed":
                    errors = st.get("errors") or [{}]
                    msg.status, msg.error = "failed", f"WhatsApp {errors[0].get('code', '')}: {errors[0].get('title', 'failed')}"[:300]
                    if msg.kind == "report_ready" and msg.report_id:
                        report = db.get(Report, msg.report_id)
                        if report and report.status == "sent":
                            _send_report_sms(db, report)
                            fallbacks += 1
    db.commit()
    return fallbacks
