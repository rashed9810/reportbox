"""Common tests, their LOINC codes and the default repeat interval used for recall reminders.

The lab can override intervals later; these defaults are a starting point, not medical advice.
"""

TEST_CATALOG: dict[str, dict] = {
    "hba1c": {"name": "HbA1c", "name_bn": "রক্তের সুগার (HbA1c)", "loinc": "4548-4", "recall_days": 90},
    "fbs": {"name": "Fasting blood sugar", "name_bn": "খালি পেটে সুগার", "loinc": "1558-6", "recall_days": 90},
    "lipid": {"name": "Lipid profile", "name_bn": "লিপিড প্রোফাইল", "loinc": "24331-1", "recall_days": 180},
    "tsh": {"name": "TSH (thyroid)", "name_bn": "থাইরয়েড (TSH)", "loinc": "3016-3", "recall_days": 180},
    "creatinine": {"name": "Creatinine", "name_bn": "ক্রিয়েটিনিন", "loinc": "2160-0", "recall_days": 180},
    "cbc": {"name": "CBC", "name_bn": "সিবিসি (রক্ত পরীক্ষা)", "loinc": "58410-2", "recall_days": None},
}


def validate_codes(codes: list[str]) -> list[str]:
    unknown = [c for c in codes if c not in TEST_CATALOG]
    if unknown:
        raise ValueError(f"Unknown test codes: {', '.join(unknown)}")
    return codes
