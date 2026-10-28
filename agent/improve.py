"""How well the scores agree with your Good and Nope, what to change, and what each change you applied did.

The idea comes from the course's Week 7 job agent (suggest.py, outcomes.py), rebuilt on this agent's verdicts table:
code gathers the evidence and checks every suggestion; nothing changes until you apply it.

- agreement   how often a post you marked Good scored above one you marked Nope (pairs; ties count half)
- suggest     code-only suggestions, each checked against your verdicts before you see it:
                weights      the weights that would have ranked your judged posts best, offered only if they gain CLEAR points
                drop_titles  title words found in at least two Nope titles and in no Good title (preferences → prefilter)
                source_off   watched companies whose postings never pass the prefilter, or that you only ever marked Nope
              Rubric wording needs the model: learn.propose reads the posts where you and the scores disagree.
- outcomes    for every change you applied: your verdicts on posts scored before it and after it, with the counts, and
              nothing called better or worse on fewer than MIN_JUDGED posts. learn.propose reads this record too.
"""
from __future__ import annotations
import json
import re
from . import config, db, scoring

MIN_EACH = 3      # Good and Nope verdicts each, on scored posts, before weights are suggested
MIN_JUDGED = 3    # posts judged since a change before its effect is read
CLEAR = 10        # points of agreement or share Good that count as a real change
STEP = 5          # weights move in steps of 5 points, each staying at 5 or more
MIN_SEEN = 10     # postings from a board before it can be called quiet


# ---------------------------------------------------------------- your verdicts
def judged(con) -> list[dict]:
    """Your verdicts on model-scored posts, with the scores as they were when you judged them."""
    out = []
    for r in con.execute("SELECT v.job_id, v.verdict, v.reason, v.at, v.score, v.score_json, j.title, j.company, j.source "
                         "FROM verdicts v JOIN jobs j ON j.id=v.job_id").fetchall():
        sc = json.loads(r["score_json"] or "{}")
        if not sc.get("dims") or r["score"] is None:
            continue
        out.append({**dict(r), "dims": sc["dims"], "scored_at": sc.get("scored_at") or r["at"], "guard": sc.get("guard")})
    return out


def agreement(good: list[float], nope: list[float]) -> int | None:
    if not good or not nope:
        return None
    w = sum(1 if g > n else .5 if g == n else 0 for g in good for n in nope)
    return round(100 * w / (len(good) * len(nope)))


def _total(row: dict, dims: list[dict]) -> float:
    """A judged post's total under other weights: its dimension scores stay, only the weighting changes (code, exact)."""
    t = scoring.total({d["key"]: d.get("score") for d in row["dims"]}, dims)
    return min(t, scoring.GUARD_CAP) if row.get("guard") else t


def agreement_of(rows: list[dict], dims: list[dict] | None = None) -> int | None:
    tot = (lambda r: _total(r, dims)) if dims else (lambda r: r["score"])
    return agreement([tot(r) for r in rows if r["verdict"] == "good"], [tot(r) for r in rows if r["verdict"] == "nope"])


def best_weights(rows: list[dict], dims: list[dict]) -> tuple[dict, int] | None:
    """Move STEP points between two dimensions while it ranks your Good above your Nope more often."""
    w = {d["key"]: d["weight"] for d in dims}
    as_dims = lambda w: [{**d, "weight": w[d["key"]]} for d in dims]
    best = agreement_of(rows, as_dims(w))
    if best is None:
        return None
    for _ in range(60):
        moves = [{**w, a: w[a] - STEP, b: w[b] + STEP} for a in w for b in w if a != b and w[a] - STEP >= STEP]
        top = max(moves, key=lambda m: agreement_of(rows, as_dims(m)), default=None)
        if not top or agreement_of(rows, as_dims(top)) <= best:
            break
        w, best = top, agreement_of(rows, as_dims(top))
    return w, best


def nope_only_words(rows: list[dict]) -> list[tuple[str, int]]:
    """Title words (and two-word phrases) in at least two Nope titles and no Good title, found by code."""
    def grams(t):
        w = re.findall(r"[a-z0-9]+", (t or "").lower())
        return {x for x in w if len(x) > 3} | {f"{a} {b}" for a, b in zip(w, w[1:])}
    good = set().union(*(grams(r["title"]) for r in rows if r["verdict"] == "good"))
    count: dict[str, int] = {}
    for r in rows:
        if r["verdict"] == "nope":
            for g in grams(r["title"]) - good:
                count[g] = count.get(g, 0) + 1
    return sorted(((g, c) for g, c in count.items() if c >= 2), key=lambda x: -x[1])[:10]


# ---------------------------------------------------------------- sources
def source_of(source: str, company: str | None) -> str:
    """A company's own board is the company; a board of many companies is the board."""
    return company or source if source in ("greenhouse", "lever", "ashby") else source


def source_yield(con) -> list[dict]:
    """Per source: postings seen, passed the prefilter, scored by the model, queued or applied, and your verdicts."""
    out: dict[str, dict] = {}
    for r in con.execute("SELECT j.source, j.company, j.status, j.score, j.score_reason, v.verdict FROM jobs j "
                         "LEFT JOIN verdicts v ON v.job_id=j.id").fetchall():
        y = out.setdefault(source_of(r["source"], r["company"]), {"source": source_of(r["source"], r["company"]), "seen": 0, "passed": 0,
                                                                  "scored": 0, "kept": 0, "good": 0, "nope": 0})
        y["seen"] += 1
        y["passed"] += not (r["score_reason"] or "").startswith("prefilter")
        y["scored"] += r["score"] is not None
        y["kept"] += r["status"] in ("queued", "applied_draft", "applied")
        if r["verdict"]:
            y[r["verdict"]] += 1
    return sorted(out.values(), key=lambda y: (-y["good"], -y["kept"], -y["seen"]))


def quiet_sources(yields: list[dict]) -> list[dict]:
    """Watched companies that cost reading and give nothing: no posting ever passed, or you only ever said Nope."""
    watched = {c["name"] for c in config.companies() if not c.get("paused")}
    return [y for y in yields if y["source"] in watched and y["good"] == 0
            and ((y["seen"] >= MIN_SEEN and y["passed"] == 0) or y["nope"] >= MIN_EACH)]


# ---------------------------------------------------------------- suggestions
def _known(con, kind: str, after: str) -> bool:
    """Already suggested and still waiting, or dismissed: never shown twice."""
    return con.execute("SELECT 1 FROM proposals WHERE kind=? AND after=? AND status IN ('pending', 'rejected')", (kind, after)).fetchone() is not None


def _propose(con, kind, target, before, after, reason, source) -> int:
    if _known(con, kind, after):
        return 0
    con.execute("INSERT INTO proposals(at, kind, target, before, after, reason, source) VALUES (?,?,?,?,?,?,?)",
                (db.now(), kind, target, before, after, reason, source))
    return 1


def suggest(con) -> int:
    """Code's own suggestions from your verdicts and the sources' yield. Returns how many are new."""
    from .learn import init
    init(con)
    rows, dims, n = judged(con), scoring.dimensions(), 0
    good, nope = sum(r["verdict"] == "good" for r in rows), sum(r["verdict"] == "nope" for r in rows)
    if good >= MIN_EACH and nope >= MIN_EACH:
        now = agreement_of(rows, dims)
        found = best_weights(rows, dims)
        if found and now is not None and found[1] - now >= CLEAR:
            w, then = found
            cur = {d["key"]: d["weight"] for d in dims}
            names = {d["key"]: d["name"] for d in dims}
            moved = ", ".join(f"{names[k]} {cur[k]} → {w[k]}" for k in w if w[k] != cur[k])
            n += _propose(con, "weights", "profile/preferences.yaml", json.dumps(cur), json.dumps(w),
                          f"Weights: {moved}. On your {good} Good and {nope} Nope posts, Good would rank above Nope {then}% of the "
                          f"time instead of {now}%. The posts keep their scores; only the totals change.",
                          f"{good} Good, {nope} Nope")
    words = [w for w, c in nope_only_words(rows)]
    if words:
        pats = [rf"\b{re.escape(w)}\b" for w in words[:3]]
        n += _propose(con, "drop_titles", "profile/preferences.yaml", "", json.dumps(pats),
                      f"Skip titles with {', '.join(repr(w) for w in words[:3])}: each is in two or more titles you marked Nope "
                      f"and in none you marked Good. They would be dropped before any scoring.",
                      "; ".join(f"{w} ({c} Nope)" for w, c in nope_only_words(rows)[:3]))
    for y in quiet_sources(source_yield(con))[:3]:
        why = (f"none of its {y['seen']} postings passed your prefilter" if y["passed"] == 0
               else f"you marked all {y['nope']} of its posts you judged Nope")
        n += _propose(con, "source_off", "profile/companies.yaml", "", y["source"],
                      f"Stop reading {y['source']}: {why}.", f"{y['seen']} seen, {y['passed']} passed, {y['good']} Good, {y['nope']} Nope")
    con.commit()
    return n


# ---------------------------------------------------------------- what your changes did
def outcomes(con) -> list[dict]:
    """Every change you applied, newest first, with what your verdicts say since."""
    from .learn import init
    init(con)
    rows = judged(con)
    out = []
    for p in con.execute("SELECT * FROM proposals WHERE status='applied' ORDER BY decided_at DESC LIMIT 30").fetchall():
        p = dict(p)
        if p["kind"] in ("brief_example", "ban_phrase", "storybook_line"):
            continue   # writing changes: read in your reviews, not in scores
        at = p["decided_at"] or ""
        if p["kind"] == "source_off":
            out.append({**p, "verdict": "na", "text": "Not read since, so there is nothing to measure."}); continue
        before = [r for r in rows if (r["scored_at"] or "") < at]
        after = [r for r in rows if (r["scored_at"] or "") >= at]
        by_order = p["kind"] == "weights" or "rubric" in (p["before"] or "")
        if by_order:
            name, b, a = "agreement", agreement_of(before), agreement_of(after)
        else:
            share = lambda rs: round(100 * sum(r["verdict"] == "good" for r in rs) / len(rs)) if rs else None
            name, b, a = "share marked Good", share(before), share(after)
        c = {"metric": name, "before": b, "after": a, "judged_before": len(before), "judged_after": len(after)}
        if b is None:
            v, t = "too_early", f"No posts judged before it to compare with; {len(after)} judged since."
        elif len(after) < MIN_JUDGED or a is None:
            v, t = "too_early", f"{len(after)} posts judged since; it needs {MIN_JUDGED} or more" + (", Good and Nope among them." if by_order else ".")
        else:
            d = a - b
            v = "helped" if d >= CLEAR else "hurt" if d <= -CLEAR else "no_change"
            t = f"{name.capitalize()} {b}% before, {a}% after, on {len(before)} and {len(after)} judged posts."
        out.append({**p, **c, "verdict": v, "text": t})
    return out


def summary(con) -> dict:
    """What the dashboard shows: agreement, the record, the sources."""
    rows = judged(con)
    yields = source_yield(con)
    quiet = {y["source"] for y in quiet_sources(yields)}
    return {"good": sum(r["verdict"] == "good" for r in rows), "nope": sum(r["verdict"] == "nope" for r in rows),
            "agreement": agreement_of(rows), "min_each": MIN_EACH, "outcomes": outcomes(con),
            "sources": [{**y, "quiet": y["source"] in quiet} for y in yields[:40]]}


# ---------------------------------------------------------------- applying
def set_weights(text: str, weights: dict) -> str:
    """preferences.yaml with new weights, written in place so its comments stay."""
    import yaml
    for k, w in weights.items():
        text, n = re.subn(rf"(- key: {re.escape(k)}\s*\n(?:[ \t]+\S.*\n)*?[ \t]+weight: )\d+", rf"\g<1>{int(w)}", text, count=1)
        if n != 1:
            raise ValueError(f"the weight of '{k}' was not found in preferences.yaml")
    yaml.safe_load(text)
    return text


def retotal(con) -> int:
    """After a weight change: every model-scored post still waiting gets its total again from the scores it has (no model)."""
    dims = scoring.dimensions()
    auto = config.preferences().get("automation", {})
    n = 0
    for j in con.execute("SELECT id, status, score_json FROM jobs WHERE status IN ('queued', 'skipped') AND score_json LIKE '%\"dims\"%' "
                         "AND id NOT IN (SELECT job_id FROM verdicts)").fetchall():
        sc = json.loads(j["score_json"])
        if j["status"] == "skipped" and sc.get("action") != "skip":
            continue   # skipped by you or by a rule, not by its score
        t = scoring.total({d["key"]: d.get("score") for d in sc["dims"]}, dims)
        t = min(t, scoring.GUARD_CAP) if sc.get("guard") else t
        action = ("skip" if sc.get("hard_blockers") or t < auto.get("min_score_to_queue", 50)
                  else "maybe" if sc.get("guard") or t < auto.get("min_score_to_apply", 70) else "apply")
        for d in sc["dims"]:
            d["weight"] = next((x["weight"] for x in dims if x["key"] == d["key"]), d.get("weight"))
        sc.update(score=t, action=action, weights_changed=db.now())
        con.execute("UPDATE jobs SET score=?, score_json=?, status=? WHERE id=?",
                    (t, json.dumps(sc, ensure_ascii=False), "skipped" if action == "skip" else "queued", j["id"]))
        n += 1
    con.commit()
    return n
