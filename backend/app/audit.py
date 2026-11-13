from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditEvent


def audit(db: Session, request: Request | None, *, actor_type: str, actor_id: int | None, action: str,
          entity: str, entity_id: int | None = None, lab_id: int | None = None, detail: dict | None = None) -> None:
    ip = request.client.host if request and request.client else None
    db.add(AuditEvent(actor_type=actor_type, actor_id=actor_id, action=action, entity=entity,
                      entity_id=entity_id, lab_id=lab_id, ip=ip, detail=detail))
