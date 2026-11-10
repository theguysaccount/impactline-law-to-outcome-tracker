"""Tell IndexNow search engines which pages exist. Does nothing while the site is staged (noindex).

  python3 -m impactline.indexnow --urls _site/urls.txt
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .common import ROOT, indexable, load_config, site_url


def submit(urls, key, base, ua):
    host = urlparse(base).netloc
    body = json.dumps({"host": host, "key": key, "keyLocation": f"{base}/{key}.txt",
                       "urlList": [u for u in urls if urlparse(u).netloc == host][:10000]}).encode()
    for attempt in range(4):
        if attempt:
            time.sleep(30 * attempt)
        req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": ua})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                print(f"IndexNow: {r.status} for {len(urls)} URLs")
                return r.status
        except urllib.error.HTTPError as e:
            print(f"IndexNow: {e.code} {e.read()[:200]!r}")
            if e.code not in (403, 429) and e.code < 500:
                return e.code
        except Exception as e:
            print(f"IndexNow: {e}")
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", required=True)
    a = ap.parse_args(argv)
    cfg = load_config()
    if not indexable(cfg):
        print("IndexNow: skipped (the site is staged and not indexable)")
        return 0
    with open(a.urls, encoding="utf-8") as f:
        urls = [u.strip() for u in f if u.strip().startswith("http")]
    if not urls:
        print("IndexNow: nothing to submit")
        return 0
    with open(os.path.join(ROOT, "config", "indexnow-key.txt"), encoding="utf-8") as f:
        key = f.read().strip()
    submit(urls, key, site_url(cfg), cfg["user_agent"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
