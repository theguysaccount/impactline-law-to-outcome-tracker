"""Spending records from USAspending.gov (U.S. Treasury). No key needed.

Two very different kinds of link between a law and money are kept apart everywhere:

1. TAGGED BY LAW (official). Treasury tags some funds with a Disaster Emergency Fund Code (DEFC)
   that names the public law which provided them: emergency, disaster and wildfire supplementals,
   the COVID-19 relief laws and the Infrastructure Investment and Jobs Act. For those laws
   USAspending reports budget authority, obligations and outlays under the law's own code.

2. NAMED IN AN AWARD (candidates). For other laws there is no official tag. The only automatic
   signal is that an award's description cites the law by number or by a distinctive name. These
   are keyword matches. They are never summed and never called the law's spending.
"""
import os
import re
from datetime import timedelta

from .common import ROOT, Checks, data_path, parse_iso, read_json, write_json

API = "https://api.usaspending.gov/api/v2"
GROUPS = {"grants": ["02", "03", "04", "05"], "contracts": ["A", "B", "C", "D"], "direct_payments": ["06", "10"],
          "loans": ["07", "08"], "other": ["09", "11"], "idvs": ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"]}
GROUP_LABEL = {"grants": "grants", "contracts": "contracts", "direct_payments": "direct payments", "loans": "loans",
               "other": "other assistance", "idvs": "contract vehicles"}
STOP = {"of", "the", "and", "for", "to", "a", "an", "in", "on", "act", "at", "by", "with", "or"}
GENERIC = re.compile(r"appropriations|authorization|extension|continuing|amendments?\b|reauthorization|technical corrections|"
                     r"improvements? act|reform act$|relief act$|modernization act$|protection act$|safety act$|"
                     r"enhancement act$|accountability act$|transparency act$", re.I)


def defc_path():
    return data_path("spending", "defc.json")


def load_codes():
    return (read_json(defc_path(), {}) or {}).get("codes", [])


def tagged_path(law_id):
    return data_path("spending", f"{law_id}.json")


def named_path(law_id):
    return data_path("awards", f"{law_id}.json")


# ------------------------------------------------------------------------------------------------
# 1. Funds tagged by law (DEF codes)
# ------------------------------------------------------------------------------------------------
def parse_codes(payload):
    """USAspending's DEF code list -> [{'code', 'title', 'parts': [{'designation', 'law'}]}] for codes that name laws."""
    out = []
    for c in payload.get("codes", []):
        parts = []
        for piece in (c.get("public_law") or "").split("|"):
            m = re.fullmatch(r"\s*(.*?)\s*P\.L\.\s*(\d+)-(\d+)\s*", piece)
            if m:
                parts.append({"designation": m.group(1).strip() or "Designated", "law": f"{int(m.group(2))}-{int(m.group(3))}"})
        if parts:
            out.append({"code": c["code"], "title": (c.get("title") or "").split("|")[0].strip(), "parts": parts,
                        "group": c.get("disaster") or ""})
    return out


def codes_for(codes, law_id):
    """(exclusive codes, shared codes) for a law. A shared code covers several laws at once, so its
    amounts cannot be credited to any one of them."""
    mine = [c for c in codes if any(p["law"] == law_id for p in c["parts"])]
    exclusive = [c for c in mine if len({p["law"] for p in c["parts"]}) == 1]
    return exclusive, [c for c in mine if c not in exclusive]


def fetch_tagged(http, law, exclusive, shared):
    names = [c["code"] for c in exclusive]
    rec = {"law": law["id"], "codes": [{"code": c["code"], "designation": c["parts"][0]["designation"]} for c in exclusive],
           "shared_codes": [{"code": c["code"], "laws": sorted({p["law"] for p in c["parts"]})} for c in shared],
           "source": f"{API}/disaster/overview/?def_codes={','.join(names)}"}
    if not names:
        return rec
    o = http.json(rec["source"], timeout=180)
    sp = o.get("spending") or {}
    rec["overview"] = {"budget_authority": o.get("total_budget_authority"), "total_obligations": sp.get("total_obligations"),
                       "total_outlays": sp.get("total_outlays"), "award_obligations": sp.get("award_obligations"),
                       "award_outlays": sp.get("award_outlays")}
    rec["funding_by_code"] = {f["def_code"]: f["amount"] for f in o.get("funding", [])}
    a = http.json(f"{API}/disaster/agency/spending/", {
        "filter": {"def_codes": names}, "spending_type": "total",
        "pagination": {"limit": 15, "page": 1, "sort": "obligation", "order": "desc"}}, timeout=180)
    rec["agencies"] = [{"name": r.get("description", ""), "obligations": r.get("obligation"), "outlays": r.get("outlay"),
                        "budgetary_resources": r.get("total_budgetary_resources")} for r in a.get("results", [])]
    c = http.json(f"{API}/search/spending_by_category/cfda/", {"filters": {"def_codes": names}, "limit": 15, "page": 1}, timeout=180)
    rec["programs"] = [{"listing": r.get("code", ""), "name": r.get("name", ""), "obligations": r.get("amount")}
                       for r in c.get("results", []) if r.get("code")]
    rec["awards"] = []
    for group in ("grants", "contracts"):
        w = http.json(f"{API}/search/spending_by_award/", {
            "filters": {"def_codes": names, "award_type_codes": GROUPS[group]},
            "fields": ["Award ID", "Recipient Name", "Award Amount", "Total Outlays", "Awarding Agency", "Description", "generated_internal_id"],
            "limit": 8, "page": 1, "sort": "Award Amount", "order": "desc"}, timeout=180)
        rec["awards"] += [_award(r, group) for r in w.get("results", [])]
    return rec


def _award(r, group):
    gid = r.get("generated_internal_id") or ""
    return {"id": r.get("Award ID") or "", "recipient": " ".join((r.get("Recipient Name") or "").split())[:120],
            "amount": r.get("Award Amount"), "outlays": r.get("Total Outlays"), "agency": r.get("Awarding Agency") or "",
            "description": " ".join((r.get("Description") or "").split())[:240], "kind": group,
            "url": f"https://www.usaspending.gov/award/{gid}" if gid else ""}


# ------------------------------------------------------------------------------------------------
# 2. Awards that name the law (keyword candidates)
# ------------------------------------------------------------------------------------------------
def search_phrases(law, all_laws):
    """The phrases searched in award descriptions: always the citation; the law's name only when it
    is distinctive enough not to pull in other laws' awards."""
    phrases = [{"phrase": f"Public Law {law['congress']}-{law['number']}", "match": "citation"}]
    name = law.get("also_called") or (law["title"] if law.get("title_source") != "official title" else "")
    if name:
        bare = re.sub(r"(?:,| of)\s+\d{4}$", "", name).strip()
        words = [w for w in re.findall(r"[A-Za-z0-9']+", bare) if w.lower() not in STOP]
        others = {re.sub(r"(?:,| of)\s+\d{4}$", "", (x.get("also_called") or x["title"])).strip().lower()
                  for x in all_laws if x["id"] != law["id"]}
        if len(words) >= 2 and len(bare) >= 18 and not GENERIC.search(bare) and bare.lower() not in others:
            phrases.append({"phrase": bare, "match": "name"})
    return phrases


def fetch_named(http, law, all_laws, now):
    period = [{"start_date": law["approved"], "end_date": now.strftime("%Y-%m-%d")}]
    out = []
    for p in search_phrases(law, all_laws):
        filters = {"keywords": [p["phrase"]], "time_period": period}
        counts = http.json(f"{API}/search/spending_by_award_count/", {"filters": filters}).get("results", {})
        counts = {k: int(counts.get(k) or 0) for k in GROUPS}
        item = dict(p, counts={k: v for k, v in counts.items() if v}, top=[],
                    search_url="https://www.usaspending.gov/search/?keyword=" + p["phrase"].replace(" ", "%20"))
        biggest = max(("grants", "contracts", "direct_payments", "loans", "other"), key=lambda g: counts[g])
        if counts[biggest]:
            w = http.json(f"{API}/search/spending_by_award/", {
                "filters": dict(filters, award_type_codes=GROUPS[biggest]),
                "fields": ["Award ID", "Recipient Name", "Award Amount", "Awarding Agency", "Description", "generated_internal_id"],
                "limit": 6, "page": 1, "sort": "Award Amount", "order": "desc"})
            item["top"] = [_award(r, biggest) for r in w.get("results", [])]
        out.append(item)
    return {"law": law["id"], "phrases": out, "total": sum(sum(p["counts"].values()) for p in out),
            "period_start": law["approved"]}


# ------------------------------------------------------------------------------------------------
# Refresh
# ------------------------------------------------------------------------------------------------
def refresh_tagged(http, cfg, laws, now, only=None, checks=None, force=False):
    """Official by-law totals. Weekly per law; the code list itself is re-read every run."""
    checks = checks or Checks()
    payload = http.json(f"{API}/references/def_codes/")
    codes = parse_codes(payload)
    if len(codes) < 5:
        raise RuntimeError("USAspending returned an implausibly short DEF code list")
    write_json(defc_path(), {"codes": codes, "source": f"{API}/references/def_codes/"})
    by_id = {law["id"]: law for law in laws}
    done, changed, errors = 0, 0, []
    tagged_ids = sorted({p["law"] for c in codes for p in c["parts"]} & set(by_id))
    for lid in tagged_ids:
        if only and lid not in only:
            continue
        last = checks.get("tagged", lid)
        if not force and last and now - last < timedelta(days=6, hours=20) and os.path.exists(tagged_path(lid)):
            continue
        exclusive, shared = codes_for(codes, lid)
        try:
            rec = fetch_tagged(http, by_id[lid], exclusive, shared)
        except Exception as e:
            errors.append(f"{lid}: {type(e).__name__}: {e}"[:160])
            continue
        changed += 1 if write_json(tagged_path(lid), rec) else 0
        checks.set("tagged", lid, now)
        done += 1
    # A law that lost its tag upstream keeps no stale file.
    for fn in os.listdir(data_path("spending")):
        if fn.endswith(".json") and fn != "defc.json" and fn[:-5] not in tagged_ids:
            os.remove(data_path("spending", fn))
    checks.save()
    return {"note": f"{len(tagged_ids)} laws carry a spending code; {done} re-read, {changed} changed", "changed": bool(changed),
            "errors": errors[:10], "ok": not errors or done > 0, "checked": done}


# ------------------------------------------------------------------------------------------------
# 3. Program traces: a law's fund code joined to a program's Assistance Listing number
# ------------------------------------------------------------------------------------------------
PROGRAMS = os.path.join(ROOT, "config", "programs.json")
AWARD_FIELDS = ["Award ID", "Recipient Name", "Award Amount", "Total Outlays", "Awarding Agency", "Description", "generated_internal_id"]


def program_path(slug):
    return data_path("programs", f"{slug}.json")


def load_programs():
    return (read_json(PROGRAMS, {}) or {}).get("programs", [])


def _scope(http, filters):
    counts = http.json(f"{API}/search/spending_by_award_count/", {"filters": filters}, timeout=180).get("results", {})
    counts = {k: int(counts.get(k) or 0) for k in GROUPS if counts.get(k)}
    awards = []
    for group in sorted(counts, key=counts.get, reverse=True)[:2]:
        if group == "idvs":
            continue
        w = http.json(f"{API}/search/spending_by_award/", {
            "filters": dict(filters, award_type_codes=GROUPS[group]), "fields": AWARD_FIELDS,
            "limit": 8, "page": 1, "sort": "Award Amount", "order": "desc"}, timeout=180)
        awards += [_award(r, group) for r in w.get("results", [])]
    awards.sort(key=lambda a: a["amount"] or 0, reverse=True)
    return {"counts": counts, "awards": awards[:10]}


def fetch_program(http, prog, codes):
    exclusive, _ = codes_for(codes, prog["law"])
    names = [c["code"] for c in exclusive]
    if not names:
        raise RuntimeError(f"law {prog['law']} carries no fund code")
    base = {"def_codes": names, "program_numbers": [prog["listing"]]}
    total = http.json(f"{API}/search/spending_by_category/cfda/", {"filters": base, "limit": 5, "page": 1}, timeout=180)
    row = next((r for r in total.get("results", []) if r.get("code") == prog["listing"]), None)
    rec = {"slug": prog["slug"], "law": prog["law"], "listing": prog["listing"], "codes": names,
           "listing_name": (row or {}).get("name", ""), "obligations": (row or {}).get("amount"),
           "national": _scope(http, base)}
    if prog.get("pilot_state"):
        rec["state"] = dict(_scope(http, dict(base, place_of_performance_locations=[{"country": "USA", "state": prog["pilot_state"]}])),
                            code=prog["pilot_state"])
    return rec


def refresh_programs(http, now, checks=None, force=False):
    checks = checks or Checks()
    codes = load_codes()
    done, changed, errors = 0, 0, []
    for prog in load_programs():
        last = checks.get("programs", prog["slug"])
        if not force and last and now - last < timedelta(days=6, hours=20) and os.path.exists(program_path(prog["slug"])):
            continue
        try:
            rec = fetch_program(http, prog, codes)
        except Exception as e:
            errors.append(f"{prog['slug']}: {type(e).__name__}: {e}"[:160])
            continue
        changed += 1 if write_json(program_path(prog["slug"]), rec) else 0
        checks.set("programs", prog["slug"], now)
        done += 1
    checks.save()
    return {"note": f"{done} program traces re-read, {changed} changed", "changed": bool(changed), "errors": errors,
            "ok": not errors, "checked": done}


def named_interval(rec):
    return timedelta(days=6, hours=20) if (rec or {}).get("total") else timedelta(days=27, hours=20)


def refresh_named(http, cfg, laws, now, budget=None, only=None, checks=None):
    budget = cfg["budget"]["awards_per_run"] if budget is None else budget
    checks = checks or Checks()
    codes = load_codes()
    queue = []
    for law in laws:
        if only and law["id"] not in only:
            continue
        if codes_for(codes, law["id"])[0]:
            continue  # officially tagged laws do not need keyword candidates
        last = checks.get("named", law["id"])
        if last is None or now - last >= named_interval(read_json(named_path(law["id"]))):
            queue.append((last or parse_iso("2000-01-01T00:00:00Z"), law))
    queue.sort(key=lambda x: (x[0], x[1]["id"]))
    done, changed, errors = 0, 0, []
    for _, law in queue[:budget]:
        try:
            rec = fetch_named(http, law, laws, now)
        except Exception as e:
            errors.append(f"{law['id']}: {type(e).__name__}: {e}"[:160])
            if len(errors) >= 10 and done == 0:
                raise RuntimeError("USAspending search is not answering: " + errors[0])
            continue
        changed += 1 if write_json(named_path(law["id"]), rec) else 0
        checks.set("named", law["id"], now)
        done += 1
    checks.save()
    return {"note": f"{done} laws searched, {changed} changed, {max(0, len(queue) - done)} still due", "changed": bool(changed),
            "errors": errors[:10], "ok": done > 0 or not queue, "checked": done, "waiting": max(0, len(queue) - done)}
