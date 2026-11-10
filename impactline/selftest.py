"""Self-test of the live site. Exit 1 if anything a visitor would notice is broken or stale.

  python3 -m impactline.selftest [--site-url URL] [--max-age-hours 60]

Reads only this project's own site. Checks the key pages, a spread of law pages, that each sampled
evidence packet still matches the manifest, that the build is recent, and that the staged or
indexed state on the live site is the one this repository is configured for. Prints `stale=true`
on its own line when the build is older than the limit, so the workflow can start a refresh.
"""
import argparse
import concurrent.futures
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import timedelta

from .common import indexable, load_config, now_utc, parse_iso, site_url


def fetch(url, ua):
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return e.code, b""
        except Exception:
            pass
    return 0, b""


def main(argv=None):
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-url", default=site_url(cfg))
    ap.add_argument("--max-age-hours", type=float, default=60)
    ap.add_argument("--sample", type=int, default=40)
    a = ap.parse_args(argv)
    base, ua = a.site_url.rstrip("/"), cfg["user_agent"]
    problems, stale = [], False

    code, home = fetch(base + "/", ua)
    if code != 200:
        print(f"FAIL home page answered {code}")
        return 1
    want_index = indexable(cfg)
    has_noindex = b'<meta name="robots" content="noindex' in home
    if want_index and has_noindex:
        problems.append("the site is configured as indexable but the live home page is noindex")
    if not want_index and not has_noindex:
        problems.append("the site is configured as staged but the live home page is missing noindex")
    code, body = fetch(base + "/build.json", ua)
    try:
        build = json.loads(body)
        built = parse_iso(build["built_at"])
    except Exception:
        build, built = {}, None
        problems.append(f"build.json did not load (status {code})")
    if built is not None and now_utc() - built > timedelta(hours=a.max_age_hours):
        stale = True
        problems.append(f"the live build is from {build.get('built_at')} (limit {a.max_age_hours:g} hours)")
    if build and build.get("laws", 0) < cfg["min_laws_to_publish"]:
        problems.append(f"only {build.get('laws')} laws on the live site")
    code, body = fetch(base + "/evidence/manifest.json", ua)
    try:
        packets = json.loads(body)["packets"]
    except Exception:
        packets = {}
        problems.append(f"evidence manifest did not load (status {code})")
    ids = sorted(packets, key=lambda i: tuple(map(int, i.split("-"))))
    step = max(1, len(ids) // max(1, a.sample))
    sample = ids[::step][: a.sample] + ids[-5:]
    pages = [base + p for p in ("/laws/", "/spending/", "/federal-register/", "/programs/", "/method/", "/data/", "/about/",
                                "/feed.xml", "/data/laws.csv", "/data/laws.json", "/static/style.css", "/static/app.js",
                                "/og/default.png", "/robots.txt")]
    pages += [f"{base}/laws/{i}/" for i in sample]

    def packet_ok(i):
        c, raw = fetch(f"{base}/evidence/{i}.json", ua)
        return i, c == 200 and hashlib.sha256(raw).hexdigest() == packets[i]["sha256"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda u: (u, fetch(u, ua)), pages))
        digests = list(ex.map(packet_ok, sample))
    for u, (c, body) in results:
        if c != 200:
            problems.append(f"{u} answered {c}")
        elif "/laws/" in u and u.rstrip("/").split("/")[-1] in packets and b"<time datetime=" not in body:
            problems.append(f"{u} carries no check date")
    for i, ok in digests:
        if not ok:
            problems.append(f"evidence packet {i} does not match the manifest")
    if not want_index:
        code, robots = fetch(base + "/robots.txt", ua)
        if b"Disallow: /" not in robots:
            problems.append("staged site's robots.txt does not disallow crawling")
    for p in problems[:40]:
        print("FAIL", p)
    print(f"selftest: {len(results)} URLs and {len(digests)} evidence packets checked, {len(problems)} problems")
    print(f"stale={'true' if stale else 'false'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
