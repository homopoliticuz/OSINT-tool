"""Реестр источников ОКО: встроенный список (data/sources.json) + пользовательские источники и
правки (data/state/sources_user.json) + состояние обнаружения лент (кэш)."""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from . import htmlmeta
from .feedparse import parse_feed
from .net import FetchError, HttpClient
from .util import now_ts, read_json, write_json

DISCOVERY_TTL = 7 * 86400
ANALYTIC_TYPES = {"think_tank", "intl_org", "official", "media_analytic", "academic", "ratings", "ngo"}
TYPE_LABELS = {
    "think_tank": "Аналитический центр",
    "intl_org": "Международная организация",
    "official": "Официальный источник",
    "agency": "Информационное агентство",
    "media_global": "Издание мирового уровня",
    "media_national": "Национальное издание",
    "media_analytic": "Аналитическое издание",
    "media_regional": "СМИ Центральной Азии",
    "academic": "Научное / академическое",
    "ratings": "Рейтинги и индексы",
    "ngo": "НКО / правозащита",
}


class Registry:
    def __init__(self, sources_path: str, user_path: str, discovery_path: str, http: HttpClient):
        self.sources_path = sources_path
        self.user_path = user_path
        self.discovery_path = discovery_path
        self.http = http
        self.lock = threading.RLock()
        self.discovery = read_json(discovery_path, {}) or {}
        self._disc_dirty = False
        self.progress = {"running": False, "done": 0, "total": 0, "started": 0}
        self.reload()

    # ------------------------------------------------------------ загрузка
    def reload(self):
        base = read_json(self.sources_path, {}) or {}
        user = read_json(self.user_path, {}) or {}
        sources = []
        overrides = user.get("overrides", {})
        for s in base.get("sources", []):
            s = dict(s)
            ov = overrides.get(s["id"])
            if ov:
                for k in ("tier", "off", "name", "type", "country", "note"):
                    if k in ov:
                        s[k] = ov[k]
                s["edited"] = True
            sources.append(s)
        known = {s["id"] for s in sources}
        for s in user.get("added", []):
            if s.get("id") and s["id"] not in known and s.get("domains"):
                s = dict(s)
                s["user"] = True
                sources.append(s)
        with self.lock:
            self.sources = sources
            self.by_id = {s["id"]: s for s in sources}
            self._index = {}
            for s in sources:
                for d in s.get("domains", []):
                    host, _, path = d.lower().partition("/")
                    self._index.setdefault(host, []).append(("/" + path if path else "", s))
            for lst in self._index.values():
                lst.sort(key=lambda x: -len(x[0]))

    def save_user(self, user: dict):
        write_json(self.user_path, user)
        self.reload()

    def user_data(self) -> dict:
        return read_json(self.user_path, {}) or {"overrides": {}, "added": []}

    # ------------------------------------------------------------ поиск по домену
    def lookup(self, url_or_host: str, path: str | None = None):
        if "://" in url_or_host:
            p = urlsplit(url_or_host)
            host, path = (p.hostname or "").lower(), p.path or "/"
        else:
            host, path = url_or_host.lower(), path or "/"
        path = path.lower()
        parts = host.split(".")
        for i in range(len(parts) - 1):
            h = ".".join(parts[i:])
            for pfx, s in self._index.get(h, []):
                if not pfx or path.startswith(pfx):
                    return s
        return None

    # ------------------------------------------------------------ обнаружение лент
    def disc(self, sid: str) -> dict:
        return self.discovery.get(sid) or {}

    def feeds_for(self, s: dict):
        d = self.disc(s["id"])
        feeds = list(d.get("feeds_ok") or [])
        if not feeds:
            feeds = list(s.get("feeds") or []) + list(d.get("feeds") or [])
        bad = set(d.get("feeds_bad") or [])
        out = []
        for f in feeds:
            if f not in bad and f not in out:
                out.append(f)
        return out[:3]

    def wp_api_for(self, s: dict) -> str:
        return self.disc(s["id"]).get("wp_api") or ""

    def needs_discovery(self, s: dict) -> bool:
        d = self.disc(s["id"])
        return not d or now_ts() - d.get("ts", 0) > DISCOVERY_TTL

    def mark_feed(self, sid: str, feed: str, ok: bool):
        with self.lock:
            d = self.discovery.setdefault(sid, {})
            if ok:
                lst = d.setdefault("feeds_ok", [])
                if feed not in lst:
                    lst.append(feed)
                if feed in d.get("feeds_bad", []):
                    d["feeds_bad"].remove(feed)
            else:
                lst = d.setdefault("feeds_bad", [])
                if feed not in lst:
                    lst.append(feed)
                if feed in d.get("feeds_ok", []):
                    d["feeds_ok"].remove(feed)
            self._disc_dirty = True

    def mark_wp(self, sid: str, ok: bool, hard: bool = False):
        with self.lock:
            d = self.discovery.setdefault(sid, {})
            if not ok:
                d["wp_bad"] = d.get("wp_bad", 0) + 1
                if d["wp_bad"] >= 2 or hard:
                    d["wp_api"] = ""
            else:
                d["wp_bad"] = 0
            self._disc_dirty = True

    def request_rediscovery(self, sid: str):
        """Поискать новую ленту источника в фоне (не чаще раза в сутки на источник)."""
        s = self.by_id.get(sid)
        if not s or s.get("off"):
            return False
        with self.lock:
            d = self.discovery.setdefault(sid, {})
            if now_ts() - d.get("redisc", 0) < 86400:
                return False
            d["redisc"] = now_ts()
            self._disc_dirty = True

        def job():
            try:
                self.discover_one(s)
                self.flush()
            except Exception:  # noqa: BLE001 — фоновая попытка, ошибка не критична
                pass
        threading.Thread(target=job, name="oko-rediscover-" + sid, daemon=True).start()
        return True

    def flush(self):
        with self.lock:
            if self._disc_dirty:
                write_json(self.discovery_path, self.discovery)
                self._disc_dirty = False

    def discover_one(self, s: dict, cancel: threading.Event | None = None) -> dict:
        """Открыть главную страницу источника, найти ленты RSS/Atom и REST API WordPress."""
        dom = s["domains"][0]
        host, _, path = dom.partition("/")
        base = "https://%s/%s" % (host if host.count(".") > 1 or host.startswith("www.") else "www." + host, path)
        result = {"ts": now_ts(), "feeds": [], "wp_api": "", "status": "", "error": ""}
        html_text, final = None, base
        for candidate in dict.fromkeys((base, "https://%s/%s" % (host, path))):
            try:
                r = self.http.get(candidate, timeout=12, retries=1, ttl=6 * 3600, cancel=cancel)
                html_text, final = r.text(), r.url
                break
            except FetchError as e:
                result["error"] = e.short()
        if html_text is None:
            result["status"] = "unreachable"
            return self._store_disc(s, result)
        info = htmlmeta.discover(html_text, final)
        result["wp_api"] = info["wp_api"]
        feeds = list(s.get("feeds") or []) + info["feeds"]
        if not feeds:
            feeds = htmlmeta.feed_guesses(final)[:4] if info["wordpress"] else []
        ok = []
        for f in feeds[:5]:
            try:
                r = self.http.get(f, timeout=10, retries=0, ttl=1800, cancel=cancel)
                parsed = parse_feed(r.body, r.url, r.charset())
                if parsed["items"]:
                    ok.append(f)
                    if len(ok) >= 2:
                        break
            except FetchError:
                continue
        result["feeds"] = ok
        result["feeds_ok"] = ok
        result["status"] = "ok" if (ok or result["wp_api"]) else "no_feed"
        result["error"] = ""
        return self._store_disc(s, result)

    def _store_disc(self, s, result):
        with self.lock:
            prev = self.discovery.get(s["id"], {})
            if result["status"] == "unreachable" and prev.get("feeds_ok"):
                # временная недоступность — не забываем рабочие ленты
                prev = dict(prev)
                prev.update({"ts": result["ts"], "status": "unreachable", "error": result["error"]})
                result = prev
            if prev.get("redisc") and "redisc" not in result:
                result["redisc"] = prev["redisc"]
            self.discovery[s["id"]] = result
            self._disc_dirty = True
        return result

    def run_discovery(self, only_stale: bool = True, ids=None, workers: int = 10,
                      cancel: threading.Event | None = None, on_progress=None):
        with self.lock:
            if self.progress["running"]:
                return False
            targets = [s for s in self.sources if not s.get("off")
                       and (ids is None or s["id"] in ids)
                       and (not only_stale or self.needs_discovery(s))]
            self.progress = {"running": True, "done": 0, "total": len(targets), "started": time.time()}

        def job(s):
            if cancel is not None and cancel.is_set():
                return
            try:
                res = self.discover_one(s, cancel)
            except Exception as e:  # noqa: BLE001 — один сбойный источник не должен останавливать обход
                res = {"status": "error", "error": str(e)[:120]}
            with self.lock:
                self.progress["done"] += 1
                if self.progress["done"] % 25 == 0:
                    self.flush()
            if on_progress:
                on_progress(s, res, self.progress)

        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(job, targets))
        finally:
            with self.lock:
                self.progress["running"] = False
            self.flush()
        return True

    # ------------------------------------------------------------ для клиента
    def public(self) -> list:
        out = []
        for s in self.sources:
            d = self.disc(s["id"])
            x = {k: v for k, v in s.items() if k != "feeds"}
            x["channel"] = ("rss" if (d.get("feeds_ok") or s.get("feeds")) else "") + \
                           ("+wp" if d.get("wp_api") else "")
            x["disc_status"] = d.get("status", "")
            x["disc_ts"] = d.get("ts", 0)
            out.append(x)
        return out


def guess_type(name: str, url: str) -> str:
    n = (name or "") + " " + (url or "")
    if re.search(r"(institut|institute|center|centre|centro|zentrum|foundation|fondation|stiftung|fondazione|"
                 r"council|forum|академ|институт|центр|фонд|совет|研究|연구|مركز|مرکز|پژوهش|enstit|merkez|"
                 r"araştırma|vakf|society|chatham|brookings|rand|policy|studies|strateg)", n, re.I):
        return "think_tank"
    if re.search(r"(\.gov|\.gob|\.gouv|\.go\.[a-z]{2}|ministry|министерств|мид|president|президент)", n, re.I):
        return "official"
    if re.search(r"(university|universit|университет|\.edu|\.ac\.)", n, re.I):
        return "academic"
    if re.search(r"(news agency|агентств|agenzia|agence|ajans|通信|통신|وكالة|خبرگزاری)", n, re.I):
        return "agency"
    return "media_national"
