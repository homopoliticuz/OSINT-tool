"""Локальный веб-сервер ОКО: интерфейс + API. Слушает только 127.0.0.1.

Защита: проверка заголовка Host (от DNS-rebinding), токен сессии для всех API (его знает только
страница ОКО), запрет обращений к локальной сети при загрузке внешних страниц.
"""
from __future__ import annotations

import html
import ipaddress
import json
import logging
import mimetypes
import os
import queue
import re
import secrets
import shutil
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import VERSION, htmlmeta, osint, pdfprint, person, query, relevance, tgbot, translate, webdata
from .health import Health
from .lexicon import Languages, Lexicon
from .net import FetchError, HttpClient
from .providers import gnews, reports as rep_provider, social
from .registry import TYPE_LABELS, Registry
from .search import PROVIDERS, SearchJob
from .state import State, public_settings
from .util import is_http_url, norm_text, now_ts

log = logging.getLogger("oko.server")
MAX_BODY = 8 * 1024 * 1024
STATE_DOCS = {"dossier", "history", "ui", "watch"}


class App:
    def __init__(self, root: str, data_dir: str | None = None, fixtures: str | None = None,
                 allow_private: bool = False, port: int = 8765):
        self.root = root
        self.web = os.path.join(root, "web")
        self.data = data_dir or os.path.join(root, "data")
        self.state_dir = os.path.join(self.data, "state")
        self.pdf_dir = os.path.join(data_dir, "pdf") if data_dir else os.path.join(root, "pdf")
        os.makedirs(self.state_dir, exist_ok=True)
        webdata.ensure(root)
        self.token = secrets.token_urlsafe(24)
        self.port = port
        self.http = HttpClient(os.path.join(self.data, "cache", "http"), fixtures=fixtures,
                               allow_private=allow_private)
        self.state = State(self.state_dir)
        self.languages = Languages(os.path.join(root, "data", "languages.json"))
        self.lexicon = Lexicon(os.path.join(root, "data", "lexicon.json"), self.http, self.state.glossary)
        self.registry = Registry(os.path.join(root, "data", "sources.json"),
                                 os.path.join(self.state_dir, "sources_user.json"),
                                 os.path.join(self.data, "cache", "discovery.json"), self.http)
        self.health = Health(os.path.join(self.state_dir, "health.json"))
        self.bot = tgbot.TgBot(self)
        self.lan = False
        self.lan_urls: list[str] = []
        self.sessions: dict[str, float] = {}      # вход с других устройств: сессия → срок действия
        self.login_fails: dict[str, list] = {}
        self.jobs: dict[str, SearchJob] = {}
        self.jobs_lock = threading.Lock()
        self.fixtures = bool(fixtures)

    def start_background(self):
        def worker():
            time.sleep(1.5)
            try:
                self.http.cleanup_cache(10)
            except OSError:
                pass
            if self.state.settings().get("auto_discovery", True):
                self.registry.run_discovery(only_stale=True, workers=16)
        threading.Thread(target=worker, name="oko-discovery", daemon=True).start()
        if not self.fixtures:
            self.bot.start()

    def bootstrap(self) -> dict:
        return {
            "version": VERSION,
            "languages": self.languages.items,
            "providers": [{"id": p[0], "label": p[1], "default": p[4], "modes": sorted(p[5]), "group": p[6]}
                          for p in PROVIDERS],
            "settings": public_settings(self.state.settings()),
            "types": TYPE_LABELS,
            "entities": [{"id": e["id"], "label": e["label"]} for e in self.lexicon.entities if e.get("kind") != "theme"],
            "themes": self.lexicon.themes(),
            "sources": len(self.registry.sources),
            "discovery": self.registry.progress,
            "pdf_browser": bool(pdfprint.find_browser()),
            "data_dir": os.path.abspath(self.data),
            "pdf_dir": os.path.abspath(self.pdf_dir),
            "fixtures": self.fixtures,
            "now": now_ts(),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "OKO"
    protocol_version = "HTTP/1.1"
    app: App = None  # назначается при запуске

    def log_message(self, fmt, *args):  # тихий журнал
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ------------------------------------------------------------ служебное
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        allowed = {"127.0.0.1:%d" % self.app.port, "localhost:%d" % self.app.port, "[::1]:%d" % self.app.port}
        if host in allowed:
            return True
        if not self.app.lan:
            return False
        # доступ из домашней сети — только по IP-адресу (защита от подмены DNS)
        name, _, port = host.rpartition(":")
        if port != str(self.app.port):
            return False
        try:
            ip = ipaddress.ip_address(name.strip("[]"))
        except ValueError:
            return False
        return ip.is_private or ip.is_loopback or ip.is_link_local

    def _local_client(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _session_ok(self) -> bool:
        if self._local_client():
            return True
        c = self.headers.get("Cookie") or ""
        m = re.search(r"(?:^|;\s*)oko_s=([A-Za-z0-9_\-]+)", c)
        if not m:
            return False
        exp = self.app.sessions.get(m.group(1))
        return bool(exp and exp > time.time())

    def _login(self, method: str):
        app = self.app
        if method == "GET":
            return self._send(200, LOGIN_PAGE.replace("{{MSG}}", "").encode("utf-8"), "text/html; charset=utf-8",
                              {"Cache-Control": "no-store"})
        ip = self.client_address[0]
        now = time.time()
        fails = [t for t in app.login_fails.get(ip, []) if now - t < 300]
        if len(fails) >= 5:
            return self._send(429, LOGIN_PAGE.replace("{{MSG}}", "Слишком много попыток — подождите 5 минут.")
                              .encode("utf-8"), "text/html; charset=utf-8")
        n = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(min(n, 4096)).decode("utf-8", "replace"))
        pw = (form.get("password") or [""])[0]
        real = app.state.settings().get("lan_password") or ""
        if real and len(real) >= 8 and secrets.compare_digest(pw.encode(), real.encode()):
            sid = secrets.token_urlsafe(32)
            app.sessions[sid] = now + 30 * 86400
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", "oko_s=%s; Path=/; Max-Age=2592000; HttpOnly; SameSite=Strict" % sid)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        fails.append(now)
        app.login_fails[ip] = fails
        return self._send(401, LOGIN_PAGE.replace("{{MSG}}", "Неверный пароль.").encode("utf-8"),
                          "text/html; charset=utf-8")

    def _token_ok(self, qs) -> bool:
        tok = self.headers.get("X-OKO-Token") or (qs.get("t") or [""])[0]
        return bool(tok) and secrets.compare_digest(tok, self.app.token)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _err(self, code: int, msg: str):
        self._json({"error": msg}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("слишком большой запрос")
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    # ------------------------------------------------------------ маршрутизация
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        if not self._host_ok():
            return self._send(421, "Недопустимый адрес".encode(), "text/plain; charset=utf-8")
        parts = urlsplit(self.path)
        path, qs = unquote(parts.path), parse_qs(parts.query)
        try:
            if path == "/login" and self.app.lan:
                return self._login(method)
            if not self._session_ok() and not path.startswith("/assets/") and path != "/favicon.ico":
                if path.startswith("/api/"):
                    return self._err(401, "нужен вход: откройте ОКО заново")
                self.send_response(303)
                self.send_header("Location", "/login")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            if method in ("GET", "HEAD") and (path == "/" or path == "/index.html"):
                return self._index()
            if method in ("GET", "HEAD") and path.startswith("/assets/"):
                return self._static(path[len("/assets/"):])
            if path == "/favicon.ico":
                return self._static("favicon.svg")
            if not self._token_ok(qs):
                return self._err(403, "нет доступа: перезагрузите страницу ОКО")
            if path == "/reader" and method == "GET":
                return self._reader(qs)
            if path.startswith("/files/pdf/") and method in ("GET", "HEAD"):
                return self._pdf_file(path[len("/files/pdf/"):])
            if path.startswith("/api/"):
                return self._api(method, path[5:], qs)
            return self._err(404, "не найдено")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return None
        except ValueError as e:
            return self._err(400, str(e))
        except Exception as e:  # noqa: BLE001
            log.error("request failed: %s", traceback.format_exc())
            try:
                return self._err(500, "внутренняя ошибка: %s" % e)
            except OSError:
                return None

    # ------------------------------------------------------------ статические файлы
    def _index(self):
        with open(os.path.join(self.app.web, "index.html"), "rb") as f:
            body = f.read().decode("utf-8")
        body = body.replace('<meta name="oko-token" content="">',
                            '<meta name="oko-token" content="%s">' % self.app.token, 1)
        self._send(200, body.encode("utf-8"), "text/html; charset=utf-8",
                   {"Cache-Control": "no-store",
                    "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' "
                    "https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' "
                    "https://www.wikidata.org https://api.gdeltproject.org https://api.openalex.org; "
                    "frame-src 'self'; base-uri 'none'; form-action 'none'"})

    def _static(self, rel: str):
        rel = rel.split("?")[0]
        base = os.path.realpath(os.path.join(self.app.web, "assets"))
        p = os.path.realpath(os.path.join(base, rel))
        if not p.startswith(base + os.sep) or not os.path.isfile(p):
            return self._err(404, "не найдено")
        ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
        if p.endswith(".webmanifest"):
            ctype = "application/manifest+json"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        if p.endswith(".js"):
            ctype = "text/javascript; charset=utf-8"
        with open(p, "rb") as f:
            self._send(200, f.read(), ctype, {"Cache-Control": "no-cache"})

    def _pdf_file(self, name: str):
        if not re.fullmatch(r"[\w\-.]+\.pdf", name):
            return self._err(404, "не найдено")
        p = os.path.join(self.app.pdf_dir, name)
        if not os.path.isfile(p):
            return self._err(404, "файл не найден")
        with open(p, "rb") as f:
            self._send(200, f.read(), "application/pdf",
                       {"Content-Disposition": "inline; filename*=UTF-8''%s" % quote(name)})

    # ------------------------------------------------------------ API
    def _api(self, method: str, route: str, qs):
        app = self.app
        if route == "health":
            return self._json({"ok": True, "version": VERSION, "discovery": app.registry.progress})
        if route == "bootstrap":
            return self._json(app.bootstrap())
        if route == "sources" and method == "GET":
            return self._json({"sources": app.registry.public(), "types": TYPE_LABELS,
                               "progress": app.registry.progress})
        if route == "sources/user":
            if method == "GET":
                return self._json(app.registry.user_data())
            data = self._body()
            user = {"overrides": data.get("overrides") or {}, "added": data.get("added") or []}
            for s in user["added"]:
                s["domains"] = [d.lower().replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
                                for d in s.get("domains", []) if d]
            app.registry.save_user(user)
            return self._json({"ok": True, "count": len(app.registry.sources)})
        if route == "sources/discover" and method == "POST":
            data = self._body()
            ids = set(data.get("ids") or []) or None
            threading.Thread(target=app.registry.run_discovery,
                             kwargs={"only_stale": bool(data.get("only_stale")), "ids": ids}, daemon=True).start()
            return self._json({"ok": True})
        if route == "sources/progress":
            return self._json(app.registry.progress)
        if route == "sources/health":
            if method == "GET":
                return self._json({"channels": app.health.snapshot()})
            data = self._body()
            app.health.reset(data.get("key") or None)
            return self._json({"ok": True})
        if route == "expand" and method == "POST":
            return self._json(self._expand(self._body()))
        if route == "glossary":
            if method == "GET":
                return self._json(app.state.glossary())
            data = self._body()
            g = app.state.glossary()
            key = norm_text(data.get("topic", ""))
            if not key:
                raise ValueError("пустая тема")
            entry = g.setdefault(key, {})
            lang = data.get("lang")
            terms = [str(t).strip() for t in (data.get("terms") or []) if str(t).strip()][:10]
            if terms:
                entry[lang] = terms
            else:
                entry.pop(lang, None)
            if not entry:
                g.pop(key, None)
            app.state.put_doc("glossary", g)
            return self._json({"ok": True})
        if route == "search" and method == "POST":
            return self._search(self._body())
        if route == "search/stop" and method == "POST":
            data = self._body()
            with app.jobs_lock:
                job = app.jobs.get(data.get("job", ""))
            if job:
                job.cancel.set()
            return self._json({"ok": bool(job)})
        if route == "article" and method == "GET":
            return self._json(self._article((qs.get("url") or [""])[0]))
        if route == "article" and method == "POST":
            data = self._body()
            terms = [str(t)[:120] for t in (data.get("terms") or []) if str(t).strip()][:400]
            ctx_terms = [str(t)[:120] for t in (data.get("ctx") or []) if str(t).strip()][:100]
            return self._json(self._article(str(data.get("url") or ""), terms, ctx_terms))
        if route == "resolve" and method == "GET":
            url = (qs.get("url") or [""])[0]
            return self._json({"url": gnews.resolve(app.http, url) if gnews.is_gnews(url) else url})
        if route == "reports" and method == "GET":
            return self._json({"reports": app.state.list_reports()})
        if route.startswith("reports/"):
            rid = route[len("reports/"):]
            if method == "DELETE":
                return self._json({"ok": app.state.delete_report(rid)})
            rep = app.state.load_report(rid)
            return self._json(rep) if rep else self._err(404, "отчёт не найден")
        if route.startswith("state/"):
            name = route[len("state/"):]
            if name not in STATE_DOCS:
                return self._err(404, "не найдено")
            if method == "GET":
                return self._json(app.state.get_doc(name, None))
            app.state.put_doc(name, self._body())
            return self._json({"ok": True})
        if route == "settings":
            if method == "GET":
                return self._json(public_settings(app.state.settings()))
            return self._json(public_settings(app.state.update_settings(self._body())))
        if route == "translate" and method == "POST":
            data = self._body()
            texts = [str(t)[:5000] for t in (data.get("texts") or [])][:120]
            src = str(data.get("from") or "auto")
            if src not in app.languages.by_code and src not in ("zh-Hant", "uk", "kk", "uz", "auto"):
                src = "auto"
            return self._json(translate.translate_many(app.http, texts, data.get("to") or "ru", src=src,
                                                       deepl_key=app.state.settings().get("deepl_key", "")))
        if route == "translate/article" and method == "POST":
            return self._json(self._translate_article(str(self._body().get("url") or "")))
        if route == "person/search" and method == "GET":
            q = (qs.get("q") or [""])[0]
            return self._json({"candidates": person.search(app.http, q, (qs.get("lang") or ["ru"])[0])})
        if route.startswith("person/") and method == "GET":
            return self._json(person.profile(app.http, route[len("person/"):]))
        if route == "osint" and method == "POST":
            return self._json(osint.analyze(app.http, str(self._body().get("value") or "")[:300], app.registry))
        if route == "social" and method == "GET":
            st = app.state.settings()
            q = (qs.get("q") or [""])[0]
            return self._json({"platforms": social.platforms(), "channels": social.telegram_channels(st),
                               "default_channels": [c["id"] for c in social.data()["telegram_channels"]],
                               "keys": {"vk": bool(st.get("vk_token")), "x": bool(st.get("x_bearer")),
                                        "brave": bool(st.get("brave_key")),
                                        "gcse": bool(st.get("gcse_key") and st.get("gcse_cx")),
                                        "youtube": bool(st.get("youtube_key"))},
                               "links": social.search_links(q) if q else []})
        if route == "catalog/reports" and method == "GET":
            return self._json(rep_provider.catalog())
        if route == "bot/status":
            return self._json(dict(app.bot.status(), lan=", ".join(app.lan_urls) if app.lan else ""))
        if route == "bot/restart" and method == "POST":
            return self._json({"ok": app.bot.restart(), **app.bot.status()})
        if route == "pdf" and method == "POST":
            return self._json(self._pdf(self._body()))
        if route == "cache/clear" and method == "POST":
            shutil.rmtree(os.path.join(app.data, "cache", "http"), ignore_errors=True)
            os.makedirs(os.path.join(app.data, "cache", "http"), exist_ok=True)
            app.http._mem.clear()
            return self._json({"ok": True})
        return self._err(404, "неизвестный запрос")

    # ------------------------------------------------------------ расширение запроса
    def _expand(self, data: dict) -> dict:
        return query.expand_query(self.app, data)

    # ------------------------------------------------------------ поиск (поток событий)
    def _search(self, params: dict):
        app = self.app
        for k in ("t_from", "t_to", "plan", "langs"):
            if k not in params:
                raise ValueError("не хватает параметра %s" % k)
        if int(params["t_to"]) <= int(params["t_from"]):
            raise ValueError("конец периода раньше начала")
        job = SearchJob(app, params)
        with app.jobs_lock:
            for jid in [j for j, x in app.jobs.items() if x.done.is_set()]:
                app.jobs.pop(jid, None)
            app.jobs[job.id] = job
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        job.start()
        try:
            while True:
                try:
                    ev = job.events.get(timeout=12)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                payload = json.dumps(ev["data"], ensure_ascii=False)
                self.wfile.write(("event: %s\ndata: %s\n\n" % (ev["type"], payload)).encode("utf-8"))
                self.wfile.flush()
                if ev["type"] == "done":
                    break
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            job.cancel.set()

    # ------------------------------------------------------------ глубокая проверка статьи
    def _article(self, url: str, terms=None, ctx_terms=None) -> dict:
        app = self.app
        if not is_http_url(url):
            raise ValueError("некорректная ссылка")
        real, resolved = url, False
        if gnews.is_gnews(url):
            r = gnews.resolve(app.http, url)
            if not r:
                return {"ok": False, "error": "не удалось раскрыть ссылку Google News — откройте материал по ссылке",
                        "url": url}
            real, resolved = r, True
        try:
            resp = app.http.get(real, ttl=86400, timeout=15, retries=1, max_bytes=4_000_000)
        except FetchError as e:
            return {"ok": False, "error": "страница недоступна: %s" % e.short(), "url": real, "resolved": resolved}
        ctype = resp.content_type.lower()
        if "pdf" in ctype:
            return {"ok": True, "url": real, "final_url": resp.url, "resolved": resolved, "kind": "pdf",
                    "authors": [], "canonical": "", "credits": []}
        if terms:
            rd = htmlmeta.extract_readable(resp.text(), resp.url)
            meta = rd["meta"]
            meta["mentions"] = relevance.mention_stats(rd["blocks"], meta.get("title", ""),
                                                       meta.get("description") or meta.get("lead") or "",
                                                       terms, ctx_terms)
        else:
            meta = htmlmeta.extract_meta(resp.text(), resp.url)
        meta.update(ok=True, url=real, final_url=resp.url, resolved=resolved)
        s = app.registry.lookup(meta["canonical"] or resp.url)
        meta["canonical_source"] = s["id"] if s else ""
        return meta

    # ------------------------------------------------------------ перевод статьи
    def _fetch_readable(self, url: str):
        app = self.app
        if not is_http_url(url):
            raise ValueError("некорректная ссылка")
        real = gnews.resolve(app.http, url) if gnews.is_gnews(url) else url
        if not real:
            return None, url, "не удалось раскрыть ссылку Google News"
        try:
            resp = app.http.get(real, ttl=86400, timeout=15, retries=1, max_bytes=4_000_000)
        except FetchError as e:
            return None, real, "страница недоступна: %s" % e.short()
        return htmlmeta.extract_readable(resp.text(), resp.url), resp.url, ""

    def _translate_article(self, url: str) -> dict:
        data, real, err = self._fetch_readable(url)
        if not data or not data["blocks"]:
            return {"ok": False, "error": err or "основной текст извлечь не удалось (платный доступ или защита сайта)",
                    "url": real}
        key = self.app.state.settings().get("deepl_key", "")
        title = data["meta"].get("title") or ""
        src = (data["meta"].get("lang") or "auto").split("-")[0].lower() or "auto"
        blocks, engine = translate.translate_blocks(self.app.http, data["blocks"], "ru", key, src=src)
        ttl_tr = translate.translate_one(self.app.http, title, "ru", src, deepl_key=key)[0] if title else ""
        return {"ok": True, "url": real, "title": title, "title_tr": ttl_tr, "blocks": blocks, "engine": engine,
                "lang": data["meta"].get("lang") or "", "truncated": len(blocks) < len(data["blocks"])}

    # ------------------------------------------------------------ режим чтения
    def _reader(self, qs):
        app = self.app
        url = (qs.get("url") or [""])[0]
        if not is_http_url(url):
            return self._send(400, "Некорректная ссылка".encode(), "text/plain; charset=utf-8")
        data, real, err = self._fetch_readable(url)
        tr = (qs.get("tr") or [""])[0] == "ru"
        engine = ""
        if tr and data and data["blocks"]:
            key = app.state.settings().get("deepl_key", "")
            data["blocks"], engine = translate.translate_blocks(app.http, data["blocks"], "ru", key)
            t0 = data["meta"].get("title") or ""
            if t0:
                data["meta"]["title_tr"] = translate.translate_one(app.http, t0, "ru", deepl_key=key)[0]
        body = render_reader(real or url, data, err, {k: (qs.get(k) or [""])[0] for k in
                                                     ("title", "source", "date", "status", "tier", "authors")},
                             translated=engine)
        self._send(200, body.encode("utf-8"), "text/html; charset=utf-8",
                   {"Cache-Control": "no-store",
                    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline' "
                    "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src data:; "
                    "script-src 'unsafe-inline'"})

    def _pdf(self, data: dict) -> dict:
        app = self.app
        url = data.get("url", "")
        if not is_http_url(url):
            raise ValueError("некорректная ссылка")
        mode = data.get("mode", "original")
        target = url
        if mode in ("reader", "reader_ru"):
            target = "http://127.0.0.1:%d/reader?t=%s&url=%s" % (app.port, app.token, quote(url, safe=""))
            if mode == "reader_ru":
                target += "&tr=ru"
            for k in ("title", "source", "date", "status", "tier", "authors"):
                if data.get(k):
                    target += "&%s=%s" % (k, quote(str(data[k])[:400], safe=""))
        elif gnews.is_gnews(url):
            target = gnews.resolve(app.http, url) or url
        try:
            path = pdfprint.print_to_pdf(target, app.pdf_dir, data.get("title", ""), data.get("source", ""))
        except RuntimeError as e:
            return {"ok": False, "error": str(e), "browser": bool(pdfprint.find_browser())}
        name = os.path.basename(path)
        return {"ok": True, "name": name, "href": "/files/pdf/%s?t=%s" % (quote(name), app.token),
                "path": os.path.abspath(path)}


LOGIN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#090c11">
<title>ОКО — вход</title><link rel="manifest" href="/assets/manifest.webmanifest"><link rel="icon" href="/assets/favicon.svg">
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#090c11;color:#e3e8ee;
font:15px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}form{width:min(340px,90vw);display:grid;gap:12px;padding:26px;
border:1px solid #2a3543;border-radius:6px;background:#11161e}b{letter-spacing:.3em;color:#e3bd4b;font-size:20px}
input{padding:11px;border-radius:4px;border:1px solid #2a3543;background:#0d1117;color:#e3e8ee;font-size:16px}
button{padding:11px;border:0;border-radius:4px;background:#c9a227;color:#111;font-weight:600;letter-spacing:.12em;font-size:15px}
.m{color:#ff9c95;font-size:13px;min-height:1em}.s{color:#7e8997;font-size:12.5px}</style></head><body>
<form method="post" action="/login"><b>ОКО</b><span class="s">Вход с другого устройства домашней сети</span>
<input type="password" name="password" placeholder="пароль" autofocus autocomplete="current-password">
<button type="submit">ВОЙТИ</button><span class="m">{{MSG}}</span></form></body></html>"""


def render_reader(url: str, data, err: str, hint: dict, translated: str = "") -> str:
    e = html.escape
    meta = (data or {}).get("meta") or {}
    title = meta.get("title") or hint.get("title") or url
    if translated and meta.get("title_tr"):
        title = meta["title_tr"]
    rows = []

    def row(k, v):
        if v:
            rows.append("<tr><th>%s</th><td>%s</td></tr>" % (e(k), v))
    row("Издание", e(hint.get("source") or meta.get("site_name") or meta.get("publisher") or ""))
    authors = ", ".join(meta.get("authors") or []) or hint.get("authors", "")
    row("Авторы", e(authors))
    pub = meta.get("published")
    row("Опубликовано", e(time.strftime("%d.%m.%Y %H:%M UTC", time.gmtime(pub)) if pub else hint.get("date", "")))
    row("Статус", e(hint.get("status", "")))
    row("Уровень", e(hint.get("tier", "")))
    row("Ссылка", '<a href="%s">%s</a>' % (e(url), e(url)))
    if meta.get("canonical") and meta["canonical"].rstrip("/") != url.rstrip("/"):
        row("Каноническая ссылка", e(meta["canonical"]))
    row("Дата обращения", e(time.strftime("%d.%m.%Y %H:%M")))
    if translated:
        row("Перевод", e("машинный перевод на русский (%s); заголовок оригинала: %s" % (translated, meta.get("title") or "")))
    parts = []
    for b in (data or {}).get("blocks", []):
        tag = {"h2": "h2", "h3": "h3", "blockquote": "blockquote", "li": "li"}.get(b["k"], "p")
        txt = b.get("tr") or b["t"] if translated else b["t"]
        if tag == "li":
            parts.append("<p class=li>• %s</p>" % e(txt))
        else:
            parts.append("<%s>%s</%s>" % (tag, e(txt), tag))
    text = "\n".join(parts)
    if not text:
        text = '<p class="note">%s</p>' % e(err or "Основной текст извлечь не удалось (платный доступ, "
                                               "динамическая загрузка или защита сайта). Откройте оригинал.")
    lang = "ru" if translated else e(meta.get("lang") or "")
    return READER_TEMPLATE.replace("{{TITLE}}", e(title)).replace("{{ROWS}}", "\n".join(rows)) \
        .replace("{{TEXT}}", text).replace("{{URL}}", e(url)).replace("{{LANG}}", lang or "ru")


READER_TEMPLATE = """<!doctype html>
<html lang="{{LANG}}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}} — ОКО</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=Noto+Serif:wght@400;700&family=Noto+Naskh+Arabic&family=Noto+Sans+SC&family=Noto+Sans+JP&family=Noto+Sans+KR&display=swap">
<style>
:root{--ink:#111418;--mut:#5b6572;--line:#d5dae1;--acc:#8a6d1d}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font:16px/1.65 "Noto Serif",Georgia,"Times New Roman","Noto Naskh Arabic","Noto Sans SC","Noto Sans JP","Noto Sans KR",serif}
.bar{position:sticky;top:0;background:#0f141a;color:#e6eaf0;padding:10px 16px;display:flex;gap:10px;align-items:center;font:14px "IBM Plex Sans",system-ui,sans-serif}
.bar b{letter-spacing:.2em;color:#d4af37}.bar .sp{flex:1}
.bar button,.bar a{background:#1b2430;color:#e6eaf0;border:1px solid #2e3947;padding:6px 12px;border-radius:4px;cursor:pointer;text-decoration:none;font:inherit}
main{max-width:780px;margin:0 auto;padding:28px 20px 60px}
.kicker{font:600 11px "IBM Plex Sans",sans-serif;letter-spacing:.18em;text-transform:uppercase;color:var(--acc)}
h1{font-size:28px;line-height:1.25;margin:8px 0 18px}
table{border-collapse:collapse;width:100%;font:13px/1.45 "IBM Plex Sans",system-ui,sans-serif;margin-bottom:22px}
th{text-align:left;color:var(--mut);font-weight:600;width:170px;padding:5px 10px 5px 0;vertical-align:top;border-top:1px solid var(--line)}
td{padding:5px 0;border-top:1px solid var(--line);word-break:break-word}
a{color:#1f4f8f}
h2,h3{font-family:"IBM Plex Sans",sans-serif;margin:26px 0 8px}
blockquote{margin:14px 0;padding-left:14px;border-left:3px solid var(--line);color:#333}
p.li{margin:4px 0}.note{color:var(--mut);font-style:italic}
footer{margin-top:40px;padding-top:10px;border-top:1px solid var(--line);font:12px "IBM Plex Sans",sans-serif;color:var(--mut)}
[dir=rtl]{text-align:right}
@media print{.bar{display:none}main{padding:0;max-width:none}a{color:var(--ink)}}
</style></head><body>
<div class="bar"><b>ОКО</b><span>режим чтения</span><span class="sp"></span>
<button onclick="window.print()">Печать / PDF</button><a href="{{URL}}" target="_blank" rel="noopener noreferrer">Оригинал ↗</a></div>
<main dir="auto"><div class="kicker">Материал из открытого источника</div><h1>{{TITLE}}</h1>
<table>{{ROWS}}</table>
{{TEXT}}
<footer>Текст извлечён автоматически платформой ОКО для служебного анализа. Правообладатель — издание-источник. Сверяйте с оригиналом: {{URL}}</footer>
</main></body></html>"""
