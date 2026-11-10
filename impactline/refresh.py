"""Refresh every source, each one on its own, within a nightly budget.

  python3 -m impactline.refresh                    # what the nightly job runs
  python3 -m impactline.refresh --only laws,fr     # some sources (laws, fr, tagged, named)
  python3 -m impactline.refresh --budget 2000      # read more laws this run (first fill, catch-up)
  python3 -m impactline.refresh --law 117-58       # one law, now
  python3 -m impactline.refresh --check-fresh      # exit 1 if a source has not been read in time

A source that fails keeps its last good files: data/status.json records the error and the last
success, and every page prints each record's own check date, so old numbers never pass as new.
"""
import argparse
import os
import sys
import traceback
from datetime import timedelta

from . import fedreg, laws as laws_mod, spending
from .common import Checks, Http, data_path, iso, load_config, now_utc, parse_iso, read_json, write_json



def status_path():
    return data_path("status.json")


SOURCES = ["laws", "fr", "tagged", "programs", "named"]
# How long a source may go without one successful read before --check-fresh fails the workflow.
MAX_AGE = {"laws": timedelta(days=3), "fr": timedelta(days=3), "tagged": timedelta(days=10), "programs": timedelta(days=10),
           "named": timedelta(days=4)}
LABEL = {"laws": "GovInfo public laws", "fr": "Federal Register citations", "tagged": "USAspending funds tagged by law",
         "programs": "USAspending program traces", "named": "USAspending awards naming a law"}


def run(only=None, budget=None, law=None, force=False, now=None, http=None):
    now = now or now_utc()
    cfg = load_config()
    http = http or Http(cfg)
    status = read_json(status_path(), {}) or {}
    ids = {law} if law else None

    def record(name, fn):
        st = status.get(name, {})
        st["checked_at"] = iso(now)
        try:
            res = fn()
            ok = res.get("ok", True)
            st.update(ok=ok, note=res.get("note", ""), warnings=res.get("errors", [])[:10],
                      error="" if ok else (res.get("errors") or ["source did not answer"])[0])
            if ok:
                st["last_success"] = iso(now)
            if res.get("changed"):
                st["last_changed"] = iso(now)
            if "waiting" in res:
                st["waiting"] = res["waiting"]
        except Exception as e:  # keep the previous files; report and carry on with the other sources
            st.update(ok=False, error=f"{type(e).__name__}: {e}"[:400])
            traceback.print_exc()
        status[name] = st
        print(f"{name}: {'ok' if st.get('ok') else 'FAILED'} {st.get('note') if st.get('ok') else st.get('error')}", flush=True)

    want = [s for s in SOURCES if not only or s in only]
    if "laws" in want:
        record("laws", lambda: laws_mod.refresh(http, cfg, now, force=force))
    all_laws = laws_mod.load()
    if all_laws:
        checks = Checks()
        if "fr" in want:
            record("fr", lambda: fedreg.refresh(http, cfg, all_laws, now, budget=budget, only=ids, checks=checks))
        if "tagged" in want:
            record("tagged", lambda: spending.refresh_tagged(http, cfg, all_laws, now, only=ids, checks=checks, force=force))
        if "programs" in want and not law:
            record("programs", lambda: spending.refresh_programs(http, now, checks=checks, force=force))
        if "named" in want:
            record("named", lambda: spending.refresh_named(http, cfg, all_laws, now, budget=budget, only=ids, checks=checks))
        Checks().save(keep_ids={x["id"] for x in all_laws} | {p["slug"] for p in spending.load_programs()})
    status["http_calls"] = http.calls
    write_json(status_path(), status)
    return status


def check_fresh(now=None):
    now = now or now_utc()
    status = read_json(status_path(), {}) or {}
    bad = []
    for name, age in MAX_AGE.items():
        st = status.get(name, {})
        last = parse_iso(st.get("last_success"))
        if last is None or now - last > age:
            bad.append(f"{LABEL[name]}: last successful read {st.get('last_success', 'never')} (limit {age.days} days); "
                       f"last error: {st.get('error', '')}")
    for b in bad:
        print("STALE", b)
    return not bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated: " + ",".join(SOURCES))
    ap.add_argument("--budget", type=int, help="laws to read per source this run (default: config)")
    ap.add_argument("--law", help="refresh one law by id, such as 117-58")
    ap.add_argument("--force", action="store_true", help="re-read law files and tagged spending even if recently read")
    ap.add_argument("--check-fresh", action="store_true")
    a = ap.parse_args(argv)
    if a.check_fresh:
        return 0 if check_fresh() else 1
    status = run(only=set(filter(None, a.only.split(","))), budget=a.budget, law=a.law, force=a.force)
    # The job fails only when the law list itself could not be read and none is on file.
    return 0 if laws_mod.load() else 1


if __name__ == "__main__":
    sys.exit(main())
