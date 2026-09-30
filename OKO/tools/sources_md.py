#!/usr/bin/env python3
"""Сформировать SOURCES.md — справочник реестра источников ОКО (из data/sources.json)."""
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from okolib.registry import TYPE_LABELS  # noqa: E402

COUNTRY = {"US": "США", "GB": "Великобритания", "RU": "Россия", "CN": "Китай", "UZ": "Узбекистан", "KZ": "Казахстан",
           "KG": "Кыргызстан", "TJ": "Таджикистан", "TM": "Туркменистан", "AF": "Афганистан", "IR": "Иран",
           "PK": "Пакистан", "IN": "Индия", "TR": "Турция", "DE": "Германия", "FR": "Франция", "IT": "Италия",
           "ES": "Испания", "JP": "Япония", "KR": "Республика Корея", "SA": "Саудовская Аравия", "AE": "ОАЭ",
           "QA": "Катар", "IL": "Израиль", "EG": "Египет", "AZ": "Азербайджан", "GE": "Грузия", "CH": "Швейцария",
           "AT": "Австрия", "BE": "Бельгия", "NL": "Нидерланды", "SE": "Швеция", "LV": "Латвия", "HK": "Гонконг",
           "TW": "Тайвань", "SG": "Сингапур", "AU": "Австралия", "AR": "Аргентина", "MX": "Мексика",
           "INT": "Международные организации", "EU": "Европейский союз"}
TIER = {1: "A", 2: "B", 3: "C"}


def main():
    with open(os.path.join(ROOT, "data", "sources.json"), encoding="utf-8") as f:
        src = json.load(f)["sources"]
    by_country = defaultdict(list)
    for s in src:
        by_country[s["country"]].append(s)
    tiers = Counter(s["tier"] for s in src)
    types = Counter(s["type"] for s in src)
    out = ["# Реестр источников ОКО", "",
           "Сгенерировано `tools/sources_md.py` из `data/sources.json`. Правки уровней и новые источники удобнее вносить "
           "в интерфейсе (раздел «Источники»).", "",
           "**Всего: %d** · уровень A — %d · B — %d · C — %d · из ваших закладок — %d" % (
               len(src), tiers[1], tiers[2], tiers[3], sum(1 for s in src if s.get("bm"))), "",
           "По типам: " + " · ".join("%s — %d" % (TYPE_LABELS[t], n) for t, n in types.most_common()), "",
           "Обозначения: 🔖 — из закладок; ЦА — специализация на Центральной Азии; 💰 — платный доступ; "
           "гос. — государственное СМИ; гос. фин. — государственное финансирование.", ""]
    for cc in sorted(by_country, key=lambda c: (c != "UZ", c != "INT", COUNTRY.get(c, c))):
        items = sorted(by_country[cc], key=lambda s: (s["tier"], s["type"], s["name"].lower()))
        out += ["## %s (%s) — %d" % (COUNTRY.get(cc, cc), cc, len(items)), "",
                "| Ур. | Источник | Сайт | Тип | Языки | Отметки |", "|---|---|---|---|---|---|"]
        for s in items:
            marks = []
            if s.get("bm"):
                marks.append("🔖 " + s["bm"])
            if s.get("ca"):
                marks.append("ЦА")
            if s.get("paywall"):
                marks.append("💰")
            if s.get("state") == "control":
                marks.append("гос.")
            elif s.get("state") == "public":
                marks.append("гос. фин.")
            if s.get("agg"):
                marks.append("агрегатор")
            if s.get("off"):
                marks.append("отключён")
            name = s["name"].replace("|", "/")
            out.append("| %s | %s | %s | %s | %s | %s |" % (
                TIER[s["tier"]], name, s["domains"][0], TYPE_LABELS.get(s["type"], s["type"]), " ".join(s["lang"]),
                ", ".join(marks)))
        out.append("")
    with open(os.path.join(ROOT, "SOURCES.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("SOURCES.md:", len(src), "sources")


if __name__ == "__main__":
    main()
