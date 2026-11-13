"""Price plans. Prices and allowances follow the pricing in the ReportBox research; change them here.

Only messages that were actually sent count (failed ones are free). A report counts once, in the
month it was created, however many times its SMS is resent.
"""

PLANS: dict[str, dict] = {
    "starter": {"name": "Starter (Shuru)", "price_bdt": 2500, "reports": 600, "messages": 1200},
    "growth": {"name": "Growth (Briddhi)", "price_bdt": 4500, "reports": 2000, "messages": 4000},
    "pro": {"name": "Pro", "price_bdt": 8000, "reports": 5000, "messages": 10000},
}

OVERAGE_PAISA_PER_MESSAGE = 60  # BDT 0.60
OVERAGE_PAISA_PER_REPORT = 100  # BDT 1.00
PAYMENT_DUE_DAY = 15  # invoices are due on this day of the month after the billed month


def get_plan(code: str) -> dict:
    return PLANS.get(code) or PLANS["growth"]


def taka(paisa: int) -> str:
    """12345 -> '123.45'"""
    sign = "-" if paisa < 0 else ""
    paisa = abs(paisa)
    return f"{sign}{paisa // 100:,}.{paisa % 100:02d}"
