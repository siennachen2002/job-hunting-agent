"""What a posting pays, as US dollars a year, from what it states: the board's own pay summary first (Ashby, Built In, YC),
else amounts in the description that sit next to a pay word ("salary", "pay range", "$45 per hour").

Hourly × 2,080, weekly × 52, monthly × 12. An amount with no unit is read by its size: under $300 an hour, under $20,000
a month, else a year. Pay in another currency, and amounts that can't be pay (a $250 a year perk), give nothing, so a
posting is never dropped on a guess: preferences.yaml → targets → salary_floor drops only what tops out below it.
"""
from __future__ import annotations
import json
import re

AMOUNT = re.compile(r"(?P<cur>US\$|USD\s?|\$|€|£|₹|CA\$|C\$|A\$)\s?(?P<n>\d[\d,]*(?:\.\d+)?)\s?(?P<k>[kK]\b|[mM]\b)?"
                    r"(?:\s?(?:-|–|—|to)\s?(?:US\$|USD\s?|\$)?\s?(?P<n2>\d[\d,]*(?:\.\d+)?)\s?(?P<k2>[kK]\b)?)?"
                    r"(?P<unit>\s?(?:/|per|an|a)\s?(?:hour|hr|year|yr|annum|month|mo|week|wk)\b|\s?(?:hourly|annually|yearly|monthly))?", re.I)
PAY_WORD = re.compile(r"salary|compensation|\bpay\b|pay range|base|wage|hourly|per hour|/hr|annual|\bOTE\b|range", re.I)
NOT_PAY = re.compile(r"stipend|housing|relocation|bonus|perk|lunch|gear|budget|credit|reimburs|allowance|equipment|learning|wellness|gym|401", re.I)
FOREIGN = re.compile(r"\b(CAD|AUD|NZD|SGD|HKD|MXN|BRL|EUR|GBP|INR|JPY|CHF|SEK|ILS|CNY|RMB)\b|\b(R|CA|C|A|NZ|HK|S|MX|NT)\$")
PER = {"hour": 2080, "hr": 2080, "hourly": 2080, "week": 52, "wk": 52, "month": 12, "mo": 12, "monthly": 12,
       "year": 1, "yr": 1, "annum": 1, "annually": 1, "yearly": 1}


def _num(n: str | None, k: str | None) -> float | None:
    if not n:
        return None
    v = float(n.replace(",", ""))
    return v * (1000 if (k or "").lower() == "k" else 1_000_000 if (k or "").lower() == "m" else 1)


def _yearly(v: float, unit: str) -> float | None:
    u = re.sub(r"[^a-z]", " ", unit.lower()).split()
    per = next((PER[w] for w in u if w in PER), None)
    if per is None:   # no unit: read it by its size
        per = 2080 if v < 300 else 12 if v < 20000 else 1
    y = v * per
    if per == 2080 and v > 500 or per == 1 and v < 10000:
        return None   # not pay: "$2,000 an hour", "$250 a year"
    return y


def amounts(text: str, near_pay_word: bool = True) -> list[float]:
    """Every yearly USD amount in the text; with near_pay_word, only those with a pay word in the 80 characters before
    and no stipend, perk or bonus word just before."""
    out = []
    for m in AMOUNT.finditer(text or ""):
        if m["cur"].strip().upper() not in ("$", "US$", "USD") or FOREIGN.search(text[max(0, m.start() - 5):m.end() + 6]):
            return []   # pay in another currency (R$, CAD $72,000, $34/hour CAD): unknown here, never a reason to drop
        if near_pay_word and (not PAY_WORD.search(text[max(0, m.start() - 80):m.start()])
                              or NOT_PAY.search(text[max(0, m.start() - 40):m.start()])):
            continue
        unit = m["unit"] or ""
        for n, k in ((m["n"], m["k"]), (m["n2"], m["k2"] or m["k"])):
            v = _num(n, k)
            y = _yearly(v, unit) if v else None
            if y:
                out.append(y)
    return out


def yearly_range(job: dict) -> tuple[float, float] | None:
    """(lowest, highest) pay a year in USD the posting states, or None when it states none we can read."""
    raw = job.get("raw")
    raw = json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else raw if isinstance(raw, dict) else {}
    comp = (raw or {}).get("compensation") or {}
    summary = comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary")
    found = amounts(summary, near_pay_word=False) if summary else []
    if not found and not summary:
        from .scoring import plain
        found = amounts(plain(job.get("description")))
    return (min(found), max(found)) if found else None


def floor() -> float | None:
    """preferences.yaml → targets → salary_floor ("90000 USD", 90000, "$90K"), as dollars a year."""
    from . import config
    v = (config.preferences().get("targets") or {}).get("salary_floor")
    if v in (None, "", 0):
        return None
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s?([kK])?", str(v))
    return _num(m.group(1), m.group(2)) if m else None
