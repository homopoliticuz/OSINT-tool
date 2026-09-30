"""Дополнительные провайдеры: Bing News, OpenAlex (наука), Всемирный банк (документы и доклады),
GOV.UK (официальные публикации Великобритании), ReliefWeb (доклады ООН и НКО)."""
from __future__ import annotations

import json
from functools import partial
from urllib.parse import parse_qs, urlencode, urlsplit

from ..feedparse import parse_feed
from ..net import FetchError
from ..util import detect_lang, host_of, now_ts, parse_date, strip_html, ts_to_date, utc_iso
from . import Task, make_item, or_group, query_meta

# ---------------------------------------------------------------- Bing News


def bing_tasks(ctx) -> list:
    age = now_ts() - ctx.t_from
    if age > 31 * 86400:
        ctx.note("Bing News: период старше месяца — источник не используется")
        return []
    interval = "7" if age <= 86400 else ("8" if age <= 7 * 86400 else "9")
    out = []
    for code in ctx.lang_codes:
        lang = ctx.languages.by_code.get(code) or {}
        mk = lang.get("bing")
        p = ctx.plan.get(code)
        if not mk or not p or not p["q"]:
            continue
        out.append(Task("bing", "bing:" + code, "Bing News · %s" % mk[1],
                        partial(_run_bing, code=code, mk=mk, interval=interval), group=code,
                        meta=dict(query_meta(p["q"][:3], p.get("ctx", [])[:2]), host="www.bing.com")))
    return out


def _run_bing(ctx, task, code, mk, interval) -> int:
    p = ctx.plan[code]
    q = or_group(p["q"][:3])
    if p.get("ctx"):
        q += " " + or_group(p["ctx"][:2])
    url = "https://www.bing.com/news/search?" + urlencode({
        "q": q, "format": "rss", "setlang": mk[0], "cc": mk[1], "count": "50",
        "qft": 'interval="%s"' % interval})
    r = ctx.http.get(url, ttl=20 * 60, timeout=15, retries=1, lang=mk[0], cancel=ctx.cancel)
    feed = parse_feed(r.body, url, r.charset())
    if feed["kind"] == "html":
        ctx.http.block_host("www.bing.com", 900)
        raise FetchError("Bing показал страницу проверки вместо ленты — Bing News приостановлен на 15 мин", 429, url)
    added = 0
    for it in feed["items"]:
        link = it["link"]
        if "bing.com" in link and "url=" in link:
            qs = parse_qs(urlsplit(link).query)
            link = (qs.get("url") or [link])[0]
        item = make_item(url=link, title=it["title"], ts=it["ts"], lang=detect_lang(it["title"], code),
                         prov="bing", via="Bing News · " + mk[1], src_name=it.get("source_name", ""),
                         snippet=it.get("summary", ""))
        if ctx.add(item):
            added += 1
    return added


# ---------------------------------------------------------------- OpenAlex

def openalex_tasks(ctx) -> list:
    if not (ctx.plan.get("en") or {}).get("q"):
        return []
    en = ctx.plan["en"]
    terms = en["q"][:3] + (ctx.plan.get("ru") or {}).get("q", [])[:1]
    return [Task("openalex", "openalex", "OpenAlex · научные публикации", _run_openalex, group="academic",
                 meta=query_meta(terms, en.get("ctx", [])[:3]))]


def _run_openalex(ctx, task) -> int:
    en = ctx.plan["en"]
    terms = en["q"][:3]
    ru = (ctx.plan.get("ru") or {}).get("q", [])[:1]
    s = "(" + " OR ".join('"%s"' % t if " " in t else t for t in terms + ru) + ")"
    if en.get("ctx"):
        s += " AND (" + " OR ".join('"%s"' % t if " " in t else t for t in en["ctx"][:3]) + ")"
    params = {"search": s, "per-page": "50", "sort": "publication_date:desc",
              "filter": "from_publication_date:%s,to_publication_date:%s" % (
                  ts_to_date(ctx.t_from), ts_to_date(ctx.t_to)),
              "select": "id,doi,display_name,publication_date,authorships,primary_location,open_access,"
                        "language,type,cited_by_count"}
    r = ctx.http.get("https://api.openalex.org/works?" + urlencode(params), ttl=3 * 3600, timeout=20,
                     retries=1, cancel=ctx.cancel)
    data = r.json()
    added = 0
    for w in data.get("results") or []:
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        url = loc.get("landing_page_url") or w.get("doi") or w.get("id")
        title = strip_html(w.get("display_name") or "", 400)
        if not title or not url:
            continue
        authors = [((a.get("author") or {}).get("display_name") or "") for a in (w.get("authorships") or [])]
        oa = w.get("open_access") or {}
        item = make_item(url=url, title=title, ts=parse_date(w.get("publication_date")), prec="day",
                         lang=(w.get("language") or detect_lang(title, "en")), prov="openalex",
                         via="OpenAlex", src_name=src.get("display_name") or "", authors=authors,
                         kind="paper", pdf=oa.get("oa_url") or loc.get("pdf_url") or "",
                         snippet=w.get("type", ""),
                         extra={"publisher": src.get("host_organization_name") or "", "doi": w.get("doi") or "",
                                "cited": w.get("cited_by_count", 0), "venue_type": src.get("type") or ""})
        if ctx.add(item):
            added += 1
    return added


# ---------------------------------------------------------------- Всемирный банк

def worldbank_tasks(ctx) -> list:
    if not (ctx.plan.get("en") or {}).get("q"):
        return []
    en = ctx.plan["en"]
    return [Task("worldbank", "worldbank", "Всемирный банк · документы и доклады", _run_wb, group="intl_org",
                 meta=query_meta(en["q"][:1], en.get("ctx", [])[:1]))]


def _run_wb(ctx, task) -> int:
    en = ctx.plan["en"]
    q = en["q"][0] + ((" " + en["ctx"][0]) if en.get("ctx") else "")
    params = {"format": "json", "qterm": q, "strdate": ts_to_date(ctx.t_from), "enddate": ts_to_date(ctx.t_to),
              "rows": "50", "os": "0", "srt": "docdt", "order": "desc",
              "fl": "docdt,docty,display_title,pdfurl,url,repnme,lang,count,majdocty,authr"}
    r = ctx.http.get("https://search.worldbank.org/api/v2/wds?" + urlencode(params), ttl=6 * 3600,
                     timeout=20, retries=1, cancel=ctx.cancel)
    data = r.json()
    docs = data.get("documents") or {}
    added = 0
    for key, d in docs.items():
        if key == "facets" or not isinstance(d, dict):
            continue
        title = strip_html(d.get("display_title") or d.get("repnme") or "", 400)
        url = d.get("url") or d.get("pdfurl") or ""
        if not title or not url:
            continue
        url = url.replace("http://", "https://", 1)
        authors = []
        au = d.get("authr") or d.get("authors")
        if isinstance(au, dict):
            authors = [v.get("authr") or v.get("author") or "" for v in au.values() if isinstance(v, dict)]
        elif isinstance(au, str):
            authors = [au]
        item = make_item(url=url, title=title, ts=parse_date(d.get("docdt")), prec="day", lang="en",
                         prov="worldbank", via="World Bank Documents & Reports", src_name="World Bank",
                         src_url="https://www.worldbank.org", snippet=" · ".join(
                             x for x in [d.get("majdocty"), d.get("docty"), d.get("count")] if isinstance(x, str) and x),
                         authors=authors, source_id="worldbank", kind="report",
                         pdf=(d.get("pdfurl") or "").replace("http://", "https://", 1))
        if ctx.add(item):
            added += 1
    return added


# ---------------------------------------------------------------- GOV.UK

def govuk_tasks(ctx) -> list:
    if not (ctx.plan.get("en") or {}).get("q"):
        return []
    en = ctx.plan["en"]
    return [Task("govuk", "govuk", "GOV.UK · официальные публикации", _run_govuk, group="official",
                 meta=query_meta(en["q"][:1], en.get("ctx", [])[:1]))]


def _run_govuk(ctx, task) -> int:
    en = ctx.plan["en"]
    kw = en["q"][0] + ((" " + en["ctx"][0]) if en.get("ctx") else "")
    url = "https://www.gov.uk/search/all.atom?" + urlencode({"keywords": kw, "order": "updated-newest"})
    r = ctx.http.get(url, ttl=3600, timeout=15, retries=1, cancel=ctx.cancel)
    feed = parse_feed(r.body, url, r.charset())
    added = 0
    for it in feed["items"]:
        ts = it.get("ts")
        if not ts or ts < ctx.t_from or ts > ctx.t_to:
            continue
        hit = ctx.match_item(it["title"], it.get("summary", ""))
        item = make_item(url=it["link"], title=it["title"], ts=ts, lang="en", prov="govuk", via="GOV.UK",
                         src_name="GOV.UK", src_url="https://www.gov.uk", snippet=it.get("summary", ""),
                         source_id="gov_uk", kind="official", hit=hit[0] if hit else "engine",
                         term=hit[1] if hit else "")
        if ctx.add(item):
            added += 1
    return added


# ---------------------------------------------------------------- ReliefWeb

def reliefweb_tasks(ctx) -> list:
    app = (ctx.settings.get("reliefweb_appname") or "").strip()
    if not app:
        return []
    en = ctx.plan.get("en") or {}
    if not en.get("q"):
        return []
    return [Task("reliefweb", "reliefweb", "ReliefWeb · доклады ООН и НКО", partial(_run_rw, app=app),
                 group="intl_org", meta=query_meta(en["q"][:3]))]


def _run_rw(ctx, task, app) -> int:
    en = ctx.plan["en"]
    body = {
        "query": {"value": " OR ".join(en["q"][:3]), "operator": "OR"},
        "filter": {"field": "date.original", "value": {"from": utc_iso(ctx.t_from).replace("Z", "+00:00"),
                                                       "to": utc_iso(ctx.t_to).replace("Z", "+00:00")}},
        "fields": {"include": ["title", "url_alias", "url", "source.name", "source.homepage", "date.original",
                               "language.code"]},
        "sort": ["date.original:desc"], "limit": 50,
    }
    added = 0
    last = None
    for ver in ("v2", "v1"):
        try:
            r = ctx.http.post("https://api.reliefweb.int/%s/reports?appname=%s" % (ver, app),
                              json.dumps(body).encode(), headers={"Content-Type": "application/json"},
                              ttl=3600, timeout=20, retries=1, cancel=ctx.cancel)
            data = r.json()
            break
        except (FetchError, ValueError) as e:
            last = e
            data = None
    if data is None:
        raise last if isinstance(last, FetchError) else FetchError("ReliefWeb недоступен")
    for d in data.get("data") or []:
        f = d.get("fields") or {}
        srcs = f.get("source") or [{}]
        s0 = srcs[0] if isinstance(srcs, list) and srcs else {}
        langs = f.get("language") or [{}]
        item = make_item(url=f.get("url_alias") or f.get("url") or "", title=strip_html(f.get("title", ""), 400),
                         ts=parse_date((f.get("date") or {}).get("original")), lang=(langs[0] or {}).get("code"),
                         prov="reliefweb", via="ReliefWeb", src_name="ReliefWeb",
                         src_url="https://reliefweb.int", source_id="reliefweb", kind="report",
                         extra={"original_publisher": s0.get("name", ""),
                                "original_domain": host_of(s0.get("homepage") or "")})
        if item["url"] and ctx.add(item):
            added += 1
    return added
