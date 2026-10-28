"""Job boards that list roles across many companies: Built In (builtinnyc.com) and Y Combinator's Work at a Startup.

They find companies and roles; the company's own Greenhouse, Lever or Ashby board has the form the agent can fill. So a
role found here is kept in its ATS version when the company has one with the same title, and otherwise as the board's
listing, for you to apply to by hand. Each company's board is looked up once and remembered (the companies table).

Only pages each site's robots.txt allows are read: Built In category pages 1-3 and job pages, YC's /jobs. One request
at a time, PAUSE seconds apart (Built In answers 429 to faster reading); a 429 ends that board until the next refresh,
and a listing already seen is never fetched again (the board_seen table).
"""
from __future__ import annotations
import html as _html
import json
import re
import time
from urllib.parse import urlparse
from .. import db
from . import ats
from .base import client, strip_html, looks_remote

PAUSE = {"builtin": 1.5, "yc": 0.5}   # seconds between requests to each site
MAX_NEW = 80      # job pages read per board per refresh; the rest wait for the next one


class TooFast(Exception):
    """The site answered 429: stop reading it until the next refresh."""


def _get(url: str, pause: float) -> str:
    time.sleep(pause)
    r = client.get(url)
    if r.status_code == 429:
        raise TooFast(url)
    return r.text if r.status_code == 200 else ""


def _ld(page: str) -> list[dict]:
    """Every schema.org object in the page's JSON-LD blocks, @graph flattened."""
    out = []
    for block in re.findall(r'<script[^>]*type="application/ld(?:\+|&#x2B;)json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        for it in d if isinstance(d, list) else [d]:
            out += it.get("@graph", [it]) if isinstance(it, dict) else []
    return out


def _inertia(page: str) -> dict:
    """The props a ycombinator.com page renders from (its data-page attribute)."""
    m = re.search(r'data-page="([^"]+)"', page)
    return json.loads(_html.unescape(m.group(1))).get("props", {}) if m else {}


def _money(lo, hi, cur="USD", unit="YEAR") -> str | None:
    if not lo and not hi:
        return None
    f = lambda n: f"${n / 1000:.0f}K" if cur == "USD" else f"{n:,.0f} {cur}"
    return "–".join(f(n) for n in (lo, hi) if n) + ("/yr" if unit == "YEAR" else "/hr" if unit == "HOUR" else "")


# ---- Built In ------------------------------------------------------------
def builtin(site: str, category: str, seen) -> list[dict]:
    get = lambda u: _get(u, PAUSE["builtin"])
    listing = []
    for p in (1, 2, 3):   # robots.txt allows pages 1-3 of a category
        page = get(f"https://www.{site}/jobs/{category}" + (f"?page={p}" if p > 1 else ""))
        items = [i for o in _ld(page) if o.get("@type") == "ItemList" for i in o.get("itemListElement", [])]
        if not items:
            break
        listing += [i["url"] for i in items if "/job/" in i.get("url", "")]
    out = []
    for url in dict.fromkeys(listing):
        jid = url.rstrip("/").rsplit("/", 1)[-1]
        if seen(f"builtin:{jid}"):
            continue
        if len(out) >= MAX_NEW:
            break
        try:
            jp = next((o for o in _ld(get(url)) if o.get("@type") == "JobPosting"), None)
        except TooFast:
            break

        if not jp:
            continue
        places = jp.get("jobLocation") or []
        places = [x.get("address", {}) for x in (places if isinstance(places, list) else [places])]
        loc = " · ".join(dict.fromkeys(", ".join(filter(None, (a.get("addressLocality"), a.get("addressRegion")))) for a in places)) or None
        pay = ((jp.get("baseSalary") or {}).get("value") or {})
        out.append({
            "source": "builtin", "external_id": jid, "company": (jp.get("hiringOrganization") or {}).get("name"),
            "title": jp.get("title"), "location": loc, "remote": jp.get("jobLocationType") == "TELECOMMUTE" or looks_remote(loc),
            "url": url, "apply_url": None, "description": strip_html(jp.get("description")), "posted_at": jp.get("datePosted"),
            "raw": {"board": site, "website": None,
                    "compensation": {"compensationTierSummary": _money(pay.get("minValue"), pay.get("maxValue"),
                                                                       (jp.get("baseSalary") or {}).get("currency", "USD"), pay.get("unitText"))}},
        })
    return out


# ---- Y Combinator --------------------------------------------------------
def yc(role: str, seen) -> list[dict]:
    get = lambda u: _get(u, PAUSE["yc"])
    out = []
    for j in _inertia(get(f"https://www.ycombinator.com/jobs/role/{role}")).get("jobPostings", []):
        if seen(f"yc:{j['id']}"):
            continue
        if len(out) >= MAX_NEW:
            break
        try:
            props = _inertia(get("https://www.ycombinator.com" + j["url"]))
        except TooFast:
            break
        job, co = props.get("job") or {}, props.get("company") or {}
        out.append({
            "source": "yc", "external_id": str(j["id"]), "company": j.get("companyName"), "title": j.get("title"),
            "location": j.get("location"), "remote": looks_remote(j.get("location")),
            "url": "https://www.ycombinator.com" + j["url"], "apply_url": None,
            "description": strip_html(job.get("description")) or j.get("companyOneLiner", ""), "posted_at": None,
            "raw": {"board": "ycombinator.com", "website": co.get("website"), "batch": j.get("companyBatchName"),
                    "type": j.get("type"), "min_experience": j.get("minExperience"), "visa": j.get("visa"),
                    "compensation": {"compensationTierSummary": j.get("salaryRange") or None}},
        })
    return out


# ---- the company's own board ---------------------------------------------
def _slugs(name: str | None, website: str | None) -> list[str]:
    n = (name or "").lower()
    host = urlparse(website or "").netloc.lower().removeprefix("www.")
    return list(dict.fromkeys(s for s in (re.sub(r"[^a-z0-9]", "", n), re.sub(r"[^a-z0-9]+", "-", n).strip("-"),
                                            host.split(".")[0] if host else "") if s))


def company_board(con, name: str | None, website: str | None) -> tuple[str, str] | None:
    """The company's Greenhouse, Lever or Ashby board: looked up once by its name and website, then remembered."""
    row = con.execute("SELECT ats, board_token FROM companies WHERE name=?", (name,)).fetchone()
    if row:
        return (row["ats"], row["board_token"]) if row["ats"] != "none" else None
    found = next((f[0] for s in _slugs(name, website) for f in [ats.probe_company(s)] if f), None)
    con.execute("INSERT OR IGNORE INTO companies(name, slug, domain, ats, board_token, created_at) VALUES (?,?,?,?,?,?)",
                (name, found[1] if found else None, urlparse(website or "").netloc or None, found[0] if found else "none",
                 found[1] if found else None, db.now()))
    return found


def _title(t: str | None) -> str:
    return re.sub(r"\W+", " ", (t or "").lower()).strip()


def fetch(con, board: dict) -> list[dict]:
    """New roles from one board in profile/companies.yaml → boards, each in its ATS version when the company has one."""
    con.execute("CREATE TABLE IF NOT EXISTS board_seen (key TEXT PRIMARY KEY, at TEXT)")
    seen = lambda k: con.execute("SELECT 1 FROM board_seen WHERE key=?", (k,)).fetchone() is not None
    found = (builtin(board.get("site", "builtinnyc.com"), board.get("category", "design-ux"), seen) if board["board"] == "builtin"
             else yc(board.get("role", "design"), seen) if board["board"] == "yc" else [])
    have = {db.role_key(c, t) for c, t in con.execute("SELECT company, title FROM jobs").fetchall()}
    boards: dict[tuple, list] = {}
    out = []
    for j in found:
        con.execute("INSERT OR IGNORE INTO board_seen(key, at) VALUES (?,?)", (f"{j['source']}:{j['external_id']}", db.now()))
        if db.role_key(j["company"], j["title"]) in have:
            continue   # already found, on the company's own board or another listing
        try:   # a network hiccup here keeps the board's own listing rather than losing the role
            b = company_board(con, j["company"], j["raw"].get("website"))
            if b and b not in boards:
                boards[b] = ats.FETCHERS[b[0]](b[1], j["company"])
        except Exception:
            b = None
        if b:
            same = [x for x in boards[b] if _title(x["title"]) == _title(j["title"])]
            here = set(_title(j["location"]).split()) - {"us", "usa", "united", "states"}
            # the same role in the same place; a board listing with no place takes the first
            twin = next((x for x in same if not here or here & set(_title(x["location"]).split())), None)
            if twin:
                twin["raw"] = {**(twin.get("raw") or {}), "found_on": j["url"]}
                j = twin
        have.add(db.role_key(j["company"], j["title"]))
        out.append(j)
    con.commit()
    return out
