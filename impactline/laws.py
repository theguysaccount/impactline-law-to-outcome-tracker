"""Public laws from GovInfo's bulk data (Government Publishing Office). No key needed.

For each Congress in the window, GovInfo publishes one ZIP of every public law as USLM XML, plus a
JSON listing that says when the ZIP last changed. This module reads the listing, downloads a ZIP only
when it changed, and takes each law's identity straight from the law's own file: number, approval
date, Statutes at Large citation, bill, official title and short title.

A Congress that cannot be read keeps its last good laws. Nothing is guessed or filled in.
"""
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import timedelta
from xml.etree import ElementTree as ET

from .common import ROOT, data_path, iso, now_utc, read_json, write_json



def laws_path():
    return data_path("laws.json")


def titles_path():
    """Popular titles from the original ImpactLine's Congress.gov import."""
    return data_path("congress-titles.json")


LISTING = "https://www.govinfo.gov/bulkdata/json/PLAW/{c}/public"
NS = "{http://schemas.gpo.gov/xml/uslm}"
DC = "{http://purl.org/dc/elements/1.1/}"
BILL_PATH = {"hr": "house-bill", "s": "senate-bill", "hjres": "house-joint-resolution", "sjres": "senate-joint-resolution"}
BILL_LABEL = {"hr": "H.R.", "s": "S.", "hjres": "H.J. Res.", "sjres": "S.J. Res."}
_WS = re.compile(r"\s+")
ALIASES = read_json(os.path.join(ROOT, "config", "aliases.json"), {}) or {}


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def congress_of(d):
    """The Congress sitting on a date (a new one starts on January 3 of odd years)."""
    year = d.year - (1 if (d.month, d.day) < (1, 3) else 0)
    return (year - 1789) // 2 + 1


def window(today, years):
    """Congress numbers whose laws fall in the rolling window: from the Congress sitting `years` ago to now."""
    start = today.replace(year=today.year - years) if (today.month, today.day) != (2, 29) else today - timedelta(days=365 * years)
    return list(range(congress_of(start), congress_of(today) + 1))


def _text(el, skip=()):
    """Element text without the given child tags (margin notes sit inside titles)."""
    if el is None:
        return ""
    parts = [el.text or ""]
    for child in el:
        if child.tag not in skip:
            parts.append(_text(child, skip))
        parts.append(child.tail or "")
    return "".join(parts)


def _clean(s):
    return _WS.sub(" ", (s or "").replace("­", "")).strip()


def kind_of(official_title, title):
    """A plain sorting label taken from the title's own wording."""
    low = official_title.lower()
    if "congressional disapproval under chapter 8 of title 5" in low:
        return "disapproval"
    named = (title or official_title).lower()   # a short title, when the law has one, says what the law is
    if re.search(r"\bmaking\b[^.]{0,60}\bappropriations\b|\bappropriations act\b|\bcontinuing appropriations\b|\bcontinuing resolution\b", named):
        return "appropriations"
    if re.search(r"^to (?:designate|name|rename|redesignate)\b", low) and re.search(
            r"postal service|post office|building|courthouse|clinic|medical center|facility|federal building|visitor center|"
            r"memorial|trail|wilderness|bridge|highway|airport|locks?\b|dam\b|forest|refuge|cemetery|laboratory|house\b|center\b", low):
        return "naming"
    return "general"


_MONTHS = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _in_term(date, congress):
    """Is this YYYY-MM-DD date inside (or just after) the two-year term of the Congress?"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        return False
    start = 1789 + 2 * (congress - 1)
    return f"{start}-01-03" <= date <= f"{start + 2}-01-31"


def _running_head_date(xml_bytes):
    """'PUBLIC LAW 118–53—MAY 7, 2024' in the printed running head -> '2024-05-07'."""
    m = re.search(rb"PUBLIC LAW \d+\S\d+\S+?([A-Z]{3})[A-Z]*\.? (\d{1,2}), (\d{4})", xml_bytes[:6000])
    if not m or m.group(1).decode() not in _MONTHS:
        return ""
    return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1).decode()]:02d}-{int(m.group(2)):02d}"


def parse_law(xml_bytes, popular=None):
    """One law's identity from its USLM file. Raises ValueError when the essentials are missing."""
    root = ET.fromstring(xml_bytes)
    meta = root.find(f"{NS}meta")
    if meta is None:
        raise ValueError("no <meta>")
    congress = int(_clean(meta.findtext(f"{NS}congress")))
    number = int(_clean(meta.findtext(f"{NS}docNumber")))
    approved, approved_from = _clean(meta.findtext(f"{NS}approvedDate")), "metadata"
    if not _in_term(approved, congress):
        # A few files carry a placeholder date in their metadata; the printed running head has the real one.
        approved, approved_from = _running_head_date(xml_bytes), "running head"
        if not _in_term(approved, congress):
            raise ValueError("no usable approval date")
    cites = [_clean(c.text) for c in meta.findall(f"{NS}citableAs")]
    stat = next((c for c in cites if re.match(r"\d+ Stat\. \d+", c)), "")
    official = _clean(_text(root.find(f".//{NS}longTitle/{NS}officialTitle"), skip=(f"{NS}sidenote",)))
    if not official:
        dc_title = _clean(meta.findtext(f"{DC}title"))
        official = dc_title.split(":", 1)[1].strip() if ":" in dc_title else dc_title
    doc_type = _clean(root.findtext(f".//{NS}longTitle/{NS}docTitle")) or "An Act"
    bill = None
    for ref in root.iter(f"{NS}ref"):
        m = re.fullmatch(r"/us/bill/(\d+)/([a-z]+)/(\d+)", ref.get("href", ""))
        if m and m.group(2) in BILL_PATH:
            t, n = m.group(2), m.group(3)
            bill = {"type": t, "number": n, "label": f"{BILL_LABEL[t]} {n}",
                    "url": f"https://www.congress.gov/bill/{ordinal(int(m.group(1)))}-congress/{BILL_PATH[t]}/{n}"}
            break
    short, parts = "", []
    for st in root.iter(f"{NS}shortTitle"):
        name = _clean(_text(st))
        if not name:
            continue
        if st.get("role") == "act" and not short:
            short = name
        elif name not in parts and name != short:
            parts.append(name)
    lid = f"{congress}-{number}"
    alias = (ALIASES.get(lid) or {}).get("name", "")
    if short:
        title, source = short, "law text"
    elif popular and popular.get(lid):
        title, source = popular[lid], "Congress.gov"
    else:
        title, source = official, "official title"
    pkg = f"PLAW-{congress}publ{number}"
    return {
        "id": lid, "congress": congress, "number": number, "approved": approved, "approved_from": approved_from,
        "title": title, "title_source": source,
        "official_title": official, "short_title": short, "also_called": alias, "doc_type": doc_type, "stat": stat, "bill": bill,
        "parts": parts[:80], "sections": sum(1 for s in root.iter(f"{NS}section") if s.get("identifier", "").startswith("/us/pl/")),
        "kind": kind_of(official, title if source != "official title" else ""), "xml_bytes": len(xml_bytes), "xml_sha256": hashlib.sha256(xml_bytes).hexdigest(),
        "links": {"details": f"https://www.govinfo.gov/app/details/{pkg}",
                  "pdf": f"https://www.govinfo.gov/content/pkg/{pkg}/pdf/{pkg}.pdf",
                  "text": f"https://www.govinfo.gov/content/pkg/{pkg}/html/{pkg}.htm",
                  "xml": f"https://www.govinfo.gov/bulkdata/PLAW/{congress}/public/{pkg}.xml"}}


def parse_zip(blob, popular=None):
    laws, errors = [], []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if not re.search(r"PLAW-\d+publ\d+\.xml$", name):
                continue
            try:
                laws.append(parse_law(z.read(name), popular))
            except Exception as e:  # one malformed file must not lose a Congress
                errors.append(f"{os.path.basename(name)}: {type(e).__name__}: {e}"[:160])
    return laws, errors


def refresh(http, cfg, now=None, force=False):
    """Update data/laws.json. Returns {'note', 'changed', 'errors'}; raises only if nothing could be read at all."""
    now = now or now_utc()
    store = read_json(laws_path(), {"laws": [], "sources": {}}) or {"laws": [], "sources": {}}
    popular = read_json(titles_path(), {}) or {}
    by_congress = {}
    for law in store["laws"]:
        by_congress.setdefault(law["congress"], []).append(law)
    wanted = window(now.date(), cfg["window_years"])
    sources, errors, changed, read_ok = dict(store.get("sources", {})), [], False, 0
    for c in wanted:
        key = str(c)
        try:
            listing = http.json(LISTING.format(c=c))
            entry = next((f for f in listing.get("files", []) if f.get("name", "").endswith("-public.zip")), None)
            if not entry:
                if not listing.get("files"):
                    read_ok += 1  # a new Congress with no public laws published yet
                    continue
                raise ValueError("listing has no ZIP")
            read_ok += 1
            prev = sources.get(key, {})
            stamp = f'{entry.get("formattedLastModifiedTime")}|{entry.get("size")}'
            if not force and prev.get("stamp") == stamp and by_congress.get(c):
                prev["checked_at"] = iso(now)
                continue
            blob = http.request(entry["link"], accept="application/zip", timeout=300)
            laws, errs = parse_zip(blob, popular)
            errors += errs
            old = by_congress.get(c, [])
            if old and len(laws) < len(old) * (1 - cfg["max_law_drop_share"]):
                errors.append(f"Congress {c}: new file has {len(laws)} laws, last good had {len(old)}; kept the last good set")
                continue
            by_congress[c] = laws
            changed = True
            sources[key] = {"listing": LISTING.format(c=c), "zip": entry["link"], "stamp": stamp,
                            "modified": entry.get("formattedLastModifiedTime"), "bytes": len(blob),
                            "sha256": hashlib.sha256(blob).hexdigest(), "laws": len(laws),
                            "retrieved_at": iso(now), "checked_at": iso(now)}
        except Exception as e:
            errors.append(f"Congress {c}: {type(e).__name__}: {e}"[:200])
    if not read_ok and not store["laws"]:
        raise RuntimeError("; ".join(errors) or "no Congress could be read")
    laws = [law for c in sorted(by_congress) if c in wanted for law in by_congress[c]]
    laws.sort(key=lambda x: (x["approved"], x["congress"], x["number"]), reverse=True)
    out = {"laws": laws, "sources": {k: v for k, v in sources.items() if int(k) in wanted},
           "window": {"congresses": wanted, "years": cfg["window_years"]}}
    if changed or not os.path.exists(laws_path()) or set(out["sources"]) != set(store.get("sources", {})):
        out["updated_at"] = iso(now)
    else:
        out["updated_at"] = store.get("updated_at", iso(now))
    write_json(laws_path(), out)
    return {"note": f"{len(laws)} laws from Congresses {wanted[0]}-{wanted[-1]}" + ("" if changed else " (unchanged)"),
            "changed": changed, "errors": errors, "ok": read_ok == len(wanted)}


def load():
    return (read_json(laws_path(), {"laws": []}) or {"laws": []})["laws"]


if __name__ == "__main__":
    from .common import Http, load_config
    print(json.dumps(refresh(Http(), load_config()), indent=1))
