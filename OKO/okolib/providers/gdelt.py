"""GDELT DOC 2.0 — мониторинг мировых СМИ на 65 языках (скользящее окно ~3 месяца).

GDELT индексирует машинный перевод материалов на английский, поэтому в запрос включаются
английские термины и оригинальные формы; оператор sourcelang ограничивает язык публикации.
Ограничение сервиса — не чаще одного запроса в 5 секунд (соблюдается сетевым слоем).
"""
from __future__ import annotations

import json
import re
from functools import partial
from urllib.parse import urlencode

from ..net import FetchError
from ..util import now_ts, parse_date, ts_to_date
from . import Task, make_item, or_group

API = "https://api.gdeltproject.org/api/v2/doc/doc?"
WINDOW = 89 * 86400
PRIORITY = ["ru", "zh", "fa", "ar", "ur", "tr", "ja", "ko", "fr", "de", "es", "it", "he", "hi", "kk", "pt"]

LANG_CODES = {
    "english": "en", "russian": "ru", "french": "fr", "german": "de", "spanish": "es", "italian": "it",
    "korean": "ko", "japanese": "ja", "chinese": "zh", "persian": "fa", "arabic": "ar", "urdu": "ur",
    "turkish": "tr", "hebrew": "he", "hindi": "hi", "kazakh": "kk", "portuguese": "pt", "ukrainian": "uk",
    "uzbek": "uz", "polish": "pl", "dutch": "nl", "romanian": "ro", "azerbaijani": "az", "georgian": "ka",
    "armenian": "hy", "bengali": "bn", "indonesian": "id", "malay": "ms", "thai": "th", "vietnamese": "vi",
    "greek": "el", "czech": "cs", "hungarian": "hu", "swedish": "sv", "norwegian": "no", "danish": "da",
    "finnish": "fi", "bulgarian": "bg", "serbian": "sr", "croatian": "hr", "slovak": "sk", "slovenian": "sl",
    "mongolian": "mn", "pashto": "ps", "tamil": "ta", "telugu": "te", "marathi": "mr", "gujarati": "gu",
}

COUNTRIES = {
    "united states": "US", "united kingdom": "GB", "russia": "RU", "china": "CN", "uzbekistan": "UZ",
    "kazakhstan": "KZ", "kyrgyzstan": "KG", "tajikistan": "TJ", "turkmenistan": "TM", "afghanistan": "AF",
    "iran": "IR", "pakistan": "PK", "india": "IN", "turkey": "TR", "germany": "DE", "france": "FR",
    "italy": "IT", "spain": "ES", "japan": "JP", "south korea": "KR", "north korea": "KP", "korea, south": "KR",
    "saudi arabia": "SA", "united arab emirates": "AE", "qatar": "QA", "israel": "IL", "egypt": "EG",
    "azerbaijan": "AZ", "georgia": "GE", "armenia": "AM", "ukraine": "UA", "belarus": "BY", "poland": "PL",
    "canada": "CA", "australia": "AU", "new zealand": "NZ", "brazil": "BR", "mexico": "MX", "argentina": "AR",
    "switzerland": "CH", "austria": "AT", "belgium": "BE", "netherlands": "NL", "sweden": "SE", "norway": "NO",
    "denmark": "DK", "finland": "FI", "ireland": "IE", "portugal": "PT", "greece": "GR", "czech republic": "CZ",
    "czechia": "CZ", "hungary": "HU", "romania": "RO", "bulgaria": "BG", "serbia": "RS", "croatia": "HR",
    "latvia": "LV", "lithuania": "LT", "estonia": "EE", "moldova": "MD", "mongolia": "MN", "singapore": "SG",
    "malaysia": "MY", "indonesia": "ID", "thailand": "TH", "vietnam": "VN", "philippines": "PH",
    "bangladesh": "BD", "sri lanka": "LK", "nepal": "NP", "hong kong": "HK", "taiwan": "TW", "iraq": "IQ",
    "syria": "SY", "lebanon": "LB", "jordan": "JO", "kuwait": "KW", "bahrain": "BH", "oman": "OM",
    "yemen": "YE", "morocco": "MA", "algeria": "DZ", "tunisia": "TN", "libya": "LY", "nigeria": "NG",
    "kenya": "KE", "south africa": "ZA", "ethiopia": "ET", "chile": "CL", "colombia": "CO", "peru": "PE",
    "venezuela": "VE", "cuba": "CU", "slovakia": "SK", "slovenia": "SI", "cyprus": "CY", "luxembourg": "LU",
    "iceland": "IS", "albania": "AL", "bosnia and herzegovina": "BA", "macedonia": "MK", "north macedonia": "MK",
    "montenegro": "ME", "kosovo": "XK", "myanmar": "MM", "burma": "MM", "cambodia": "KH", "laos": "LA",
}


def tasks(ctx) -> list:
    now = now_ts()
    if ctx.t_to < now - WINDOW:
        ctx.note("GDELT: период старше 3 месяцев — источник не используется")
        return []
    en = ctx.plan.get("en") or {}
    if not en.get("q"):
        return []
    out = [Task("gdelt", "gdelt:all", "GDELT · все языки", partial(_run, code=None), group="all")]
    for code in PRIORITY:
        if code not in ctx.lang_codes:
            continue
        lang = ctx.languages.by_code.get(code) or {}
        if lang.get("gdelt"):
            out.append(Task("gdelt", "gdelt:" + code, "GDELT · " + lang.get("name", code),
                            partial(_run, code=code), group=code))
    return out


def build_query(ctx, code) -> str:
    en = ctx.plan.get("en") or {}
    terms = list(en.get("q", [])[:4])
    native = []
    if code and code != "en":
        native = [t for t in (ctx.plan.get(code) or {}).get("q", [])[:2] if len(t) >= 2]
    ctx_terms = list(en.get("ctx", [])[:3])
    q = or_group([t for t in terms + native if len(t) >= 3 or not t.isascii()], "gdelt")
    if ctx_terms:
        q += " " + or_group(ctx_terms, "gdelt")
    for x in (en.get("not") or [])[:3]:
        if len(x) >= 3:
            q += ' -"%s"' % x.replace('"', "") if " " in x else " -" + x
    if code:
        q += " sourcelang:" + ctx.languages.by_code[code]["gdelt"]
    return q


def _run(ctx, task, code) -> int:
    now = now_ts()
    start = max(ctx.t_from, now - WINDOW)
    end = min(ctx.t_to, now)
    if end <= start:
        return 0
    if code is None and ctx.t_from < now - WINDOW:
        task.meta["note"] = "GDELT хранит только последние 3 месяца — начало периода обрезано"
    q = build_query(ctx, code)
    try:
        arts = _fetch(ctx, q, start, end)
    except FetchError as e:
        if code and code != "en" and "sourcelang" in q and not q.isascii():
            # запасной вариант — только английские термины
            en = ctx.plan.get("en") or {}
            q2 = or_group(en.get("q", [])[:4], "gdelt") + " sourcelang:" + ctx.languages.by_code[code]["gdelt"]
            arts = _fetch(ctx, q2, start, end)
            task.meta["note"] = "поиск по английским терминам (%s)" % e.short()
        else:
            raise
    added = 0
    for a in arts:
        item = convert(a, code)
        if item and ctx.add(item):
            added += 1
    return added


def _fetch(ctx, q, start, end):
    params = {"query": q, "mode": "artlist", "format": "json", "maxrecords": "250", "sort": "datedesc",
              "startdatetime": ts_to_date(start, "%Y%m%d%H%M%S"), "enddatetime": ts_to_date(end, "%Y%m%d%H%M%S")}
    ttl = 6 * 3600 if now_ts() - end > 86400 else 15 * 60
    r = ctx.http.get(API + urlencode(params), ttl=ttl, timeout=25, retries=2, cancel=ctx.cancel)
    text = r.text().strip()
    if not text:
        return []
    if not text.startswith("{"):
        msg = re.sub(r"\s+", " ", text)[:160]
        if "limit requests" in msg.lower():
            raise FetchError("GDELT: превышена частота запросов", 429)
        raise FetchError("GDELT: %s" % msg)
    try:
        data = json.loads(text, strict=False)
    except ValueError:
        # в заголовках иногда встречаются неэкранированные символы — чистим и пробуем снова
        data = json.loads(re.sub(r"[\x00-\x1f]", " ", text), strict=False)
    return data.get("articles") or []


def convert(a: dict, code) -> dict | None:
    url = a.get("url") or ""
    title = (a.get("title") or "").strip()
    if not url or not title:
        return None
    lang = LANG_CODES.get((a.get("language") or "").strip().lower(), code)
    country = COUNTRIES.get((a.get("sourcecountry") or "").strip().lower())
    return make_item(url=url, title=title, ts=parse_date(a.get("seendate")), lang=lang, prov="gdelt",
                     via="GDELT" + (" · " + code.upper() if code else ""), src_name=a.get("domain", ""),
                     country=country, extra={"gdelt_country": a.get("sourcecountry", "")})
