import os
import tempfile
import unittest
from datetime import date, datetime, timezone

from impactline import common, laws
from impactline.common import load_config

from .fixtures import FakeHttp, gone, law_xml, law_zip, listing, read

NOW = datetime(2026, 3, 2, 7, 0, tzinfo=timezone.utc)


class ParseTest(unittest.TestCase):
    def test_identity_comes_from_the_laws_own_file(self):
        law = laws.parse_law(law_xml(119, 7, short="Clear Roads Act of 2025", parts=["Safer Bridges Act", "Rural Transit Act"], bill=("s", 240)))
        self.assertEqual((law["id"], law["approved"], law["title"], law["title_source"]), ("119-7", "2025-03-14", "Clear Roads Act of 2025", "law text"))
        self.assertEqual(law["official_title"], "To do a thing, and for other purposes.")
        self.assertEqual(law["stat"], "139 Stat. 7")
        self.assertEqual(law["bill"], {"type": "s", "number": "240", "label": "S. 240", "url": "https://www.congress.gov/bill/119th-congress/senate-bill/240"})
        self.assertEqual(law["parts"], ["Safer Bridges Act", "Rural Transit Act"])
        self.assertEqual(law["sections"], 5)
        self.assertEqual(law["links"]["pdf"], "https://www.govinfo.gov/content/pkg/PLAW-119publ7/pdf/PLAW-119publ7.pdf")
        self.assertEqual(len(law["xml_sha256"]), 64)

    def test_title_falls_back_to_congress_gov_then_to_the_official_title(self):
        xml = law_xml(119, 8)
        self.assertEqual(laws.parse_law(xml, {"119-8": "Popular Name Act"})["title_source"], "Congress.gov")
        law = laws.parse_law(xml)
        self.assertEqual((law["title"], law["title_source"]), ("To do a thing, and for other purposes.", "official title"))

    def test_placeholder_date_is_replaced_from_the_running_head_or_the_law_is_refused(self):
        law = laws.parse_law(law_xml(118, 53, approved="2024-05-07", meta_date="0001-01-01", head_date="MAY 7, 2024"))
        self.assertEqual((law["approved"], law["approved_from"]), ("2024-05-07", "running head"))
        with self.assertRaises(ValueError):
            laws.parse_law(law_xml(118, 54, meta_date="0001-01-01", head_date="SOMEDAY"))
        with self.assertRaises(ValueError):  # a date outside the Congress's own term is not believed
            laws.parse_law(law_xml(118, 55, approved="2031-01-01", meta_date="2031-01-01", head_date="JAN. 1, 2031"))

    def test_kinds_follow_the_titles_wording(self):
        k = laws.kind_of
        self.assertEqual(k("Providing for congressional disapproval under chapter 8 of title 5, United States Code, of the rule...", ""), "disapproval")
        self.assertEqual(k("To designate the facility of the United States Postal Service located at 1 Main St as the “A B Post Office”.", ""), "naming")
        self.assertEqual(k("Making consolidated appropriations for the fiscal year ending September 30, 2026.", "Consolidated Appropriations Act, 2026"), "appropriations")
        self.assertEqual(k("Making appropriations for the Legislative Branch.", "Chips and Science Act"), "general")
        self.assertEqual(k("To amend title 38.", "Veterans Benefits Act"), "general")

    def test_congress_arithmetic(self):
        self.assertEqual(laws.congress_of(date(2021, 1, 2)), 116)
        self.assertEqual(laws.congress_of(date(2021, 1, 3)), 117)
        self.assertEqual(laws.congress_of(date(2026, 11, 10)), 119)
        self.assertEqual(laws.window(date(2026, 11, 10), 5), [117, 118, 119])
        self.assertEqual(laws.window(date(2027, 2, 1), 5), [117, 118, 119, 120])
        self.assertEqual([laws.ordinal(n) for n in (117, 121, 122, 123, 111)], ["117th", "121st", "122nd", "123rd", "111th"])

    def test_a_broken_file_in_the_zip_does_not_lose_the_rest(self):
        got, errors = laws.parse_zip(law_zip(119, {1: {}, 2: {"short": "Second Act"}}, junk=True))
        self.assertEqual(sorted(x["id"] for x in got), ["119-1", "119-2"])
        self.assertEqual(len(errors), 1)


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old = common.DATA_DIR[0]
        common.DATA_DIR[0] = self.tmp.name
        self.addCleanup(lambda: common.DATA_DIR.__setitem__(0, self._old))
        self.cfg = dict(load_config(), window_years=1)   # one Congress: the 119th
        self.zips = {119: law_zip(119, {n: {"approved": "2025-03-14"} for n in range(1, 21)})}
        self.stamp = "01-Jan-2026 10:00"

    def route(self, url, body):
        c = 119
        if "/bulkdata/json/" in url:
            return listing(c, self.stamp)
        return self.zips[c]

    def test_downloads_only_when_the_file_changed(self):
        http = FakeHttp(self.route)
        r = laws.refresh(http, self.cfg, NOW)
        self.assertTrue(r["changed"] and r["ok"])
        self.assertEqual(len(laws.load()), 20)
        http2 = FakeHttp(self.route)
        r = laws.refresh(http2, self.cfg, NOW)
        self.assertFalse(r["changed"])
        self.assertEqual(http2.calls, 1, "only the listing is read when the ZIP is unchanged")
        self.stamp = "02-Feb-2026 09:00"
        self.zips[119] = law_zip(119, {n: {} for n in range(1, 23)})
        r = laws.refresh(FakeHttp(self.route), self.cfg, NOW)
        self.assertTrue(r["changed"])
        self.assertEqual(len(laws.load()), 22)

    def test_a_failing_source_keeps_the_last_good_laws(self):
        laws.refresh(FakeHttp(self.route), self.cfg, NOW)
        before = read(laws.laws_path())
        r = laws.refresh(FakeHttp(lambda url, body: gone(url)), self.cfg, NOW)
        self.assertFalse(r["ok"])
        self.assertTrue(r["errors"])
        self.assertEqual(read(laws.laws_path()), before)

    def test_a_file_that_suddenly_lost_laws_is_not_trusted(self):
        laws.refresh(FakeHttp(self.route), self.cfg, NOW)
        self.stamp = "03-Mar-2026 09:00"
        self.zips[119] = law_zip(119, {1: {}, 2: {}})
        r = laws.refresh(FakeHttp(self.route), self.cfg, NOW)
        self.assertEqual(len(laws.load()), 20)
        self.assertTrue(any("kept the last good set" in e for e in r["errors"]))

    def test_first_run_with_no_source_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            laws.refresh(FakeHttp(lambda url, body: gone(url)), self.cfg, NOW)

    def test_laws_are_sorted_newest_first(self):
        self.zips[119] = law_zip(119, {1: {"approved": "2025-03-14"}, 2: {"approved": "2026-01-20", "head_date": "JAN. 20, 2026"}, 3: {"approved": "2025-07-04"}})
        laws.refresh(FakeHttp(self.route), self.cfg, NOW)
        self.assertEqual([x["id"] for x in laws.load()], ["119-2", "119-3", "119-1"])


if __name__ == "__main__":
    unittest.main()
