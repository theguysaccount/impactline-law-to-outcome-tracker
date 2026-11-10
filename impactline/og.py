"""Open Graph share cards (1200x630 PNG), rendered with headless Chrome after impactline.build.

  python3 -m impactline.og [--site _site]

Cards are drawn for the home page, program traces and the laws with a substantial trail. Every other
page uses static/og-default.png. Without Chrome, or if a render fails, the default card is used, so
no page points at a missing image and a Chrome problem never blocks a deploy.
"""
import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
from html import escape as E

from .common import ROOT

CHROMES = [os.environ.get("CHROME", ""), "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
DEFAULT = os.path.join(ROOT, "static", "og-default.png")
FONTS = os.path.join(ROOT, "static", "fonts")
CSS = """
@font-face{font-family:"Inter";font-weight:100 900;src:url("file://%(fonts)s/inter-latin.woff2") format("woff2")}
@font-face{font-family:"Instrument Serif";font-weight:400;src:url("file://%(fonts)s/instrument-serif-latin.woff2") format("woff2")}
*{box-sizing:border-box}html,body{margin:0;width:1200px;height:630px;overflow:hidden}
body{background:#fbfbfa;color:#0d0d0d;font-family:"Inter",Arial,sans-serif;border-top:10px solid #2f56b5;padding:54px 68px;display:flex;flex-direction:column}
.brand{font-family:"Instrument Serif",Georgia,serif;font-size:40px;letter-spacing:-.5px}
.eyebrow{font-size:17px;letter-spacing:.16em;text-transform:uppercase;color:#5a6477;margin-top:44px}
h1{font-family:"Instrument Serif",Georgia,serif;font-weight:400;line-height:1.08;letter-spacing:-1px;margin:14px 0 0;max-height:300px;overflow:hidden}
.sub{font-size:27px;color:#3f4348;margin-top:auto}
.foot{font-size:20px;color:#6b7076;border-top:1px solid #e4e4e1;margin-top:22px;padding-top:18px}
"""


def find_chrome():
    for c in CHROMES:
        if c and (os.path.exists(c) or shutil.which(c)):
            return shutil.which(c) or c
    return None


def render(chrome, title, subtitle, out_png):
    size = 76 if len(title) < 50 else 60 if len(title) < 90 else 48
    html = (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS % {'fonts': FONTS}}h1{{font-size:{size}px}}</style></head><body>"
            f"<div class='brand'>impactline</div><div class='eyebrow'>The public delivery record</div><h1>{E(title)}</h1>"
            f"<div class='sub'>{E(subtitle)}</div><div class='foot'>Official records. Traceable sources. Open questions.</div></body></html>")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "card.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write(html)
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--mute-audio", "--allow-file-access-from-files",
               "--force-device-scale-factor=1", "--window-size=1200,630", f"--user-data-dir={os.path.join(d, 'profile')}",
               "--virtual-time-budget=3000", f"--screenshot={out_png}", "file://" + src]
        subprocess.run(cmd, check=True, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(out_png) and os.path.getsize(out_png) > 1000


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=os.path.join(ROOT, "_site"))
    a = ap.parse_args(argv)
    chrome = find_chrome()
    jobs_path = os.path.join(a.site, "og-jobs.json")
    with open(jobs_path, encoding="utf-8") as f:
        jobs = {j[0]: j for j in json.load(f)}
    os.remove(jobs_path)
    out_dir = os.path.join(a.site, "og")
    os.makedirs(out_dir, exist_ok=True)
    shutil.copyfile(DEFAULT, os.path.join(out_dir, "default.png"))

    def one(job):
        key, title, sub = job
        out = os.path.join(out_dir, key + ".png")
        try:
            if chrome and render(chrome, title, sub, out):
                return 1
        except Exception as e:  # a Chrome hiccup must not stop a deploy
            print(f"og: {key}: {type(e).__name__}")
        shutil.copyfile(DEFAULT, out)
        return 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        made = sum(ex.map(one, jobs.values()))
    print(f"og: {made} rendered, {len(jobs) - made} fell back to the default card")
    return 0


if __name__ == "__main__":
    sys.exit(main())
