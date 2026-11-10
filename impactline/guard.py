"""Check a built site before it is published. Exit 1 (and publish nothing) if anything is off.

  python3 -m impactline.guard [_site]

Checks: enough laws; every law has its page, its feed and an evidence packet whose digest matches
the manifest; every law page carries the seven steps, its limits, a source and a check date; every
internal link resolves; and, while the site is staged, every page is noindex and no sitemap exists.
"""
import hashlib
import json
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .common import ROOT, indexable, load_config, site_url
from .laws import load as load_laws

MUST = ["index.html", "404.html", "robots.txt", "urls.txt", "feed.xml", "build.json", "static/style.css", "static/app.js",
        "static/fonts/inter-latin.woff2", "static/favicon-96x96.png", "laws/index.html", "spending/index.html",
        "federal-register/index.html", "programs/index.html", "method/index.html", "about/index.html", "data/index.html",
        "data/laws.csv", "data/laws.json", "evidence/manifest.json", "og/default.png"]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for k in ("href", "src", "data-packet", "data-manifest"):
            if a.get(k):
                self.links.append(a[k])


def check(site_dir):
    cfg = load_config()
    errors = []
    base_path = urlparse(site_url(cfg)).path.rstrip("/")
    staged = not indexable(cfg)
    for f in MUST:
        if not os.path.exists(os.path.join(site_dir, f)):
            errors.append(f"missing {f}")
    laws = load_laws()
    if len(laws) < cfg["min_laws_to_publish"]:
        errors.append(f"only {len(laws)} laws (minimum {cfg['min_laws_to_publish']})")
    try:
        with open(os.path.join(site_dir, "evidence", "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = {"packets": {}}
        errors.append("evidence/manifest.json unreadable")
    for law in laws:
        lid = law["id"]
        page = os.path.join(site_dir, "laws", lid, "index.html")
        packet = os.path.join(site_dir, "evidence", f"{lid}.json")
        if not os.path.exists(page) or not os.path.exists(os.path.join(site_dir, "laws", lid, "feed.xml")):
            errors.append(f"law {lid}: page or feed missing")
            continue
        try:
            with open(packet, "rb") as f:
                raw = f.read()
            json.loads(raw)
            if manifest["packets"].get(lid, {}).get("sha256") != hashlib.sha256(raw).hexdigest():
                errors.append(f"law {lid}: packet digest does not match the manifest")
        except (OSError, ValueError):
            errors.append(f"law {lid}: evidence packet missing or unreadable")
        with open(page, encoding="utf-8") as f:
            html = f.read()
        if html.count('class="stage ') != 7:
            errors.append(f"law {lid}: page does not show the seven steps")
        if 'id="limits"' not in html or "govinfo.gov" not in html or "<time datetime=" not in html:
            errors.append(f"law {lid}: page lacks its limits, its source or a check date")
    if len(manifest.get("packets", {})) != len(laws):
        errors.append(f"manifest lists {len(manifest.get('packets', {}))} packets for {len(laws)} laws")
    if staged:
        if os.path.exists(os.path.join(site_dir, "sitemap.xml")):
            errors.append("staged site must not publish a sitemap")
        with open(os.path.join(site_dir, "robots.txt"), encoding="utf-8") as f:
            if "Disallow: /" not in f.read():
                errors.append("staged site must disallow crawling in robots.txt")
    elif not os.path.exists(os.path.join(site_dir, "sitemap.xml")):
        errors.append("missing sitemap.xml")
    pages = 0
    for dirpath, _, files in os.walk(site_dir):
        for fn in files:
            if not fn.endswith(".html"):
                continue
            pages += 1
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, site_dir).replace(os.sep, "/")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if "<title>" not in text or 'name="description"' not in text or 'rel="canonical"' not in text:
                errors.append(f"{rel}: missing title, description or canonical")
            if staged and '<meta name="robots" content="noindex' not in text:
                errors.append(f"{rel}: staged page is missing noindex")
            if len(re.findall(r"<h1[ >]", text)) != 1:
                errors.append(f"{rel}: expected exactly one h1")
            if rel == "404.html":
                continue
            p = Links()
            p.feed(text)
            for link in p.links:
                u = urlparse(link)
                if u.scheme or link.startswith(("#", "mailto:", "data:", "//")):
                    continue
                target = u.path
                if target.startswith("/"):
                    if base_path and not target.startswith(base_path + "/"):
                        errors.append(f"{rel}: link {link} ignores the site base path")
                        continue
                    target = target[len(base_path):]
                else:
                    target = urlparse(urljoin("file:///" + rel, target)).path
                full = os.path.join(site_dir, target.lstrip("/"))
                if target.endswith("/") or os.path.isdir(full):
                    full = os.path.join(full, "index.html")
                if not os.path.exists(full):
                    errors.append(f"{rel}: broken link {link}")
            if len(errors) > 200:
                return errors, {"pages": pages, "laws": len(laws)}
    return errors, {"pages": pages, "laws": len(laws)}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    site_dir = argv[0] if argv else os.path.join(ROOT, "_site")
    errors, counts = check(site_dir)
    for e in errors[:50]:
        print("GUARD", e)
    print(f"guard: {counts['pages']} pages, {counts['laws']} laws, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
