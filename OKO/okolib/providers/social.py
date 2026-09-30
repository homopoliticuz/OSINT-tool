"""Соцсети — отдельная выдача ОКО.

* Telegram — публичные каналы через веб-версию t.me/s/<канал> (поиск внутри канала), без ключей;
  пересланные сообщения помечаются как перепубликация с указанием первоисточника;
* ВКонтакте — метод newsfeed.search (сервисный ключ приложения VK);
* X (Twitter) — API v2 recent search (платный доступ X, последние 7 дней);
* LinkedIn, Facebook, Instagram, X, VK, Telegram, WhatsApp-каналы — поиск публичных публикаций,
  проиндексированных поисковиками: Brave Search API или Google Programmable Search (ключи бесплатные);
* YouTube — YouTube Data API v3 (бесплатный ключ Google).

Закрытые группы, личные страницы и переписка недоступны — ОКО работает только с открытыми данными.
"""
from __future__ import annotations

import html as htmlmod
import json
import os
import re
from functools import partial
from urllib.parse import quote, urlencode

from ..net import FetchError
from ..util import detect_lang, now_ts, parse_date, strip_html, ts_to_date, utc_iso
from . import Task, make_item, or_group

_DATA = None


def data() -> dict:
    global _DATA
    if _DATA is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "data", "social.json")
        with open(path, encoding="utf-8") as f:
            _DATA = json.load(f)
    return _DATA


def platforms() -> dict:
    return data()["platforms"]


def telegram_channels(settings: dict) -> list:
    """Каналы по умолчанию + добавленные пользователем − отключённые."""
    off = {str(x).lower() for x in settings.get("tg_channels_off") or []}
    out, seen = [], set()
    for ch in list(data()["telegram_channels"]) + list(settings.get("tg_channels_add") or []):
        if not isinstance(ch, dict):
            continue
        cid = clean_channel(ch.get("id", ""))
        if not cid or cid.lower() in seen or cid.lower() in off:
            continue
        seen.add(cid.lower())
        out.append(dict(ch, id=cid))
    return out


def clean_channel(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/(s/)?", "", s)
    s = s.lstrip("@").split("/")[0].split("?")[0]
    return s if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", s) else ""


def _terms_for(ctx, langs, n=1) -> list:
    """Первые поисковые термины для списка языков (с запасным русским/английским)."""
    out = []
    for code in list(langs) + ["ru", "en"]:
        p = ctx.plan.get(code)
        if p and p.get("q"):
            for t in p["q"][:n]:
                if t not in out:
                    out.append(t)
            if out:
                break
    return out


def _all_main_terms(ctx, codes=("en", "ru", "uz"), per=1) -> list:
    out = []
    for code in codes:
        p = ctx.plan.get(code)
        for t in (p or {}).get("q", [])[:per]:
            if t not in out:
                out.append(t)
    if not out:
        for p in ctx.plan.values():
            if p.get("q"):
                out.append(p["q"][0])
                break
    return out


# ================================================================ Telegram

TG = "https://t.me/s/"
_MSG = re.compile(r'<div class="tgme_widget_message[^"]*"[^>]*data-post="([^"]+)"', re.S)


def telegram_tasks(ctx) -> list:
    chans = ctx.social_channels()
    if not chans:
        return []
    out = []
    for ch in chans:
        terms = [] if ctx.watch else _terms_for(ctx, [ch.get("lang") or "ru"], 1)
        if not ctx.watch and not terms:
            continue
        q = terms[0] if terms else ""
        meta = {"query": ("поиск в канале: " + q) if q else "последние публикации канала", "terms": terms,
                "host": "t.me", "source": "tg:" + ch["id"], "platform": "telegram"}
        out.append(Task("telegram", "tg:" + ch["id"], "Telegram · " + (ch.get("name") or ch["id"]),
                        partial(_run_tg, channel=ch, q=q), group="social", meta=meta))
    return out


def _run_tg(ctx, task, channel, q) -> int:
    cid = channel["id"]
    added, before, pages = 0, None, 0
    while pages < 4 and not ctx.cancel.is_set():
        params = {}
        if q:
            params["q"] = q
        if before:
            params["before"] = str(before)
        url = TG + cid + ("?" + urlencode(params) if params else "")
        r = ctx.http.get(url, ttl=10 * 60 if now_ts() - ctx.t_to < 86400 else 3 * 3600, timeout=15, retries=1,
                         cancel=ctx.cancel, lang=channel.get("lang") or "ru")
        text = r.text()
        if pages == 0 and "tgme_channel_info" not in text and "tgme_widget_message" not in text:
            raise FetchError("канал не найден или закрыт (нет публичной веб-версии)", 404, url)
        msgs = parse_tg(text, cid)
        pages += 1
        if not msgs:
            break
        for m in msgs:
            if not m["ts"] or m["ts"] < ctx.t_from or m["ts"] > ctx.t_to:
                continue
            item = tg_item(m, channel)
            if not ctx.watch:
                hit = ctx.match_item(item["title"], m["text"])
                if not hit:
                    continue
                item["hit"], item["term"] = hit[0], hit[1]
            if ctx.add(item):
                added += 1
        oldest = min((m["ts"] for m in msgs if m["ts"]), default=None)
        ids = [m["num"] for m in msgs if m["num"]]
        if not oldest or oldest < ctx.t_from or not ids:
            break
        before = min(ids)
    return added


def parse_tg(text: str, channel: str = "") -> list:
    """Сообщения со страницы t.me/s/<канал>."""
    title = ""
    m = re.search(r'<meta property="og:title" content="([^"]*)"', text)
    if m:
        title = htmlmod.unescape(m.group(1))
    starts = [(mm.start(), mm.group(1)) for mm in _MSG.finditer(text)]
    out = []
    for i, (pos, post) in enumerate(starts):
        block = text[pos: starts[i + 1][0] if i + 1 < len(starts) else len(text)]
        num = post.rsplit("/", 1)[-1]
        tm = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        body = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        owner = re.search(r'tgme_widget_message_owner_name[^>]*>(?:<span[^>]*>)?(.*?)<', block, re.S)
        fwd = re.search(r'tgme_widget_message_forwarded_from_name"(?:\s+href="([^"]+)")?[^>]*>(?:<span[^>]*>)?(.*?)<',
                        block, re.S)
        views = re.search(r'tgme_widget_message_views">([^<]+)<', block)
        raw = body.group(1) if body else ""
        raw = re.sub(r"<br\s*/?>", "\ue000", raw)  # переводы строк переживают очистку разметки
        txt = "\n".join(x.strip() for x in strip_html(raw).split("\ue000"))
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        out.append({
            "post": post, "num": int(num) if num.isdigit() else 0,
            "url": "https://t.me/" + post,
            "ts": parse_date(tm.group(1)) if tm else None,
            "text": txt,
            "owner": htmlmod.unescape(owner.group(1)).strip() if owner else title,
            "fwd": {"name": htmlmod.unescape(fwd.group(2)).strip(), "url": fwd.group(1) or ""} if fwd else None,
            "views": views.group(1).strip() if views else "",
            "channel": post.split("/")[0] if "/" in post else channel,
        })
    return out


def _title_of(text: str, limit: int = 150) -> str:
    first = (text or "").strip().split("\n", 1)[0].strip()
    if len(first) > limit:
        cut = first[:limit]
        sp = cut.rfind(" ")
        first = (cut[:sp] if sp > limit * 0.6 else cut).rstrip(",;:—- ") + "…"
    return first or "(сообщение без текста)"


def tg_item(m: dict, channel: dict) -> dict:
    name = channel.get("name") or m.get("owner") or m["channel"]
    extra = {"platform": "telegram", "channel": m["channel"], "views": m.get("views", "")}
    if m.get("fwd"):
        extra["fwd"] = m["fwd"]
    return make_item(url=m["url"], title=_title_of(m["text"]), ts=m["ts"],
                     lang=detect_lang(m["text"][:400], channel.get("lang")), prov="telegram",
                     via="Telegram · @" + m["channel"], src_name=name, src_url="https://t.me/" + m["channel"],
                     snippet=m["text"][:900], source_id=channel.get("source"), country=channel.get("country"),
                     kind="social", extra=extra)


# ================================================================ ВКонтакте

def vk_tasks(ctx) -> list:
    token = (ctx.settings.get("vk_token") or "").strip()
    if not token or ctx.watch:
        return []
    terms = _all_main_terms(ctx, ("ru", "uz", "en"))[:3]
    return [Task("vk", "vk:" + str(i), "ВКонтакте · «%s»" % t, partial(_run_vk, token=token, term=t), group="social",
                 meta={"query": t, "terms": [t], "platform": "vk"}) for i, t in enumerate(terms)]


def _run_vk(ctx, task, token, term) -> int:
    params = {"q": term, "count": "200", "extended": "1", "v": "5.199", "access_token": token,
              "start_time": str(ctx.t_from), "end_time": str(ctx.t_to)}
    r = ctx.http.get("https://api.vk.com/method/newsfeed.search?" + urlencode(params), ttl=15 * 60, timeout=20,
                     retries=1, cancel=ctx.cancel)
    data_ = r.json()
    if "error" in data_:
        err = data_["error"]
        code = err.get("error_code")
        raise FetchError("VK API: %s" % err.get("error_msg", "ошибка"), 401 if code in (5, 15, 27, 28) else 400)
    resp = data_.get("response") or {}
    names = {}
    for g in resp.get("groups") or []:
        names[-int(g["id"])] = (g.get("name") or "", g.get("screen_name") or "")
    for p in resp.get("profiles") or []:
        names[int(p["id"])] = ((p.get("first_name", "") + " " + p.get("last_name", "")).strip(), p.get("screen_name") or "")
    added = 0
    for it in resp.get("items") or []:
        text = (it.get("text") or "").strip()
        owner = int(it.get("owner_id") or it.get("from_id") or 0)
        if not text or not owner:
            continue
        name, screen = names.get(owner, ("", ""))
        extra = {"platform": "vk", "views": str((it.get("views") or {}).get("count", ""))}
        rep = (it.get("copy_history") or [None])[0]
        if rep:
            ro = int(rep.get("owner_id") or 0)
            rn = names.get(ro, ("", ""))[0] or ("vk.com/wall%s_%s" % (ro, rep.get("id")))
            extra["fwd"] = {"name": rn, "url": "https://vk.com/wall%s_%s" % (ro, rep.get("id"))}
        item = make_item(url="https://vk.com/wall%s_%s" % (owner, it.get("id")), title=_title_of(text),
                         ts=int(it.get("date") or 0) or None, lang=detect_lang(text[:400], "ru"), prov="vk",
                         via="ВКонтакте", src_name=name or ("vk.com/" + screen if screen else "ВКонтакте"),
                         src_url="https://vk.com/" + screen if screen else "https://vk.com", snippet=text[:900],
                         kind="social", extra=extra)
        hit = ctx.match_item(item["title"], text)
        if hit:
            item["hit"], item["term"] = hit[0], hit[1]
        if ctx.add(item):
            added += 1
    return added


# ================================================================ X (Twitter)

def x_tasks(ctx) -> list:
    token = (ctx.settings.get("x_bearer") or "").strip()
    if not token or ctx.watch:
        return []
    if ctx.t_to < now_ts() - 7 * 86400 + 60:
        ctx.note("X: поиск по API охватывает только последние 7 дней")
        return []
    terms = _all_main_terms(ctx, ("en", "ru", "uz"))[:5]
    if not terms:
        return []
    q = or_group(terms) + " -is:retweet"
    return [Task("x", "x:recent", "X (Twitter) · API", partial(_run_x, token=token, q=q), group="social",
                 meta={"query": q, "terms": terms, "platform": "x"})]


def _run_x(ctx, task, token, q) -> int:
    start = max(ctx.t_from, now_ts() - 7 * 86400 + 60)
    end = min(ctx.t_to, now_ts() - 15)
    params = {"query": q[:512], "max_results": "100", "start_time": utc_iso(start), "end_time": utc_iso(end),
              "tweet.fields": "created_at,lang,author_id,public_metrics,referenced_tweets",
              "expansions": "author_id", "user.fields": "name,username,verified"}
    r = ctx.http.get("https://api.x.com/2/tweets/search/recent?" + urlencode(params), ttl=10 * 60, timeout=20,
                     retries=1, cancel=ctx.cancel, headers={"Authorization": "Bearer " + token})
    d = r.json()
    users = {u["id"]: u for u in (d.get("includes") or {}).get("users") or []}
    added = 0
    for t in d.get("data") or []:
        u = users.get(t.get("author_id"), {})
        text = t.get("text") or ""
        uname = u.get("username") or "i"
        extra = {"platform": "x", "views": str((t.get("public_metrics") or {}).get("impression_count", ""))}
        item = make_item(url="https://x.com/%s/status/%s" % (uname, t["id"]), title=_title_of(text), ts=parse_date(t.get("created_at")),
                         lang=t.get("lang") or detect_lang(text), prov="x", via="X (Twitter)",
                         src_name="%s (@%s)" % (u.get("name") or uname, uname), src_url="https://x.com/" + uname,
                         snippet=text, kind="social", extra=extra)
        hit = ctx.match_item(item["title"], text)
        if hit:
            item["hit"], item["term"] = hit[0], hit[1]
        if ctx.add(item):
            added += 1
    return added


# ================================================================ поиск по сайтам соцсетей (Brave / Google CSE)

def websocial_tasks(ctx) -> list:
    brave = (ctx.settings.get("brave_key") or "").strip()
    gkey, gcx = (ctx.settings.get("gcse_key") or "").strip(), (ctx.settings.get("gcse_cx") or "").strip()
    if not brave and not (gkey and gcx) or ctx.watch:
        return []
    want = list(ctx.platforms) if ctx.platforms else (ctx.settings.get("social_platforms") or list(platforms()))
    terms = _all_main_terms(ctx, ("en", "ru", "uz"))[:3]
    if not terms:
        return []
    out = []
    for pid, p in platforms().items():
        if pid not in want or pid == "youtube":
            continue
        sites = p["sites"]
        q = or_group(terms) + " " + ("(" + " OR ".join("site:" + s for s in sites) + ")" if len(sites) > 1 else "site:" + sites[0])
        engine = "brave" if brave else "gcse"
        out.append(Task("websocial", "ws:%s:%s" % (engine, pid), "%s · через %s" % (p["name"], "Brave" if brave else "Google"),
                        partial(_run_brave if brave else _run_gcse, q=q, platform=pid, key=brave or gkey, cx=gcx),
                        group="social", meta={"query": q, "terms": terms, "platform": pid}))
    return out


def _period_days(ctx) -> int:
    return max(1, int((now_ts() - ctx.t_from) // 86400) + 1)


def _web_item(ctx, *, url, title, snippet, ts, platform, via):
    p = platforms().get(platform, {})
    item = make_item(url=url, title=strip_html(title, 300), ts=ts, lang=detect_lang(title + " " + snippet),
                     prov="websocial", via=via, src_name=p.get("name", platform), snippet=strip_html(snippet, 600),
                     kind="social", prec="" if ts else "range", extra={"platform": platform})
    hit = ctx.match_item(item["title"], item["snippet"])
    if hit:
        item["hit"], item["term"] = hit[0], hit[1]
    return item


def _run_brave(ctx, task, q, platform, key, cx="") -> int:
    params = {"q": q, "count": "20", "freshness": "%sto%s" % (ts_to_date(ctx.t_from), ts_to_date(ctx.t_to)),
              "safesearch": "off"}
    r = ctx.http.get("https://api.search.brave.com/res/v1/web/search?" + urlencode(params), ttl=30 * 60, timeout=20,
                     retries=1, cancel=ctx.cancel, headers={"X-Subscription-Token": key, "Accept": "application/json"})
    added = 0
    for x in ((r.json().get("web") or {}).get("results") or []):
        ts = parse_date(x.get("page_age")) if x.get("page_age") else None
        item = _web_item(ctx, url=x.get("url", ""), title=x.get("title", ""), snippet=x.get("description", ""), ts=ts,
                         platform=platform, via="Brave Search · " + platform)
        if item["url"] and ctx.add(item):
            added += 1
    return added


def _run_gcse(ctx, task, q, platform, key, cx) -> int:
    params = {"key": key, "cx": cx, "q": q, "num": "10", "dateRestrict": "d%d" % _period_days(ctx), "sort": "date"}
    r = ctx.http.get("https://www.googleapis.com/customsearch/v1?" + urlencode(params), ttl=30 * 60, timeout=20,
                     retries=1, cancel=ctx.cancel)
    added = 0
    for x in r.json().get("items") or []:
        ts = None
        for mt in ((x.get("pagemap") or {}).get("metatags") or [])[:1]:
            for k in ("article:published_time", "og:updated_time", "date", "article:modified_time"):
                if mt.get(k):
                    ts = parse_date(mt[k])
                    break
        item = _web_item(ctx, url=x.get("link", ""), title=x.get("title", ""), snippet=x.get("snippet", ""), ts=ts,
                         platform=platform, via="Google Programmable Search · " + platform)
        if item["url"] and ctx.add(item):
            added += 1
    return added


# ================================================================ YouTube

def youtube_tasks(ctx) -> list:
    key = (ctx.settings.get("youtube_key") or "").strip()
    if not key or ctx.watch:
        return []
    terms = _all_main_terms(ctx, ("en", "ru", "uz"))[:3]
    if not terms:
        return []
    q = "|".join(('"%s"' % t) if " " in t else t for t in terms)
    return [Task("youtube", "youtube", "YouTube · Data API", partial(_run_yt, key=key, q=q), group="social",
                 meta={"query": q, "terms": terms, "platform": "youtube"})]


def _run_yt(ctx, task, key, q) -> int:
    params = {"part": "snippet", "type": "video", "order": "date", "maxResults": "50", "q": q, "key": key,
              "publishedAfter": utc_iso(ctx.t_from), "publishedBefore": utc_iso(ctx.t_to)}
    r = ctx.http.get("https://www.googleapis.com/youtube/v3/search?" + urlencode(params), ttl=30 * 60, timeout=20,
                     retries=1, cancel=ctx.cancel)
    added = 0
    for x in r.json().get("items") or []:
        vid = (x.get("id") or {}).get("videoId")
        sn = x.get("snippet") or {}
        if not vid:
            continue
        item = make_item(url="https://www.youtube.com/watch?v=" + vid, title=htmlmod.unescape(sn.get("title", "")),
                         ts=parse_date(sn.get("publishedAt")), lang=detect_lang(sn.get("title", "")), prov="youtube",
                         via="YouTube", src_name=(sn.get("channelTitle") or "YouTube") + " (YouTube)",
                         src_url="https://www.youtube.com/channel/" + sn.get("channelId", ""),
                         snippet=htmlmod.unescape(sn.get("description", "")), kind="social",
                         extra={"platform": "youtube"})
        hit = ctx.match_item(item["title"], item["snippet"])
        if hit:
            item["hit"], item["term"] = hit[0], hit[1]
        if ctx.add(item):
            added += 1
    return added


def search_links(query: str) -> list:
    """Ссылки для ручного поиска на самих платформах (где вы авторизованы)."""
    return [{"id": pid, "name": p["name"], "url": p["search"].replace("{q}", quote(query)), "note": p.get("note", "")}
            for pid, p in platforms().items()]


__all__ = ["telegram_tasks", "vk_tasks", "x_tasks", "websocial_tasks", "youtube_tasks", "parse_tg", "platforms",
           "telegram_channels", "clean_channel", "search_links"]
