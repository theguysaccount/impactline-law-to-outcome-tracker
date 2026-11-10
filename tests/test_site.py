import csv
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from impactline import build, common, fedreg, guard, og, spending
from impactline.common import Checks

from .fixtures import read
from .test_sources import law

NOW = datetime(2026, 3, 2, 7, 0, tzinfo=timezone.utc)
CHECKED = datetime(2026, 3, 1, 7, 0, tzinfo=timezone.utc)


def doc(n, kind, date):
    return {"n": f"2026-{n:05d}", "t": f"Rule about <thing> & {n}", "k": kind, "d": date, "u": f"https://www.federalregister.gov/d/{n}", "a": ["Energy Department"]}


def seed(n_laws=320):
    """A synthetic record set: mostly quiet laws, one tagged, one named, one much cited."""
    laws_ = [law(i, approved=f"2025-{1 + i % 12:02d}-{1 + i % 27:02d}") for i in range(1, n_laws + 1)]
    laws_[0].update(title="Big Works Act", parts=["Rural Bridges Act", "Clean Buses Act"], kind="general")
    laws_[1].update(title="An act to provide for reconciliation.", title_source="Congress.gov", also_called="Lower Prices Act of 2025")
    laws_[2].update(title="To designate a post office <in> Akron & Canton.", title_source="official title", official_title="To designate a post office <in> Akron & Canton.", kind="naming")
    laws_.append(law(58, congress=117, approved="2021-11-15", title="Infrastructure Investment and Jobs Act"))   # the pilot traces' law
    laws_.sort(key=lambda x: (x["approved"], x["number"]), reverse=True)
    common.write_json(common.data_path("laws.json"), {
        "laws": laws_, "updated_at": "2026-02-27T07:00:00Z",
        "sources": {"119": {"zip": "https://www.govinfo.gov/bulkdata/PLAW/119/public/PLAW-119-public.zip", "modified": "26-Feb-2026 15:10",
                            "retrieved_at": "2026-02-27T07:00:00Z"}}})
    checks = Checks()
    for x in laws_:
        checks.set("fr", x["id"], CHECKED)
        checks.set("named", x["id"], CHECKED)
    common.write_json(fedreg.path("119-1"), {
        "law": "119-1", "term": fedreg.term(law(1)), "search_url": fedreg.search_url(law(1)), "total": 57, "complete": True,
        "by_type": {"Rule": 9, "Proposed Rule": 6, "Notice": 42}, "by_year": {"2025": 30, "2026": 27},
        "agencies": [["Energy Department", 40], ["Transportation Department", 17]], "first": "2025-04-01", "last": "2026-02-20",
        "latest": [doc(i, "Notice" if i % 2 else "Rule", "2026-02-%02d" % (20 - i)) for i in range(8)],
        "rules": [doc(i, "Rule", "2026-02-%02d" % (20 - i)) for i in range(0, 8, 2)]})
    common.write_json(spending.defc_path(), {"codes": [
        {"code": "ZZ", "title": "Big Works Act", "group": "", "parts": [{"designation": "Emergency", "law": "119-1"}]},
        {"code": "OO", "title": "x", "group": "", "parts": [{"designation": "Non-emergency", "law": "119-1"}, {"designation": "Non-emergency", "law": "119-4"}]},
        {"code": "YY", "title": "Relief Act", "group": "", "parts": [{"designation": "Emergency", "law": "119-5"}]}]})   # tagged, but its totals never loaded
    common.write_json(spending.tagged_path("119-1"), {
        "law": "119-1", "codes": [{"code": "ZZ", "designation": "Emergency"}], "shared_codes": [{"code": "OO", "laws": ["119-1", "119-4"]}],
        "source": "https://api.usaspending.gov/api/v2/disaster/overview/?def_codes=ZZ",
        "overview": {"budget_authority": 2.5e9, "total_obligations": 1.5e9, "total_outlays": 0.5e9, "award_obligations": 1.2e9, "award_outlays": 0.4e9},
        "funding_by_code": {"ZZ": 2.5e9}, "agencies": [{"name": "Department of Energy", "obligations": 1.5e9, "outlays": 0.5e9, "budgetary_resources": 2.5e9}],
        "programs": [{"listing": "81.999", "name": "Grid <Upgrade> Grants", "obligations": 9e8}],
        "awards": [{"id": "DE-1", "recipient": "CITY OF <X>", "amount": 4e8, "outlays": 1e8, "agency": "Department of Energy", "description": "GRID WORK",
                    "kind": "grants", "url": "https://www.usaspending.gov/award/ASST_NON_DE1_089"}]})
    checks.set("tagged", "119-1", CHECKED)
    common.write_json(spending.named_path("119-2"), {
        "law": "119-2", "period_start": law(2)["approved"], "total": 15, "phrases": [
            {"phrase": "Public Law 119-2", "match": "citation", "counts": {}, "top": [], "search_url": "https://www.usaspending.gov/search/?keyword=Public%20Law%20119-2"},
            {"phrase": "Lower Prices Act", "match": "name", "counts": {"grants": 12, "contracts": 3}, "search_url": "https://www.usaspending.gov/search/?keyword=Lower%20Prices%20Act",
             "top": [{"id": "G-1", "recipient": "STATE OF Y", "amount": 1e6, "outlays": None, "agency": "HHS", "description": "FUNDED UNDER THE LOWER PRICES ACT",
                      "kind": "grants", "url": "https://www.usaspending.gov/award/ASST_NON_G1_075"}]}]})
    for p in spending.load_programs():
        common.write_json(spending.program_path(p["slug"]), {
            "slug": p["slug"], "law": p["law"], "listing": p["listing"], "codes": ["ZZ"], "listing_name": "Program", "obligations": 3e8,
            "national": {"counts": {"grants": 5}, "awards": []}, "state": {"code": p.get("pilot_state", ""), "counts": {}, "awards": []}})
        checks.set("programs", p["slug"], CHECKED)
    checks.save()
    common.write_json(common.data_path("status.json"), {k: {"ok": True, "last_success": "2026-03-01T07:00:00Z", "note": "ok"} for k in ("laws", "fr", "tagged", "programs", "named")})
    return laws_


class SiteTest(unittest.TestCase):
    def build(self, env=None, n_laws=320):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old = common.DATA_DIR[0]
        common.DATA_DIR[0] = os.path.join(self.tmp.name, "data")
        self.addCleanup(lambda: common.DATA_DIR.__setitem__(0, old))
        clean = {k: v for k, v in os.environ.items() if k not in ("SITE_URL", "SITE_INDEXABLE", "GOATCOUNTER_URL", "ALERTS_URL", "CLOCK_OFFSET_SECONDS")}
        clean.update(env or {})
        for p in (mock.patch.dict(os.environ, clean, clear=True), mock.patch.object(og, "find_chrome", lambda: None)):
            p.start()
            self.addCleanup(p.stop)
        self.laws = seed(n_laws)
        self.out = os.path.join(self.tmp.name, "_site")
        self.summary = build.build(self.out, now=NOW)
        og.main(["--site", self.out])
        return self.out

    def page(self, rel):
        return read(os.path.join(self.out, rel))

    def test_build_passes_its_own_guard_staged_by_default(self):
        self.build()
        errors, counts = guard.check(self.out)
        self.assertEqual(errors, [])
        self.assertEqual(counts["laws"], len(self.laws))
        self.assertFalse(self.summary["indexable"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "sitemap.xml")))
        self.assertEqual(self.page("robots.txt"), "User-agent: *\nDisallow: /\n")
        self.assertEqual(self.page("urls.txt"), "")
        self.assertIn('<meta name="robots" content="noindex, nofollow">', self.page("laws/119-1/index.html"))

    def test_cutover_is_two_settings(self):
        self.build({"SITE_URL": "https://app.example.org", "SITE_INDEXABLE": "true"})
        home = self.page("index.html")
        self.assertIn('<link rel="canonical" href="https://app.example.org/">', home)
        self.assertNotIn("noindex", home)
        self.assertIn('href="/static/style.css"', home)
        self.assertIn("<loc>https://app.example.org/laws/119-1/</loc>", self.page("sitemap.xml"))
        self.assertIn("Sitemap: https://app.example.org/sitemap.xml", self.page("robots.txt"))
        self.assertNotIn("github.io", home + self.page("laws/119-1/index.html"))
        self.assertEqual(guard.check(self.out)[0], [])

    def test_tagged_law_shows_official_figures_with_source_date_and_shared_code_note(self):
        self.build()
        html = self.page("laws/119-1/index.html")
        for figure in ("$2.5 billion", "$1.5 billion", "$500.0 million", "$1.2 billion"):
            self.assertIn(figure, html)
        self.assertIn("(60% of budget authority)", html)
        self.assertIn("api.usaspending.gov/api/v2/disaster/overview/?def_codes=ZZ", html)
        self.assertIn('<time datetime="2026-03-01T07:00:00Z">March 1, 2026</time>', html)
        self.assertIn("fund code <b>OO</b> for Public Laws 119-1, 119-4 together", html)
        self.assertIn("57 Federal Register documents cite Public Law 119-1", html)
        self.assertIn("Rule about &lt;thing&gt; &amp; 0", html)
        self.assertIn("CITY OF &lt;X&gt;", html)
        self.assertNotIn("<thing>", html)
        self.assertEqual(html.count('class="stage documented"'), 4)
        self.assertEqual(html.count('class="stage candidates"'), 1)

    def test_a_tagged_law_whose_totals_did_not_load_is_still_shown_as_tagged(self):
        self.build()
        html = self.page("laws/119-5/index.html")
        self.assertIn("Treasury tags spending to this law with fund code YY", html)
        self.assertIn("did not return the totals", html)
        self.assertNotIn("No fund code ties appropriations to this law", html)
        self.assertNotIn("No award is tagged to this law", html)
        self.assertNotIn("No spending is tagged to this law", html)
        packet = json.loads(self.page("evidence/119-5.json"))
        authority = next(s for s in packet["stages"] if s["id"] == "authority")
        self.assertEqual(authority["status"], "documented")
        self.assertIn("fund code YY", authority["summary"])
        self.assertNotIn("$", authority["summary"], "no amount is invented")

    def test_named_law_is_labelled_candidates_and_never_summed(self):
        self.build()
        html = self.page("laws/119-2/index.html")
        self.assertIn("Commonly called the Lower Prices Act of 2025", html)
        self.assertIn('<span class="chip candidates">Candidates</span>', html)
        self.assertIn("12 grants, 3 contracts", html)
        self.assertIn("They are not added up", html)
        self.assertNotIn("Budget authority tagged", html)
        self.assertNotIn("$1.0 million award total</small><span class=\"desc\">FUNDED UNDER THE LOWER PRICES ACT</span></li></ul>\n<p>Total", html)

    def test_quiet_law_states_its_gaps_plainly(self):
        self.build()
        html = self.page("laws/119-3/index.html")
        self.assertIn("No Federal Register document cites Public Law 119-3 by number", html)
        self.assertIn("No spending is tagged to this law, and no award description names it", html)
        self.assertIn("To designate a post office &lt;in&gt; Akron &amp; Canton.", html)
        self.assertEqual(html.count('class="stage needs-evidence"'), 6)

    def test_every_law_is_listed_and_searchable_by_number_name_alias_and_part(self):
        self.build()
        html = self.page("laws/index.html")
        self.assertEqual(html.count("<li data-t="), len(self.laws))
        row = re.search(r'<li data-t="([^"]*)"[^>]*data-fr="57"', html).group(1)
        for needle in ("119-1", "public law 119-1", "big works act", "rural bridges act", "h.r. 1"):
            self.assertIn(needle, row)
        self.assertIn("lower prices act of 2025", html)
        self.assertEqual(self.page("congress/119/index.html").count("<li data-t="), len(self.laws) - 1)
        self.assertEqual(self.page("congress/117/index.html").count("<li data-t="), 1)

    def test_downloads_and_packets_match_the_pages(self):
        self.build()
        rows = list(csv.DictReader(io.StringIO(self.page("data/laws.csv"))))
        self.assertEqual(len(rows), len(self.laws))
        one = next(r for r in rows if r["public_law"] == "119-1")
        self.assertEqual((one["federal_register_documents"], one["tagged_budget_authority"]), ("57", "2500000000.0"))
        manifest = json.loads(self.page("evidence/manifest.json"))
        raw = open(os.path.join(self.out, "evidence", "119-1.json"), "rb").read()
        self.assertEqual(manifest["packets"]["119-1"]["sha256"], hashlib.sha256(raw).hexdigest())
        packet = json.loads(raw)
        self.assertEqual(packet["spending_tagged_by_law"]["overview"]["budget_authority"], 2.5e9)
        self.assertEqual(packet["federal_register"]["checked_at"], "2026-03-01T07:00:00Z")
        self.assertEqual(packet["awards_naming_the_law"], None)

    def test_program_traces_carry_guides_cautions_and_sources(self):
        self.build()
        for p in spending.load_programs():
            html = self.page(f"programs/{p['slug']}/index.html")
            self.assertIn("Read this before drawing conclusions", html)
            self.assertIn(f"Assistance Listing {p['listing']}", html)
            for g in p["guides"]:
                self.assertIn(g["url"].replace("&", "&amp;"), html)
            self.assertIn("<time datetime=", html)

    def test_guard_refuses_a_shrunken_or_inconsistent_build(self):
        self.build(n_laws=40)
        self.assertTrue(any("minimum" in e for e in guard.check(self.out)[0]))
        self.build()
        with open(os.path.join(self.out, "evidence", "119-5.json"), "a") as f:
            f.write(" ")
        self.assertTrue(any("119-5: packet digest does not match" in e for e in guard.check(self.out)[0]))

    def test_marked_slot_is_off_until_configured(self):
        self.build()
        self.assertNotIn('class="slot"', self.page("laws/119-1/index.html"))
        self.build({"ALERTS_URL": "https://alerts.example.org/"})
        self.assertIn('<aside class="slot" aria-label="Paid service"><small>Paid service</small>', self.page("laws/119-1/index.html"))

    def test_feeds(self):
        self.build()
        self.assertEqual(self.page("feed.xml").count("<entry>"), 40)
        feed = self.page("laws/119-1/feed.xml")
        self.assertEqual(feed.count("<entry>"), 8)
        self.assertIn("Rule about &lt;thing&gt;", feed)


if __name__ == "__main__":
    unittest.main()
