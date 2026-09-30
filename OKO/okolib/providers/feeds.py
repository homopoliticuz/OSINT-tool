"""Прямой опрос источников реестра.

* RSS/Atom — свежие публикации аналитических центров и изданий, фильтр по терминам и периоду;
* REST API WordPress — полнотекстовый поиск по сайту с точными датами (многие аналитические
  центры работают на WordPress: Atlantic Council, Brookings, Stimson, CABAR, Jamestown и др.).
"""
from __future__ import annotations

from functools import partial
from urllib.parse import urlencode

from ..feedparse import parse_feed
from ..health import classify
from ..net import FetchError
from ..util import detect_lang, now_ts, parse_date, strip_html, utc_iso
from . import Task, make_item


def rss_tasks(ctx) -> list:
    out = []
    pending = 0
    for s in ctx.registry.sources:
        if s.get("off") or not ctx.source_allowed(s):
            continue
        if not any(l in ctx.lang_codes for l in s.get("lang", [])) and s.get("type") not in ("intl_org",):
            continue
        feeds = ctx.registry.feeds_for(s)
        if not feeds:
            if ctx.registry.needs_discovery(s):
                pending += 1
            continue
        out.append(Task("rss", "rss:" + s["id"], s["name"], partial(_run_rss, source=s, feeds=feeds),
                        group=s.get("type", ""), meta={"query": "", "terms": [], "source": s["id"]}))
    if pending:
        ctx.note("Ленты ещё не обнаружены для %d источников — идёт фоновая проверка реестра" % pending)
    return out


def _run_rss(ctx, task, source, feeds) -> int:
    added, errors, ok = 0, [], 0
    ttl = 15 * 60 if now_ts() - ctx.t_to < 86400 else 6 * 3600
    for f in feeds[:2]:
        if ctx.cancel.is_set():
            break
        try:
            r = ctx.http.get(f, ttl=ttl, timeout=12, retries=1, lang=(source.get("lang") or ["en"])[0],
                             cancel=ctx.cancel)
            parsed = parse_feed(r.body, r.url, r.charset())
        except FetchError as e:
            errors.append(e)
            # адрес ленты исчез или сайт закрыл её — ищем новую; сетевые сбои ленту не «портят»
            if classify(e) in ("gone", "denied", "format"):
                ctx.registry.mark_feed(source["id"], f, False)
            continue
        if not parsed["items"]:
            errors.append(FetchError("лента пуста или повреждена (%s)" % parsed.get("kind", "?"), url=f))
            ctx.registry.mark_feed(source["id"], f, False)
            continue
        ok += 1
        ctx.registry.mark_feed(source["id"], f, True)
        oldest = min((it["ts"] for it in parsed["items"] if it.get("ts")), default=None)
        if oldest and oldest > ctx.t_from:
            task.meta["coverage"] = "лента охватывает период с %s" % utc_iso(oldest)[:10]
        for it in parsed["items"]:
            ts = it.get("ts")
            if not ts or ts < ctx.t_from or ts > ctx.t_to:
                continue
            text = " ".join([it.get("summary", ""), " ".join(it.get("categories", []))])
            hit = ctx.match_item(it["title"], text)
            if not hit:
                continue
            item = make_item(url=it["link"], title=it["title"], ts=ts,
                             lang=detect_lang(it["title"], (source.get("lang") or [None])[0]),
                             prov="rss", via="RSS · " + source["name"], src_name=source["name"],
                             src_url="https://" + source["domains"][0], snippet=it.get("summary", ""),
                             authors=it.get("authors"), source_id=source["id"], hit=hit[0], term=hit[1])
            if ctx.add(item):
                added += 1
    if not ok and errors:
        if not ctx.registry.feeds_for(source):
            ctx.registry.request_rediscovery(source["id"])
            task.meta["note"] = "ищу новую ленту на сайте источника"
        first = errors[0]
        raise FetchError("; ".join(e.short() for e in errors[:2]), first.status, first.url)
    return added


# ---------------------------------------------------------------- WordPress

def wp_tasks(ctx) -> list:
    out = []
    for s in ctx.registry.sources:
        if s.get("off") or not ctx.source_allowed(s):
            continue
        api = ctx.registry.wp_api_for(s)
        if not api:
            continue
        langs = [l for l in s.get("lang", []) if l in ctx.lang_codes][:2]
        for code in langs:
            p = ctx.plan.get(code)
            if not p or not p["q"]:
                continue
            term = p["q"][0]
            if p.get("ctx"):
                term += " " + p["ctx"][0]
            out.append(Task("wp", "wp:%s:%s" % (s["id"], code), "%s (%s)" % (s["name"], code.upper()),
                            partial(_run_wp, source=s, api=api, term=term, code=code), group=code,
                            meta={"query": "поиск по сайту: " + term, "terms": [p["q"][0]], "source": s["id"]}))
    return out


def _wp_url(api: str, params: dict) -> str:
    if "rest_route=" in api:
        base = api.split("rest_route=")[0] + "rest_route=/wp/v2/posts"
        return base + "&" + urlencode(params)
    if not api.endswith("/"):
        api += "/"
    return api + "wp/v2/posts?" + urlencode(params)


def _run_wp(ctx, task, source, api, term, code) -> int:
    params = {"search": term, "after": utc_iso(ctx.t_from - 86400), "before": utc_iso(ctx.t_to + 86400),
              "per_page": "25", "orderby": "date", "order": "desc", "_embed": "author",
              "_fields": "id,date_gmt,date,link,title,excerpt,author,_links,_embedded"}
    url = _wp_url(api, params)
    ttl = 30 * 60 if now_ts() - ctx.t_to < 86400 else 6 * 3600
    try:
        r = ctx.http.get(url, ttl=ttl, timeout=15, retries=1, lang=code, cancel=ctx.cancel,
                         headers={"Accept": "application/json"})
        data = r.json()
    except FetchError as e:
        if e.status in (401, 403, 404, 410):
            ctx.registry.mark_wp(source["id"], False, hard=True)
        elif e.status in (400, 405, 501):
            ctx.registry.mark_wp(source["id"], False)
        raise
    except ValueError:
        ctx.registry.mark_wp(source["id"], False)
        raise FetchError("WordPress API вернул не JSON")
    if not isinstance(data, list):
        ctx.registry.mark_wp(source["id"], False)
        raise FetchError("WordPress API: неожиданный ответ")
    ctx.registry.mark_wp(source["id"], True)
    added = 0
    for p in data:
        if not isinstance(p, dict):
            continue
        ts = parse_date((p.get("date_gmt") or "") + "Z") if p.get("date_gmt") else parse_date(p.get("date"))
        if not ts or ts < ctx.t_from or ts > ctx.t_to:
            continue
        title = strip_html((p.get("title") or {}).get("rendered", ""), 400)
        excerpt = strip_html((p.get("excerpt") or {}).get("rendered", ""), 500)
        authors = []
        for a in ((p.get("_embedded") or {}).get("author") or []):
            if isinstance(a, dict) and a.get("name"):
                authors.append(strip_html(a["name"]))
        hit = ctx.match_item(title, excerpt)
        item = make_item(url=p.get("link", ""), title=title, ts=ts,
                         lang=detect_lang(title, code), prov="wp", via="Поиск по сайту · " + source["name"],
                         src_name=source["name"], src_url="https://" + source["domains"][0], snippet=excerpt,
                         authors=authors, source_id=source["id"],
                         hit=hit[0] if hit else "engine", term=hit[1] if hit else "")
        if ctx.add(item):
            added += 1
    return added
