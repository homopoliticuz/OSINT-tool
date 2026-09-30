"""HTML-сводка результатов поиска (для Telegram-бота и расписаний): уровни авторитетности, статус
«первоисточник / перепубликация», по какому ключевому слову найдено, ссылки."""
from __future__ import annotations

import html
import time

TIER = {1: "A — высший", 2: "B — высокий", 3: "C — базовый", 4: "D — вне реестра"}
STATUS = {"primary": "✔ первоисточник", "reprint": "⟳ перепубликация", "unknown": "? статус не определён"}


def _fmt(ts) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else "без даты"


def build_html(title: str, subtitle: str, items: list, social: list | None = None) -> str:
    e = html.escape
    parts = []
    n = 0
    for tier in (1, 2, 3, 4):
        grp = [x for x in items if x.get("tier", 4) == tier]
        if not grp:
            continue
        parts.append("<h2>Уровень %s · %d</h2>" % (e(TIER[tier]), len(grp)))
        for x in grp:
            n += 1
            why = ""
            if x.get("kw") or x.get("term"):
                why = "найдено по: «%s»%s" % (e(x.get("kw") or ""), (" · термин «%s»" % e(x["term"])) if x.get("term") else "")
            parts.append(
                '<div class="it"><div class="n">%d</div><div><a class="t" href="%s" dir="auto">%s</a>'
                '<div class="m">%s · %s · %s</div><div class="s %s">%s</div>%s</div></div>' % (
                    n, e(x.get("url", "")), e(x.get("title", "")), e(x.get("srcName") or x.get("src_name") or ""),
                    e((x.get("lang") or "").upper()), e(_fmt(x.get("ts"))), e(x.get("status", "unknown")),
                    e(STATUS.get(x.get("status", "unknown"), "")), ('<div class="m">%s</div>' % why) if why else ""))
    if social:
        parts.append("<h2>Соцсети · %d</h2>" % len(social))
        for x in social:
            n += 1
            parts.append('<div class="it"><div class="n">%d</div><div><a class="t" href="%s" dir="auto">%s</a>'
                         '<div class="m">%s · %s</div></div></div>' % (
                             n, e(x.get("url", "")), e(x.get("title", "")), e(x.get("srcName") or ""), e(_fmt(x.get("ts")))))
    if not parts:
        parts.append("<p>За период материалов не найдено.</p>")
    return ("<!doctype html><html lang=ru><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>%s — ОКО</title><style>body{font:14px/1.5 -apple-system,'Segoe UI',Roboto,Arial,'Noto Sans',sans-serif;"
            "color:#111;max-width:860px;margin:18px auto;padding:0 14px}h1{font-size:20px;margin:4px 0}.k{letter-spacing:.3em;"
            "color:#8a6d1d;font-weight:600}h2{font-size:14px;border-bottom:1px solid #ccc;padding-bottom:3px;margin:20px 0 6px}"
            ".it{display:grid;grid-template-columns:30px 1fr;padding:6px 0;border-bottom:1px solid #eee}.n{color:#888;font-size:12px}"
            "a.t{color:#111;font-weight:600;text-decoration:none;unicode-bidi:plaintext}.m{color:#555;font-size:12px}"
            ".s{font-size:12px;font-weight:600}.s.primary{color:#137a53}.s.reprint{color:#a86a00}.s.unknown{color:#777}"
            "footer{margin-top:20px;color:#777;font-size:11px}</style></head><body><div class=k>ОКО</div><h1>%s</h1>"
            "<div>%s</div>%s<footer>Сформировано платформой ОКО %s. Статусы определены автоматически — проверяйте "
            "ключевые материалы по оригиналу.</footer></body></html>") % (
        e(title), e(title), e(subtitle), "".join(parts), e(time.strftime("%d.%m.%Y %H:%M")))


__all__ = ["build_html"]
