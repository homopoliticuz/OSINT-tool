"""Google News RSS: поиск по изданиям разных стран и языков за точный период.

* широкие запросы — по каждому изданию (США, Великобритания, Индия, Франция, Япония…);
* адресные запросы site: — по группам аналитических источников реестра;
* при «переполнении» выдачи (≈100 материалов) период автоматически делится пополам;
* раскрытие ссылок news.google.com в исходный адрес статьи (для проверки первоисточника).
"""
from __future__ import annotations

import base64
import json
import re
from functools import partial
from urllib.parse import quote, urlencode

from ..feedparse import google_related, parse_feed
from ..net import FetchError
from ..registry import ANALYTIC_TYPES
from ..util import canonical_url, detect_lang, host_of, now_ts, ts_to_date
from . import Task, make_item, or_group, query_meta, quote_term

RSS = "https://news.google.com/rss/search?"
SITE_GROUP = 11


def build_query(terms, ctx_terms, not_terms, t_from, t_to, sites=None) -> str:
    parts = [or_group(terms)]
    if ctx_terms:
        parts.append(or_group(ctx_terms))
    for x in not_terms or []:
        qt = quote_term(x)
        if qt:
            parts.append("-" + qt)
    if sites:
        parts.append("(" + " OR ".join("site:" + s for s in sites) + ")")
    # Google учитывает только даты; границы расширяем на сутки, точная фильтрация — у нас
    parts.append("after:" + ts_to_date(t_from - 86400))
    parts.append("before:" + ts_to_date(t_to + 86400))
    return " ".join(p for p in parts if p)


def _cache_ttl(t_to: int) -> int:
    return 12 * 3600 if now_ts() - t_to > 2 * 86400 else 10 * 60


def tasks(ctx) -> list:
    out = []
    for code in ctx.lang_codes:
        lang = ctx.languages.by_code.get(code)
        if not lang:
            continue
        for ed in lang.get("gnews") or []:
            hl, gl = ed[0], ed[1]
            tcode = "zh-Hant" if len(ed) > 3 and ed[3] == "Hant" else code
            p = ctx.plan.get(tcode) or ctx.plan.get(code)
            if not p or not p["q"]:
                continue
            label = "Google News · %s (%s)" % (gl, hl)
            meta = query_meta(p["q"][:4], p["ctx"][:3], p["not"][:4])
            meta["host"] = "news.google.com"
            out.append(Task("gnews", "gn:%s:%s" % (gl, hl), label,
                            partial(_run, ed=ed, code=code, terms=p["q"][:4], ctx_terms=p["ctx"][:3],
                                    not_terms=p["not"][:4], sites=None),
                            group=code, meta=meta))
    # адресный поиск по аналитическим источникам реестра: сначала уровень A, профильные по Центральной
    # Азии и источники из закладок — чтобы при исчерпании лимита запросов важное было уже опрошено
    groups = {}
    ranked = sorted(ctx.registry.sources, key=lambda s: (s.get("tier", 3), not s.get("ca"), not s.get("bm")))
    for s in ranked:
        if s.get("off") or not ctx.source_allowed(s):
            continue
        if s.get("type") not in ANALYTIC_TYPES and not s.get("ca"):
            continue
        langs = [l for l in s.get("lang", []) if l in ctx.lang_codes]
        pick = langs[:1] + (["en"] if "en" in langs[1:] else [])
        for l in pick:
            if not ctx.languages.by_code.get(l, {}).get("gnews"):
                continue
            for d in s["domains"][:1]:
                groups.setdefault(l, []).append(d)
    site_tasks = []
    for code, domains in groups.items():
        lang = ctx.languages.by_code[code]
        ed = lang["gnews"][0]
        p = ctx.plan.get(code)
        if not p or not p["q"]:
            continue
        for i in range(0, len(domains), SITE_GROUP):
            chunk = domains[i:i + SITE_GROUP]
            meta = query_meta(p["q"][:2], p["ctx"][:2], p["not"][:3],
                              "site:(%s)" % ", ".join(chunk[:4]) + (" и ещё %d" % (len(chunk) - 4) if len(chunk) > 4 else ""))
            meta["sites"] = len(chunk)
            meta["host"] = "news.google.com"
            site_tasks.append((i // SITE_GROUP, Task(
                "gnews", "gns:%s:%d" % (code, i // SITE_GROUP),
                "Google News · аналитика %s #%d" % (code.upper(), i // SITE_GROUP + 1),
                partial(_run, ed=ed, code=code, terms=p["q"][:2], ctx_terms=p["ctx"][:2],
                        not_terms=p["not"][:3], sites=chunk),
                group=code, meta=meta)))
    # чередуем языки: первые (самые авторитетные) группы каждого языка — раньше остальных
    site_tasks.sort(key=lambda x: x[0])
    return out + [t for _, t in site_tasks]


def _run(ctx, task, *, ed, code, terms, ctx_terms, not_terms, sites, t_from=None, t_to=None, depth=0) -> int:
    t_from = ctx.t_from if t_from is None else t_from
    t_to = ctx.t_to if t_to is None else t_to
    if not ctx.take_budget("gnews"):
        task.meta["skipped"] = "исчерпан лимит запросов Google News"
        return 0
    hl, gl, ceid = ed[0], ed[1], ed[2]
    q = build_query(terms, ctx_terms, not_terms, t_from, t_to, sites)
    url = RSS + urlencode({"q": q, "hl": hl, "gl": gl, "ceid": ceid})
    r = ctx.http.get(url, ttl=_cache_ttl(t_to), timeout=15, lang=hl, cancel=ctx.cancel)
    feed = parse_feed(r.body, url, r.charset())
    if feed["kind"] == "html":
        # проверка «я не робот» или согласие на cookies — это пауза сервиса целиком
        ctx.http.block_host("news.google.com", 600)
        raise FetchError("Google показал проверку «я не робот» — запросы к Google News приостановлены на 10 мин",
                         429, url)
    added = 0
    for it in feed["items"]:
        item = convert(it, code, "%s:%s" % (gl, hl))
        if ctx.add(item):
            added += 1
    # выдача переполнена — делим период пополам, чтобы не потерять материалы
    if len(feed["items"]) >= 95 and depth < 3 and t_to - t_from > 36 * 3600 and not sites:
        mid = (t_from + t_to) // 2
        for a, b in ((t_from, mid), (mid, t_to)):
            if ctx.cancel.is_set():
                break
            try:
                added += _run(ctx, task, ed=ed, code=code, terms=terms, ctx_terms=ctx_terms,
                              not_terms=not_terms, sites=sites, t_from=a, t_to=b, depth=depth + 1)
            except FetchError as e:
                task.meta.setdefault("partial", []).append(e.short())
    return added


def convert(it: dict, code: str, edition: str) -> dict:
    title = it["title"]
    src = it.get("source_name") or ""
    if src and title.endswith(" - " + src):
        title = title[: -len(src) - 3].rstrip()
    elif " - " in title and not src:
        title, src = title.rsplit(" - ", 1)
    related = google_related(it.get("summary_html", ""))
    related = [x for x in related if x["title"] and x["source"] != src]
    lang = detect_lang(title, code)
    item = make_item(url=it["link"], title=title, ts=it["ts"], lang=lang, prov="gnews",
                     via="Google News · " + edition, src_name=src, src_url=it.get("source_url", ""),
                     gn=True, related=related[:8], extra={"edition": edition})
    # ссылки старого формата раскрываются без обращения к сети
    m = _ART.search(it["link"] or "")
    direct = _decode_offline(m.group(1)) if m else None
    if direct:
        item["extra"]["gn_url"] = item["url"]
        item["url"] = direct
        item["gn"] = False
        item["curl"] = canonical_url(direct)
        item["domain"] = host_of(direct) or item["domain"]
    return item


# ---------------------------------------------------------------- раскрытие ссылок Google News

_ART = re.compile(r"news\.google\.com/(?:rss/)?(?:articles|read)/([A-Za-z0-9_\-]+)")


def is_gnews(url: str) -> bool:
    return bool(url and _ART.search(url))


def _decode_offline(aid: str):
    try:
        raw = base64.urlsafe_b64decode(aid + "=" * (-len(aid) % 4))
    except (ValueError, TypeError):
        return None
    if raw.startswith(b"\x08\x13\x22"):
        raw = raw[3:]
    # длина (varint), затем полезная нагрузка
    n, shift, i = 0, 0, 0
    while i < len(raw) and i < 5:
        b = raw[i]
        n |= (b & 0x7F) << shift
        i += 1
        if not b & 0x80:
            break
        shift += 7
    payload = raw[i:i + n] if n else raw[i:]
    if payload.startswith(b"AU_yqL"):
        return None  # новый формат — нужен онлайн-запрос
    m = re.match(rb"https?://[\x21-\x7e]+", payload)
    return m.group(0).decode("ascii", "ignore") if m else None


def resolve(http, url: str) -> str | None:
    """Вернуть исходный адрес статьи для ссылки news.google.com (или None)."""
    m = _ART.search(url or "")
    if not m:
        return None
    aid = m.group(1)
    direct = _decode_offline(aid)
    if direct:
        return direct
    sig = ts = None
    for page in ("https://news.google.com/rss/articles/%s?hl=en-US&gl=US&ceid=US:en" % aid,
                 "https://news.google.com/articles/%s?hl=en-US&gl=US&ceid=US:en" % aid):
        try:
            html_text = http.get(page, ttl=30 * 86400, timeout=12, retries=1).text()
        except FetchError:
            continue
        ms = re.search(r'data-n-a-sg="([^"]+)"', html_text)
        mt = re.search(r'data-n-a-ts="([^"]+)"', html_text)
        if ms and mt:
            sig, ts = ms.group(1), mt.group(1)
            break
    if not sig:
        return None
    inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
             '"X","X",1,[1,1,1],1,1,null,0,0,null,0],"%s",%s,"%s"]' % (aid, ts, sig))
    body = "f.req=" + quote(json.dumps([[["Fbv4je", inner]]]))
    try:
        r = http.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", body.encode(),
                      headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                               "Referer": "https://news.google.com/"},
                      ttl=365 * 86400, timeout=12, retries=1)
    except FetchError:
        return None
    return parse_batchexecute(r.text())


def parse_batchexecute(text: str) -> str | None:
    """Разбор ответа batchexecute: )]}' + JSON-массив строк [["wrb.fr","Fbv4je","[\"garturlres\",URL,1]",...]]."""
    chunk = text.split("\n\n", 1)[1] if "\n\n" in text else text
    chunk = chunk.lstrip()
    if chunk[:1].isdigit():  # вариант с длиной фрагмента перед JSON
        chunk = chunk.split("\n", 1)[1] if "\n" in chunk else chunk
    try:
        rows, _end = json.JSONDecoder().raw_decode(chunk.lstrip())
        for row in rows:
            if isinstance(row, list) and len(row) > 2 and row[0] == "wrb.fr" and row[1] == "Fbv4je" and row[2]:
                data = json.loads(row[2])
                if isinstance(data, list) and len(data) > 1 and str(data[1]).startswith("http"):
                    return data[1]
    except (ValueError, TypeError, IndexError):
        pass
    m = re.search(r'garturlres\\",\\"(https?://[^"\\]+)', text)
    return m.group(1) if m else None
