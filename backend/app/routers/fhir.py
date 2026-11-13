"""Read-only HL7 FHIR R4 views, so ReportBox can later connect to DGHS's Shared Health Record
or other systems without changing how data is stored."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..catalog import TEST_CATALOG
from ..db import get_db
from ..deps import current_staff
from ..models import Patient, Report, Staff

router = APIRouter(prefix="/fhir", tags=["fhir"])

_SEX = {"F": "female", "M": "male", "O": "other"}


def patient_resource(p: Patient) -> dict:
    res = {"resourceType": "Patient", "id": str(p.id), "name": [{"text": p.name}],
           "gender": _SEX.get(p.sex, "unknown"),
           "telecom": [{"system": "phone", "value": "+" + p.phone_account.phone, "use": "mobile"}],
           "managingOrganization": {"reference": f"Organization/{p.lab_id}"}}
    if p.birth_year:
        res["birthDate"] = str(p.birth_year)
    return res


def diagnostic_report_resource(r: Report) -> dict:
    codings = [{"system": "http://loinc.org", "code": TEST_CATALOG[c]["loinc"], "display": TEST_CATALOG[c]["name"]}
               for c in r.test_codes]
    return {
        "resourceType": "DiagnosticReport", "id": str(r.id),
        "status": "final" if r.status == "sent" else "preliminary",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "LAB"}]}],
        "code": {"coding": codings, "text": r.title},
        "subject": {"reference": f"Patient/{r.patient_id}"},
        "performer": [{"reference": f"Organization/{r.lab_id}"}],
        "issued": (r.sent_at or r.created_at).isoformat() + "Z",
        "presentedForm": [{"contentType": "application/pdf", "size": r.file_size,
                           "hash": r.sha256, "title": r.title}],
    }


@router.get("/Patient/{patient_id}")
def read_patient(patient_id: int, staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    p = db.get(Patient, patient_id)
    if not p or p.lab_id != staff.lab_id:
        raise HTTPException(404, "Not found")
    return patient_resource(p)


@router.get("/DiagnosticReport/{report_id}")
def read_report(report_id: int, staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if not r or r.lab_id != staff.lab_id:
        raise HTTPException(404, "Not found")
    return diagnostic_report_resource(r)
