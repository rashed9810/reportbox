"""Login checks used by the API routes.

The website signs in with httpOnly cookies (JavaScript cannot read them, so a script injected
into a page cannot steal a session). Other programs can still use an `Authorization: Bearer`
header. Requests that change data with a cookie must carry the `X-RB-CSRF: 1` header, which
other websites cannot add, so they cannot trick a signed-in browser into acting.
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import PatientSession, PhoneAccount, Staff, StaffSession, utcnow
from .security import hash_token

STAFF_COOKIE = "rb_staff"
PATIENT_COOKIE = "rb_patient"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _token(request: Request, cookie_name: str) -> str:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    token = request.cookies.get(cookie_name)
    if not token:
        raise HTTPException(401, "Not signed in")
    if request.method not in SAFE_METHODS and request.headers.get("x-rb-csrf") != "1":
        raise HTTPException(403, "Missing security header")
    return token


def current_staff(request: Request, db: Session = Depends(get_db)) -> Staff:
    sess = db.get(StaffSession, hash_token(_token(request, STAFF_COOKIE)))
    if not sess or sess.expires_at < utcnow():
        raise HTTPException(401, "Session expired, please sign in again")
    staff = db.get(Staff, sess.staff_id)
    if not staff or not staff.active:
        raise HTTPException(401, "Account disabled")
    return staff


def current_admin(staff: Staff = Depends(current_staff)) -> Staff:
    if staff.role != "admin":
        raise HTTPException(403, "Only the lab admin can do this")
    return staff


def current_phone_account(request: Request, db: Session = Depends(get_db)) -> PhoneAccount:
    sess = db.get(PatientSession, hash_token(_token(request, PATIENT_COOKIE)))
    if not sess or sess.expires_at < utcnow():
        raise HTTPException(401, "Please enter a new code")
    account = db.get(PhoneAccount, sess.phone_account_id)
    if not account:
        raise HTTPException(401, "Please enter a new code")
    return account
