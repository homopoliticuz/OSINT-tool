"""Персонализированный поиск: профиль человека по Wikidata (имя на всех языках поиска, должности,
гражданство, официальные страницы и аккаунты в соцсетях) — для поиска упоминаний в СМИ и соцсетях.

Используются только открытые данные Wikidata; ОКО не собирает персональные данные частных лиц.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlencode

from .net import FetchError
from .util import norm_text

API = "https://www.wikidata.org/w/api.php?"
TTL = 7 * 86400
LANGS = ["ru", "en", "uz", "fr", "de", "es", "it", "ko", "ja", "zh-hans", "zh-hant", "zh", "fa", "ar", "ur", "tr",
         "he", "hi", "kk", "pt"]
SOCIAL_PROPS = {
    "P2002": ("x", "X (Twitter)", "https://x.com/{}"),
    "P2013": ("facebook", "Facebook", "https://www.facebook.com/{}"),
    "P2003": ("instagram", "Instagram", "https://www.instagram.com/{}/"),
    "P3789": ("telegram", "Telegram", "https://t.me/{}"),
    "P3185": ("vk", "ВКонтакте", "https://vk.com/{}"),
    "P6634": ("linkedin", "LinkedIn", "https://www.linkedin.com/in/{}/"),
    "P2397": ("youtube", "YouTube", "https://www.youtube.com/channel/{}"),
}


def _claims(ent, prop):
    return ent.get("claims", {}).get(prop) or []


def _val(claim):
    return ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")


def _qid(v):
    return v.get("id") if isinstance(v, dict) else None


def _time(v):
    if isinstance(v, dict) and v.get("time"):
        m = re.match(r"[+-](\d{4})-(\d{2})-(\d{2})", v["time"])
        if m:
            y, mo, d = m.groups()
            prec = v.get("precision", 11)
            return y if prec <= 9 else (y + "-" + mo if prec == 10 else "%s-%s-%s" % (y, mo, d))
    return ""


def search(http, name: str, lang: str = "ru", limit: int = 8) -> list:
    """Кандидаты-люди по имени: [{"id", "label", "description"}]."""
    name = (name or "").strip()
    if len(name) < 2:
        return []
    data = http.get_json(API + urlencode({"action": "wbsearchentities", "search": name, "language": lang,
                                          "uselang": lang, "type": "item", "limit": 15, "format": "json"}),
                         ttl=TTL, timeout=12, retries=1)
    ids = [r["id"] for r in data.get("search") or []]
    if not ids:
        return []
    ents = http.get_json(API + urlencode({"action": "wbgetentities", "ids": "|".join(ids[:15]),
                                          "props": "labels|descriptions|claims", "languages": "ru|en",
                                          "format": "json"}), ttl=TTL, timeout=12, retries=1).get("entities") or {}
    out = []
    for qid in ids:
        e = ents.get(qid) or {}
        if not any(_qid(_val(c)) == "Q5" for c in _claims(e, "P31")):
            continue  # только люди
        lab = e.get("labels", {})
        desc = e.get("descriptions", {})
        out.append({"id": qid, "label": (lab.get(lang) or lab.get("ru") or lab.get("en") or {}).get("value", qid),
                    "description": (desc.get(lang) or desc.get("ru") or desc.get("en") or {}).get("value", ""),
                    "born": _time(_val((_claims(e, "P569") or [{}])[0]) or {})})
        if len(out) >= limit:
            break
    return out


def profile(http, qid: str) -> dict:
    if not re.fullmatch(r"Q\d+", qid or ""):
        raise ValueError("некорректный идентификатор Wikidata")
    e = http.get_json(API + urlencode({"action": "wbgetentities", "ids": qid,
                                       "props": "labels|aliases|descriptions|claims|sitelinks",
                                       "languages": "|".join(LANGS), "format": "json"}),
                      ttl=TTL, timeout=12, retries=1)["entities"][qid]
    refs = set()

    def items(prop, quals=()):
        out = []
        for c in _claims(e, prop):
            q = _qid(_val(c))
            if not q:
                continue
            refs.add(q)
            row = {"id": q}
            for qp, key in quals:
                qs = (c.get("qualifiers") or {}).get(qp) or []
                if qs:
                    row[key] = _time(((qs[0].get("datavalue") or {}).get("value")) or {})
            out.append(row)
        return out
    positions = items("P39", (("P580", "from"), ("P582", "to")))
    citizenship = items("P27")
    employers = items("P108", (("P580", "from"), ("P582", "to")))
    parties = items("P102")
    education = items("P69")
    labels = {}
    if refs:
        ids = list(refs)[:50]
        ents = http.get_json(API + urlencode({"action": "wbgetentities", "ids": "|".join(ids), "props": "labels",
                                              "languages": "ru|en", "format": "json"}),
                             ttl=TTL, timeout=12, retries=1).get("entities") or {}
        for k, v in ents.items():
            lab = v.get("labels", {})
            labels[k] = (lab.get("ru") or lab.get("en") or {}).get("value", k)
    for lst in (positions, citizenship, employers, parties, education):
        for row in lst:
            row["label"] = labels.get(row["id"], row["id"])
    socials = []
    for prop, (pid, name, tpl) in SOCIAL_PROPS.items():
        for c in _claims(e, prop)[:2]:
            v = _val(c)
            if isinstance(v, str) and v:
                socials.append({"platform": pid, "name": name, "handle": v, "url": tpl.format(quote(v, safe="@._-"))})
    sites = [v for v in (_val(c) for c in _claims(e, "P856")) if isinstance(v, str)][:3]
    wiki = []
    for key, lang in (("ruwiki", "ru"), ("enwiki", "en"), ("uzwiki", "uz")):
        sl = (e.get("sitelinks") or {}).get(key)
        if sl:
            wiki.append({"lang": lang, "title": sl["title"],
                         "url": "https://%s.wikipedia.org/wiki/%s" % (lang, quote(sl["title"].replace(" ", "_")))})
    names = {}
    for code in LANGS:
        key = {"zh-hans": "zh", "zh-hant": "zh-Hant"}.get(code, code)
        vals = []
        lab = e.get("labels", {}).get(code, {}).get("value")
        if lab:
            vals.append(re.sub(r"\s*\(.*?\)\s*$", "", lab))
        for al in e.get("aliases", {}).get(code, [])[:6]:
            v = al.get("value", "")
            if len(v.split()) >= 2 and len(v) >= 6:  # только полные имена — фамилия отдельно слишком неоднозначна
                vals.append(v)
        if vals:
            seen, uniq = set(), []
            for v in vals:
                if norm_text(v) not in seen:
                    seen.add(norm_text(v))
                    uniq.append(v)
            if key == "zh" and names.get("zh"):
                continue
            names[key] = uniq[:3]
    lab = e.get("labels", {})
    desc = e.get("descriptions", {})
    return {
        "id": qid, "label": (lab.get("ru") or lab.get("en") or {}).get("value", qid),
        "description": (desc.get("ru") or desc.get("en") or {}).get("value", ""),
        "born": _time(_val((_claims(e, "P569") or [{}])[0]) or {}),
        "died": _time(_val((_claims(e, "P570") or [{}])[0]) or {}),
        "citizenship": citizenship, "positions": positions[-12:], "employers": employers[-8:],
        "parties": parties, "education": education[:5], "websites": sites, "socials": socials, "wikipedia": wiki,
        "names": names, "wikidata": "https://www.wikidata.org/wiki/" + qid,
    }


def expansion(prof: dict, langs) -> dict:
    """Расширение запроса для поиска упоминаний человека (формат Lexicon.expand)."""
    out = {"topic": prof["label"], "entity": {"id": prof["id"], "label": prof["label"], "source": "Wikidata",
                                             "description": prof.get("description", "")}, "langs": {}}
    want = list(langs) + (["zh-Hant"] if "zh" in langs else [])
    for code in want:
        vals = prof["names"].get(code) or (prof["names"].get("zh") if code == "zh-Hant" else None)
        if vals:
            out["langs"][code] = {"q": vals, "m": [], "src": "wikidata", "note": "Wikidata " + prof["id"]}
        else:
            base = prof["names"].get("en") or [prof["label"]]
            out["langs"][code] = {"q": base[:1], "m": [], "src": "original",
                                  "note": "нет написания на этом языке в Wikidata — используется английское"}
    return out


__all__ = ["search", "profile", "expansion", "FetchError"]
