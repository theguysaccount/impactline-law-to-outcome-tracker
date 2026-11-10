"""Load the built site in headless Chrome and check the parts that need a browser.

  python3 -m impactline.e2e [_site]

Serves the build at the same path it has on the web, then checks that the law list filters and
sorts, and that a law page's "check this packet" button verifies the packet against the manifest.
Skips (exit 0, with a warning) when no Chrome is installed; GitHub's runners have Chrome.
"""
import functools
import http.server
import os
import re
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit

from .common import ROOT, load_config, site_url
from .laws import load as load_laws
from .og import find_chrome


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def dump(chrome, url, profile):
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--mute-audio", f"--user-data-dir={profile}",
           "--virtual-time-budget=9000", "--dump-dom", url]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    site_dir = os.path.abspath(argv[0] if argv else os.path.join(ROOT, "_site"))
    chrome = find_chrome()
    if not chrome:
        print("::warning::e2e skipped: no Chrome found")
        return 0
    base = urlsplit(site_url(load_config())).path.strip("/")
    laws = load_laws()
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        web = os.path.join(tmp, "web")
        os.makedirs(web)
        if base:
            os.makedirs(os.path.dirname(os.path.join(web, base)), exist_ok=True)
            os.symlink(site_dir, os.path.join(web, base))
        else:
            os.rmdir(web)
            os.symlink(site_dir, web)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=web))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        root = f"http://127.0.0.1:{srv.server_address[1]}/{base + '/' if base else ''}"
        try:
            n = 0

            def page(path):
                nonlocal n
                n += 1
                return dump(chrome, root + path, os.path.join(tmp, f"profile{n}"))

            law = laws[len(laws) // 3]
            html = page("laws/?c=%d" % law["congress"])
            want = sum(1 for x in laws if x["congress"] == law["congress"])
            m = re.search(r'id="count"[^>]*>([\d,]+) laws? of ([\d,]+)', html)
            if not m or int(m.group(1).replace(",", "")) != want or int(m.group(2).replace(",", "")) != len(laws):
                problems.append(f"law list: Congress filter shows {m.group(0) if m else 'no count'}, expected {want} of {len(laws)}")
            shown = len(re.findall(r'<li data-t=', html)) - len(re.findall(r'<li data-t=[^>]*class="hidden"', html))
            if shown != want:
                problems.append(f"law list: {shown} rows visible under the Congress filter, expected {want}")
            html = page("laws/?q=public+law+%s" % law["id"])
            m = re.search(r'id="count"[^>]*>([\d,]+) laws?', html)
            if not m or int(m.group(1).replace(",", "")) < 1 or int(m.group(1).replace(",", "")) > 12:
                problems.append(f"law list: search for the law number gave {m.group(1) if m else 'no count'} rows")
            html = page("laws/?s=fr")
            first = re.search(r'<ul class="lawlist" id="lawlist"><li [^>]*data-fr="(\d+)"', html)
            top = max((int(x) for x in re.findall(r'data-fr="(\d+)"', html)), default=0)
            if not first or int(first.group(1)) != top:
                problems.append("law list: sorting by Federal Register documents did not put the largest first")
            html = page(f"laws/{law['id']}/#verify-now")
            if "Match. This packet" not in html:
                problems.append(f"law {law['id']}: in-browser packet check did not report a match")
        finally:
            srv.shutdown()
    for p in problems:
        print("E2E", p)
    print(f"e2e: list filter, search, sort and packet verification checked in Chrome; {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
