"""Режим «Доклады»: новые выпуски глобальных докладов и индексов (каталог data/reports.json).

* Google News — новости о выходе флагманских докладов (точные названия в кавычках, по 6 в запросе);
* Google News site: — публикации «report / index / outlook…» на сайтах организаций-авторов;
* RSS-ленты организаций-авторов — отбор материалов, похожих на доклады и индексы.

Каждому найденному материалу, в заголовке которого есть название доклада из каталога, присваивается
отметка report — интерфейс показывает, какой доклад вышел, и календарь ожидаемых выпусков.
"""
from __future__ import annotations

import json
import os
from functools import partial

from ..feedparse import parse_feed
from ..net import FetchError
from ..util import TermMatcher, detect_lang, norm_text, now_ts
from . import Task, make_item, or_group
from .gnews import _run as gnews_run

REPORT_WORDS = ["report", "index", "outlook", "survey", "yearbook", "review", "ranking", "barometer", "monitor",
                "доклад", "индекс", "обзор", "рейтинг", "ежегодник", "rapport", "bericht", "informe", "rapporto"]
_CAT = None


def catalog() -> dict:
    global _CAT
    if _CAT is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "data", "reports.json")
        with open(path, encoding="utf-8") as f:
            _CAT = json.load(f)
    return _CAT


class ReportMatcher:
    """Определить доклад каталога по заголовку материала."""

    def __init__(self):
        self.by_term = {}
        terms = []
        for r in catalog()["reports"]:
            for q in r.get("q") or []:
                self.by_term[norm_text(q)] = r["id"]
                terms.append(q)
        self.m = TermMatcher(terms)
        self.words = TermMatcher(REPORT_WORDS)

    def find(self, title: str, text: str = ""):
        t = self.m.find(title) or (self.m.find(text) if text else None)
        return self.by_term.get(t) if t else None

    def reportish(self, title: str) -> bool:
        return bool(self.words.find(title))


def tasks(ctx) -> list:
    cat = catalog()
    rm = ReportMatcher()
    ctx.report_matcher = rm
    out = []
    en = ctx.languages.by_code.get("en") or {}
    ed = (en.get("gnews") or [None])[0]
    names = []
    for r in cat["reports"]:
        names.extend(r.get("q") or [])
    ctx_terms = (ctx.plan.get("en") or {}).get("ctx", [])[:2] if ctx.report_topic else []
    if ed:
        for i in range(0, len(names), 6):
            chunk = names[i:i + 6]
            out.append(Task("reports", "rep:gn:%d" % (i // 6), "Доклады · Google News #%d" % (i // 6 + 1),
                            partial(_run_gn, ed=ed, terms=chunk, ctx_terms=ctx_terms), group="reports",
                            meta={"query": or_group(chunk) + ((" " + or_group(ctx_terms)) if ctx_terms else ""),
                                  "terms": chunk, "host": "news.google.com"}))
    # сайты организаций-авторов: адресный поиск «доклад/индекс» + их ленты
    ids = []
    for r in cat["reports"]:
        if r["src"] not in ids:
            ids.append(r["src"])
    domains = []
    for sid in ids:
        s = ctx.registry.by_id.get(sid)
        if not s or s.get("off"):
            continue
        domains.append(s["domains"][0])
        feeds = ctx.registry.feeds_for(s)
        if feeds:
            out.append(Task("reports", "rep:rss:" + sid, "Доклады · лента " + s["name"],
                            partial(_run_rss, source=s, feeds=feeds), group="reports",
                            meta={"query": "", "terms": [], "source": sid}))
    words = ["report", "index", "outlook", "survey", "yearbook"]
    if ed:
        for i in range(0, len(domains), 10):
            chunk = domains[i:i + 10]
            out.append(Task("reports", "rep:site:%d" % (i // 10), "Доклады · сайты организаций #%d" % (i // 10 + 1),
                            partial(_run_gn, ed=ed, terms=words, ctx_terms=ctx_terms, sites=chunk), group="reports",
                            meta={"query": or_group(words) + " site:(%s…)" % ", ".join(chunk[:3]), "terms": words,
                                  "host": "news.google.com"}))
    return out


def _mark(ctx, item) -> dict | None:
    rm = ctx.report_matcher
    rid = rm.find(item["title"], item.get("snippet", ""))
    if not rid and not rm.reportish(item["title"]):
        return None
    item["kind"] = "report"
    if rid:
        item.setdefault("extra", {})["report"] = rid
    if ctx.report_topic and ctx.topic_matcher:
        t = ctx.topic_matcher.find(item["title"]) or ctx.topic_matcher.find(item.get("snippet", ""))
        if t:
            item["extra"]["topic_hit"] = t
    item["hit"], item["term"] = "title", ""
    return item


def _run_gn(ctx, task, ed, terms, ctx_terms, sites=None) -> int:
    # Google News с отбором «похоже на доклад»
    return gnews_run(ctx, task, ed=ed, code="en", terms=terms, ctx_terms=ctx_terms, not_terms=[], sites=sites,
                     transform=lambda item: _mark(ctx, item))


def _run_rss(ctx, task, source, feeds) -> int:
    added, errors, ok = 0, [], 0
    for f in feeds[:2]:
        try:
            r = ctx.http.get(f, ttl=30 * 60 if now_ts() - ctx.t_to < 86400 else 6 * 3600, timeout=12, retries=1,
                             cancel=ctx.cancel)
            parsed = parse_feed(r.body, r.url, r.charset())
        except FetchError as e:
            errors.append(e)
            continue
        ok += 1
        for it in parsed["items"]:
            ts = it.get("ts")
            if not ts or ts < ctx.t_from or ts > ctx.t_to:
                continue
            item = make_item(url=it["link"], title=it["title"], ts=ts, lang=detect_lang(it["title"], "en"),
                             prov="reports", via="Доклады · " + source["name"], src_name=source["name"],
                             src_url="https://" + source["domains"][0], snippet=it.get("summary", ""),
                             source_id=source["id"])
            item = _mark(ctx, item)
            if item and ctx.add(item):
                added += 1
    if not ok and errors:
        raise errors[0]
    return added


__all__ = ["tasks", "catalog", "ReportMatcher"]
