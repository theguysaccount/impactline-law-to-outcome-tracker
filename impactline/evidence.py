"""Evidence packets: one JSON file per law holding everything a law's page shows, with its sources.

Each packet is written as canonical JSON (sorted keys, no extra whitespace, UTF-8), so the same data
always produces the same bytes and the same SHA-256. A manifest lists every packet's digest. The
nightly workflow asks GitHub to attest the manifest (a Sigstore signature bound to this repository's
workflow), so anyone can check that a packet came from this build and has not been altered.

A packet records what public sources said on the dates shown. It is not proof that the sources are
right, not a legal finding, and not a complete account of a law's implementation.
"""
import hashlib
import json
import os

from . import fedreg, spending
from .common import human_date, money

STAGE_DEFS = [
    ("law", "Enacted law", "Congress and the President"),
    ("authority", "Authority and funding", "Congress and the administering agency"),
    ("agency", "Agency implementation", "The responsible federal agency"),
    ("state", "State and local delivery", "State and local administering bodies"),
    ("award", "Grant or contract", "The awarding agency and the recipient"),
    ("payment", "Payments and progress", "The recipient and its contractors"),
    ("outcome", "Delivered outcome", "The project owner or an independent reviewer"),
]
LIMITS = [
    "A Federal Register document is listed because it cites this law by number. Citing a law is not the same as implementing it, and a law can be implemented by documents that never cite its number.",
    "Spending is shown as this law's only where the U.S. Treasury tagged the funds with the law's own fund code. Other spending under the law is not tagged by law and cannot be shown here.",
    "An award listed because its description names this law is a keyword match. Keyword matches are never added up.",
    "Nothing here says whether the law worked, whether money was well spent, or whether anyone did anything wrong.",
    "No state or local records, inspection records or outcome data are read.",
]


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stages(law, fr, tagged, named):
    """The seven steps from enactment to outcome, each marked by what the public record supports."""
    out = []

    def add(key, status, summary):
        title, owner = next((t, o) for k, t, o in STAGE_DEFS if k == key)
        out.append({"id": key, "title": title, "owner": owner, "status": status, "summary": summary})

    add("law", "documented", f"Approved {human_date(law['approved'])}. Text published by the Government Publishing Office.")
    ov = (tagged or {}).get("overview") or {}
    codes = ", ".join(c["code"] for c in (tagged or {}).get("codes", []))
    if ov.get("budget_authority"):
        add("authority", "documented", f"Treasury tags {money(ov['budget_authority'])} in budget authority to this law (fund code {codes}).")
    else:
        add("authority", "needs-evidence", "No fund code ties appropriations to this law. An authorization is not an appropriation.")
    total = (fr or {}).get("total", 0)
    if total:
        bt = fr.get("by_type", {})
        parts = [f"{bt[k]:,} {label}" for k, label in (("Rule", "final rules"), ("Proposed Rule", "proposed rules"), ("Notice", "notices"),
                                                         ("Presidential Document", "presidential documents")) if bt.get(k)]
        add("agency", "candidates", f"{total:,} Federal Register documents cite this law by number: {', '.join(parts)}.")
    else:
        add("agency", "needs-evidence", "No Federal Register document cites this law by number. Not every law needs a rule.")
    add("state", "needs-evidence", "Not covered. ImpactLine reads no state or local records.")
    n_named = (named or {}).get("total", 0)
    if ov.get("award_obligations"):
        add("award", "documented", f"{money(ov['award_obligations'])} obligated to grants, contracts and other awards under the law's fund code.")
    elif n_named:
        floor = "At least " if (named or {}).get("partial") else ""
        add("award", "candidates", f"{floor}{n_named:,} award descriptions name this law. Keyword matches only: not a list of the law's awards.")
    else:
        add("award", "needs-evidence", "No award is tagged to this law, and no award description names it.")
    if ov.get("total_outlays"):
        add("payment", "documented", f"{money(ov['total_outlays'])} in outlays reported under the law's fund code.")
    else:
        add("payment", "needs-evidence", "No payment data can be tied to this law.")
    add("outcome", "needs-evidence", "No reconciled outcome record. ImpactLine does not judge whether a law delivered.")
    return out


def packet(law, fr, tagged, named, checks, repo_url):
    lid = law["id"]
    p = {
        "packet": "impactline-evidence/1",
        "law": {
            "public_law": lid, "congress": law["congress"], "title": law["title"], "title_source": law["title_source"],
            "official_title": law["official_title"], "also_called": law.get("also_called", ""), "approved": law["approved"],
            "statutes_at_large": law.get("stat", ""), "bill": law.get("bill"), "sections": law.get("sections", 0),
            "source": {"name": "GovInfo bulk data, U.S. Government Publishing Office", "url": law["links"]["xml"],
                       "sha256": law["xml_sha256"], "bytes": law["xml_bytes"]},
            "links": law["links"]},
        "federal_register": None, "spending_tagged_by_law": None, "awards_naming_the_law": None,
        "stages": stages(law, fr, tagged, named), "limits": LIMITS,
        "generator": {"name": "ImpactLine static edition", "repository": repo_url}}
    if fr:
        p["federal_register"] = {
            "label": "candidate-match", "checked_at": checks.text("fr", lid), "source": "Federal Register API", "query": fr["term"],
            "search_url": fr["search_url"], "total": fr["total"], "by_type": fr["by_type"], "by_year": fr["by_year"],
            "agencies": fr["agencies"], "latest_documents": fr["latest"], "latest_rules": fr["rules"]}
    if tagged and tagged.get("overview"):
        p["spending_tagged_by_law"] = {
            "label": "official-record", "checked_at": checks.text("tagged", lid), "source": tagged["source"],
            "codes": tagged["codes"], "shared_codes": tagged.get("shared_codes", []), "overview": tagged["overview"],
            "funding_by_code": tagged.get("funding_by_code", {}), "agencies": tagged.get("agencies", []),
            "programs": tagged.get("programs", []), "largest_awards": tagged.get("awards", [])}
    if named:
        p["awards_naming_the_law"] = {
            "label": "candidate-match", "checked_at": checks.text("named", lid), "source": "USAspending.gov award search",
            "searched_from": named.get("period_start", ""), "phrases": named["phrases"]}
    return p


def write_all(site_dir, laws, checks, repo_url, generated_at):
    """Write evidence/<id>.json for every law and evidence/manifest.json. Returns the manifest."""
    out_dir = os.path.join(site_dir, "evidence")
    os.makedirs(out_dir, exist_ok=True)
    listed = {}
    for law in laws:
        lid = law["id"]
        data = canonical(packet(law, fedreg.load(lid), _read(spending.tagged_path(lid)), _read(spending.named_path(lid)), checks, repo_url))
        with open(os.path.join(out_dir, f"{lid}.json"), "wb") as f:
            f.write(data)
        listed[lid] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    manifest = {"manifest": "impactline-evidence-manifest/1", "generated_at": generated_at, "repository": repo_url,
                "commit": os.environ.get("GITHUB_SHA", ""), "run": os.environ.get("GITHUB_RUN_ID", ""),
                "count": len(listed), "packets": listed}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, sort_keys=True, indent=0)
        f.write("\n")
    return manifest


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
