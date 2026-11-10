"""Weekly, gentle check of outbound source links. Report-only.

  python3 -m impactline.linkcheck [--sample 45]

Checks every program-guide link and a date-seeded sample of law, Federal Register and award links,
one request a second. Government sites often refuse automated requests (401/403/429): those are
reported as "refused", never as broken, and nothing here tries to get around a refusal. The job
fails only if most GovInfo links are broken, which would mean the address pattern changed.
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

from . import fedreg, spending
from .common import load_config, now_utc, read_json
from .laws import load as load_laws


def probe(url, ua):
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": ua, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code in (405, 501) and method == "HEAD":
                continue
            return e.code
        except Exception:
            if method == "GET":
                return 0
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=45)
    a = ap.parse_args(argv)
    cfg = load_config()
    laws = load_laws()
    rng = random.Random(now_utc().strftime("%G-%V"))   # the same sample all week, a new one each week
    links = []
    for p in spending.load_programs():
        links += [("program guide", g["url"]) for g in p["guides"] + p.get("state_guides", [])]
    picked = rng.sample(laws, min(len(laws), a.sample))
    for law in picked[: a.sample // 3]:
        links.append(("GovInfo", law["links"]["pdf"]))
    for law in picked[a.sample // 3:]:
        fr = fedreg.load(law["id"]) or {}
        if fr.get("latest"):
            links.append(("Federal Register", fr["latest"][0]["u"]))
        tagged = read_json(spending.tagged_path(law["id"])) or {}
        if tagged.get("awards"):
            links.append(("USAspending", tagged["awards"][0]["url"]))
    seen, results = set(), []
    for kind, url in links:
        if url in seen or not url.startswith("http"):
            continue
        seen.add(url)
        code = probe(url, cfg["user_agent"])
        state = "ok" if 200 <= code < 400 else "refused" if code in (401, 403, 429) else "broken" if code in (404, 410) else "unreachable"
        results.append((kind, url, code, state))
        time.sleep(1.0)
    lines = ["| Source | Result | Link |", "|---|---|---|"]
    for kind, url, code, state in results:
        if state != "ok":
            lines.append(f"| {kind} | {state} ({code}) | {url} |")
            print(f"::warning::{kind} link {state} ({code}): {url}")
    counts = {s: sum(1 for r in results if r[3] == s) for s in ("ok", "refused", "broken", "unreachable")}
    summary = f"Link check: {len(results)} links, " + ", ".join(f"{v} {k}" for k, v in counts.items())
    print(summary)
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"### {summary}\n\n" + ("\n".join(lines) + "\n" if len(lines) > 2 else "All sampled links answered.\n"))
    print(json.dumps(counts))
    gov = [r for r in results if r[0] == "GovInfo"]
    return 1 if gov and sum(1 for r in gov if r[3] == "broken") > len(gov) / 2 else 0


if __name__ == "__main__":
    sys.exit(main())
