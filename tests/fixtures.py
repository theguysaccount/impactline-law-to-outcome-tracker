"""Synthetic inputs for the tests: invented laws in the real file format, and a scripted HTTP client."""
import io
import json
import zipfile
from urllib.parse import parse_qs, urlsplit

from impactline.common import HttpError


def law_xml(congress, number, approved="2025-03-14", official="To do a thing, and for other purposes.", short=None, parts=(),
            bill=("hr", 35), stat="139 Stat. 7", meta_date=None, sections=2, head_date="MAR. 14, 2025"):
    short_xml = f'<section identifier="/us/pl/{congress}/{number}/s1"><content>This Act may be cited as the “<shortTitle role="act">{short}</shortTitle>”.</content></section>' if short else ""
    parts_xml = "".join(f'<section identifier="/us/pl/{congress}/{number}/d{i}"><content>This division may be cited as the “<shortTitle role="division">{p}</shortTitle>”.</content></section>'
                        for i, p in enumerate(parts))
    extra = "".join(f'<section identifier="/us/pl/{congress}/{number}/s{i + 10}"><content>Text.</content></section>' for i in range(sections))
    stat_xml = f"<citableAs>{stat}</citableAs>" if stat else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<pLaw xmlns="http://schemas.gpo.gov/xml/uslm" xmlns:dc="http://purl.org/dc/elements/1.1/">
<?I50 PUBLIC LAW {congress}–{number}—{head_date}?>
<meta><dc:title>Public Law {congress}–{number}: {official}</dc:title><dc:type>Public Law</dc:type><docNumber>{number}</docNumber>
<citableAs>Public Law {congress}–{number}</citableAs>{stat_xml}
<approvedDate>{meta_date or approved}</approvedDate><congress>{congress}</congress><publicPrivate>public</publicPrivate></meta>
<main><longTitle><docTitle>An Act</docTitle><officialTitle>{official}<sidenote><p><approvedDate date="{approved}">x</approvedDate></p>
<p>[<ref href="/us/bill/{congress}/{bill[0]}/{bill[1]}">B</ref>]</p></sidenote></officialTitle></longTitle>
{short_xml}{parts_xml}{extra}</main></pLaw>""".encode("utf-8")


def law_zip(congress, laws, junk=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for number, kw in laws.items():
            z.writestr(f"PLAW-{congress}publ{number}.xml", law_xml(congress, number, **kw))
        if junk:
            z.writestr(f"PLAW-{congress}publ999.xml", b"<pLaw><broken")
    return buf.getvalue()


class FakeHttp:
    """Answers from a routing function: route(url, body) -> bytes | dict | Exception."""

    def __init__(self, route):
        self.route, self.calls, self.log = route, 0, []

    def request(self, url, body=None, **kw):
        self.calls += 1
        self.log.append((url, body))
        out = self.route(url, body)
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, bytes) else json.dumps(out).encode()

    def json(self, url, body=None, **kw):
        return json.loads(self.request(url, body))


def listing(congress, stamp="01-Jan-2026 10:00", size=1000):
    return {"files": [{"name": f"PLAW-{congress}-public.zip", "link": f"https://www.govinfo.gov/bulkdata/PLAW/{congress}/public/PLAW-{congress}-public.zip",
                       "formattedLastModifiedTime": stamp, "size": size}]}


def fr_doc(n, kind="Rule", date="2025-06-01", agency="Transportation Department"):
    return {"document_number": f"2025-{n:05d}", "title": f"Document {n}", "type": kind, "publication_date": date,
            "html_url": f"https://www.federalregister.gov/documents/2025/06/01/2025-{n:05d}/document-{n}", "agencies": [{"name": agency}]}


def query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def gone(url):
    return HttpError(url, 503)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()
