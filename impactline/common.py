"""Shared helpers: paths, config, time, JSON files, and one polite HTTP client."""
import gzip
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = [os.path.join(ROOT, "data")]   # a one-item list so tests can point the whole pipeline at a temporary folder
CONFIG = os.path.join(ROOT, "config", "site.json")


def data_path(*parts):
    return os.path.join(DATA_DIR[0], *parts)


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def site_url(cfg=None):
    """The one base-URL setting: env SITE_URL (a repository variable in the workflows) or the config default."""
    cfg = cfg or load_config()
    return (os.environ.get("SITE_URL") or cfg["default_url"]).rstrip("/")


def indexable(cfg=None):
    """Staged copies are not indexable. SITE_INDEXABLE=true|false overrides the config."""
    cfg = cfg or load_config()
    env = os.environ.get("SITE_INDEXABLE", "").strip().lower()
    if env in ("true", "false"):
        return env == "true"
    return bool(cfg.get("indexable", False))


def now_utc():
    """Current UTC time. CLOCK_OFFSET_SECONDS (a development aid) is subtracted, for a machine whose clock runs fast."""
    skew = int(os.environ.get("CLOCK_OFFSET_SECONDS", "0") or 0)
    return datetime.fromtimestamp(time.time() - skew, timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def human_date(d):
    """'November 15, 2021' from a date, datetime or 'YYYY-MM-DD' string."""
    if isinstance(d, str):
        d = parse_iso(d if "T" in d else d + "T00:00:00Z")
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, obj, compact=False):
    """Write JSON atomically and only when the content changed, so quiet nights make no commit."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if compact:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except FileNotFoundError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def slugify(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def money(x):
    """$807.7 billion / $4.5 billion / $12.3 million / $8,500. None -> 'not reported'."""
    if x is None:
        return "not reported"
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e12:
        return f"{sign}${x / 1e12:.2f} trillion"
    if x >= 1e9:
        return f"{sign}${x / 1e9:.1f} billion"
    if x >= 1e6:
        return f"{sign}${x / 1e6:.1f} million"
    return f"{sign}${x:,.0f}"


class HttpError(Exception):
    def __init__(self, url, status, detail=""):
        super().__init__(f"{status} for {url} {detail}".strip())
        self.url, self.status = url, status


class Http:
    """GET and JSON POST with an honest User-Agent, a pause between requests to each host, and
    patient retries of 429 and 5xx answers. One instance per run."""

    def __init__(self, cfg=None, sleep=time.sleep, clock=time.monotonic, opener=None):
        cfg = cfg or load_config()
        self.ua = cfg["user_agent"]
        self.pace = cfg.get("pace", {})
        self._next = {}
        self._lock = threading.Lock()
        self._sleep, self._clock = sleep, clock
        self._open = opener or urllib.request.urlopen
        self.calls = 0

    def _wait(self, host):
        with self._lock:
            now = self._clock()
            at = max(now, self._next.get(host, 0.0))
            self._next[host] = at + self.pace.get(host, 0.5)
            self.calls += 1
        if at > now:
            self._sleep(at - now)

    def request(self, url, body=None, timeout=90, retries=4, accept="application/json"):
        host = urlsplit(url).hostname or ""
        data = json.dumps(body).encode() if body is not None else None
        headers = {"User-Agent": self.ua, "Accept": accept, "Accept-Encoding": "gzip"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        last = None
        for attempt in range(retries):
            if attempt:
                self._sleep(min(60, 4 * 2 ** attempt))
            self._wait(host)
            req = urllib.request.Request(url, data=data, headers=headers)
            try:
                with self._open(req, timeout=timeout) as r:
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return raw
            except urllib.error.HTTPError as e:
                last = HttpError(url, e.code)
                if e.code not in (429, 500, 502, 503, 504):
                    raise last
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = HttpError(url, 0, type(e).__name__)
        raise last

    def json(self, url, body=None, **kw):
        return json.loads(self.request(url, body, **kw))


class Checks:
    """When each law's record was last read from each source. One small file changes every night, so
    the per-law data files change only when the data does."""

    def __init__(self):
        self.path = data_path("checked.json")
        self.data = read_json(self.path, {}) or {}

    def get(self, source, law_id):
        return parse_iso(self.data.get(source, {}).get(law_id))

    def text(self, source, law_id):
        return self.data.get(source, {}).get(law_id, "")

    def set(self, source, law_id, when):
        self.data.setdefault(source, {})[law_id] = iso(when)

    def save(self, keep_ids=None):
        if keep_ids is not None:
            for source in self.data:
                self.data[source] = {k: v for k, v in self.data[source].items() if k in keep_ids}
        write_json(self.path, self.data, compact=True)
