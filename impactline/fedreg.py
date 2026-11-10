"""Federal Register documents that cite a law by its public-law number. No key needed.

One search per law against the Federal Register API for the three ways documents write a citation:
"Public Law 117-58", "Pub. L. 117-58" and "P.L. 117-58". A match means the document cites the law.
It does not mean the document implements the law, and a law can be implemented by documents that
never cite its number. These are labelled candidates.
"""
import os
from collections import Counter
from datetime import timedelta
from urllib.parse import urlencode

from .common import Checks, data_path, parse_iso, read_json, write_json

API = "https://www.federalregister.gov/api/v1/documents"
FIELDS = ["document_number", "title", "type", "publication_date", "html_url", "agencies"]
TYPES = ["Rule", "Proposed Rule", "Notice", "Presidential Document"]
FACET_TYPE = {"RULE": "Rule", "PRORULE": "Proposed Rule", "NOTICE": "Notice", "PRESDOCU": "Presidential Document"}
MAX_DOCS = 2000          # documents read per law; larger sets take their totals from the API's own counts


def term(law):
    c, n = law["congress"], law["number"]
    return f'"Public Law {c}-{n}" | "Pub. L. {c}-{n}" | "P.L. {c}-{n}"'


def search_url(law):
    return "https://www.federalregister.gov/documents/search?" + urlencode({"conditions[term]": term(law), "order": "newest"})


def path(law_id):
    return data_path("fr", f"{law_id}.json")


def _doc(r):
    agencies = [a.get("name") or a.get("raw_name") or "" for a in (r.get("agencies") or [])]
    return {"n": r.get("document_number", ""), "t": " ".join((r.get("title") or "").split())[:300], "k": r.get("type", ""),
            "d": r.get("publication_date", ""), "u": r.get("html_url", ""), "a": [a for a in agencies if a][:3]}


def fetch(http, law, now):
    """Read the citing documents for one law and return its record."""
    q = [("conditions[term]", term(law)), ("per_page", "1000"), ("order", "newest")] + [("fields[]", f) for f in FIELDS]
    url = f"{API}.json?{urlencode(q)}"
    docs, total, pages = [], 0, 0
    while url and len(docs) < MAX_DOCS and pages < 3:
        d = http.json(url)
        total = d.get("count", 0)
        docs += [_doc(r) for r in d.get("results", [])]
        url = d.get("next_page_url")
        pages += 1
    by_type = Counter(x["k"] for x in docs)
    by_year = Counter(x["d"][:4] for x in docs if x["d"])
    agencies = Counter(a for x in docs for a in x["a"])
    complete = len(docs) >= total
    if not complete:
        # More documents than we read: take the totals from the API's own facet counts.
        cond = urlencode({"conditions[term]": term(law)})
        ft = http.json(f"{API}/facets/type?{cond}")
        by_type = Counter({FACET_TYPE.get(k, v.get("name", k)): v.get("count", 0) for k, v in ft.items()})
        fy = http.json(f"{API}/facets/yearly?{cond}")
        by_year = Counter({str(v.get("name", k))[:4]: v.get("count", 0) for k, v in fy.items()})
        fa = http.json(f"{API}/facets/agency?{cond}")
        agencies = Counter({v.get("name", k): v.get("count", 0) for k, v in fa.items()})
    rules = [x for x in docs if x["k"] in ("Rule", "Proposed Rule")]
    return {"law": law["id"], "term": term(law), "search_url": search_url(law), "total": total,
            "by_type": {t: by_type.get(t, 0) for t in TYPES if by_type.get(t)}, "by_year": dict(sorted(by_year.items())),
            "agencies": [[a, n] for a, n in agencies.most_common(12)], "latest": docs[:15], "rules": rules[:15],
            "first": min((x["d"] for x in docs if x["d"]), default="") if complete else "",
            "last": max((x["d"] for x in docs if x["d"]), default=""), "complete": complete}


def interval(law, rec, now):
    """How long a law's record may rest: a day for young or busy laws, up to two weeks for silent ones."""
    young = (now.date() - parse_iso(law["approved"] + "T00:00:00Z").date()).days <= 540
    total = (rec or {}).get("total", 0)
    if young or total >= 25:
        return timedelta(hours=20)
    return timedelta(days=6, hours=20) if total else timedelta(days=13, hours=20)


def due(laws, now, checks):
    out = []
    for law in laws:
        last = checks.get("fr", law["id"])
        if last is None or now - last >= interval(law, read_json(path(law["id"])), now):
            out.append((last or parse_iso("2000-01-01T00:00:00Z"), law))
    out.sort(key=lambda x: (x[0], x[1]["id"]))
    return [law for _, law in out]


def refresh(http, cfg, laws, now, budget=None, only=None, checks=None):
    budget = cfg["budget"]["fedreg_per_run"] if budget is None else budget
    checks = checks or Checks()
    todo = [law for law in due(laws, now, checks) if not only or law["id"] in only][:budget]
    done, errors, changed = 0, [], 0
    for law in todo:
        try:
            rec = fetch(http, law, now)
        except Exception as e:  # keep the last good record for this law; try again next run
            errors.append(f"{law['id']}: {type(e).__name__}: {e}"[:160])
            if len(errors) >= 12 and done == 0:
                raise RuntimeError("Federal Register API is not answering: " + errors[0])
            continue
        changed += 1 if write_json(path(law["id"]), rec) else 0
        checks.set("fr", law["id"], now)
        done += 1
    checks.save()
    waiting = len(due(laws, now, checks))
    return {"note": f"{done} laws checked, {changed} changed, {waiting} still due", "changed": bool(changed),
            "errors": errors[:10], "ok": done > 0 or not todo, "checked": done, "waiting": waiting}


def load(law_id):
    return read_json(path(law_id))
