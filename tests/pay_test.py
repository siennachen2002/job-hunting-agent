"""Reading pay from postings, on made-up text in the shapes real postings use: no network, nothing of yours read.

    python3 tests/pay_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.pay import yearly_range  # noqa: E402

CASES = [   # (posting, (lowest, highest) dollars a year, or None: unknown, never a reason to drop)
    ({"raw": {"compensation": {"compensationTierSummary": "$164.4K - $210.3K"}}}, (164400, 210300)),
    ({"raw": '{"compensation": {"compensationTierSummary": "$110K–$120K/yr"}}'}, (110000, 120000)),
    ({"raw": {"compensation": {"compensationTierSummary": "₹15K - ₹18K INR / monthly"}}}, None),
    ({"description": "The hourly pay for this role is $40 - $45 per hour."}, (83200, 93600)),
    ({"description": "Intern pay $43 per hour"}, (89440, 89440)),
    ({"description": "Base salary range: $70,000 to $80,000. Perks worth $80"}, (70000, 80000)),
    ({"description": "Pay: $60.58 per hour. Housing stipend $10,500.00"}, (126006.4, 126006.4)),
    ({"description": "Salary range is $123,372.00 - $161,925.75 per year"}, (123372, 161925.75)),
    ({"description": "Our cash compensation amount for this role is $69,000/yearly - $85,000/yearly"}, (69000, 85000)),
    ({"description": "The base pay range is: $88,000 - $110,000, plus bonus of $5,000"}, (88000, 110000)),
    ({"description": "We have $80 lunches and $200 gear, no pay listed"}, None),
    ({"description": "Compensation $250/year for books"}, None),
    ({"description": "The annual salary range is €60,000"}, None),
    ({"description": "Brazil Monthly Pay Range R$22.000—R$27.500 BRL"}, None),
    ({"description": "The base pay range in the Montreal area is $34-$36/hour CAD."}, None),
    ({"description": "est de CAD $72,000 - CAD 90,000."}, None),
]
for job, want in CASES:
    got = yearly_range(job)
    got = tuple(round(x, 2) for x in got) if got else None
    if got != (tuple(float(x) for x in want) if want else None):
        raise SystemExit(f"FAIL {job}: got {got}, want {want}")
print("pay: all checks pass")
