"""Соответствие материала теме запроса («строго по теме»).

Поисковые системы (Google News, GDELT, Bing, поиск по сайтам) возвращают и статьи, где тема
упомянута один раз где-то в тексте или в боковой колонке «читайте также». ОКО различает:

  title    — ключевое слово (перевод, словоформа) в заголовке;
  rtitle   — связанный термин (столица, глава государства, город) в заголовке;
  text     — ключевое слово в аннотации;
  rtext    — связанный термин в аннотации;
  body     — страница проверена: тема упоминается в тексте по существу (2+ абзаца или в начале);
  passing  — страница проверена: одно упоминание вскользь;
  absent   — страница проверена: упоминания не найдено;
  unverified — термин виден только поисковой системе, страница ещё не проверена.

Режим «Строго по теме» показывает title, rtitle, text, rtext и body. Логика совпадает с oko-core.js.
"""
from __future__ import annotations

import re

from .util import TermMatcher, norm_text

STRICT_OK = {"title", "rtitle", "text", "rtext", "body"}
LABELS = {
    "title": "ключевое слово в заголовке",
    "rtitle": "связанный термин в заголовке",
    "text": "ключевое слово в аннотации",
    "rtext": "связанный термин в аннотации",
    "body": "тема в тексте статьи (проверено)",
    "passing": "упоминание вскользь (проверено)",
    "absent": "на странице не найдено (проверено)",
    "unverified": "только по данным поисковика (не проверено)",
}
_WORD = re.compile(r"[\w'’]", re.UNICODE)


def level(item: dict, mentions: dict | None = None) -> str:
    hit = item.get("hit") or "engine"
    related = item.get("role") == "related"
    if hit == "title":
        return "rtitle" if related else "title"
    if hit == "text":
        return "rtext" if related else "text"
    m = mentions if mentions is not None else item.get("mentions")
    if not m or m.get("paras") is None:
        return "unverified"
    if m.get("in_title") or m.get("hits", 0) >= 2 or m.get("in_lead") or (m.get("hits") and m.get("first", 99) <= 1):
        return "body"
    if m.get("hits", 0) == 1:
        return "passing"
    return "absent"


def strict_ok(item: dict, mentions: dict | None = None) -> bool:
    return level(item, mentions) in STRICT_OK


def locate(text: str, term: str):
    """Позиция нормализованного термина в исходном тексте → (начало, конец слова) или None."""
    if not text or not term:
        return None
    fold = []
    for ch in text:
        n = norm_text(ch)
        fold.append(n if len(n) == len(ch) else ch)
    hay = "".join(fold)
    if len(hay) != len(text):
        return None
    cjk = bool(re.match(r"[぀-ヿ㐀-鿿가-힯]", term))
    start = 0
    while True:
        i = hay.find(term, start)
        if i < 0:
            return None
        if cjk or i == 0 or not _WORD.match(hay[i - 1]) or re.match(r"[֐-ۿ]", term):
            break
        start = i + 1
    j = i + len(term)
    if not cjk:
        while j < len(text) and _WORD.match(text[j]):
            j += 1
    return i, j


def excerpt(text: str, term: str, width: int = 120) -> str:
    pos = locate(text, term)
    if not pos:
        return text[: width * 2].strip() + ("…" if len(text) > width * 2 else "")
    a, b = pos
    s, e = max(0, a - width), min(len(text), b + width)
    if s > 0:
        sp = text.find(" ", s)
        s = sp + 1 if 0 <= sp < a else s
    if e < len(text):
        sp = text.rfind(" ", b, e)
        e = sp if sp > b else e
    return ("…" if s > 0 else "") + text[s:e].strip() + ("…" if e < len(text) else "")


def mention_stats(blocks, title: str, lead: str, terms, ctx_terms=None) -> dict:
    """Сколько абзацев статьи упоминают тему; цитаты с упоминанием; есть ли термин контекста."""
    matcher = TermMatcher(terms or [])
    ctxm = TermMatcher(ctx_terms) if ctx_terms else None
    paras = [b["t"] for b in blocks or [] if b.get("t") and b.get("k") != "h1"]
    hits = []
    for i, t in enumerate(paras):
        term = matcher.find(t)
        if term:
            hits.append((i, term, t))
    res = {
        "paras": len(paras),
        "hits": len(hits),
        "first": hits[0][0] if hits else None,
        "in_title": bool(matcher.find(title or "")),
        "in_lead": bool(lead and matcher.find(lead)),
        "terms": sorted({h[1] for h in hits})[:6],
        "samples": [excerpt(t, term) for _, term, t in hits[:2]],
    }
    if ctxm:
        res["ctx"] = bool(ctxm.find(title or "") or any(ctxm.find(t) for t in paras))
    return res


__all__ = ["level", "strict_ok", "locate", "excerpt", "mention_stats", "LABELS", "STRICT_OK"]
