"""Разбор лент RSS 2.0 / RSS 1.0 (RDF) / Atom.

Ленты в интернете часто повреждены: неэкранированные «&», HTML-сущности, управляющие символы,
кодировки GBK/Shift_JIS/Windows-1251. Поэтому разбор идёт в три шага: очистка → xml.etree →
запасной разбор регулярными выражениями.
"""
from __future__ import annotations

import html
import html.entities
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from .util import parse_date, strip_html


class FeedItem(dict):
    """title, link, summary, ts, authors, categories, guid, source_name, source_url, related, image"""


_INVALID_XML = re.compile("[^\u0009\u000a\u000d -퟿-�\U00010000-\U0010ffff]")
_BARE_AMP = re.compile(r"&(?!(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);)")
_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.I)
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


def decode_bytes(data: bytes, http_charset: str | None = None) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    m = re.search(rb"<\?xml[^>]*encoding\s*=\s*[\"']([\w\-.:]+)[\"']", data[:500], re.I)
    candidates = [m.group(1).decode("ascii", "ignore") if m else None, http_charset, "utf-8"]
    for enc in candidates:
        if not enc:
            continue
        enc = enc.lower()
        enc = {"gb2312": "gb18030", "gbk": "gb18030", "euc-kr": "cp949", "ks_c_5601-1987": "cp949",
               "x-sjis": "shift_jis", "windows-31j": "cp932", "iso-8859-1": "cp1252"}.get(enc, enc)
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def _clean_xml(text: str) -> str:
    text = _XML_DECL.sub("", text, count=1)
    text = _INVALID_XML.sub("", text)

    def ent(m):
        name = m.group(1)
        if name in _XML_ENTITIES:
            return m.group(0)
        cp = html.entities.name2codepoint.get(name)
        return "&#%d;" % cp if cp else "&amp;" + name + ";"
    text = _ENTITY.sub(ent, text)
    text = _BARE_AMP.sub("&amp;", text)
    return text.lstrip()


def _local(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.split(":")[-1].lower()


def _text(el) -> str:
    if el is None:
        return ""
    # Atom: <title type="html"> или вложенный XHTML
    if len(el):
        return "".join(el.itertext()).strip()
    return (el.text or "").strip()


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _first(el, *names):
    for n in names:
        for c in el:
            if _local(c.tag) == n:
                return c
    return None


def parse_feed(data: bytes, base_url: str = "", http_charset: str | None = None) -> dict:
    """Вернуть {"title", "link", "items": [FeedItem...], "kind"}. Исключения не бросает:
    при полной неудаче — пустой список и kind="invalid"."""
    text = decode_bytes(data, http_charset)
    head = text[:1500].lower()
    if "<html" in head and "<rss" not in head and "<feed" not in head and "<rdf" not in head:
        return {"title": "", "link": "", "items": [], "kind": "html"}
    cleaned = _clean_xml(text)
    try:
        root = ET.fromstring(cleaned)
        return _from_tree(root, base_url)
    except ET.ParseError:
        items = _regex_items(cleaned, base_url)
        return {"title": "", "link": "", "items": items, "kind": "regex" if items else "invalid"}


def _from_tree(root, base_url: str) -> dict:
    kind = _local(root.tag)
    out = {"title": "", "link": "", "items": [], "kind": kind}
    if kind == "feed":  # Atom
        out["title"] = _text(_first(root, "title"))
        out["link"] = _atom_link(root, base_url)
        for e in _children(root, "entry"):
            out["items"].append(_atom_entry(e, base_url))
        return out
    channel = _first(root, "channel")
    if channel is not None:
        out["title"] = _text(_first(channel, "title"))
        out["link"] = _text(_first(channel, "link"))
    containers = [root] + ([channel] if channel is not None else [])
    for c in containers:
        for it in _children(c, "item"):
            out["items"].append(_rss_item(it, base_url))
    if kind not in ("rss", "rdf") and not out["items"]:
        out["kind"] = "invalid"
    return out


def _atom_link(el, base_url):
    best = ""
    for l in _children(el, "link"):
        rel = (l.get("rel") or "alternate").lower()
        href = l.get("href") or ""
        if rel == "alternate" and href:
            return urljoin(base_url, href)
        if not best and href:
            best = href
    return urljoin(base_url, best) if best else ""


def _atom_entry(e, base_url) -> FeedItem:
    summary = _text(_first(e, "summary")) or _text(_first(e, "content"))
    authors = [_text(_first(a, "name")) for a in _children(e, "author")]
    cats = [c.get("term") or c.get("label") or "" for c in _children(e, "category")]
    date = _text(_first(e, "published")) or _text(_first(e, "updated")) or _text(_first(e, "date"))
    return FeedItem(
        title=strip_html(_text(_first(e, "title")), 400),
        link=_atom_link(e, base_url),
        summary=strip_html(summary, 600),
        ts=parse_date(date),
        authors=[a for a in authors if a],
        categories=[c for c in cats if c],
        guid=_text(_first(e, "id")),
        source_name="", source_url="", related=[], image="",
    )


def _rss_item(it, base_url) -> FeedItem:
    link = _text(_first(it, "link"))
    guid_el = _first(it, "guid")
    guid = _text(guid_el)
    if not link and guid and guid_el is not None and (guid_el.get("isPermaLink", "true").lower() != "false") \
            and guid.startswith("http"):
        link = guid
    if not link:
        l = _first(it, "link")
        if l is not None and l.get("href"):
            link = l.get("href")
    raw_desc = _text(_first(it, "description"))
    content = _text(_first(it, "encoded"))  # content:encoded
    summary = raw_desc or content
    authors = []
    for n in ("creator", "author"):
        for a in _children(it, n):
            v = strip_html(_text(a) or _text(_first(a, "name")))
            if v:
                authors.extend(_split_authors(v))
    cats = [strip_html(_text(c)) for c in _children(it, "category")] + \
           [strip_html(_text(c)) for c in _children(it, "subject")]
    date = _text(_first(it, "pubdate")) or _text(_first(it, "date")) or _text(_first(it, "published")) \
        or _text(_first(it, "updated")) or _text(_first(it, "issued"))
    src = _first(it, "source")
    image = ""
    for c in it:
        ln = _local(c.tag)
        if ln in ("content", "thumbnail", "enclosure") and (c.get("url") or "").startswith("http"):
            if (c.get("type") or "image").startswith("image") or ln == "thumbnail":
                image = c.get("url")
                break
    return FeedItem(
        title=strip_html(_text(_first(it, "title")), 400),
        link=urljoin(base_url, link) if link else "",
        summary=strip_html(summary, 600),
        summary_html=raw_desc[:4000],
        ts=parse_date(date),
        authors=authors,
        categories=[c for c in cats if c],
        guid=guid,
        source_name=_text(src) if src is not None else "",
        source_url=(src.get("url") or "") if src is not None else "",
        related=[], image=image,
    )


_AUTHOR_SPLIT = re.compile(r"\s*(?:,|;| and | и | et | und | y | e |&)\s*")


def _split_authors(s: str):
    s = re.sub(r"^\s*(?:by|автор[ы]?:?|par|von|por|di)\s+", "", s, flags=re.I)
    s = re.sub(r"\S+@\S+\s*\(([^)]+)\)", r"\1", s)  # «mail@x (Имя)»
    parts = [p.strip() for p in _AUTHOR_SPLIT.split(s) if p.strip()]
    return [p for p in parts if 1 < len(p) <= 80][:8]


# ---------------------------------------------------------------- запасной разбор

_RX_BLOCK = re.compile(r"<(item|entry)\b[^>]*>(.*?)</\1\s*>", re.S | re.I)


def _rx_tag(block: str, *names) -> str:
    for n in names:
        m = re.search(r"<(?:\w+:)?%s\b[^>]*>(.*?)</(?:\w+:)?%s\s*>" % (n, n), block, re.S | re.I)
        if m:
            v = m.group(1).strip()
            cm = re.match(r"^<!\[CDATA\[(.*?)\]\]>$", v, re.S)
            return cm.group(1) if cm else html.unescape(v)
    return ""


def _regex_items(text: str, base_url: str):
    items = []
    for m in _RX_BLOCK.finditer(text):
        b = m.group(2)
        link = _rx_tag(b, "link")
        if not link:
            lm = re.search(r"<link\b[^>]*href=[\"']([^\"']+)", b, re.I)
            link = html.unescape(lm.group(1)) if lm else ""
        if not link:
            g = _rx_tag(b, "guid", "id")
            link = g if g.startswith("http") else ""
        desc = _rx_tag(b, "description", "summary", "content", "encoded")
        items.append(FeedItem(
            title=strip_html(_rx_tag(b, "title"), 400),
            link=urljoin(base_url, link.strip()) if link else "",
            summary=strip_html(desc, 600),
            summary_html=desc[:4000],
            ts=parse_date(_rx_tag(b, "pubDate", "published", "updated", "date")),
            authors=_split_authors(strip_html(_rx_tag(b, "creator", "author", "name"))),
            categories=[], guid=_rx_tag(b, "guid", "id"),
            source_name=strip_html(_rx_tag(b, "source")), source_url="", related=[], image="",
        ))
    return [i for i in items if i["title"] or i["link"]]


# ---------------------------------------------------------------- Google News

_GN_LI = re.compile(r"<li>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>(?:&nbsp;|\s|\xa0)*"
                    r"<font[^>]*>(.*?)</font>", re.S | re.I)


def google_related(desc_html: str):
    """Из описания элемента Google News (кластер «Полное освещение») извлечь связанные публикации."""
    if not desc_html or "<li" not in desc_html.lower():
        return []
    out = []
    for m in _GN_LI.finditer(html.unescape(desc_html) if "&lt;" in desc_html else desc_html):
        out.append({"url": html.unescape(m.group(1)), "title": strip_html(m.group(2), 300),
                    "source": strip_html(m.group(3))})
    return out[:12]
