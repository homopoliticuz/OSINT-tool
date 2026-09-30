"""Провайдеры сбора ОКО. Каждый провайдер формирует список задач (Task) для конкретного поиска.

Задача получает контекст поиска (search.SearchCtx) и добавляет найденные материалы через
ctx.add(item). Ошибка одной задачи не влияет на остальные — она отображается в журнале.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from ..util import canonical_url, host_of, norm_text, short_hash


@dataclass
class Task:
    provider: str
    key: str
    label: str
    fn: Callable
    group: str = ""
    meta: dict = field(default_factory=dict)


def make_item(*, url: str, title: str, ts, lang: str | None, prov: str, via: str,
              src_name: str = "", src_url: str = "", snippet: str = "", authors=None,
              source_id: str | None = None, country: str | None = None, gn: bool = False,
              hit: str = "engine", term: str = "", kind: str = "news", pdf: str = "",
              related=None, prec: str = "", extra: dict | None = None) -> dict:
    if gn:
        domain = host_of(src_url) if src_url else ""
    else:
        domain = host_of(url) or (host_of(src_url) if src_url else "")
    cu = canonical_url(url) if url and not gn else ""
    if gn:
        ident = "g" + short_hash("%s|%s" % (domain, norm_text(title)))
    else:
        ident = "u" + short_hash(cu or url or title)
    return {
        "id": ident,
        "url": url,
        "curl": cu,
        "gn": gn,
        "title": title.strip(),
        "snippet": (snippet or "").strip(),
        "ts": ts,
        "prec": prec,
        "lang": lang,
        "src_name": (src_name or "").strip(),
        "src_url": src_url or "",
        "domain": domain,
        "source_id": source_id,
        "authors": [a for a in (authors or []) if a][:10],
        "prov": [prov],
        "via": [via],
        "hit": hit,
        "term": term,
        "country": country,
        "kind": kind,
        "pdf": pdf or "",
        "related": related or [],
        "extra": extra or {},
    }


def quote_term(t: str, engine: str = "google") -> str:
    t = t.replace('"', "").replace("(", " ").replace(")", " ").strip()
    if not t:
        return ""
    if re.search(r"[\s\-:/.,;&+]", t) or (engine == "gdelt" and not t.isascii()):
        return '"%s"' % t
    return t


def or_group(terms, engine: str = "google") -> str:
    parts = [quote_term(t, engine) for t in terms]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def query_meta(terms, ctx_terms=None, not_terms=None, suffix: str = "", engine: str = "google") -> dict:
    """Читаемый запрос задачи и его термины — для пояснения «найдено по запросу» в карточке."""
    q = or_group(list(terms or []), engine)
    if ctx_terms:
        q += " " + or_group(list(ctx_terms), engine)
    for x in not_terms or []:
        qt = quote_term(x, engine)
        if qt:
            q += " -" + qt
    if suffix:
        q += " " + suffix
    return {"query": q.strip(), "terms": list(terms or [])}
