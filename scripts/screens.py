#!/usr/bin/env python3
"""Save desktop and phone screenshots of the built site to docs/screens/ (a development aid).

  python3 scripts/screens.py [_site]

Serves the build at its real base path and photographs key pages with headless Chrome. Phone shots
load the page in a 390-pixel frame, because headless Chrome will not open a window that narrow.
"""
import functools
import http.server
import os
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from impactline.common import load_config, site_url  # noqa: E402
from impactline.og import find_chrome  # noqa: E402

PAGES = [("home", ""), ("law", "laws/117-58/"), ("law-candidates", "laws/117-169/"), ("laws", "laws/?k=tagged"),
         ("program", "programs/clean-school-bus/"), ("spending", "spending/"), ("method", "method/")]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    site_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_site"))
    chrome = find_chrome()
    if not chrome:
        print("no Chrome found")
        return 1
    base = urlsplit(site_url(load_config())).path.strip("/")
    out = os.path.join(ROOT, "docs", "screens")
    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        web = os.path.join(tmp, "web")
        os.makedirs(web)
        os.symlink(site_dir, os.path.join(web, base))
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=web))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        root = f"http://127.0.0.1:{srv.server_address[1]}/{base}/"
        n = 0
        for name, path in PAGES:
            for kind, size, url in (("desktop", "1280,1500", root + path), ("phone", "560,1700", None)):
                n += 1
                if kind == "phone":
                    frame = os.path.join(web, f"frame{n}.html")
                    with open(frame, "w") as f:
                        f.write(f'<body style="margin:0;background:#888"><iframe src="/{base}/{path}" '
                                f'style="width:390px;height:1700px;border:0;display:block;margin:0 auto"></iframe></body>')
                    url = f"http://127.0.0.1:{srv.server_address[1]}/frame{n}.html"
                png = os.path.join(out, f"{name}-{kind}.png")
                subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                                f"--user-data-dir={os.path.join(tmp, 'p%d' % n)}", f"--window-size={size}",
                                "--virtual-time-budget=6000", f"--screenshot={png}", url],
                               check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("saved", os.path.relpath(png, ROOT))
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
