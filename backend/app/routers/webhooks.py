"""Delivery updates from Meta's WhatsApp Cloud API.

In the Meta app dashboard set the webhook URL to https://YOUR-DOMAIN/api/webhooks/whatsapp, the
verify token to WA_VERIFY_TOKEN, and subscribe to the "messages" field.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import whatsapp
from ..config import get_settings
from ..db import get_db

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
def verify_webhook(request: Request):
    q = request.query_params
    token = get_settings().wa_verify_token
    if q.get("hub.mode") == "subscribe" and token and q.get("hub.verify_token") == token:
        return Response(q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "Verification failed")


@router.post("/whatsapp")
async def whatsapp_update(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not whatsapp.signature_ok(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "Bad signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Bad JSON")
    fallbacks = whatsapp.handle_status_update(db, payload)
    return {"ok": True, "sms_fallbacks": fallbacks}
