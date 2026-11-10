import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from impactline import common, evidence, fedreg, refresh, spending
from impactline.common import Checks, HttpError, load_config

from .fixtures import FakeHttp, fr_doc, gone, query, read

NOW = datetime(2026, 3, 2, 7, 0, tzinfo=timezone.utc)


def law(n, approved="2025-03-14", title=None, congress=119, **kw):
    base = {"id": f"{congress}-{n}", "congress": congress, "number": n, "approved": approved, "title": title or f"Law Number {n} Act",
            "title_source": "law text", "official_title": f"To do thing {n}.", "short_title": title or "", "also_called": "",
            "stat": "139 Stat. 7", "bill": {"type": "hr", "number": str(n), "label": f"H.R. {n}", "url": "https://www.congress.gov/x"},
            "parts": [], "sections": 3, "kind": "general", "xml_sha256": "a" * 64, "xml_bytes": 100,
            "links": {"details": "https://www.govinfo.gov/app/details/PLAW-119publ1", "pdf": "https://www.govinfo.gov/p.pdf",
                      "text": "https://www.govinfo.gov/t.htm", "xml": "https://www.govinfo.gov/x.xml"}}
    base.update(kw)
    return base


class TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old = common.DATA_DIR[0]
        common.DATA_DIR[0] = self.tmp.name
        self.addCleanup(lambda: common.DATA_DIR.__setitem__(0, old))
        self.cfg = load_config()


class FedRegTest(TempData):
    def route(self, docs, count=None, facets=None):
        def r(url, body):
            if "/facets/" in url:
                return (facets or {})[url.split("/facets/")[1].split("?")[0]]
            return {"count": len(docs) if count is None else count, "results": [d for d in docs], "next_page_url": None}
        return r

    def test_search_term_covers_the_three_citation_styles(self):
        self.assertEqual(fedreg.term(law(58, congress=117)), '"Public Law 117-58" | "Pub. L. 117-58" | "P.L. 117-58"')
        self.assertIn("federalregister.gov/documents/search?", fedreg.search_url(law(58)))

    def test_record_is_built_from_the_documents_themselves(self):
        docs = [fr_doc(1, "Rule", "2026-02-01"), fr_doc(2, "Notice", "2025-08-01", "Energy Department"), fr_doc(3, "Proposed Rule", "2025-05-01")]
        http = FakeHttp(self.route(docs))
        rec = fedreg.fetch(http, law(1), NOW)
        self.assertEqual((rec["total"], rec["complete"]), (3, True))
        self.assertEqual(rec["by_type"], {"Rule": 1, "Proposed Rule": 1, "Notice": 1})
        self.assertEqual(rec["by_year"], {"2025": 2, "2026": 1})
        self.assertEqual((rec["first"], rec["last"]), ("2025-05-01", "2026-02-01"))
        self.assertEqual([d["k"] for d in rec["rules"]], ["Rule", "Proposed Rule"])
        self.assertEqual(rec["agencies"][0], ["Transportation Department", 2])
        self.assertEqual(query(http.log[0][0])["conditions[term]"], fedreg.term(law(1)))
        self.assertEqual(http.calls, 1)

    def test_large_sets_take_totals_from_the_apis_own_counts(self):
        facets = {"type": {"RULE": {"count": 900, "name": "Rule"}, "NOTICE": {"count": 4100, "name": "Notice"}},
                  "yearly": {"2025-01-01": {"count": 5000, "name": "2025"}}, "agency": {"x": {"count": 5000, "name": "Energy Department"}}}
        rec = fedreg.fetch(FakeHttp(self.route([fr_doc(i) for i in range(50)], count=5000, facets=facets)), law(1), NOW)
        self.assertEqual((rec["total"], rec["complete"]), (5000, False))
        self.assertEqual(rec["by_type"], {"Rule": 900, "Notice": 4100})
        self.assertEqual(rec["by_year"], {"2025": 5000})
        self.assertEqual(rec["first"], "", "the oldest date is unknown when not every document was read")

    def test_rotation_young_laws_nightly_quiet_laws_fortnightly_within_a_budget(self):
        laws_ = [law(1, approved="2026-01-10"), law(2, approved="2023-01-10"), law(3, approved="2023-01-11")]
        docs = {1: [], 2: [fr_doc(1)], 3: []}

        def route(url, body):
            n = int(query(url)["conditions[term]"].split("-")[1].split('"')[0])
            return {"count": len(docs[n]), "results": docs[n], "next_page_url": None}

        r = fedreg.refresh(FakeHttp(route), self.cfg, laws_, NOW, budget=2)
        self.assertEqual((r["checked"], r["waiting"]), (2, 1), "the budget caps a run and the rest wait")
        fedreg.refresh(FakeHttp(route), self.cfg, laws_, NOW)
        http = FakeHttp(route)
        fedreg.refresh(http, self.cfg, laws_, NOW + timedelta(days=1))
        self.assertEqual(http.calls, 1, "after a day only the young law is due")
        http = FakeHttp(route)
        fedreg.refresh(http, self.cfg, laws_, NOW + timedelta(days=8))
        self.assertEqual(http.calls, 2, "after a week the cited law is due too")
        http = FakeHttp(route)
        fedreg.refresh(http, self.cfg, laws_, NOW + timedelta(days=23))
        self.assertEqual(http.calls, 3)

    def test_unchanged_data_does_not_rewrite_the_law_file_but_the_check_date_moves(self):
        route = self.route([fr_doc(1)])
        one = [law(1, approved="2026-01-10")]
        fedreg.refresh(FakeHttp(route), self.cfg, one, NOW)
        before, mtime = read(fedreg.path("119-1")), os.path.getmtime(fedreg.path("119-1"))
        r = fedreg.refresh(FakeHttp(route), self.cfg, one, NOW + timedelta(days=1))
        self.assertFalse(r["changed"])
        self.assertEqual((read(fedreg.path("119-1")), os.path.getmtime(fedreg.path("119-1"))), (before, mtime))
        self.assertEqual(Checks().text("fr", "119-1"), "2026-03-03T07:00:00Z")

    def test_api_failure_keeps_old_records_and_reports(self):
        one = [law(1, approved="2026-01-10")]
        fedreg.refresh(FakeHttp(self.route([fr_doc(1)])), self.cfg, one, NOW)
        before = read(fedreg.path("119-1"))
        r = fedreg.refresh(FakeHttp(lambda u, b: gone(u)), self.cfg, one, NOW + timedelta(days=2))
        self.assertFalse(r["ok"])
        self.assertEqual(read(fedreg.path("119-1")), before)
        self.assertEqual(Checks().text("fr", "119-1"), "2026-03-02T07:00:00Z", "a failed read does not move the check date")


CODES = {"codes": [
    {"code": "Z", "public_law": "Emergency P.L. 117-58", "title": "Infrastructure Investment and Jobs Act", "disaster": "infrastructure"},
    {"code": "1", "public_law": "Non-emergency P.L. 117-58", "title": "Infrastructure Investment and Jobs Act", "disaster": "infrastructure"},
    {"code": "O", "public_law": "Non-emergency P.L. 116-136|Non-emergency P.L. 117-2", "title": "CARES|ARP", "disaster": "covid_19"},
    {"code": "V", "public_law": "Non-emergency P.L. 117-2", "title": "American Rescue Plan Act of 2021", "disaster": "covid_19"},
    {"code": "AAL", "public_law": "Emergency P.L. 119-4", "title": "Full-Year Continuing Appropriations and Extensions Act, 2025", "disaster": None},
    {"code": "AAK", "public_law": "Emergency P.L. 118-158", "title": "American Relief Act, 2025", "disaster": None},
    {"code": "AAJ", "public_law": "Emergency P.L. 118-50", "title": "Supplemental", "disaster": None},
    {"code": "Q", "public_law": "Not Designated Nonemergency/Emergency/Disaster/Wildfire Suppression", "title": "x", "disaster": None},
    {"code": "9", "public_law": "DEFC of '9' Indicates that the data for this row is not related to a COVID-19 P.L.", "title": "x", "disaster": None}]}


class SpendingTest(TempData):
    def test_codes_name_laws_and_shared_codes_are_never_credited_to_one_law(self):
        codes = spending.parse_codes(CODES)
        self.assertEqual([c["code"] for c in codes], ["Z", "1", "O", "V", "AAL", "AAK", "AAJ"], "codes that name no law are dropped")
        ex, sh = spending.codes_for(codes, "117-58")
        self.assertEqual(([c["code"] for c in ex], sh), (["Z", "1"], []))
        ex, sh = spending.codes_for(codes, "117-2")
        self.assertEqual(([c["code"] for c in ex], [c["code"] for c in sh]), (["V"], ["O"]))
        self.assertEqual(spending.codes_for(codes, "119-99"), ([], []))

    def test_name_search_only_for_distinctive_unshared_names(self):
        others = [law(2, title="Inflation Reduction Act of 2022"), law(3, title="Consolidated Appropriations Act, 2024"),
                  law(4, title="Water Resources Development Act of 2022"), law(5, title="Water Resources Development Act of 2024"),
                  law(6, title="PACT Act"), law(7, title="To designate a post office.", title_source="official title")]

        def phrases(x):
            return [p["phrase"] for p in spending.search_phrases(x, others)]

        self.assertEqual(phrases(others[0]), ["Public Law 119-2", "Inflation Reduction Act"])
        self.assertEqual(phrases(others[1]), ["Public Law 119-3"], "generic appropriations names are not searched")
        self.assertEqual(phrases(others[2]), ["Public Law 119-4"], "a name shared with another law is not searched")
        self.assertEqual(phrases(others[4]), ["Public Law 119-6"], "a one-word name is too loose")
        self.assertEqual(phrases(others[5]), ["Public Law 119-7"], "official long titles are never used as a name")
        aka = law(8, title="An act to provide for reconciliation.", title_source="Congress.gov", also_called="One Big Beautiful Bill Act")
        self.assertEqual(phrases(aka)[1], "One Big Beautiful Bill Act")

    def route(self, url, body):
        if url.endswith("/references/def_codes/"):
            return CODES
        if "/disaster/overview/" in url:
            return {"funding": [{"def_code": "Z", "amount": 60.0}, {"def_code": "1", "amount": 40.0}], "total_budget_authority": 100.0,
                    "spending": {"award_obligations": 50.0, "award_outlays": 20.0, "total_obligations": 70.0, "total_outlays": 30.0}}
        if "/disaster/agency/spending/" in url:
            return {"results": [{"description": "Department of Transportation", "obligation": 70.0, "outlay": 30.0, "total_budgetary_resources": 100.0}]}
        if "/spending_by_category/cfda/" in url:
            return {"results": [{"code": "20.205", "name": "Highway Planning and Construction", "amount": 44.0}]}
        if "/spending_by_award_count/" in url:
            kw = body["filters"].get("keywords", [""])[0]
            return {"results": {"grants": 12, "contracts": 3} if "Clear Rural Roads" in kw else {"grants": 2} if kw == "Public Law 119-10" else {"grants": 0}}
        if "/spending_by_award/" in url and "keywords" in body["filters"]:
            # USAspending's keyword search is loose: one row names the law, one does not, one cites a longer law number.
            rows = [{"Award ID": "A1", "Recipient Name": "CITY OF X", "Award Amount": 9.0, "Awarding Agency": "DOT",
                     "Description": "ROAD WORK UNDER THE CLEAR  RURAL ROADS ACT OF 2025 " + "AND MORE " * 60, "generated_internal_id": "ASST_NON_A1_069"},
                    {"Award ID": "A2", "Recipient Name": "CITY OF Y", "Award Amount": 8.0, "Awarding Agency": "DOT",
                     "Description": "RURAL ROADS CLEARING", "generated_internal_id": "ASST_NON_A2_069"},
                    {"Award ID": "A3", "Recipient Name": "CITY OF Z", "Award Amount": 7.0, "Awarding Agency": "DOT",
                     "Description": "WORK REQUIRED BY PUBLIC LAW 119-100", "generated_internal_id": "ASST_NON_A3_069"}]
            return {"results": rows if body["filters"]["award_type_codes"] == spending.GROUPS["grants"] else rows[1:]}
        if "/spending_by_award/" in url:
            return {"results": [{"Award ID": "A1", "Recipient Name": "CITY OF X", "Award Amount": 9.0, "Total Outlays": 4.0,
                                 "Awarding Agency": "DOT", "Description": "ROAD WORK " * 60, "generated_internal_id": "ASST_NON_A1_069"}]}
        raise AssertionError(url)

    def test_tagged_totals_are_read_only_for_a_laws_own_codes(self):
        laws_ = [law(58, congress=117, approved="2021-11-15", title="Infrastructure Investment and Jobs Act"), law(2, congress=117, approved="2021-03-11"),
                 law(9)]
        http = FakeHttp(self.route)
        r = spending.refresh_tagged(http, self.cfg, laws_, NOW)
        self.assertTrue(r["ok"])
        rec = json.loads(read(spending.tagged_path("117-58")))
        self.assertEqual(rec["overview"], {"budget_authority": 100.0, "total_obligations": 70.0, "total_outlays": 30.0,
                                           "award_obligations": 50.0, "award_outlays": 20.0})
        self.assertEqual([c["code"] for c in rec["codes"]], ["Z", "1"])
        self.assertIn("def_codes=Z,1", rec["source"])
        self.assertEqual(rec["programs"][0]["listing"], "20.205")
        self.assertLessEqual(len(rec["awards"][0]["description"]), 240)
        arp = json.loads(read(spending.tagged_path("117-2")))
        self.assertEqual(arp["shared_codes"], [{"code": "O", "laws": ["116-136", "117-2"]}])
        self.assertFalse(os.path.exists(spending.tagged_path("119-9")))
        sent = [b["filter"]["def_codes"] for u, b in http.log if "/disaster/agency/spending/" in u]
        self.assertEqual(sorted(sent), [["V"], ["Z", "1"]], "the shared code O is never sent for the American Rescue Plan")
        http2 = FakeHttp(self.route)
        spending.refresh_tagged(http2, self.cfg, laws_, NOW + timedelta(days=2))
        self.assertEqual(http2.calls, 1, "within a week only the code list is re-read")

    def test_one_law_whose_totals_do_not_load_is_a_warning_and_is_asked_once_a_day(self):
        laws_ = [law(58, congress=117, approved="2021-11-15"), law(2, congress=117, approved="2021-03-11")]

        def route(url, body):
            if "/disaster/overview/" in url and "def_codes=V" in url:
                raise HttpError(url, 502)
            return self.route(url, body)

        http = FakeHttp(route)
        r = spending.refresh_tagged(http, self.cfg, laws_, NOW)
        self.assertTrue(r["ok"], "the code list answered; one law failing does not fail the source")
        self.assertEqual(r["checked"], 1)
        self.assertTrue(r["errors"] and r["errors"][0].startswith("117-2:"))
        self.assertTrue(os.path.exists(spending.tagged_path("117-58")))
        self.assertFalse(os.path.exists(spending.tagged_path("117-2")))
        http = FakeHttp(route)
        spending.refresh_tagged(http, self.cfg, laws_, NOW + timedelta(hours=6))
        self.assertFalse(any("/disaster/overview/" in u for u, _ in http.log), "not asked again the same day")
        http = FakeHttp(route)
        spending.refresh_tagged(http, self.cfg, laws_, NOW + timedelta(hours=26))
        self.assertEqual(sum(1 for u, _ in http.log if "def_codes=V" in u), 1, "asked again the next day")

    def test_a_law_that_loses_its_code_loses_its_file(self):
        laws_ = [law(4, approved="2025-03-15", title="Full-Year Continuing Appropriations and Extensions Act, 2025")]
        spending.refresh_tagged(FakeHttp(self.route), self.cfg, laws_, NOW)
        self.assertTrue(os.path.exists(spending.tagged_path("119-4")))
        fewer = {"codes": [c for c in CODES["codes"] if c["code"] != "AAL"]}
        spending.refresh_tagged(FakeHttp(lambda u, b: fewer if u.endswith("/def_codes/") else self.route(u, b)), self.cfg, laws_, NOW)
        self.assertFalse(os.path.exists(spending.tagged_path("119-4")))

    def test_a_citation_must_be_this_exact_law_number(self):
        x = {"congress": 118, "number": 21}
        cite = {"match": "citation", "phrase": "Public Law 118-21"}
        self.assertTrue(spending.mentions("FUNDED UNDER PUBLIC LAW 118-21, SECTION 2", cite, x))
        self.assertTrue(spending.mentions("per P.L. 118-21", cite, x))
        self.assertTrue(spending.mentions("Pub. L. No. 118–21", cite, x))
        self.assertTrue(spending.mentions("FY23 NDAA PUBLIC LAW 118 21 DEC 23", cite, x))
        self.assertFalse(spending.mentions("IMPROVEMENT ACT OF 2025 (PUBLIC LAW 118-210)", cite, x))
        self.assertFalse(spending.mentions("PUBLIC LAW 117-118-21", cite, x))
        self.assertFalse(spending.mentions("INVOICE 118-21", cite, x))
        name = {"match": "name", "phrase": "Coastal Habitat Conservation Act"}
        self.assertTrue(spending.mentions("under the COASTAL  HABITAT-CONSERVATION ACT of 2023", name, x))
        self.assertFalse(spending.mentions("ERADICATING NONNATIVE LIMONIUM IN SAN DIEGO BAY", name, x))

    def test_keyword_candidates_skip_tagged_laws_and_search_from_the_approval_date(self):
        spending.refresh_tagged(FakeHttp(self.route), self.cfg, [law(58, congress=117, approved="2021-11-15")], NOW)
        laws_ = [law(58, congress=117, approved="2021-11-15"), law(10, title="Clear Rural Roads Act of 2025"), law(11, title="Short Act")]
        http = FakeHttp(self.route)
        r = spending.refresh_named(http, self.cfg, laws_, NOW)
        self.assertEqual(r["checked"], 2)
        self.assertFalse(os.path.exists(spending.named_path("117-58")))
        rec = json.loads(read(spending.named_path("119-10")))
        self.assertEqual([(p["phrase"], p["match"], p["counts"]) for p in rec["phrases"]],
                         [("Public Law 119-10", "citation", {}), ("Clear Rural Roads Act", "name", {"grants": 1})],
                         "only descriptions that contain the phrase count; 119-100 is not 119-10")
        self.assertEqual(rec["phrases"][0]["returned"], {"grants": 2}, "what the loose search reported is kept for the record")
        self.assertEqual(rec["phrases"][1]["returned"], {"grants": 12, "contracts": 3})
        self.assertEqual(rec["total"], 1)
        self.assertEqual(rec["phrases"][1]["top"][0]["url"], "https://www.usaspending.gov/award/ASST_NON_A1_069")
        periods = [b["filters"]["time_period"] for u, b in http.log if "award_count" in u]
        self.assertTrue(all(p == [{"start_date": "2025-03-14", "end_date": "2026-03-02"}] for p in periods))
        http = FakeHttp(self.route)
        spending.refresh_named(http, self.cfg, laws_, NOW + timedelta(days=8))
        self.assertEqual({b["filters"]["keywords"][0] for u, b in http.log if "award_count" in u}, {"Public Law 119-10", "Clear Rural Roads Act"},
                         "a law with matches is re-read weekly; a law with none waits four weeks")


class EvidenceTest(TempData):
    def test_steps_are_marked_only_by_what_the_records_support(self):
        fr = {"total": 4, "by_type": {"Rule": 1, "Notice": 3}}
        tagged = {"codes": [{"code": "Z", "designation": "Emergency"}], "overview": {"budget_authority": 1e9, "total_obligations": 6e8,
                                                                                    "total_outlays": 3e8, "award_obligations": 5e8}}
        named = {"total": 7}

        def status(*a):
            return {s["id"]: s["status"] for s in evidence.stages(law(1), *a)}

        bare = status(None, None, None)
        self.assertEqual(bare["law"], "documented")
        self.assertTrue(all(v == "needs-evidence" for k, v in bare.items() if k != "law"))
        full = status(fr, tagged, named)
        self.assertEqual(full, {"law": "documented", "authority": "documented", "agency": "candidates", "state": "needs-evidence",
                                "award": "documented", "payment": "documented", "outcome": "needs-evidence"})
        self.assertEqual(status(fr, None, named)["award"], "candidates")
        self.assertEqual(status(None, None, None)["outcome"], status(fr, tagged, named)["outcome"], "no data ever marks an outcome as documented")

    def test_own_wording_never_alleges_wrongdoing_or_success(self):
        fr = {"total": 4, "by_type": {"Rule": 1, "Notice": 3}}
        text = " ".join(s["summary"] for s in evidence.stages(law(1), fr, None, {"total": 2})) + " ".join(evidence.LIMITS)
        for word in ("fraud", "waste", "abuse", "corrupt", "scandal", "misuse", "delayed", "failed", "succeeded"):
            self.assertNotIn(word, text.lower().replace("anyone did anything wrong", ""))

    def test_packets_are_canonical_and_the_manifest_matches_them(self):
        import hashlib
        common.write_json(fedreg.path("119-1"), {"law": "119-1", "term": "t", "search_url": "u", "total": 1, "by_type": {"Rule": 1},
                                                 "by_year": {"2025": 1}, "agencies": [], "latest": [], "rules": []})
        site = os.path.join(self.tmp.name, "site")
        m = evidence.write_all(site, [law(1), law(2)], Checks(), "https://github.com/x/y", "2026-03-02T07:00:00Z")
        self.assertEqual(sorted(m["packets"]), ["119-1", "119-2"])
        raw = open(os.path.join(site, "evidence", "119-1.json"), "rb").read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), m["packets"]["119-1"]["sha256"])
        self.assertEqual(raw, evidence.canonical(json.loads(raw)), "the file is already in canonical form")
        again = evidence.write_all(site, [law(2), law(1)], Checks(), "https://github.com/x/y", "2026-03-09T07:00:00Z")
        self.assertEqual(again["packets"], m["packets"], "the same data gives the same digests, whatever the build date")
        p = json.loads(raw)
        self.assertEqual((p["federal_register"]["label"], p["spending_tagged_by_law"]), ("candidate-match", None))


class RefreshTest(TempData):
    def test_one_failing_source_does_not_stop_the_others_and_freshness_is_tracked(self):
        common.write_json(common.data_path("laws.json"), {"laws": [law(1, approved="2026-01-10")], "sources": {}})

        def route(url, body):
            if "federalregister.gov" in url:
                return {"count": 0, "results": [], "next_page_url": None}
            return gone(url)

        st = refresh.run(only={"fr", "tagged", "named"}, now=NOW, http=FakeHttp(route))
        self.assertTrue(st["fr"]["ok"])
        self.assertFalse(st["tagged"]["ok"])
        self.assertFalse(st["named"]["ok"])
        self.assertIn("HttpError", st["tagged"]["error"])
        self.assertFalse(refresh.check_fresh(NOW), "sources that never succeeded count as stale")
        for name in refresh.SOURCES:
            st.setdefault(name, {})["last_success"] = "2026-03-02T07:00:00Z"
        common.write_json(refresh.status_path(), st)
        self.assertTrue(refresh.check_fresh(NOW + timedelta(days=1)))
        self.assertFalse(refresh.check_fresh(NOW + timedelta(days=5)))


if __name__ == "__main__":
    unittest.main()
