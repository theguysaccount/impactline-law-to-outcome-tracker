"""Build the static site from data/.

  python3 -m impactline.build [--site _site]

Environment (all optional):
  SITE_URL          public base URL: the one setting to change at cutover
  SITE_INDEXABLE    "true" to allow indexing (the staged copy is noindex by default)
  GOATCOUNTER_URL   privacy-friendly page counts
  ALERTS_URL        link for the one marked "alerts and API" slot
"""
import argparse
import csv
import io
import json
import os
import shutil
import sys
from html import escape as E
from urllib.parse import urlsplit

from . import evidence, fedreg, spending
from .common import (ROOT, Checks, data_path, human_date, indexable, iso, load_config, money, now_utc, parse_iso, read_json,
                     site_url)
from .laws import load as load_laws, ordinal

KIND_LABEL = {"general": "General", "naming": "Names a facility or place", "appropriations": "Appropriations",
              "disapproval": "Disapproves an agency rule"}
STATUS_LABEL = {"documented": "Official record", "candidates": "Candidates", "needs-evidence": "Needs evidence"}
STAGE_LABEL = {"authority": "Authority", "agency": "Agency", "state": "State", "award": "Award", "payment": "Payment", "outcome": "Outcome"}
STATE_NAME = {"CA": "California", "TX": "Texas"}


def short_date(s):
    d = parse_iso(s if "T" in s else s + "T00:00:00Z")
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def when(ts):
    """'<time>November 10, 2026</time>' for a check timestamp, or 'not yet checked'."""
    if not ts:
        return "not yet checked"
    return f'<time datetime="{E(ts)}">{human_date(parse_iso(ts))}</time>'


def clip(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


class Site:
    def __init__(self, out, now=None):
        self.cfg = load_config()
        self.url = site_url(self.cfg)
        self.base = urlsplit(self.url).path.rstrip("/")
        self.out = out
        self.now = now or now_utc()
        self.indexable = indexable(self.cfg)
        self.name = self.cfg["name"]
        self.repo_url = f"https://github.com/{self.cfg['repo']}"
        self.urls, self.og_jobs = [], []

    def href(self, path):
        return self.base + path

    def write(self, rel, text):
        path = os.path.join(self.out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def page(self, path, title, description, body, *, crumbs=None, jsonld=None, nav="", listed=True, og=None, lastmod=None, feed=None):
        canonical = self.url + path
        full = title if self.name in title else f"{title} | {self.name}"
        robots = "" if (self.indexable and listed) else '<meta name="robots" content="noindex, nofollow">\n'
        ld = ""
        for block in jsonld or []:
            safe = json.dumps(block, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            ld += f'<script type="application/ld+json">{safe}</script>\n'
        gc = os.environ.get("GOATCOUNTER_URL", "").strip()
        analytics = f'<script data-goatcounter="{E(gc)}" async src="https://gc.zgo.at/count.js"></script>\n' if gc else ""
        og_file = "default.png"
        if og:
            og_file = og[0] + ".png"
            self.og_jobs.append(og)
        crumb_html = ""
        if crumbs:
            crumb_html = '<p class="crumbs">' + " › ".join(f'<a href="{self.href(p)}">{E(t)}</a>' for t, p in crumbs) + "</p>"
        feed_link = f'<link rel="alternate" type="application/atom+xml" title="{E(feed[1])}" href="{self.href(feed[0])}">\n' if feed else ""

        def nav_link(key, label, p):
            cur = ' aria-current="page"' if nav == key else ""
            return f'<a href="{self.href(p)}"{cur}>{label}</a>'

        html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(full)}</title>
<meta name="description" content="{E(description)}">
{robots}<link rel="canonical" href="{E(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{E(self.name)}">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(description)}">
<meta property="og:url" content="{E(canonical)}">
<meta property="og:image" content="{E(self.url)}/og/{og_file}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{self.href('/static/favicon-96x96.png')}">
<link rel="alternate" type="application/atom+xml" title="{E(self.name)}: new public laws" href="{self.href('/feed.xml')}">
{feed_link}<link rel="preload" href="{self.href('/static/fonts/inter-latin.woff2')}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{self.href('/static/style.css')}">
{ld}{analytics}</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="masthead"><div class="wrap">
<a class="brand" href="{self.href('/')}"><img src="{self.href('/static/favicon-96x96.png')}" alt="" width="30" height="30"><span>impactline</span></a>
<span class="alpha">ALPHA</span>
<nav class="main" aria-label="Main">
{nav_link('laws', 'Laws', '/laws/')}
{nav_link('fr', 'Federal Register', '/federal-register/')}
{nav_link('spending', 'Spending', '/spending/')}
{nav_link('programs', 'Program traces', '/programs/')}
{nav_link('method', 'How evidence works', '/method/')}
{nav_link('data', 'Data', '/data/')}
</nav>
</div></header>
<main id="main"><div class="wrap">
{crumb_html}
{body}
</div></main>
<footer class="site"><div class="wrap"><div class="cols">
<div><strong>ImpactLine</strong><p>The public delivery record. Official records, traceable sources, open questions.
ImpactLine does not declare fraud, waste or success. It shows what public records say and where they stop.</p></div>
<div><strong>Sources</strong><ul>
<li><a href="https://www.govinfo.gov/bulkdata/PLAW" rel="noopener">GovInfo (U.S. Government Publishing Office)</a></li>
<li><a href="https://www.federalregister.gov/reader-aids/developer-resources/rest-api" rel="noopener">Federal Register API</a></li>
<li><a href="https://api.usaspending.gov/" rel="noopener">USAspending.gov API (U.S. Treasury)</a></li></ul></div>
<div><strong>This site</strong><ul>
<li><a href="{self.href('/method/')}">How evidence works</a></li>
<li><a href="{self.href('/data/')}">Open data and evidence packets</a></li>
<li><a href="{self.href('/about/')}">About and corrections</a></li>
<li><a href="{E(self.repo_url)}" rel="noopener">Source code</a></li></ul></div>
</div>
<p>Static edition, rebuilt by an automated job. Law list as of {when(self.asof_laws)}. Every figure on a page carries its own
source and check date. Federal data is in the public domain.</p>
</div></footer>
<script src="{self.href('/static/app.js')}" defer></script>
</body>
</html>
"""
        rel = path.lstrip("/")
        if rel.endswith("/") or rel == "":
            rel += "index.html"
        self.write(rel, html)
        if listed and self.indexable:
            self.urls.append((canonical, lastmod or self.asof_laws[:10]))

    def slot(self):
        url = os.environ.get("ALERTS_URL", "").strip()
        if not url.startswith("https://"):
            return ""
        return (f'<aside class="slot" aria-label="Paid service"><small>Paid service</small>'
                f'<a href="{E(url)}" rel="noopener">Email alerts and API access for followed laws</a></aside>')


# ------------------------------------------------------------------------------------------------
# Pieces
# ------------------------------------------------------------------------------------------------
def law_sig(rec):
    """The short signal shown at the right of a law row."""
    bits = []
    if rec["fr_total"]:
        bits.append(f"<b>{rec['fr_total']:,}</b> FR documents")
    if rec["tagged_ba"]:
        bits.append(f"<b>{E(money(rec['tagged_ba']))}</b> tagged")
    elif rec["named_total"]:
        bits.append(f"named in <b>{rec['named_total']:,}</b> awards")
    return " · ".join(bits) or "no trail found yet"


def law_row(site, rec):
    law = rec["law"]
    text = " ".join([law["id"], f"p.l. {law['id']}", f"public law {law['id']}", law["title"], law.get("also_called", ""),
                     law["official_title"], (law.get("bill") or {}).get("label", ""), " ".join(law.get("parts", [])[:40])]).lower()
    aka = f' <span class="when">Also called the {E(law["also_called"])}</span>' if law.get("also_called") else ""
    return (f'<li data-t="{E(text)}" data-c="{law["congress"]}" data-k="{law["kind"]}" data-d="{law["approved"]}" data-n="{law["number"]}" '
            f'data-fr="{rec["fr_total"]}" data-sp="{int(rec["tagged_ba"] or 0)}" data-nm="{rec["named_total"]}">'
            f'<span class="pl">P.L. {law["id"]}</span>'
            f'<span><a href="{site.href("/laws/" + law["id"] + "/")}">{E(clip(law["title"], 180))}</a>{aka}'
            f'<span class="when">Approved {short_date(law["approved"])}</span></span>'
            f'<span class="sig">{law_sig(rec)}</span></li>')


def docs_list(docs):
    items = []
    for d in docs:
        agencies = ", ".join(d.get("a", [])[:2])
        items.append(f'<li><span class="kind">{E(d["k"])}</span><a href="{E(d["u"])}" rel="noopener">{E(clip(d["t"], 220))}</a>'
                     f'<small>{short_date(d["d"]) if d.get("d") else ""}{" · " + E(agencies) if agencies else ""} · {E(d["n"])}</small></li>')
    return '<ul class="docs">' + "".join(items) + "</ul>"


def awards_list(awards):
    items = []
    for a in awards:
        outl = f" · outlays {E(money(a['outlays']))}" if a.get("outlays") is not None else ""
        link = f'<a href="{E(a["url"])}" rel="noopener">{E(a["recipient"] or a["id"])}</a>' if a.get("url") else E(a["recipient"] or a["id"])
        items.append(f'<li><span class="kind">{E(spending.GROUP_LABEL.get(a.get("kind", ""), "award"))}</span>{link}'
                     f'<small>{E(money(a["amount"]))} award total{outl} · {E(a["agency"])} · {E(a["id"])}</small>'
                     f'<span class="desc">{E(clip(a["description"], 230))}</span></li>')
    return '<ul class="docs">' + "".join(items) + "</ul>"


def year_bars(by_year):
    if not by_year:
        return ""
    top = max(by_year.values()) or 1
    bars = "".join(f'<li><b>{n:,}</b><i style="height:{max(2, round(78 * n / top))}px"></i>{E(y)}</li>' for y, n in sorted(by_year.items()))
    label = "Federal Register documents citing this law, by year: " + ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items()))
    return f'<ul class="bars" role="img" aria-label="{E(label)}">{bars}</ul>'


def tree(stage_list):
    items = []
    for i, s in enumerate(stage_list, 1):
        items.append(f'<li class="stage {s["status"]}"><span class="dot">{i:02d}</span><span class="body"><strong>{E(s["title"])}</strong>'
                     f'<span class="who">{E(s["owner"])}</span><p>{E(s["summary"])}</p></span>'
                     f'<span class="chip {s["status"]}">{STATUS_LABEL[s["status"]]}</span></li>')
    return '<ol class="tree">' + "".join(items) + "</ol>"


def pct(part, whole):
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


# ------------------------------------------------------------------------------------------------
# Build
# ------------------------------------------------------------------------------------------------
def build(out, now=None):
    site = Site(out, now)
    cfg = site.cfg
    laws = load_laws()
    store = read_json(data_path("laws.json"), {}) or {}
    checks = Checks()
    site.asof_laws = store.get("updated_at") or iso(site.now)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(out, "static"))
    codes = spending.load_codes()
    programs = spending.load_programs()
    status = read_json(data_path("status.json"), {}) or {}

    recs = []
    for law in laws:
        lid = law["id"]
        fr = fedreg.load(lid)
        tagged = read_json(spending.tagged_path(lid))
        named = read_json(spending.named_path(lid))
        recs.append({"law": law, "fr": fr, "tagged": tagged, "named": named, "fr_total": (fr or {}).get("total", 0),
                     "tagged_ba": ((tagged or {}).get("overview") or {}).get("budget_authority") or 0,
                     "named_total": (named or {}).get("total", 0)})
    by_id = {r["law"]["id"]: r for r in recs}
    congresses = sorted({r["law"]["congress"] for r in recs}, reverse=True)
    first_date = min((r["law"]["approved"] for r in recs), default="")
    last_date = max((r["law"]["approved"] for r in recs), default="")
    n_fr_laws = sum(1 for r in recs if r["fr_total"])
    tagged_recs = sorted([r for r in recs if r["tagged_ba"]], key=lambda r: -r["tagged_ba"])
    named_recs = sorted([r for r in recs if r["named_total"]], key=lambda r: -r["named_total"])
    fr_checked = [checks.text("fr", r["law"]["id"]) for r in recs if checks.text("fr", r["law"]["id"])]
    asof_fr = max(fr_checked, default="")
    oldest_fr = min(fr_checked, default="")
    home = [("ImpactLine", "/")]

    # ---------------------------------------------------------------------------------------- law pages
    for r in recs:
        law, fr, tagged, named = r["law"], r["fr"], r["tagged"], r["named"]
        lid = law["id"]
        own_codes = [c["code"] for c in spending.codes_for(codes, lid)[0]]
        st = evidence.stages(law, fr, tagged, named, own_codes)
        aka = (f'<p class="note"><b>Commonly called the {E(law["also_called"])}.</b> '
               f'{E((cfg_aliases.get(lid) or {}).get("basis", ""))}</p>') if law.get("also_called") else ""
        official = "" if law["title"] == law["official_title"] else f'<p class="lede">{E(law["official_title"])}</p>'
        bill = law.get("bill") or {}
        meta = [f"<span>Approved <b>{human_date(law['approved'])}</b></span>"]
        if law.get("stat"):
            meta.append(f"<span><b>{E(law['stat'])}</b></span>")
        if bill:
            meta.append(f'<span>Enacted as <b>{E(bill["label"])}</b></span>')
        meta.append(f"<span>{ordinal(law['congress'])} Congress</span>")
        if law.get("sections"):
            meta.append(f"<span>{law['sections']:,} sections</span>")
        links = (f'<a class="btn primary" href="{E(law["links"]["pdf"])}" rel="noopener">Read the law (PDF)</a>'
                 f'<a class="btn" href="{E(law["links"]["text"])}" rel="noopener">Text</a>'
                 + (f'<a class="btn" href="{E(bill["url"])}" rel="noopener">Bill history on Congress.gov</a>' if bill else "")
                 + f'<a class="btn" href="{site.href("/evidence/" + lid + ".json")}">Evidence packet (JSON)</a>')
        parts_html = ""
        if law.get("parts"):
            shown = law["parts"][:24]
            more = len(law["parts"]) - len(shown)
            parts_html = ("<h3>Named parts of this law</h3><p>" + "; ".join(E(p) for p in shown)
                          + (f"; and {more} more" if more > 0 else "") + ".</p>")

        # Federal Register
        fr_checked_at = checks.text("fr", lid)
        if fr and fr["total"]:
            bt = fr["by_type"]
            type_rows = "".join(f"<tr><td>{E(k)}</td><td class=\"num\">{bt[k]:,}</td></tr>" for k in fedreg.TYPES if bt.get(k))
            agency_rows = "".join(f"<tr><td>{E(a)}</td><td class=\"num\">{n:,}</td></tr>" for a, n in fr["agencies"][:8])
            rules = (f"<h3>Latest rules and proposed rules that cite it</h3>{docs_list(fr['rules'][:8])}" if fr["rules"] else
                     "<p>No final or proposed rule cites this law by number.</p>")
            fr_html = f"""<p>{fr['total']:,} Federal Register documents cite Public Law {lid} by number{', from ' + short_date(fr['first']) if fr.get('first') else ''}
{' to ' + short_date(fr['last']) if fr.get('last') else ''}. A citation means the document mentions this law. It does not mean the document
carries the law out, and it is not a complete list of what agencies have done.</p>
<p class="asof">Source: Federal Register API, search for <code>{E(fr['term'])}</code>. Checked {when(fr_checked_at)}.
<a href="{E(fr['search_url'])}" rel="noopener">See all {fr['total']:,} in the Federal Register</a>.</p>
{year_bars(fr['by_year'])}
<div class="grid"><div class="tablewrap"><table><thead><tr><th>Kind of document</th><th class="num">Citing this law</th></tr></thead><tbody>{type_rows}</tbody></table></div>
<div class="tablewrap"><table><thead><tr><th>Agency (a document can list several)</th><th class="num">Documents</th></tr></thead><tbody>{agency_rows}</tbody></table></div></div>
{rules}
<h3>Latest documents of any kind</h3>{docs_list(fr['latest'][:8])}"""
        else:
            fr_html = (f'<p>No Federal Register document cites Public Law {lid} by number. That is common: many laws name a building, '
                       f'make a technical change or act directly, and need no rule or notice.</p>'
                       f'<p class="asof">Source: Federal Register API, search for <code>{E(fedreg.term(law))}</code>. Checked {when(fr_checked_at)}. '
                       f'<a href="{E(fedreg.search_url(law))}" rel="noopener">Run the search yourself</a>.</p>')

        # Money
        exclusive, shared = spending.codes_for(codes, lid)
        money_html = ""
        if tagged and tagged.get("overview"):
            ov = tagged["overview"]
            code_txt = ", ".join(f'{c["code"]} ({c["designation"].lower()})' for c in tagged["codes"])
            ba = ov.get("budget_authority") or 0
            agency_rows = "".join(
                f'<tr><td>{E(a["name"])}</td><td class="num">{E(money(a["budgetary_resources"]))}</td><td class="num">{E(money(a["obligations"]))}</td>'
                f'<td class="num">{E(money(a["outlays"]))}</td></tr>' for a in tagged.get("agencies", [])[:10])
            prog_rows = "".join(f'<tr><td>{E(p["listing"])}</td><td>{E(p["name"])}</td><td class="num">{E(money(p["obligations"]))}</td></tr>'
                                for p in tagged.get("programs", [])[:12])
            shared_note = ""
            if tagged.get("shared_codes"):
                shared_note = ('<p class="note">Treasury also uses fund code ' + ", ".join(
                    f'<b>{E(c["code"])}</b> for Public Laws {E(", ".join(c["laws"]))} together' for c in tagged["shared_codes"])
                    + ". Money under a shared code cannot be credited to one law, so it is left out of the figures above.</p>")
            traces = [p for p in programs if p["law"] == lid]
            trace_html = ("<h3>Program traces under this law</h3>" + tiles(site, [
                (f"Assistance Listing {p['listing']}", p["name"], p["owner"], f"/programs/{p['slug']}/") for p in traces])) if traces else ""
            money_html = f"""<p><span class="chip official">Official record</span> The U.S. Treasury tags funds provided by this law with
Disaster Emergency Fund Code {E(code_txt)}. The figures below are what agencies reported under that code. Spending under this
law that carries no such tag is not included, so this can be less than everything the law funds.</p>
<div class="card stats">
<div><strong>{E(money(ba))}</strong><span>Budget authority tagged to this law</span></div>
<div><strong>{E(money(ov.get('total_obligations')))}</strong><span>Obligated ({pct(ov.get('total_obligations') or 0, ba)} of budget authority)</span></div>
<div><strong>{E(money(ov.get('total_outlays')))}</strong><span>Paid out ({pct(ov.get('total_outlays') or 0, ba)} of budget authority)</span></div>
<div><strong>{E(money(ov.get('award_obligations')))}</strong><span>Of the obligations, to grants, contracts and other awards</span></div>
</div>
<p class="asof">Source: USAspending.gov API, <a href="{E(tagged['source'])}" rel="noopener">overview for fund code {E(', '.join(c['code'] for c in tagged['codes']))}</a>.
Checked {when(checks.text('tagged', lid))}. Percentages are simple divisions of the figures shown.</p>
{shared_note}
{'<h3>By agency</h3><div class="tablewrap"><table><thead><tr><th>Agency</th><th class="num">Budgetary resources</th><th class="num">Obligated</th><th class="num">Paid out</th></tr></thead><tbody>' + agency_rows + '</tbody></table></div>' if agency_rows else ''}
{'<h3>By program (Assistance Listing)</h3><p>Award obligations carrying this law&#x27;s fund code, grouped by the federal program that made them.</p><div class="tablewrap"><table><thead><tr><th>Listing</th><th>Program</th><th class="num">Award obligations</th></tr></thead><tbody>' + prog_rows + '</tbody></table></div>' if prog_rows else ''}
{trace_html}
{'<h3>Largest awards that carry this code</h3><p>Amounts are each award&#x27;s total, which can include money from other sources.</p>' + awards_list(tagged['awards'][:10]) if tagged.get('awards') else ''}"""
        elif named and named.get("total"):
            blocks = []
            for p in named["phrases"]:
                if not p["counts"]:
                    continue
                counts = ", ".join(f"{n:,} {spending.GROUP_LABEL[k][:-1] if n == 1 and spending.GROUP_LABEL[k].endswith('s') else spending.GROUP_LABEL[k]}"
                                   for k, n in sorted(p["counts"].items(), key=lambda kv: -kv[1]))
                what = "cites" if p["match"] == "citation" else "names"
                floor = "At least " if p.get("partial") else ""
                returned = sum((p.get("returned") or {}).values())
                loose = ""
                if p.get("partial"):
                    loose = (f" USAspending's keyword search returns {returned:,} awards for this phrase. The {spending.PAGE * spending.MAX_PAGES:,} largest "
                             f"of each kind were read, and only those whose description contains the phrase are counted, so these are minimums.")
                elif returned > sum(p["counts"].values()):
                    loose = (f" USAspending's keyword search returns {returned:,} awards for this phrase; only those whose description "
                             f"contains it are counted here.")
                blocks.append(f'<h3>Awards whose description {what} “{E(p["phrase"])}”</h3><p>{floor}{counts}, among awards starting on or after '
                              f'{short_date(named["period_start"])}.{loose} <a href="{E(p["search_url"])}" rel="noopener">Run this search on USAspending.gov</a>.</p>'
                              + (f"<p>Largest by award total:</p>{awards_list(p['top'][:5])}" if p["top"] else ""))
            money_html = f"""<p><span class="chip candidates">Candidates</span> Treasury does not tag spending to this law. The only automatic
signal is an award whose description mentions the law. These are keyword matches: some awards funded by this law never say so,
and an award can mention a law it is not funded by. They are not added up, and they are not “this law's spending”.</p>
{''.join(blocks)}
<p class="asof">Source: USAspending.gov award search. Checked {when(checks.text('named', lid))}.</p>"""
        elif own_codes:
            money_html = (f'<p><span class="chip documented">Official record</span> Treasury tags spending to this law with fund code '
                          f'{E(", ".join(own_codes))}. USAspending.gov did not return the totals for that code when last asked, so no amount '
                          f'is shown here. The request is repeated on every refresh.</p>'
                          f'<p class="asof">Source: USAspending.gov API, Disaster Emergency Fund Codes. Code list read {when(status.get("tagged", {}).get("last_success", ""))}.</p>')
        elif not checks.text("named", lid) and not checks.text("tagged", lid):
            money_html = ('<p>Spending records for this law have not been read yet. They are read on a rolling schedule; '
                          'this section fills in after the next refresh.</p>')
        else:
            checked = checks.text("named", lid) or checks.text("tagged", lid)
            money_html = (f'<p>No spending is tagged to this law, and no award description names it. Treasury tags spending by law only '
                          f'for emergency, disaster and wildfire funds, the COVID-19 relief laws and the Infrastructure Investment and Jobs Act. '
                          f'Money under other laws is tracked by Treasury account, not by law.</p>'
                          f'<p class="asof">Source: USAspending.gov fund-code list and award search. Checked {when(checked)}.</p>')
            if shared:
                money_html += ('<p class="note">Treasury uses fund code ' + ", ".join(
                    f'<b>{E(c["code"])}</b> for Public Laws {E(", ".join(sorted({p["law"] for p in c["parts"]})))} together' for c in shared)
                    + ". Money under a shared code cannot be credited to one law.</p>")

        desc_bits = [f"Public Law {lid}, approved {human_date(law['approved'])}."]
        if r["fr_total"]:
            desc_bits.append(f"{r['fr_total']:,} Federal Register documents cite it.")
        if r["tagged_ba"]:
            desc_bits.append(f"{money(r['tagged_ba'])} is tagged to it by Treasury.")
        desc_bits.append("Sources, check dates and gaps shown.")
        ld = [{"@context": "https://schema.org", "@type": "Legislation", "name": law["title"], "legislationIdentifier": f"Public Law {lid}",
               "legislationDate": law["approved"], "legislationType": "Public Law", "legislationJurisdiction": "US",
               "url": site.url + f"/laws/{lid}/", "sameAs": law["links"]["details"]},
              {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                  {"@type": "ListItem", "position": 1, "name": "Laws", "item": site.url + "/laws/"},
                  {"@type": "ListItem", "position": 2, "name": f"{ordinal(law['congress'])} Congress", "item": site.url + f"/congress/{law['congress']}/"},
                  {"@type": "ListItem", "position": 3, "name": f"Public Law {lid}", "item": site.url + f"/laws/{lid}/"}]}]
        body = f"""<p class="eyebrow">Public Law {lid} · {E(KIND_LABEL[law['kind']])}</p>
<h1>{E(law['title'])}</h1>
{official}{aka}
<div class="meta-row">{''.join(meta)}</div>
<div class="links">{links}</div>
<p class="asof">Law identity from the law's own file at GovInfo (U.S. Government Publishing Office){', title from ' + E(law['title_source']) if law['title_source'] != 'law text' else ''}.
File <a href="{E(law['links']['xml'])}" rel="noopener">PLAW-{law['congress']}publ{law['number']}.xml</a>, SHA-256 <code>{law['xml_sha256'][:16]}…</code>.</p>

<h2 id="record">The record so far</h2>
<p>Seven steps separate a law from a result. Each is marked by what public records support today.</p>
{tree(st)}

<h2 id="federal-register">Federal Register trail</h2>
{fr_html}

<h2 id="money">Money</h2>
{money_html}
{site.slot()}
{parts_html}

<h2 id="limits">What this record cannot show</h2>
<ul class="prose">{''.join(f'<li>{E(x)}</li>' for x in evidence.LIMITS)}</ul>

<h2 id="evidence">Evidence packet</h2>
<p>Everything on this page, with its sources and check dates, is in one file:
<a href="{site.href('/evidence/' + lid + '.json')}"><code>evidence/{lid}.json</code></a>. Its SHA-256 is listed in the
<a href="{site.href('/evidence/manifest.json')}">manifest</a>, which GitHub attests for each build.</p>
<div class="verify"><button class="btn" id="verify" type="button" data-id="{lid}" data-packet="{site.href('/evidence/' + lid + '.json')}"
data-manifest="{site.href('/evidence/manifest.json')}">Check this packet against the manifest</button><output id="verify-out" role="status" aria-live="polite"></output></div>
<p class="asof">How to check the manifest itself: <a href="{site.href('/data/#verify')}">verify the attestation</a>.
New Federal Register documents for this law: <a href="{site.href('/laws/' + lid + '/feed.xml')}">Atom feed</a>.</p>"""
        og = (f"law-{lid}", f"P.L. {lid}: {clip(law['title'], 90)}", law_sig_text(r)) if (r["tagged_ba"] or r["fr_total"] >= 40) else None
        site.page(f"/laws/{lid}/", f"{clip(law['title'], 110)} (Public Law {lid})", " ".join(desc_bits), body,
                  crumbs=[("Laws", "/laws/"), (f"{ordinal(law['congress'])} Congress", f"/congress/{law['congress']}/"), (f"P.L. {lid}", f"/laws/{lid}/")],
                  jsonld=ld, nav="laws", og=og, lastmod=(fr_checked_at or site.asof_laws)[:10],
                  feed=(f"/laws/{lid}/feed.xml", f"Federal Register documents citing Public Law {lid}"))
        entries = "".join(
            f"<entry><title>{E(d['k'])}: {E(clip(d['t'], 200))}</title><id>{E(d['u'])}</id><link href=\"{E(d['u'])}\"/>"
            f"<updated>{E(d['d'])}T00:00:00Z</updated><summary>{E(', '.join(d.get('a', [])))} · Federal Register {E(d['n'])}</summary></entry>"
            for d in ((fr or {}).get("latest") or [])[:15] if d.get("d"))
        site.write(f"laws/{lid}/feed.xml", f'<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
                   f"<title>Federal Register documents citing Public Law {lid}</title><id>{E(site.url)}/laws/{lid}/</id>"
                   f'<link href="{E(site.url)}/laws/{lid}/"/><link rel="self" href="{E(site.url)}/laws/{lid}/feed.xml"/>'
                   f"<updated>{E(fr_checked_at or site.asof_laws)}</updated><author><name>ImpactLine</name></author>{entries}</feed>\n")

    # ---------------------------------------------------------------------------------------- lists
    finder = f"""<form class="finder" role="search" action="{site.href('/laws/')}" method="get">
<label class="f q">Search laws<input type="search" name="q" placeholder="Name, number, bill or a named part" autocomplete="off"></label>
<label class="f">Congress<select name="c"><option value="">All</option>{''.join(f'<option value="{c}">{ordinal(c)}</option>' for c in congresses)}</select></label>
<label class="f">Show<select name="k"><option value="">All laws</option><option value="fr">Cited in the Federal Register</option>
<option value="tagged">Spending tagged by law</option><option value="named">Named in award descriptions</option>
<option value="general">General laws</option><option value="appropriations">Appropriations</option><option value="disapproval">Rule disapprovals</option>
<option value="naming">Namings</option></select></label>
<label class="f">Sort by<select name="s"><option value="">Newest first</option><option value="oldest">Oldest first</option>
<option value="fr">Most Federal Register documents</option><option value="tagged">Most tagged budget authority</option>
<option value="named">Most awards naming it</option></select></label>
</form>"""
    window = f"{short_date(first_date)} to {short_date(last_date)}" if recs else ""
    site.page("/laws/", "Public laws: every enacted law and its trail",
              f"All {len(recs):,} public laws from the {ordinal(congresses[-1]) if congresses else ''} Congress on, each with its Federal Register citations and any spending tagged to it.",
              f"""<p class="eyebrow">Enacted laws</p><h1>{len(recs):,} public laws</h1>
<p class="lede">Every public law from the {ordinal(congresses[-1])} Congress to today ({window}), newest first. Open one to see its trail.</p>
<p class="asof">Law list from GovInfo bulk data, as of {when(site.asof_laws)}. Federal Register counts checked between {when(oldest_fr)} and {when(asof_fr)}.</p>
{finder}<p class="count" id="count" role="status" aria-live="polite">{len(recs):,} laws</p>
<ul class="lawlist" id="lawlist">{''.join(law_row(site, r) for r in recs)}</ul>""", crumbs=home, nav="laws")
    for c in congresses:
        rows = [r for r in recs if r["law"]["congress"] == c]
        start = 1789 + 2 * (c - 1)
        site.page(f"/congress/{c}/", f"Public laws of the {ordinal(c)} Congress",
                  f"The {len(rows):,} public laws of the {ordinal(c)} Congress ({start}-{start + 2}), with Federal Register citations and tagged spending for each.",
                  f"""<p class="eyebrow">{ordinal(c)} Congress · {start}–{start + 2}</p><h1>{len(rows):,} public laws</h1>
<p class="asof">Source: GovInfo bulk data, <a href="{E((store.get('sources', {}).get(str(c)) or {}).get('zip', 'https://www.govinfo.gov/bulkdata/PLAW'))}" rel="noopener">PLAW-{c}-public.zip</a>
(file dated {E((store.get('sources', {}).get(str(c)) or {}).get('modified', 'unknown'))}). Read {when((store.get('sources', {}).get(str(c)) or {}).get('retrieved_at', ''))}.</p>
<ul class="lawlist">{''.join(law_row(site, r) for r in rows)}</ul>""", crumbs=home + [("Laws", "/laws/")], nav="laws")

    # ---------------------------------------------------------------------------------------- spending
    t_rows = "".join(
        f'<tr><td><a href="{site.href("/laws/" + r["law"]["id"] + "/")}#money">P.L. {r["law"]["id"]}</a></td><td>{E(clip(r["law"]["title"], 90))}</td>'
        f'<td>{E(", ".join(c["code"] for c in r["tagged"]["codes"]))}</td><td class="num">{E(money(r["tagged_ba"]))}</td>'
        f'<td class="num">{E(money(r["tagged"]["overview"].get("total_obligations")))}</td><td class="num">{E(money(r["tagged"]["overview"].get("total_outlays")))}</td>'
        f'<td>{when(checks.text("tagged", r["law"]["id"]))}</td></tr>' for r in tagged_recs)
    n_rows = "".join(
        f'<tr><td><a href="{site.href("/laws/" + r["law"]["id"] + "/")}#money">P.L. {r["law"]["id"]}</a></td><td>{E(clip(r["law"].get("also_called") or r["law"]["title"], 90))}</td>'
        f'<td class="num">{r["named_total"]:,}</td><td>{when(checks.text("named", r["law"]["id"]))}</td></tr>' for r in named_recs[:60])
    site.page("/spending/", "Spending that can be tied to a law",
              f"The {len(tagged_recs)} recent laws whose spending the U.S. Treasury tags by law, with budget authority, obligations and outlays, and the laws most often named in award descriptions.",
              f"""<p class="eyebrow">Money</p><h1>Spending that can be tied to a law</h1>
<p class="lede">Federal spending is tracked by Treasury account, not by law. For a small set of laws Treasury adds a tag that names the law. Those are the only laws whose spending can be stated as fact.</p>
<h2>Tagged by law <span class="chip official">Official record</span></h2>
<p>{len(tagged_recs)} laws in the list carry their own Disaster Emergency Fund Code. Figures are what agencies reported under each law's code. They cover the tagged funds only.</p>
<div class="tablewrap"><table><thead><tr><th>Law</th><th>Title</th><th>Fund code</th><th class="num">Budget authority</th><th class="num">Obligated</th><th class="num">Paid out</th><th>Checked</th></tr></thead><tbody>{t_rows}</tbody></table></div>
<p class="asof">Source: USAspending.gov API (<a href="https://api.usaspending.gov/api/v2/references/def_codes/" rel="noopener">fund-code list</a> and per-code overview).</p>
<h2>Named in award descriptions <span class="chip candidates">Candidates</span></h2>
<p>For laws without a tag, the only automatic signal is an award description that mentions the law. Counts of such awards are shown, never their sum.</p>
<div class="tablewrap"><table><thead><tr><th>Law</th><th>Title</th><th class="num">Award descriptions naming it</th><th>Checked</th></tr></thead><tbody>{n_rows}</tbody></table></div>
<p class="asof">Source: USAspending.gov award search, by public-law number and, where the name is distinctive, by name.</p>""", crumbs=home, nav="spending")

    # ---------------------------------------------------------------------------------------- federal register
    top_fr = sorted([r for r in recs if r["fr_total"]], key=lambda r: -r["fr_total"])[:80]
    fr_rows = "".join(
        f'<tr><td><a href="{site.href("/laws/" + r["law"]["id"] + "/")}#federal-register">P.L. {r["law"]["id"]}</a></td>'
        f'<td>{E(clip(r["law"].get("also_called") or r["law"]["title"], 90))}</td><td class="num">{r["fr_total"]:,}</td>'
        f'<td class="num">{r["fr"]["by_type"].get("Rule", 0):,}</td><td class="num">{r["fr"]["by_type"].get("Proposed Rule", 0):,}</td>'
        f'<td>{short_date(r["fr"]["last"]) if r["fr"].get("last") else ""}</td></tr>' for r in top_fr)
    recent = {}
    for r in recs:
        for d in ((r["fr"] or {}).get("latest") or [])[:6]:
            if d.get("d"):
                recent.setdefault(d["n"], dict(d, laws=[]))["laws"].append(r["law"]["id"])
    recent_docs = sorted(recent.values(), key=lambda d: (d["d"], d["n"]), reverse=True)[:40]
    recent_html = '<ul class="docs">' + "".join(
        f'<li><span class="kind">{E(d["k"])}</span><a href="{E(d["u"])}" rel="noopener">{E(clip(d["t"], 200))}</a>'
        f'<small>{short_date(d["d"])} · {E(", ".join(d.get("a", [])[:2]))} · cites '
        + ", ".join(f'<a href="{site.href("/laws/" + x + "/")}">P.L. {x}</a>' for x in d["laws"][:6]) + "</small></li>"
        for d in recent_docs) + "</ul>"
    site.page("/federal-register/", "Recent laws in the Federal Register",
              f"Which recent public laws agencies cite most in rules, proposed rules and notices, and the newest Federal Register documents that cite them.",
              f"""<p class="eyebrow">Agency implementation</p><h1>Recent laws in the Federal Register</h1>
<p class="lede">{n_fr_laws:,} of the {len(recs):,} laws are cited by number in at least one Federal Register document. A citation is a lead, not proof of implementation.</p>
<p class="asof">Source: Federal Register API. Counts checked between {when(oldest_fr)} and {when(asof_fr)}; each law's page shows its own check date.</p>
<h2>Newest documents that cite a recent law</h2>{recent_html}
<h2>Most-cited laws</h2>
<div class="tablewrap"><table><thead><tr><th>Law</th><th>Title</th><th class="num">Documents</th><th class="num">Final rules</th><th class="num">Proposed rules</th><th>Latest</th></tr></thead><tbody>{fr_rows}</tbody></table></div>""",
              crumbs=home, nav="fr")

    # ---------------------------------------------------------------------------------------- programs
    prog_tiles = []
    for p in programs:
        data = read_json(spending.program_path(p["slug"])) or {}
        law = (by_id.get(p["law"]) or {}).get("law")
        if not law:
            continue
        checked = checks.text("programs", p["slug"])
        nat = data.get("national") or {}
        counts = ", ".join(f"{n:,} {spending.GROUP_LABEL[k]}" for k, n in sorted((nat.get("counts") or {}).items(), key=lambda kv: -kv[1])) or "no awards found"
        guide_html = ""
        for g in p["guides"]:
            guide_html += (f'<li><span class="kind">{E(STAGE_LABEL.get(g["stage"], g["stage"]))}</span><a href="{E(g["url"])}" rel="noopener">{E(g["title"])}</a>'
                           f'<span class="desc">{E(g["description"])}</span></li>')
        state_html = ""
        if p.get("state_guides"):
            state_html = (f'<h3>In {E(STATE_NAME.get(p["pilot_state"], p["pilot_state"]))}: official records to check</h3><ul class="docs">' + "".join(
                f'<li><span class="kind">{E(STAGE_LABEL.get(g["stage"], g["stage"]))}</span><a href="{E(g["url"])}" rel="noopener">{E(g["title"])}</a>'
                f'<span class="desc">{E(g["description"])}</span></li>' for g in p["state_guides"]) + "</ul>")
        st = data.get("state") or {}
        st_counts = ", ".join(f"{n:,} {spending.GROUP_LABEL[k]}" for k, n in sorted((st.get("counts") or {}).items(), key=lambda kv: -kv[1]))
        state_awards = ""
        if p.get("pilot_state"):
            sn = STATE_NAME.get(p["pilot_state"], p["pilot_state"])
            state_awards = (f'<h3>Awards performed in {E(sn)}</h3>' + (
                f"<p>{st_counts} with a place of performance in {E(sn)}.</p>{awards_list(st.get('awards', [])[:8])}" if st.get("counts") else
                f"<p>No award under this program with a place of performance in {E(sn)} carries the law's fund code. "
                f"That does not show that no money reached {E(sn)}: formula funds are often recorded at a state agency's address.</p>"))
        body = f"""<p class="eyebrow">Program trace · {E(p['owner'])}</p><h1>{E(p['name'])}</h1>
<p class="lede">{E(p['authority'])}</p>
<p><span class="chip official">Official record</span> This trace joins two identifiers that agencies report themselves: the fund code Treasury
gives <a href="{site.href('/laws/' + law['id'] + '/')}">Public Law {law['id']}</a> ({E(', '.join(data.get('codes', [])) or 'none')}) and
Assistance Listing {E(p['listing'])}{' (' + E(data['listing_name']) + ')' if data.get('listing_name') else ''}. An award appears only if it carries both.</p>
<div class="card stats"><div><strong>{E(money(data.get('obligations')))}</strong><span>Award obligations under both identifiers</span></div>
<div><strong>{sum((nat.get('counts') or {}).values()):,}</strong><span>Awards ({E(counts)})</span></div></div>
<p class="asof">Source: USAspending.gov API, award search filtered by fund code and Assistance Listing. Checked {when(checked)}.</p>
<p class="note warn"><b>Read this before drawing conclusions.</b> {E(p['caution'])} An award record shows money promised and paid. It does not show a bus
delivered, a bridge opened or a network lit.</p>
<h2>Largest awards</h2>{awards_list(nat.get('awards', [])[:10]) if nat.get('awards') else '<p>No awards found.</p>'}
{state_awards}
<h2>From award to outcome: the official records to collect</h2>
<p>The steps below are the program's own published requirements. ImpactLine links them; it has not collected or reviewed the records they describe.</p>
<ul class="docs">{guide_html}</ul>
{state_html}"""
        site.page(f"/programs/{p['slug']}/", f"{p['name']}: from the law to the awards",
                  f"{p['name']} under Public Law {law['id']}: awards that carry both the law's fund code and the program's Assistance Listing number, and the official records needed to check delivery.",
                  body, crumbs=home + [("Program traces", "/programs/")], nav="programs", og=(f"program-{p['slug']}", p["name"], f"Program trace · Public Law {law['id']}"))
        prog_tiles.append((f"Assistance Listing {p['listing']}", p["name"], f"{p['owner']} · {money(data.get('obligations'))} in tagged award obligations", f"/programs/{p['slug']}/"))
    site.page("/programs/", "Program traces: from a law to its awards",
              "Three pilot traces that follow one law into one program using official identifiers, then list the records needed to check delivery.",
              f"""<p class="eyebrow">Law → program → awards → outcome</p><h1>Program traces</h1>
<p class="lede">Three pilot traces inside the Infrastructure Investment and Jobs Act. Each joins the law's fund code to a program's Assistance Listing number, so every award shown is tied to both by the agencies' own reporting.</p>
{tiles(site, prog_tiles)}
<p class="note">A trace stops where the federal award record stops. What was built, delivered or accepted is in state, local and agency records that ImpactLine links but does not read.</p>""",
              crumbs=home, nav="programs")

    # ---------------------------------------------------------------------------------------- home
    latest = recs[:10]
    top_cited = sorted([r for r in recs if r["fr_total"]], key=lambda r: -r["fr_total"])[:6]
    demo = evidence.stages(recs[0]["law"], recs[0]["fr"], recs[0]["tagged"], recs[0]["named"]) if recs else []
    body = f"""<p class="eyebrow">Law → implementation → outcome</p>
<h1>Passed is only the beginning.</h1>
<p class="lede">Follow what has to happen next. See what the record can prove. ImpactLine follows each enacted law into the Federal
Register and federal spending records, and leaves the gaps visible.</p>
<div class="card stats">
<div><strong>{len(recs):,}</strong><span>enacted public laws</span><small>{window}</small></div>
<div><strong>{n_fr_laws:,}</strong><span>cited in the Federal Register</span><small>by public-law number</small></div>
<div><strong>{len(tagged_recs)}</strong><span>with spending tagged by law</span><small>Treasury fund codes</small></div>
<div><strong>{len(named_recs):,}</strong><span>named in award descriptions</span><small>keyword candidates</small></div>
</div>
<p class="asof">Law list: GovInfo, as of {when(site.asof_laws)}. Federal Register: checked through {when(asof_fr)}. Spending: USAspending.gov, check dates on each page.</p>
{finder}
<h2>Most recently enacted</h2>
<ul class="lawlist">{''.join(law_row(site, r) for r in latest)}</ul>
<p><a class="btn" href="{site.href('/laws/')}">All {len(recs):,} laws</a></p>
<h2>Most cited by agencies</h2>
<ul class="lawlist">{''.join(law_row(site, r) for r in top_cited)}</ul>
<p><a class="btn" href="{site.href('/federal-register/')}">Laws in the Federal Register</a></p>
<h2>Where the money can be followed</h2>
<p>Treasury tags spending to a law for only a few laws. These carry the most tagged budget authority.</p>
<ul class="lawlist">{''.join(law_row(site, r) for r in tagged_recs[:6])}</ul>
<p><a class="btn" href="{site.href('/spending/')}">Spending that can be tied to a law</a> <a class="btn" href="{site.href('/programs/')}">Program traces</a></p>
<h2>How to read a record</h2>
<p>Each law page shows seven steps and marks each one <span class="chip documented">Official record</span>,
<span class="chip candidates">Candidates</span> or <span class="chip">Needs evidence</span>. This is the newest law's record:</p>
{tree(demo)}
<p><a class="btn" href="{site.href('/method/')}">How evidence works</a></p>"""
    site.page("/", "ImpactLine: the public delivery record", cfg["tagline"], body, og=("home", "Passed is only the beginning.", f"{len(recs):,} enacted laws followed into the Federal Register and spending records"),
              jsonld=[{"@context": "https://schema.org", "@type": "WebSite", "name": site.name, "url": site.url + "/", "description": cfg["tagline"],
                       "potentialAction": {"@type": "SearchAction", "target": {"@type": "EntryPoint", "urlTemplate": site.url + "/laws/?q={search_term_string}"},
                                           "query-input": "required name=search_term_string"}}])

    # ---------------------------------------------------------------------------------------- static pages
    status = read_json(data_path("status.json"), {}) or {}
    src_rows = "".join(
        f"<tr><td>{E(label)}</td><td>{when((status.get(key) or {}).get('last_success', ''))}</td><td>{E((status.get(key) or {}).get('note', ''))}</td></tr>"
        for key, label in (("laws", "GovInfo: public laws"), ("fr", "Federal Register: citing documents"), ("tagged", "USAspending: funds tagged by law"),
                           ("programs", "USAspending: program traces"), ("named", "USAspending: awards naming a law")))
    method = f"""<article class="prose"><p class="eyebrow">Method</p><h1>How evidence works</h1>
<p class="lede">ImpactLine shows what public records say about a law after it passes, and marks where the records stop. It does not decide whether a law succeeded.</p>
<h2 id="labels">Three labels</h2>
<ul>
<li><span class="chip documented">Official record</span> An agency reported this fact itself, tied to this law by an official identifier: the law's
own file at the Government Publishing Office, or funds Treasury tagged with the law's fund code.</li>
<li><span class="chip candidates">Candidates</span> An automatic match that may or may not be about this law: a Federal Register document that cites
the law's number, or an award description that names the law. Candidates are leads for a person to check. They are never added up.</li>
<li><span class="chip">Needs evidence</span> ImpactLine has no public record for this step. That is a statement about ImpactLine's sources,
not a finding that nothing happened.</li>
</ul>
<h2 id="sources">Sources</h2>
<ul>
<li><b>Laws.</b> GovInfo bulk data from the U.S. Government Publishing Office: one file per public law, with its number, approval date, Statutes
at Large citation and text. Each law page shows the SHA-256 of the file it was read from.</li>
<li><b>Federal Register.</b> The Federal Register API, searched for each law's number written three ways
(<code>"Public Law 117-58"</code>, <code>"Pub. L. 117-58"</code>, <code>"P.L. 117-58"</code>).</li>
<li><b>Spending tagged by law.</b> USAspending.gov, for laws that carry a Disaster Emergency Fund Code: budget authority, obligations and outlays
reported under the law's code. A code shared by several laws is not credited to any of them.</li>
<li><b>Program traces.</b> USAspending.gov awards that carry both a law's fund code and a program's Assistance Listing number.</li>
<li><b>Awards naming a law.</b> USAspending.gov award search, for descriptions that cite the law's number or a distinctive name, limited to awards
that start on or after the law's approval date. Names shared by several laws, and generic names, are not searched.</li>
</ul>
<div class="tablewrap"><table><thead><tr><th>Source</th><th>Last successful read</th><th>Result</th></tr></thead><tbody>{src_rows}</tbody></table></div>
<h2 id="freshness">Check dates</h2>
<p>An automated job reads the sources every night within a budget: young and busy laws every night, quiet laws every one to four weeks.
Each figure shows the date it was last read. If a source fails, the last good data stays, with its older date.</p>
<h2 id="limits">What ImpactLine does not do</h2>
<ul>{''.join(f'<li>{E(x)}</li>' for x in evidence.LIMITS)}
<li>It does not use AI to summarise laws or to decide what a document means.</li>
<li>It does not send reports to anyone. A download is a file on your computer.</li></ul>
<h2 id="corrections">Corrections</h2>
<p>If a record here is wrong, <a href="{E(site.repo_url)}/issues/new/choose" rel="noopener">open an issue</a> with the law number and the official source.
Automatic matches can be wrong by nature, which is why they are labelled candidates.</p></article>"""
    site.page("/method/", "How evidence works", "What ImpactLine's labels mean, where each figure comes from, how often it is checked, and what the record cannot show.",
              method, crumbs=home, nav="method")
    about = f"""<article class="prose"><p class="eyebrow">About</p><h1>The public delivery record</h1>
<p class="lede">A law's passage is recorded in one place. What happens next is scattered across agency notices, spending systems and local files. ImpactLine keeps one page per law that gathers the federal part of that trail.</p>
<p>It is for people whose job is to ask "where did the money from this law go, and what evidence exists": auditors, reporters, legislative staff
and researchers. It tells them what the public record supports today and what they still need to request.</p>
<h2>What it will not say</h2>
<p>ImpactLine does not call anything fraud, waste, delay or success. It has no outcome data and no reviewer. Where a link between a law and a
record is an automatic match, the page says so.</p>
<h2>Nonpartisan by construction</h2>
<p>Every law in the window is listed, in date order, with the same sources and the same rules. No law is featured for its politics.</p>
<h2>Privacy</h2>
<p>No accounts, no cookies, no sign-up. Searches run in your browser. {'Page views are counted with GoatCounter, which stores no personal data.' if os.environ.get('GOATCOUNTER_URL') else 'The site runs no analytics.'}</p>
<h2>Corrections and contact</h2>
<p><a href="{E(site.repo_url)}/issues" rel="noopener">Open an issue on GitHub</a>. The code that builds this site is public in the same place.</p></article>"""
    site.page("/about/", "About ImpactLine", "What ImpactLine is for, what it will not say, and how to send a correction.", about, crumbs=home)

    # ---------------------------------------------------------------------------------------- data + evidence
    manifest = evidence.write_all(out, laws, checks, site.repo_url, iso(site.now))
    summary = [{"public_law": r["law"]["id"], "title": r["law"]["title"], "also_called": r["law"].get("also_called", ""),
                "official_title": r["law"]["official_title"], "approved": r["law"]["approved"], "congress": r["law"]["congress"],
                "statutes_at_large": r["law"].get("stat", ""), "bill": (r["law"].get("bill") or {}).get("label", ""), "kind": r["law"]["kind"],
                "federal_register_documents": r["fr_total"], "federal_register_checked_at": checks.text("fr", r["law"]["id"]),
                "tagged_budget_authority": r["tagged_ba"] or None,
                "tagged_obligations": ((r["tagged"] or {}).get("overview") or {}).get("total_obligations"),
                "tagged_outlays": ((r["tagged"] or {}).get("overview") or {}).get("total_outlays"),
                "awards_naming_law": r["named_total"], "page": site.url + f"/laws/{r['law']['id']}/",
                "evidence": site.url + f"/evidence/{r['law']['id']}.json", "govinfo": r["law"]["links"]["details"]} for r in recs]
    site.write("data/laws.json", json.dumps({"as_of": site.asof_laws, "source": site.url + "/", "laws": summary}, ensure_ascii=False, indent=1) + "\n")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    cols = list(summary[0].keys()) if summary else []
    w.writerow(cols)
    for row in summary:
        w.writerow(["" if row[c] is None else row[c] for c in cols])
    site.write("data/laws.csv", buf.getvalue())
    data_page = f"""<article class="prose"><p class="eyebrow">Open data</p><h1>Data and evidence packets</h1>
<p class="lede">Everything on this site is also a file. Federal data is in the public domain; this compilation is released under CC0.</p>
<p><a class="btn primary" href="{site.href('/data/laws.csv')}">laws.csv</a> <a class="btn" href="{site.href('/data/laws.json')}">laws.json</a>
<a class="btn" href="{site.href('/evidence/manifest.json')}">evidence/manifest.json</a></p>
<p class="asof">{len(recs):,} laws. Law list as of {when(site.asof_laws)}. Files are rebuilt after every refresh.</p>
<h2>What is in each file</h2>
<ul>
<li><code>data/laws.csv</code> and <code>data/laws.json</code>: one row per law with its number, titles, approval date, citation, Federal Register
document count, any tagged budget authority, obligations and outlays, the number of award descriptions naming it, and links.</li>
<li><code>evidence/&lt;congress&gt;-&lt;number&gt;.json</code>: the full record for one law: identity and source-file hash, Federal Register
summary and latest documents, spending records, the seven-step status, the limits, and every check date.</li>
<li><code>evidence/manifest.json</code>: the SHA-256 and size of every packet in this build, with the build's commit.</li>
</ul>
<h2 id="verify">Verify a packet</h2>
<p>Each law page has a button that recomputes the packet's SHA-256 in your browser and compares it with the manifest. To check that the
manifest itself came from this project's build and was not changed afterwards, use GitHub's attestation tool:</p>
<pre><code>curl -sO {E(site.url)}/evidence/manifest.json
gh attestation verify manifest.json --repo {E(cfg['repo'])}
curl -s {E(site.url)}/evidence/117-58.json | shasum -a 256   # compare with packets["117-58"].sha256</code></pre>
<p>The attestation is a Sigstore signature tied to this repository's workflow, made when the site is built. It shows where the file
came from. It does not make the underlying federal data correct, and it is not a trusted timestamp or an archive of the source documents.
This build's manifest lists {manifest['count']:,} packets.</p>
<h2>Feeds</h2>
<p><a href="{site.href('/feed.xml')}">New public laws</a> (Atom). Every law page also has a feed of the newest Federal Register documents that cite it.</p>
<h2>Reuse</h2>
<p>Please cite the official source for any figure (each record names it) and link the law's page here so readers can see the check date.</p></article>"""
    site.page("/data/", "Open data and evidence packets", "Download every law's record as CSV or JSON, and verify evidence packets against the attested manifest.",
              data_page, crumbs=home, nav="data", jsonld=[{
                  "@context": "https://schema.org", "@type": "Dataset", "name": "ImpactLine: U.S. public laws and their federal trail",
                  "description": "Recent U.S. public laws with Federal Register citation counts and spending tagged to each law by the U.S. Treasury.",
                  "url": site.url + "/data/", "license": "https://creativecommons.org/publicdomain/zero/1.0/", "dateModified": site.asof_laws,
                  "creator": {"@type": "Organization", "name": "ImpactLine", "url": site.url + "/"},
                  "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": site.url + "/data/laws.csv"},
                                   {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": site.url + "/data/laws.json"}]}])
    site.page("/404.html", "Page not found", "That page does not exist.",
              f'<h1>Page not found</h1><p class="lede">That address is not part of the record.</p><p><a class="btn primary" href="{site.href("/laws/")}">Search the laws</a></p>',
              listed=False)

    # ---------------------------------------------------------------------------------------- feed + crawler files
    entries = "".join(
        f"<entry><title>Public Law {r['law']['id']}: {E(clip(r['law']['title'], 200))}</title><id>{E(site.url)}/laws/{r['law']['id']}/</id>"
        f'<link href="{E(site.url)}/laws/{r["law"]["id"]}/"/><updated>{r["law"]["approved"]}T00:00:00Z</updated>'
        f"<summary>Approved {human_date(r['law']['approved'])}. {E(clip(r['law']['official_title'], 240))}</summary></entry>" for r in recs[:40])
    site.write("feed.xml", f'<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom"><title>ImpactLine: new public laws</title>'
               f'<id>{E(site.url)}/</id><link href="{E(site.url)}/laws/"/><link rel="self" href="{E(site.url)}/feed.xml"/>'
               f"<updated>{E(site.asof_laws)}</updated><author><name>ImpactLine</name></author>{entries}</feed>\n")
    key = open(os.path.join(ROOT, "config", "indexnow-key.txt")).read().strip()
    site.write(f"{key}.txt", key + "\n")
    if site.indexable:
        site.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(
            f"<url><loc>{E(u)}</loc><lastmod>{E(d)}</lastmod></url>\n" for u, d in site.urls) + "</urlset>\n")
        site.write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {site.url}/sitemap.xml\n")
    else:
        site.write("robots.txt", "User-agent: *\nDisallow: /\n")
    site.write("urls.txt", "\n".join(u for u, _ in site.urls) + ("\n" if site.urls else ""))
    site.write("og-jobs.json", json.dumps(site.og_jobs))
    site.write("build.json", json.dumps({"built_at": iso(site.now), "laws": len(recs), "laws_as_of": site.asof_laws, "fr_checked_through": asof_fr,
                                         "fr_oldest_check": oldest_fr, "indexable": site.indexable, "base_url": site.url}, indent=1) + "\n")
    site.write(".nojekyll", "")
    return {"laws": len(recs), "pages": len(recs) + 12 + len(congresses) + len(programs), "indexable": site.indexable,
            "fr_laws": n_fr_laws, "tagged": len(tagged_recs), "named": len(named_recs), "og": len(site.og_jobs)}


def tiles(site, items):
    return '<ul class="grid">' + "".join(
        f'<li><a class="tile" href="{site.href(p)}"><small>{E(a)}</small><b>{E(b)}</b><span>{E(c)}</span></a></li>' for a, b, c, p in items) + "</ul>"


def law_sig_text(r):
    bits = []
    if r["fr_total"]:
        bits.append(f"{r['fr_total']:,} Federal Register documents cite it")
    if r["tagged_ba"]:
        bits.append(f"{money(r['tagged_ba'])} tagged by Treasury")
    return " · ".join(bits)


cfg_aliases = read_json(os.path.join(ROOT, "config", "aliases.json"), {}) or {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=os.path.join(ROOT, "_site"))
    a = ap.parse_args(argv)
    print(json.dumps(build(a.site)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
