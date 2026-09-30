"""Сетевой слой ОКО: HTTP-клиент на стандартной библиотеке.

* gzip/deflate, кодировки, лимит размера ответа;
* повторы с паузой, учёт Retry-After, «предохранитель» для перегруженных хостов;
* ограничение параллельности и минимальный интервал запросов к одному хосту;
* кэш ответов в памяти и на диске;
* защита от обращений к локальной сети (SSRF);
* режим фикстур для тестов (ответы источников эмулируются из файлов).
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import http.cookiejar
import ipaddress
import json
import os
import random
import re
import socket
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from .util import parse_date, utc_iso

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/rss+xml,"
              "application/atom+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8,ru;q=0.7",
    "Accept-Encoding": "gzip, deflate",
}

# Особые правила для хостов: параллельность и минимальный интервал между запросами.
HOST_RULES = {
    "news.google.com": {"conc": 2, "gap": 0.6},
    "api.gdeltproject.org": {"conc": 1, "gap": 5.3},
    "www.bing.com": {"conc": 2, "gap": 0.4},
    "www.wikidata.org": {"conc": 4, "gap": 0.05},
    "translate.googleapis.com": {"conc": 3, "gap": 0.15},
    "api.mymemory.translated.net": {"conc": 2, "gap": 0.3},
    "api.openalex.org": {"conc": 2, "gap": 0.2},
}
DEFAULT_CONC = 3


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None, url: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.retry_after = retry_after

    def short(self) -> str:
        if self.status:
            return "HTTP %s" % self.status
        return str(self)


class Response:
    __slots__ = ("url", "status", "headers", "body", "elapsed", "from_cache")

    def __init__(self, url, status, headers, body, elapsed=0.0, from_cache=False):
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body
        self.elapsed = elapsed
        self.from_cache = from_cache

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    def charset(self) -> str | None:
        m = re.search(r"charset=([\w\-:]+)", self.content_type, re.I)
        return m.group(1).strip().lower() if m else None

    def text(self) -> str:
        cs = self.charset()
        head = self.body[:2048]
        if not cs:
            m = re.search(rb"<\?xml[^>]*encoding=[\"']([\w\-]+)", head, re.I) or \
                re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", head, re.I)
            if m:
                cs = m.group(1).decode("ascii", "ignore").lower()
        if self.body.startswith(b"\xef\xbb\xbf"):
            cs = "utf-8"
        for enc in (cs, "utf-8"):
            if not enc:
                continue
            try:
                return self.body.decode(_codec(enc))
            except (LookupError, UnicodeDecodeError):
                continue
        return self.body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text(), strict=False)


def _codec(enc: str) -> str:
    enc = enc.lower().strip()
    return {"gb2312": "gb18030", "gbk": "gb18030", "x-sjis": "shift_jis", "windows-31j": "cp932",
            "ks_c_5601-1987": "cp949", "euc-kr": "cp949", "iso-8859-1": "cp1252", "latin1": "cp1252",
            "utf8": "utf-8", "unicode": "utf-8"}.get(enc, enc)


# ---------------------------------------------------------------- SSRF

def _is_private_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast
            or a.is_reserved or a.is_unspecified or getattr(a, "is_site_local", False))


def check_public_host(host: str) -> None:
    """Запретить обращения к адресам локальной сети. Если DNS недоступен — не мешаем
    (запрос может идти через корпоративный прокси)."""
    if not host:
        raise FetchError("пустой адрес")
    h = host.strip("[]").lower()
    if h in ("localhost",) or h.endswith(".localhost") or h.endswith(".local"):
        raise FetchError("обращение к локальному адресу запрещено")
    try:
        ipaddress.ip_address(h)
        if _is_private_ip(h):
            raise FetchError("обращение к локальному адресу запрещено")
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(h, None)
    except (socket.gaierror, UnicodeError, OSError):
        return
    for info in infos:
        if _is_private_ip(info[4][0]):
            raise FetchError("адрес %s указывает на локальную сеть — запрос отклонён" % host)


class _Redirect(urllib.request.HTTPRedirectHandler):
    """Перенаправления с проверкой адреса на каждом шаге (включая 308)."""

    def __init__(self, allow_private: bool):
        super().__init__()
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        p = urllib.parse.urlsplit(newurl)
        if p.scheme not in ("http", "https"):
            raise FetchError("недопустимое перенаправление: %s" % p.scheme)
        if not self.allow_private:
            check_public_host(p.hostname or "")
        if code in (307, 308):
            m = req.get_method()
            return urllib.request.Request(newurl, data=req.data if m == "POST" else None,
                                          headers=dict(req.headers), method=m,
                                          origin_req_host=req.origin_req_host, unverifiable=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    http_error_308 = urllib.request.HTTPRedirectHandler.http_error_302


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:  # если установлен certifi (часто на macOS) — добавляем его корневые сертификаты
        import certifi  # type: ignore
        ctx.load_verify_locations(certifi.where())
    except Exception:  # noqa: BLE001 — certifi необязателен
        pass
    return ctx


def _decode_cert(pem: str) -> dict:
    """Разобрать PEM-сертификат средствами стандартной библиотеки (субъект, издатель, адреса AIA)."""
    decode = getattr(getattr(ssl, "_ssl", None), "_test_decode_cert", None)
    if not decode:
        return {}
    fd, path = tempfile.mkstemp(suffix=".pem")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(pem)
        return decode(path) or {}
    except (ssl.SSLError, OSError, ValueError):
        return {}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------- фикстуры (тесты)

class FixtureTransport:
    """Эмуляция источников: routes.json связывает регулярное выражение URL с файлом ответа.
    В теле ответа подставляются относительные даты: {{RFC822:-2h}}, {{ISO:-1d}}, {{GDELT:-3h}},
    {{DATE:-1d}}, {{WPGMT:-5h}}."""

    def __init__(self, directory: str):
        self.dir = directory
        with open(os.path.join(directory, "routes.json"), encoding="utf-8") as f:
            self.routes = [(re.compile(r["pattern"]), r) for r in json.load(f)]
        self.log = []

    _PH = re.compile(rb"\{\{(RFC822|ISO|GDELT|DATE|WPGMT):([+-]\d+)([mhd])\}\}")

    def _subst(self, body: bytes) -> bytes:
        """Подстановка дат работает с байтами — файлы могут быть в cp1251, Shift_JIS и т.п."""
        now = time.time()

        def rep(m):
            kind, n, unit = m.group(1).decode(), int(m.group(2)), m.group(3).decode()
            ts = now + n * {"m": 60, "h": 3600, "d": 86400}[unit]
            t = time.gmtime(ts)
            fmt = {"RFC822": "%a, %d %b %Y %H:%M:%S GMT", "ISO": "%Y-%m-%dT%H:%M:%SZ", "GDELT": "%Y%m%dT%H%M%SZ",
                   "WPGMT": "%Y-%m-%dT%H:%M:%S"}.get(kind, "%Y-%m-%d")
            return time.strftime(fmt, t).encode("ascii")
        return self._PH.sub(rep, body)

    def fetch(self, method: str, url: str, data: bytes | None) -> Response:
        self.log.append((method, url))
        for rx, r in self.routes:
            if rx.search(url):
                if r.get("delay"):
                    time.sleep(float(r["delay"]))
                status = int(r.get("status", 200))
                body = b""
                if r.get("file"):
                    with open(os.path.join(self.dir, r["file"]), "rb") as f:
                        body = self._subst(f.read())
                elif "body" in r:
                    body = r["body"].encode("utf-8")
                headers = {"content-type": r.get("content_type", "text/xml; charset=utf-8")}
                if status >= 400:
                    raise FetchError("HTTP %d" % status, status, url)
                return Response(url, status, headers, body)
        raise FetchError("HTTP 404", 404, url)


# ---------------------------------------------------------------- клиент

class _HostGate:
    def __init__(self, conc: int, gap: float):
        self.sem = threading.Semaphore(conc)
        self.gap = gap
        self.lock = threading.Lock()
        self.next_at = 0.0
        self.fail_streak = 0
        self.blocked_until = 0.0


class HttpClient:
    def __init__(self, cache_dir: str | None = None, fixtures: str | None = None,
                 allow_private: bool = False):
        self.cache_dir = cache_dir
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        self.fixtures = FixtureTransport(fixtures) if fixtures else None
        self.allow_private = allow_private
        self._gates: dict[str, _HostGate] = {}
        self._gates_lock = threading.Lock()
        self._mem: dict[str, tuple[float, Response]] = {}
        self._mem_lock = threading.Lock()
        self._cookies = http.cookiejar.CookieJar()
        self._ssl = _ssl_context()
        self._host_ssl: dict[str, ssl.SSLContext] = {}
        self._aia_tried: set[str] = set()
        self.stats = {"requests": 0, "cache_hits": 0, "errors": 0}

    # -- служебное
    def _gate(self, host: str) -> _HostGate:
        with self._gates_lock:
            g = self._gates.get(host)
            if g is None:
                rule = HOST_RULES.get(host, {})
                g = _HostGate(rule.get("conc", DEFAULT_CONC), rule.get("gap", 0.0))
                self._gates[host] = g
            return g

    def block_host(self, host: str, seconds: float):
        """Приостановить обращения к хосту (например, после страницы «я не робот»)."""
        g = self._gate(host)
        g.blocked_until = max(g.blocked_until, time.time() + seconds)

    def host_blocked(self, host: str) -> float:
        """Сколько секунд хост ещё «на паузе» после серии отказов (0 — доступен)."""
        g = self._gates.get(host)
        if not g:
            return 0.0
        return max(0.0, g.blocked_until - time.time())

    def _opener(self):
        handlers = [urllib.request.HTTPCookieProcessor(self._cookies),
                    urllib.request.HTTPSHandler(context=self._ssl),
                    _Redirect(self.allow_private)]
        return urllib.request.build_opener(*handlers)

    def _cache_key(self, method, url, data):
        h = hashlib.sha1()
        h.update(method.encode())
        h.update(url.encode("utf-8", "replace"))
        if data:
            h.update(data)
        return h.hexdigest()

    def _cache_get(self, key: str, ttl: float) -> Response | None:
        if ttl <= 0:
            return None
        now = time.time()
        with self._mem_lock:
            hit = self._mem.get(key)
        if hit and now - hit[0] < ttl:
            r = hit[1]
            return Response(r.url, r.status, r.headers, r.body, 0.0, True)
        if not self.cache_dir:
            return None
        meta_p = os.path.join(self.cache_dir, key[:2], key + ".json")
        try:
            with open(meta_p, encoding="utf-8") as f:
                meta = json.load(f)
            if now - meta["t"] >= ttl:
                return None
            with open(meta_p[:-5] + ".bin", "rb") as f:
                body = f.read()
        except (OSError, ValueError, KeyError):
            return None
        r = Response(meta["url"], meta["status"], meta["headers"], body, 0.0, True)
        with self._mem_lock:
            self._mem[key] = (meta["t"], r)
        return r

    def _cache_put(self, key: str, r: Response) -> None:
        now = time.time()
        with self._mem_lock:
            if len(self._mem) > 1500:
                for k in list(self._mem)[:500]:
                    self._mem.pop(k, None)
            self._mem[key] = (now, r)
        if not self.cache_dir:
            return
        d = os.path.join(self.cache_dir, key[:2])
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, key + ".bin"), "wb") as f:
                f.write(r.body)
            with open(os.path.join(d, key + ".json"), "w", encoding="utf-8") as f:
                json.dump({"t": now, "url": r.url, "status": r.status, "headers": r.headers}, f)
        except OSError:
            pass

    def cleanup_cache(self, max_age_days: float = 10) -> int:
        """Удалить устаревшие файлы кэша."""
        if not self.cache_dir or not os.path.isdir(self.cache_dir):
            return 0
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for root, _dirs, files in os.walk(self.cache_dir):
            for fn in files:
                p = os.path.join(root, fn)
                try:
                    if os.path.getmtime(p) < cutoff:
                        os.unlink(p)
                        removed += 1
                except OSError:
                    pass
        return removed

    # -- основной метод
    def request(self, url: str, *, method: str = "GET", data: bytes | None = None,
                headers: dict | None = None, timeout: float = 15.0, ttl: float = 0,
                max_bytes: int = 6_000_000, retries: int = 2, lang: str | None = None,
                allow_private: bool | None = None, cancel: threading.Event | None = None) -> Response:
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise FetchError("некорректный адрес", url=url)
        host = p.hostname.lower()
        key = self._cache_key(method, url, data)
        cached = self._cache_get(key, ttl)
        if cached:
            self.stats["cache_hits"] += 1
            return cached
        if self.fixtures:
            r = self.fixtures.fetch(method, url, data)
            if ttl > 0:
                self._cache_put(key, r)
            return r
        allow = self.allow_private if allow_private is None else allow_private
        if not allow:
            check_public_host(host)
        gate = self._gate(host)
        blocked = gate.blocked_until - time.time()
        if blocked > 0:
            raise FetchError("источник временно ограничил запросы, пауза ещё %d с" % blocked, 429, url)

        hdrs = dict(DEFAULT_HEADERS)
        if lang:
            hdrs["Accept-Language"] = "%s,%s;q=0.9,en;q=0.6" % (lang, lang.split("-")[0])
        if host.endswith("google.com"):
            hdrs["Cookie"] = "CONSENT=YES+cb; SOCS=CAI"
        if headers:
            hdrs.update(headers)

        attempt = 0
        last_err: FetchError | None = None
        while attempt <= retries:
            if cancel is not None and cancel.is_set():
                raise FetchError("отменено", url=url)
            attempt += 1
            with gate.sem:
                with gate.lock:
                    wait = gate.next_at - time.time()
                    gate.next_at = max(gate.next_at, time.time()) + gate.gap
                if wait > 0:
                    time.sleep(wait)
                t0 = time.time()
                try:
                    try:
                        r = self._do(url, method, data, hdrs, timeout, max_bytes, allow, self._host_ssl.get(host))
                    except FetchError as e:
                        # неполная цепочка сертификатов у сайта: дозагружаем промежуточный сертификат (AIA),
                        # как это делают браузеры; проверка до корневого сертификата системы сохраняется
                        if not getattr(e, "ssl_issuer", False) or host in self._aia_tried:
                            raise
                        self._aia_tried.add(host)
                        ctx = self._aia_context(host, p.port or 443, allow)
                        if ctx is None:
                            raise
                        r = self._do(url, method, data, hdrs, timeout, max_bytes, allow, ctx)
                        self._host_ssl[host] = ctx
                    self.stats["requests"] += 1
                    gate.fail_streak = 0
                    if ttl > 0 and r.status == 200:
                        self._cache_put(key, r)
                    r.elapsed = time.time() - t0
                    return r
                except FetchError as e:
                    self.stats["requests"] += 1
                    last_err = e
            # решение о повторе
            st = last_err.status
            if st in (429, 503):
                gate.fail_streak += 1
                if gate.fail_streak >= 4:
                    gate.blocked_until = time.time() + 600
                    raise FetchError("источник ограничил запросы (HTTP %s), пауза 10 мин" % st, st, url)
                ra = last_err.retry_after if last_err.retry_after is not None else 2.0 * attempt
                if ra > 25:
                    break
                time.sleep(ra + random.uniform(0, 0.6))
                continue
            if st is None or st >= 500:
                time.sleep(0.7 * attempt + random.uniform(0, 0.4))
                continue
            break  # 4xx — повтор бессмысленен
        self.stats["errors"] += 1
        raise last_err or FetchError("неизвестная ошибка", url=url)

    def _aia_context(self, host: str, port: int, allow_private: bool):
        """Контекст TLS с промежуточным сертификатом, загруженным по адресу AIA из сертификата сайта."""
        try:
            leaf = ssl.get_server_certificate((host, port), timeout=10)
        except TypeError:  # Python < 3.10: без таймаута не рискуем
            return None
        except (OSError, ssl.SSLError, ValueError):
            return None
        info = _decode_cert(leaf)
        for u in [x for x in (info.get("caIssuers") or ()) if str(x).startswith(("http://", "https://"))][:2]:
            try:
                if not allow_private:
                    check_public_host(urllib.parse.urlsplit(u).hostname or "")
                body = self._do(u, "GET", None, dict(DEFAULT_HEADERS), 10, 200_000, allow_private).body
            except FetchError:
                continue
            if body.lstrip().startswith(b"-----BEGIN CERTIFICATE"):
                pem = body.decode("ascii", "ignore")
            elif body[:1] == b"\x30":
                try:
                    pem = ssl.DER_cert_to_PEM_cert(body)
                except (ValueError, TypeError):
                    continue
            else:
                continue  # PKCS#7 и прочие форматы не поддерживаем
            ci = _decode_cert(pem)
            if not ci or ci.get("subject") == ci.get("issuer"):
                continue  # самоподписанный сертификат не может стать доверенным корнем
            ctx = _ssl_context()
            try:
                ctx.load_verify_locations(cadata=pem)
            except (ssl.SSLError, ValueError):
                continue
            if hasattr(ssl, "VERIFY_X509_PARTIAL_CHAIN"):
                # промежуточный сертификат — только звено цепочки, доверие по-прежнему от корня системы
                ctx.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
            return ctx
        return None

    def _do(self, url, method, data, hdrs, timeout, max_bytes, allow_private, ssl_ctx=None) -> Response:
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        if ssl_ctx is not None:
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(self._cookies),
                urllib.request.HTTPSHandler(context=ssl_ctx), _Redirect(allow_private))
        elif allow_private == self.allow_private:
            opener = self._opener()
        else:
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(self._cookies),
                urllib.request.HTTPSHandler(context=self._ssl), _Redirect(allow_private))
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            ra = None
            try:
                v = e.headers.get("Retry-After") if e.headers else None
                if v:
                    ra = float(v) if v.strip().isdigit() else max(0.0, (parse_date(v) or 0) - time.time())
            except (TypeError, ValueError):
                ra = None
            raise FetchError("HTTP %d" % e.code, e.code, url, ra) from None
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
                vm = str(getattr(reason, "verify_message", "") or reason)
                err = FetchError("ошибка проверки SSL-сертификата: %s (см. README: «Сертификаты на macOS»)"
                                 % vm[:80], url=url)
                err.ssl_issuer = "issuer" in vm
                raise err from None
            if isinstance(reason, FetchError):
                raise reason from None
            raise FetchError("нет соединения: %s" % _short_reason(reason), url=url) from None
        except FetchError:
            raise
        except (socket.timeout, TimeoutError):
            raise FetchError("превышено время ожидания", url=url) from None
        except (http.client.HTTPException, OSError, ValueError) as e:
            raise FetchError("сбой соединения: %s" % _short_reason(e), url=url) from None
        try:
            chunks, total = [], 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    break
            body = b"".join(chunks)
        except (socket.timeout, TimeoutError):
            raise FetchError("превышено время ожидания при чтении", url=url) from None
        except (http.client.HTTPException, OSError) as e:
            if not chunks:
                raise FetchError("обрыв соединения: %s" % _short_reason(e), url=url) from None
            body = b"".join(chunks)
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
        headers = {k.lower(): v for k, v in resp.headers.items()}
        enc = headers.get("content-encoding", "").lower()
        try:
            if "gzip" in enc or body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body) if total <= max_bytes else _gunzip_partial(body)
            elif "deflate" in enc:
                try:
                    body = zlib.decompress(body)
                except zlib.error:
                    body = zlib.decompress(body, -zlib.MAX_WBITS)
        except (OSError, EOFError, zlib.error):
            pass
        return Response(resp.geturl(), resp.status, headers, body)

    # -- удобные обёртки
    def get(self, url: str, **kw) -> Response:
        return self.request(url, **kw)

    def get_json(self, url: str, **kw):
        return self.request(url, **kw).json()

    def post(self, url: str, data: bytes, **kw) -> Response:
        return self.request(url, method="POST", data=data, **kw)


def _gunzip_partial(body: bytes) -> bytes:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        return d.decompress(body)
    except zlib.error:
        return body


def _short_reason(e) -> str:
    s = str(e)
    s = re.sub(r"^<urlopen error |>$", "", s)
    return s[:140]


__all__ = ["HttpClient", "Response", "FetchError", "check_public_host", "utc_iso"]
