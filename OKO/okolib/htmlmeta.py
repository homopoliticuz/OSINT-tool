"""Извлечение метаданных и текста из HTML-страниц.

* метаданные статьи: заголовок, авторы, издание, даты, canonical, язык, платный доступ,
  признаки синдикации (original-source, isBasedOn, агентская «шапка» в начале текста);
* обнаружение лент RSS/Atom и REST API WordPress на главной странице источника;
* «режим чтения»: основной текст статьи для печати в PDF.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from .util import host_of, parse_date, strip_html

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "form", "button", "select"}
_BOILER_TAGS = {"nav", "footer", "aside", "header"}
_BOILER_CLASS = re.compile(
    r"(comment|related|promo|advert|banner|subscribe|newsletter|share|social|footer|nav|menu|sidebar|"
    r"cookie|paywall-offer|recommend|popular|most-read|breadcrumb|tags|caption|widget|signup|modal)", re.I)
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
         "track", "wbr"}


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = []          # (key, value)
        self.links = []         # dict attrs
        self.title = ""
        self.lang = ""
        self.jsonld = []
        self.blocks = []        # (container_id, kind, text)
        self.bylines = []
        self._stack = []        # [(tag, boiler, container_id)]
        self._in_title = False
        self._in_jsonld = False
        self._buf = []
        self._cur = None        # (kind, container_id, parts)
        self._cid = 0
        self._skip = 0
        self._byline_depth = None
        self._byline_parts = []

    # контейнеры: article/main/section/div с «контентными» классами получают свой id
    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"]
        if tag == "meta":
            k = (a.get("property") or a.get("name") or a.get("itemprop") or a.get("http-equiv") or "").lower()
            if k and "content" in a:
                self.meta.append((k, a["content"]))
            return
        if tag == "link":
            self.links.append(a)
            return
        if tag == "title" and not self._stack_has("svg"):
            self._in_title = True
            return
        if tag == "script":
            if "ld+json" in a.get("type", "").lower():
                self._in_jsonld = True
                self._buf = []
            self._skip += 1
            self._stack.append((tag, False, None))
            return
        if tag in _VOID:
            return
        cls = (a.get("class", "") + " " + a.get("id", "")).strip()
        boiler = tag in _BOILER_TAGS or bool(cls and _BOILER_CLASS.search(cls)) or tag in _SKIP_TAGS
        if tag in _SKIP_TAGS:
            self._skip += 1
        cid = None
        if tag in ("article", "main", "section", "div", "td") :
            self._cid += 1
            cid = self._cid
        self._stack.append((tag, boiler, cid))
        if re.search(r"(byline|author)", cls, re.I) or a.get("rel") == "author" or \
                a.get("itemprop") == "author":
            if self._byline_depth is None:
                self._byline_depth = len(self._stack)
                self._byline_parts = []
        if tag in ("p", "h1", "h2", "h3", "blockquote", "li") and not self._in_boiler():
            self._flush()
            self._cur = (tag, self._container(), [])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag in _VOID:
            return
        if tag == "script":
            if self._in_jsonld:
                self.jsonld.append("".join(self._buf))
                self._in_jsonld = False
            self._skip = max(0, self._skip - 1)
        elif tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        if self._cur and tag == self._cur[0]:
            self._flush()
        # снимаем со стека до совпадающего тега (HTML часто не сбалансирован)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                if self._byline_depth is not None and i + 1 <= self._byline_depth:
                    txt = " ".join(self._byline_parts).strip()
                    if 2 < len(txt) < 120:
                        self.bylines.append(txt)
                    self._byline_depth = None
                del self._stack[i:]
                break

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._in_jsonld:
            self._buf.append(data)
            return
        if self._skip:
            return
        if self._byline_depth is not None:
            self._byline_parts.append(data.strip())
        if self._cur is not None:
            self._cur[2].append(data)

    def _stack_has(self, tag):
        return any(t == tag for t, _b, _c in self._stack)

    def _in_boiler(self):
        return any(b for _t, b, _c in self._stack)

    def _container(self):
        for _t, _b, cid in reversed(self._stack):
            if cid is not None:
                return cid
        return 0

    def _flush(self):
        if self._cur is None:
            return
        kind, cid, parts = self._cur
        txt = re.sub(r"\s+", " ", "".join(parts)).strip()
        if txt:
            self.blocks.append((cid, kind, txt))
        self._cur = None

    def close(self):
        self._flush()
        super().close()


def _parse(html_text: str) -> _Collector:
    c = _Collector()
    try:
        c.feed(html_text)
        c.close()
    except Exception:  # noqa: BLE001 — html.parser не должен ронять извлечение
        pass
    return c


def _meta_get(meta, *keys):
    vals = []
    for k, v in meta:
        if k in keys and v.strip():
            vals.append(v.strip())
    return vals


def _jsonld_objects(raw_list):
    out = []
    for raw in raw_list:
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw, strict=False)
        except ValueError:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw), strict=False)
            except ValueError:
                continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                out.append(x)
                if "@graph" in x:
                    stack.append(x["@graph"])
    return out


_ARTICLE_TYPES = {"newsarticle", "article", "reportagenewsarticle", "analysisnewsarticle", "opinionnewsarticle",
                  "blogposting", "report", "scholarlyarticle", "backgroundnewsarticle", "techarticle",
                  "reviewnewsarticle", "liveblogposting", "webpage", "creativework"}


def _types(o):
    t = o.get("@type")
    if isinstance(t, list):
        return {str(x).lower() for x in t}
    return {str(t).lower()} if t else set()


def _names(v):
    if not v:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        n = v.get("name")
        if isinstance(n, list):
            return [str(x) for x in n if x]
        return [str(n)] if n else []
    if isinstance(v, list):
        out = []
        for x in v:
            out.extend(_names(x))
        return out
    return []


# Агентская «шапка» в начале текста: «ТАШКЕНТ, 29 сен (Reuters) —», «(AFP) -», «— ТАСС.»
_DATELINE = re.compile(
    r"^.{0,80}?[\(（【\[]\s*(Reuters|AP|AFP|Bloomberg|dpa|EFE|ANSA|Xinhua|Kyodo|共同|時事|ロイター|"
    r"新华社|Yonhap|연합뉴스|Anadolu|AA|IRNA|ТАСС|TASS|РИА Новости|Интерфакс|Interfax|Sputnik|"
    r"Спутник|УзА|UzA|Kun\.uz|Газета\.uz|Daryo)\s*[\)）】\]]", re.I)
_DATELINE_RU = re.compile(r"^.{0,90}?[—–-]\s*(ТАСС|РИА Новости|Интерфакс|Прайм|РБК|Sputnik)\b", re.I)
_REPRINT_MARKERS = re.compile(
    r"(originally (?:published|appeared)|first (?:published|appeared) (?:in|on|at)|reprinted (?:with permission )?from|"
    r"this article (?:was|is) (?:republished|reprinted)|republished (?:from|with permission)|"
    r"впервые опубликован|перепечатка|публикуется с разрешения|оригинал статьи|перевод статьи|"
    r"initialement publié|publié à l'origine|zuerst erschienen|ursprünglich erschienen|"
    r"publicado originalmente|publicado originariamente|pubblicato originariamente|"
    r"原文刊登|本文转载自|转载自|出典[:：]|출처[:：]|منبع[:：]|المصدر[:：]|kaynak[:：]|manba[:：])", re.I)


def extract_meta(html_text: str, url: str) -> dict:
    c = _parse(html_text)
    meta = c.meta
    objs = _jsonld_objects(c.jsonld)
    art = None
    for o in objs:
        if _types(o) & _ARTICLE_TYPES and ("headline" in o or "author" in o or "datePublished" in o):
            art = o
            break
    canonical = ""
    feeds, amp, wp_api, original = [], "", "", ""
    for l in c.links:
        rel = l.get("rel", "").lower()
        href = l.get("href", "")
        if not href:
            continue
        if rel == "canonical" and not canonical:
            canonical = urljoin(url, href)
        elif rel == "amphtml":
            amp = urljoin(url, href)
        elif rel == "alternate" and re.search(r"(rss|atom)\+xml", l.get("type", ""), re.I):
            feeds.append(urljoin(url, href))
        elif rel == "https://api.w.org/":
            wp_api = urljoin(url, href)
        elif rel in ("original-source", "syndication-source"):
            original = urljoin(url, href)

    authors = []
    if art:
        authors = _names(art.get("author")) + _names(art.get("creator"))
    authors += _meta_get(meta, "author", "article:author", "parsely-author", "sailthru.author",
                         "citation_author", "dc.creator", "dcterms.creator", "byl")
    authors += c.bylines[:2]
    clean_authors = []
    generic = re.compile(r"^(редакция|редакция сайта|редакция [«\"]?.{0,20}|администратор|admin|administrator|staff|"
                         r"newsroom|editorial( team| staff)?|editor|the editors|web desk|news desk|online desk|"
                         r"la rédaction|rédaction|redaktion|redazione|redacción|staff reporter|our correspondent|"
                         r"desk|編集部|편집부|تحریریه|التحرير)$", re.I)
    for a in authors:
        a = strip_html(a)
        a = re.sub(r"^(by|автор[ы]?:?|par|von|por|di|текст:?)\s+", "", a, flags=re.I).strip(" ,;|")
        if a.startswith(("http", "@")) or generic.match(a.strip()):
            continue
        if 1 < len(a) <= 80 and a.lower() not in {x.lower() for x in clean_authors}:
            clean_authors.append(a)

    publisher = ""
    if art:
        pub = _names(art.get("publisher")) or _names(art.get("sourceOrganization"))
        publisher = pub[0] if pub else ""
    site_name = (_meta_get(meta, "og:site_name", "application-name", "publisher") or [""])[0]

    title = ""
    if art and art.get("headline"):
        title = strip_html(str(art["headline"]))
    title = title or (_meta_get(meta, "og:title", "twitter:title", "citation_title") or [""])[0] or strip_html(c.title)

    published = None
    for cand in ([art.get("datePublished")] if art else []) + _meta_get(
            meta, "article:published_time", "og:article:published_time", "pubdate", "publishdate",
            "date", "dc.date", "dcterms.created", "citation_publication_date", "parsely-pub-date",
            "sailthru.date", "article.published", "datepublished"):
        published = parse_date(cand) if cand else None
        if published:
            break
    modified = None
    for cand in ([art.get("dateModified")] if art else []) + _meta_get(meta, "article:modified_time", "og:updated_time"):
        modified = parse_date(cand) if cand else None
        if modified:
            break

    # платный доступ
    paywall = None
    paywall_evidence = ""
    if art is not None:
        free = art.get("isAccessibleForFree")
        if isinstance(free, str):
            free = free.strip().lower() not in ("false", "no", "0")
        if free is False:
            paywall, paywall_evidence = True, "schema.org: isAccessibleForFree = false"
        elif free is True:
            paywall, paywall_evidence = False, "schema.org: isAccessibleForFree = true"
    tier_meta = _meta_get(meta, "article:content_tier")
    if tier_meta and tier_meta[0].lower() in ("locked", "metered"):
        paywall = True
        paywall_evidence = "article:content_tier = %s" % tier_meta[0]

    # синдикация
    based_on = ""
    if art:
        b = art.get("isBasedOn") or art.get("isBasedOnUrl")
        if isinstance(b, dict):
            b = b.get("url") or b.get("@id") or ""
        if isinstance(b, list) and b:
            b = b[0] if isinstance(b[0], str) else (b[0].get("url") if isinstance(b[0], dict) else "")
        based_on = b if isinstance(b, str) else ""
    original = original or (_meta_get(meta, "original-source", "syndication-source", "dc.source",
                                      "dcterms.source") or [""])[0]

    text_blocks = _main_blocks(c)
    lead = " ".join(t for _k, t in text_blocks[:3])[:900]
    credits = []
    m = _DATELINE.search(lead[:200]) or _DATELINE_RU.search(lead[:200])
    if m:
        credits.append({"name": m.group(1), "evidence": "агентская шапка в начале текста: «%s»" % m.group(0)[:90].strip()})
    full = " ".join(t for _k, t in text_blocks)
    reprint_marker = ""
    for part in (full[:3000], full[-1500:]):
        rm = _REPRINT_MARKERS.search(part)
        if rm:
            reprint_marker = part[max(0, rm.start() - 60):rm.end() + 120]
            break

    lang = c.lang or (_meta_get(meta, "og:locale", "content-language", "language") or [""])[0]
    desc = (_meta_get(meta, "og:description", "description", "twitter:description") or [""])[0]
    canon_host = host_of(canonical) if canonical else ""
    return {
        "url": url,
        "canonical": canonical,
        "canonical_domain": canon_host,
        "title": strip_html(title, 500),
        "description": strip_html(desc, 600),
        "site_name": strip_html(site_name, 120),
        "publisher": strip_html(publisher, 120),
        "authors": clean_authors[:8],
        "published": published,
        "modified": modified,
        "lang": (lang or "").split("-")[0].split("_")[0].lower()[:5],
        "paywall": paywall,
        "paywall_evidence": paywall_evidence,
        "original_source": original if original.startswith("http") else "",
        "based_on": based_on if based_on.startswith("http") else "",
        "credits": credits,
        "reprint_marker": strip_html(reprint_marker, 260),
        "lead": lead[:600],
        "feeds": feeds[:5],
        "wp_api": wp_api,
        "amp": amp,
        "jsonld_types": sorted({t for o in objs for t in _types(o)})[:12],
        "words": len(full.split()),
    }


def _main_blocks(c: _Collector):
    """Выбор основного контейнера: наибольший суммарный объём абзацев."""
    by = {}
    for cid, kind, txt in c.blocks:
        if kind == "p" and len(txt) >= 40:
            by[cid] = by.get(cid, 0) + len(txt)
    if not by:
        return [(k, t) for _c, k, t in c.blocks if len(t) >= 60][:40]
    best = max(by, key=by.get)
    total = by[best]
    # если текст разбит на несколько соседних контейнеров — добавим сопоставимые по объёму
    keep = {cid for cid, n in by.items() if cid == best or n >= total * 0.35}
    out = []
    for cid, kind, txt in c.blocks:
        if cid in keep and (len(txt) >= 25 or kind in ("h2", "h3")):
            out.append((kind, txt))
    return out[:400]


def extract_readable(html_text: str, url: str) -> dict:
    c = _parse(html_text)
    meta = extract_meta(html_text, url)
    blocks = _main_blocks(c)
    # убрать повтор заголовка
    t0 = (meta.get("title") or "").strip().lower()
    blocks = [(k, t) for k, t in blocks if not (k == "h1" or (t0 and t.strip().lower() == t0))]
    return {"meta": meta, "blocks": [{"k": k, "t": t} for k, t in blocks]}


_FEED_GUESSES = ("feed/", "rss/", "rss.xml", "feed.xml", "index.xml", "atom.xml", "rss", "feed")


def discover(html_text: str, url: str) -> dict:
    """Найти ленты и признаки WordPress на странице."""
    c = _parse(html_text[:600_000])
    feeds, wp_api = [], ""
    for l in c.links:
        rel = l.get("rel", "").lower()
        href = l.get("href", "")
        if not href:
            continue
        if "alternate" in rel and re.search(r"(rss|atom)", l.get("type", ""), re.I):
            u = urljoin(url, href)
            if not re.search(r"comments", u, re.I):
                feeds.append(u)
        elif rel == "https://api.w.org/":
            wp_api = urljoin(url, href)
    generator = " ".join(v for k, v in c.meta if k == "generator").lower()
    is_wp = bool(wp_api) or "wordpress" in generator or "/wp-content/" in html_text[:400_000]
    if is_wp and not wp_api:
        wp_api = urljoin(url, "/wp-json/")
    seen, uniq = set(), []
    for f in feeds:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return {"feeds": uniq[:4], "wp_api": wp_api, "wordpress": is_wp, "lang": c.lang,
            "title": strip_html(c.title, 160)}


def feed_guesses(base: str):
    base = base if base.endswith("/") else base + "/"
    return [urljoin(base, g) for g in _FEED_GUESSES]
