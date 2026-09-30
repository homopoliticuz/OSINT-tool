"""Сборка web/assets/oko-data.js — встроенные данные для автономного режима (файл открыт без сервера)."""
from __future__ import annotations

import json
import os


def build(root: str) -> str:
    def load(name):
        with open(os.path.join(root, "data", name), encoding="utf-8") as f:
            return json.load(f)
    data = {
        "sources": load("sources.json")["sources"],
        "languages": load("languages.json")["languages"],
        "lexicon": load("lexicon.json")["entities"],
    }
    out = os.path.join(root, "web", "assets", "oko-data.js")
    body = ("/* Сгенерировано из data/*.json (okolib/webdata.py) — не редактировать вручную. */\n"
            "window.OKO_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, out)
    return out


def is_stale(root: str) -> bool:
    out = os.path.join(root, "web", "assets", "oko-data.js")
    if not os.path.exists(out):
        return True
    t = os.path.getmtime(out)
    return any(os.path.getmtime(os.path.join(root, "data", n)) > t
               for n in ("sources.json", "languages.json", "lexicon.json"))


def ensure(root: str) -> None:
    try:
        if is_stale(root):
            build(root)
    except OSError:
        pass  # папка может быть только для чтения — тогда используется существующий файл
