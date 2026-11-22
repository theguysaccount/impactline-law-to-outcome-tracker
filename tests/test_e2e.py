"""The browser check's search expectation must hold for any law, not only the one sampled today.

It used to accept "between 1 and 12 rows" for a search on a law number. A law numbered 118-2 also
matches 118-20 to 118-29 and 118-200 to 118-299, so that bound would have failed the day the sample
landed on a short number. The expectation is now the list's own rule applied to the rows on the page.
"""
import unittest

from impactline import e2e


def rows(*texts):
    """A law list as the page carries it; every second row is hidden, as a filter would leave it."""
    items = ""
    for i, text in enumerate(texts):
        hidden = ' class="hidden"' if i % 2 else ""
        items += f'<li data-t="{text}" data-c="118"{hidden}><a href="#">row</a></li>'
    return f'<ul class="lawlist" id="lawlist">{items}</ul>'


class Matching(unittest.TestCase):
    def test_a_short_law_number_matches_every_number_that_starts_with_it(self):
        html = rows("public law 118-2 an act", "public law 118-20 b", "public law 118-200 c", "public law 118-3 d", "public law 119-2 e")
        self.assertEqual(e2e.matching(html, "public law 118-2"), 3)
        self.assertEqual(e2e.matching(html, "public law 118-200"), 1)
        self.assertEqual(e2e.matching(html, "public law 117-2"), 0)

    def test_every_word_must_appear_and_case_and_spacing_do_not_matter(self):
        html = rows("public law 118-5 clean school bus act", "public law 118-6 school lunch act", "h.r. 7 r&amp;d act")
        self.assertEqual(e2e.matching(html, "  School   ACT "), 2)
        self.assertEqual(e2e.matching(html, "school bus"), 1)
        self.assertEqual(e2e.matching(html, "r&d"), 1, "the page's escaped text is read as the browser reads it")
        self.assertEqual(e2e.matching(html, "bus lunch"), 0)

    def test_hidden_rows_count_too_because_the_rule_is_about_the_data(self):
        html = rows("public law 118-9 x", "public law 118-90 y")     # the second row is hidden by the current filter
        self.assertEqual(e2e.matching(html, "118-9"), 2)


if __name__ == "__main__":
    unittest.main()
