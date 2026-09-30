"""Общие утилиты ОКО: нормализация текста, сопоставление терминов, даты, URL, файлы.

Функции norm_text() и TermMatcher повторены в web/assets/oko-core.js —
при изменении правил их нужно менять в обоих местах (тесты это проверяют).
"""
from __future__ import annotations

import datetime as _dt
import email.utils
import hashlib
import html
import json
import os
import re
import tempfile
import threading
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# ---------------------------------------------------------------- текст

_APOS = re.compile("[ʻʼ‘’`´′ʹ]")
_AR_MARKS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_HE_MARKS = re.compile("[֑-ׇ]")
_COMBINING = re.compile("[̀-ͯ]")
_ZW = re.compile("[​-‏⁠﻿]")
_WS = re.compile(r"\s+")
_AR_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",   # алифы
    "ى": "ي", "ی": "ي", "ئ": "ي",                       # йа
    "ک": "ك",                                                               # кяф
    "ہ": "ه", "ھ": "ه", "ە": "ه", "ة": "ه", "ۃ": "ه",
    "ؤ": "و",
    "ı": "i",                                                                    # турецкая ı
})


def norm_text(s: str) -> str:
    """Нормализация для сопоставления: регистр, диакритика, варианты арабской графики."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.casefold()
    s = _ZW.sub("", s)
    s = _APOS.sub("'", s)
    s = _AR_MARKS.sub("", s)
    s = _HE_MARKS.sub("", s)
    s = s.replace("़", "")  # нукта деванагари
    s = s.translate(_AR_MAP)
    s = unicodedata.normalize("NFD", s)
    s = _COMBINING.sub("", s)
    s = unicodedata.normalize("NFC", s)
    s = _WS.sub(" ", s)
    return s.strip()


def _is_word_char(ch: str) -> bool:
    if not ch:
        return False
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "M", "N") or ch == "'"


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
            or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x2FFFF)


# Приставки, которые в арабском/персидском/иврите пишутся слитно со словом.
_AR_PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال", "و", "ب", "ل", "ف", "ك")
_HE_PREFIXES = ("וה", "שה", "וב", "ול", "ומ", "מה", "ה", "ו", "ב", "ל", "מ", "ש", "כ")


class TermMatcher:
    """Сопоставление нормализованных терминов с текстом.

    Правила (одинаковые в Python и JS):
      * CJK (иероглифы/кана) — вхождение подстроки в любом месте;
      * термин длиной <= 4 символа — только целым словом (ШОС, КНР);
      * иначе — совпадение с начала слова (Узбекистан → Узбекистана, узбекский),
        для арабской графики и иврита допускаются слитные приставки (و، ب، ال…).
    """

    def __init__(self, terms):
        seen = set()
        self.terms = []
        for t in terms:
            n = norm_text(t)
            if n and n not in seen:
                seen.add(n)
                self.terms.append(n)
        # длинные термины первыми — для отчёта о совпадении
        self.terms.sort(key=len, reverse=True)

    def __bool__(self):
        return bool(self.terms)

    def find(self, text: str, normalized: bool = False):
        """Вернуть первый совпавший термин или None."""
        if not self.terms or not text:
            return None
        t = text if normalized else norm_text(text)
        for term in self.terms:
            if _match_term(t, term):
                return term
        return None


def _match_term(text: str, term: str) -> bool:
    start = 0
    cjk = _is_cjk(term[0])
    whole = len(term) <= 4 and not cjk
    while True:
        i = text.find(term, start)
        if i < 0:
            return False
        start = i + 1
        if cjk:
            return True
        end = i + len(term)
        if whole and end < len(text) and _is_word_char(text[end]):
            continue
        if i == 0 or not _is_word_char(text[i - 1]):
            return True
        # слитные приставки арабской графики и иврита
        prefixes = _AR_PREFIXES if "؀" <= term[0] <= "ۿ" else (
            _HE_PREFIXES if "֐" <= term[0] <= "׿" else ())
        for p in prefixes:
            j = i - len(p)
            if j >= 0 and text[j:i] == p and (j == 0 or not _is_word_char(text[j - 1])):
                return True


_TAG = re.compile(r"<[^>]+>")


def strip_html(s: str, limit: int = 0) -> str:
    if not s:
        return ""
    s = _TAG.sub(" ", s)
    s = html.unescape(html.unescape(s)) if "&amp;" in s else html.unescape(s)
    s = s.replace("\xa0", " ")
    s = _WS.sub(" ", s).strip()
    if limit and len(s) > limit:
        cut = s[:limit]
        sp = cut.rfind(" ")
        s = (cut[:sp] if sp > limit * 0.6 else cut).rstrip(",;:—- ") + "…"
    return s


# ---------------------------------------------------------------- язык

_RE_CYR = re.compile("[Ѐ-ӿ]")
_RE_AR = re.compile("[؀-ۿ]")
_RE_HE = re.compile("[֐-׿]")
_RE_HANGUL = re.compile("[가-힯ᄀ-ᇿ]")
_RE_KANA = re.compile("[぀-ヿ]")
_RE_HAN = re.compile("[一-鿿]")
_RE_DEVA = re.compile("[ऀ-ॿ]")
_LAT_HINTS = {
    "en": {"the", "and", "of", "to", "in", "for", "with", "on", "is", "says", "after", "over"},
    "fr": {"le", "la", "les", "des", "du", "et", "une", "pour", "dans", "sur", "avec", "au"},
    "de": {"der", "die", "das", "und", "mit", "für", "von", "ein", "eine", "im", "auf", "nach"},
    "es": {"el", "los", "las", "del", "y", "una", "para", "con", "por", "en", "sobre", "tras"},
    "it": {"il", "della", "delle", "degli", "e", "una", "per", "con", "che", "nel", "sul", "dopo"},
    "tr": {"ve", "bir", "ile", "için", "bu", "da", "de", "olarak", "ile", "yeni", "türkiye"},
    "uz": {"va", "bilan", "uchun", "bu", "haqida", "yil", "oʻzbekiston", "o'zbekiston", "prezident"},
    "pt": {"o", "os", "do", "da", "dos", "das", "e", "um", "uma", "para", "com", "não"},
}


def detect_lang(text: str, hint: str | None = None) -> str | None:
    """Грубое определение языка по письменности и частым словам."""
    if not text:
        return hint
    if _RE_HANGUL.search(text):
        return "ko"
    if _RE_KANA.search(text):
        return "ja"
    if _RE_HAN.search(text):
        return "zh" if hint not in ("ja",) else hint
    if _RE_AR.search(text):
        if re.search("[ٹڈڑںےھ]", text):
            return "ur"
        if hint in ("fa", "ur", "ar"):
            return hint
        if re.search("[پچژگیک]", text):
            return "fa"
        return "ar"
    if _RE_HE.search(text):
        return "he"
    if _RE_DEVA.search(text):
        return "hi"
    if _RE_CYR.search(text):
        low = text.lower()
        if re.search("[ўҳ]", low) or (hint == "uz" and re.search("[қғ]", low)):
            return "uz"
        if re.search("[әұһ]", low) or (hint == "kk" and re.search("[ңөүі]", low)):
            return "kk"
        if re.search("[ҷӣӯ]", low):
            return "tg"
        if hint == "ky" and re.search("[ңөү]", low):
            return "ky"
        if re.search("[іїєґ]", low):
            return "uk"
        return "ru"
    words = set(re.findall(r"[a-zà-ÿʻ'ğışçöü]+", text.lower()))
    best, score = hint, 0
    for lang, hints in _LAT_HINTS.items():
        sc = len(words & hints)
        if sc > score:
            best, score = lang, sc
    if hint and score < 2:
        return hint
    return best or "en"


# ---------------------------------------------------------------- даты

UTC = _dt.timezone.utc
_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$",
    re.I)


def parse_date(value) -> int | None:
    """Разбор даты в Unix-время (UTC). Понимает RFC 822, ISO 8601, GDELT, YYYYMMDD."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = int(value)
        return v // 1000 if v > 10_000_000_000 else v
    s = str(value).strip()
    if not s:
        return None
    m = _ISO.match(s)
    if m:
        y, mo, d, hh, mi, ss, tz = m.groups()
        try:
            dt = _dt.datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0))
        except ValueError:
            return None
        off = 0
        if tz and tz.upper() != "Z":
            sign = -1 if tz[0] == "-" else 1
            digits = tz[1:].replace(":", "")
            off = sign * (int(digits[:2]) * 3600 + int(digits[2:4]) * 60)
        return int(dt.replace(tzinfo=UTC).timestamp()) - off
    m = re.match(r"^(\d{4})(\d{2})(\d{2})T?(\d{2})(\d{2})(\d{2})Z?$", s)  # GDELT 20260929T101500Z
    if m:
        try:
            dt = _dt.datetime(*map(int, m.groups()), tzinfo=UTC)
            return int(dt.timestamp())
        except ValueError:
            return None
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp())
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    # «Mon, 29 Sep 2026 10:00:00 +0300 (MSK)» и прочие вариации
    s2 = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    s2 = re.sub(r"\b(GMT|UTC)([+-]\d{1,2})(?::?(\d{2}))?$", lambda mm: "%s%02d%s" % (
        "+" if mm.group(2)[0] == "+" else "-", abs(int(mm.group(2))), mm.group(3) or "00"), s2)
    if s2 != s:
        return parse_date(s2)
    return None


def utc_iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return _dt.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_to_date(ts: int, fmt: str = "%Y-%m-%d") -> str:
    return _dt.datetime.fromtimestamp(ts, UTC).strftime(fmt)


def now_ts() -> int:
    return int(_dt.datetime.now(UTC).timestamp())


# ---------------------------------------------------------------- URL

_TRACKING = re.compile(
    r"^(utm_|fbclid$|gclid$|yclid$|mc_cid$|mc_eid$|igshid$|ocid$|cmpid$|smid$|ref$|ref_src$|"
    r"__twitter_impression$|at_medium$|at_campaign$|guce_|_ga$|spm$|from$|feature$|rss$|cid$|mbid$|"
    r"sref$|src$|s_cid$|ito$|taid$|dicbo$|traffic_source$)", re.I)


def canonical_url(url: str) -> str:
    """URL без трекинговых параметров, фрагмента, www/m./amp — для дедупликации."""
    if not url:
        return ""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (p.hostname or "").lower()
    for pre in ("www.", "m.", "amp.", "mobile."):
        if host.startswith(pre) and host.count(".") >= 2:
            host = host[len(pre):]
    path = p.path or "/"
    path = re.sub(r"/amp/?$", "/", path)
    path = re.sub(r"/+$", "", path) or "/"
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    q.sort()
    return urlunsplit(("https", host, path, urlencode(q), ""))


def host_of(url: str) -> str:
    try:
        h = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def short_hash(s: str, n: int = 16) -> str:
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:n]


def is_http_url(url: str) -> bool:
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.hostname)


# ---------------------------------------------------------------- файлы

_io_lock = threading.Lock()


def read_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        # повреждённый файл не должен ронять программу — сохраняем копию и начинаем заново
        try:
            os.replace(path, path + ".broken")
        except OSError:
            pass
        return default


def write_json(path: str, data) -> None:
    """Атомарная запись JSON (через временный файл)."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    with _io_lock:
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def safe_filename(s: str, limit: int = 80) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[^\w\-. ]+", "", s, flags=re.U).strip().replace(" ", "_")
    s = re.sub(r"_+", "_", s)
    return (s[:limit] or "file").strip("._") or "file"
