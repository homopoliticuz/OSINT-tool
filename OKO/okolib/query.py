"""Общие операции поиска для интерфейса, Telegram-бота и расписаний: расширение запроса на языки,
синхронный запуск поиска, ранжирование результатов (уровень источника, соответствие теме, дата)."""
from __future__ import annotations

import time

from . import person, relevance
from .lexicon import build_plan, plan_origins
from .net import FetchError
from .util import now_ts


def expand_query(app, data: dict) -> dict:
    langs = [l for l in (data.get("langs") or []) if l in app.languages.by_code]
    related = bool(data.get("related", True))
    persons = data.get("persons") or {}  # тема → идентификатор Wikidata человека
    no_translate = data.get("translate") is False

    def exp(lst, rel):
        out = []
        for t in [x for x in lst if str(x).strip()][:6]:
            if no_translate:
                out.append({"topic": t, "entity": None, "langs": {
                    c: {"q": [t], "m": [], "src": "original", "note": "без перевода (выбрано пользователем)"}
                    for c in langs + (["zh-Hant"] if "zh" in langs else [])}})
                continue
            qid = persons.get(t) if isinstance(persons, dict) else None
            if qid:
                try:
                    out.append(person.expansion(person.profile(app.http, str(qid)), langs))
                    continue
                except (FetchError, ValueError, KeyError):
                    pass
            out.append(app.lexicon.expand(t, langs, related=rel))
        return out
    topics = exp(data.get("topics") or [], related)
    context = exp(data.get("context") or [], False)
    exclude = exp(data.get("exclude") or [], False)
    plan = build_plan(topics, context, exclude, langs)
    return {"topics": topics, "context": context, "exclude": exclude, "plan": plan,
            "origins": plan_origins(topics, context)}


def default_langs(app) -> list:
    return [l["code"] for l in app.languages.items if l.get("core") or l.get("default")]


def run_sync(app, params: dict, timeout: float = 280):
    """Выполнить поиск без интерфейса и дождаться результата → SearchJob."""
    from .search import SearchJob  # локальный импорт: search зависит от этого модуля косвенно
    job = SearchJob(app, params)
    with app.jobs_lock:
        app.jobs[job.id] = job
    job.start()
    # поток событий никто не читает — разгружаем очередь, чтобы не копить память
    deadline = time.time() + timeout
    while not job.done.wait(0.5):
        while not job.events.empty():
            job.events.get_nowait()
        if time.time() > deadline:
            job.cancel.set()
    while not job.events.empty():
        job.events.get_nowait()
    return job


def topic_params(app, topic: str, hours: float = 24, langs=None, mode: str = "topic", **extra) -> dict:
    langs = langs or default_langs(app)
    exp = expand_query(app, {"topics": [topic], "context": [], "exclude": [], "langs": langs, "related": True})
    now = now_ts()
    p = {"mode": mode, "topics": [topic], "context": [], "exclude": [], "langs": langs, "plan": exp["plan"],
         "origins": exp["origins"], "t_from": int(now - hours * 3600), "t_to": now, "tz_offset": _tz_minutes()}
    p.update(extra)
    return p


def _tz_minutes() -> int:
    return int(-(time.altzone if time.localtime().tm_isdst > 0 else time.timezone) // 60)


def classify_lite(app, it: dict) -> dict:
    """Упрощённая серверная классификация (как в интерфейсе): уровень, издание, соответствие, статус."""
    src = app.registry.by_id.get(it.get("source_id") or "") or \
        (app.registry.lookup(it["url"]) if it.get("url") and not it.get("gn") else None) or \
        (app.registry.lookup(it["src_url"]) if it.get("src_url") else None)
    it["tier"] = (src.get("tier") or 3) if src else 4
    it["srcName"] = (src["name"] if src else "") or it.get("src_name") or it.get("domain") or "—"
    it["rel"] = relevance.level(it)
    fwd = (it.get("extra") or {}).get("fwd")
    it["status"] = "reprint" if fwd else ("primary" if src and src.get("type") in (
        "think_tank", "intl_org", "official", "academic", "ratings", "ngo", "agency") else "unknown")
    return it


def ranked(app, job, strict: bool = True, social: bool | None = None) -> list:
    items = [classify_lite(app, dict(x)) for x in job.items.values()]
    if social is not None:
        items = [x for x in items if (x.get("kind") == "social") == social]
    has_topic = any(p.get("q") for p in (job.params.get("plan") or {}).values())
    if strict and has_topic and job.params.get("mode") != "reports":
        items = [x for x in items if x["rel"] in relevance.STRICT_OK]
    items.sort(key=lambda x: (x["tier"], -(x.get("ts") or 0)))
    return items


__all__ = ["expand_query", "run_sync", "topic_params", "ranked", "classify_lite", "default_langs"]
