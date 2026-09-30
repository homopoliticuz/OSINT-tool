"""Мультиязычное расширение запроса.

Порядок: пользовательский глоссарий → встроенный словарь (data/lexicon.json) → Wikidata
(точные названия сущностей на всех языках) → машинный перевод (Google, запасной MyMemory) →
исходное слово. Для каждого языка возвращаются поисковые формы (q) и основы для локальной
фильтрации (m), а также источник перевода — аналитик видит и может исправить каждый термин.
"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from .net import FetchError, HttpClient
from .util import detect_lang, norm_text

WIKIDATA_LANG = {"zh": "zh-hans", "zh-Hant": "zh-hant", "uz": "uz", "kk": "kk"}
MT_LANG = {"zh": "zh-CN", "zh-Hant": "zh-TW", "he": "iw"}
TTL_FOREVER = 3600 * 24 * 365


class Languages:
    def __init__(self, path: str):
        with open(path, encoding="utf-8") as f:
            self.items = json.load(f)["languages"]
        self.by_code = {l["code"]: l for l in self.items}

    def codes(self):
        return [l["code"] for l in self.items]


class Lexicon:
    def __init__(self, path: str, http: HttpClient, glossary_getter=None):
        with open(path, encoding="utf-8") as f:
            self.entities = json.load(f)["entities"]
        self.http = http
        self.glossary_getter = glossary_getter or (lambda: {})
        self.by_id = {e["id"]: e for e in self.entities}
        self._index = {}
        for e in self.entities:
            keys = [e["label"]] + e.get("aliases", [])
            if e.get("kind") != "theme":  # тему находим только по названию: «газ» — не вся «Энергетика»
                for terms in e.get("terms", {}).values():
                    keys.extend(terms)
            for k in keys:
                self._index.setdefault(norm_text(k), e["id"])

    def themes(self) -> list:
        return [{"id": e["id"], "label": e["label"]} for e in self.entities if e.get("kind") == "theme"]
        self._lock = threading.Lock()

    # ------------------------------------------------------------ поиск сущности
    def find_entity(self, text: str):
        n = norm_text(text)
        if n in self._index:
            return self.by_id[self._index[n]]
        # падежные формы: «Узбекистана», «Узбекистане» → основа словаря
        for key, eid in self._index.items():
            if len(key) >= 5 and n.startswith(key) and len(n) - len(key) <= 3 and " " not in n[len(key):]:
                return self.by_id[eid]
        return None

    # ------------------------------------------------------------ основной метод
    def expand(self, topic: str, langs, related: bool = True, allow_network: bool = True) -> dict:
        """Вернуть {"topic", "entity", "langs": {code: {"q": [...], "m": [...], "src": ..., "note": ...}}}."""
        topic = (topic or "").strip()
        out = {"topic": topic, "entity": None, "langs": {}}
        if not topic:
            return out
        want = list(dict.fromkeys(langs))
        need_hant = "zh" in want
        glossary = self.glossary_getter().get(norm_text(topic), {})
        ent = self.find_entity(topic)
        if ent:
            out["entity"] = {"id": ent["id"], "label": ent["label"], "source": "словарь ОКО"}
        missing = []
        for code in want + (["zh-Hant"] if need_hant else []):
            if code in glossary and glossary[code]:
                out["langs"][code] = {"q": list(glossary[code]), "m": [], "src": "user",
                                      "note": "задано вручную"}
                continue
            if ent and ent.get("terms", {}).get(code):
                q = list(ent["terms"][code])
                m = list(ent.get("match", {}).get(code, []))
                rel = {}  # связанный термин → к чему относится (столица, глава государства, города…)
                if related:
                    for rid in ent.get("related", []):
                        r = self.by_id.get(rid)
                        if r and r.get("terms", {}).get(code):
                            t0 = r["terms"][code][0]
                            q.append(t0)
                            rel.setdefault(t0, r["label"])
                            for x in r.get("match", {}).get(code, []):
                                m.append(x)
                                rel.setdefault(x, r["label"])
                    for x in ent.get("extra_match", {}).get(code, []):
                        m.append(x)
                        rel.setdefault(x, "")
                out["langs"][code] = {"q": _uniq(q), "m": _uniq(m), "src": "lexicon", "note": "словарь ОКО",
                                      "rel": rel}
            else:
                missing.append(code)
        if missing and allow_network:
            self._fill_network(topic, missing, out)
        for code in missing:
            if code not in out["langs"]:
                out["langs"][code] = {"q": [topic], "m": [], "src": "original",
                                      "note": "перевод недоступен — используется исходное написание"}
        return out

    def _fill_network(self, topic: str, codes, out: dict) -> None:
        src_lang = detect_lang(topic, "ru") or "ru"
        wd = None
        try:
            wd = self.wikidata(topic, src_lang)
        except FetchError:
            wd = None
        if wd:
            out["entity"] = out["entity"] or {"id": wd["id"], "label": wd.get("label") or topic,
                                              "description": wd.get("description", ""), "source": "Wikidata"}
            for code in codes:
                terms = wd["labels"].get(code, [])
                if terms:
                    out["langs"][code] = {"q": terms[:3], "m": [], "src": "wikidata",
                                          "note": "Wikidata %s" % wd["id"]}
        rest = [c for c in codes if c not in out["langs"]]
        if not rest:
            return
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(lambda c: (c, self.translate(topic, src_lang, c)), rest))
        for code, tr in results:
            if tr and tr["text"]:
                q = [tr["text"]]
                if norm_text(tr["text"]) != norm_text(topic) and _same_script(topic, code):
                    q.append(topic)
                out["langs"][code] = {"q": _uniq(q), "m": [], "src": "mt", "note": "машинный перевод (%s)" % tr["engine"]}

    # ------------------------------------------------------------ Wikidata
    def wikidata(self, text: str, lang: str):
        """Найти сущность Wikidata, точно совпадающую с запросом, и вернуть её названия на языках."""
        if len(text) < 2 or len(text) > 80:
            return None
        cased = bool(re.search(r"[A-Za-zА-Яа-яЁё]", text))
        if cased and text[:1].islower() and " " not in text:
            return None  # нарицательное слово — лучше машинный перевод
        url = "https://www.wikidata.org/w/api.php?" + urlencode({
            "action": "wbsearchentities", "search": text, "language": WIKIDATA_LANG.get(lang, lang),
            "uselang": lang, "type": "item", "limit": 7, "format": "json", "origin": "*"})
        data = self.http.get_json(url, ttl=TTL_FOREVER, timeout=10, retries=1)
        target = norm_text(text)
        hit = None
        for r in data.get("search", []):
            cands = [r.get("label", "")] + (r.get("aliases") or [])
            match = r.get("match", {}).get("text", "")
            if match:
                cands.append(match)
            if any(norm_text(c) == target for c in cands):
                hit = r
                break
        if not hit:
            return None
        codes = ["ru", "en", "fr", "de", "es", "it", "ko", "ja", "zh-hans", "zh-hant", "zh", "fa", "ar", "ur",
                 "tr", "uz", "he", "hi", "kk", "pt"]
        url2 = "https://www.wikidata.org/w/api.php?" + urlencode({
            "action": "wbgetentities", "ids": hit["id"], "props": "labels|aliases|descriptions",
            "languages": "|".join(codes), "format": "json", "origin": "*"})
        ent = self.http.get_json(url2, ttl=TTL_FOREVER, timeout=10, retries=1)["entities"][hit["id"]]
        labels = {}
        for code in codes:
            vals = []
            lab = ent.get("labels", {}).get(code, {}).get("value")
            if lab:
                vals.append(re.sub(r"\s*\(.*?\)\s*$", "", lab))
            for al in ent.get("aliases", {}).get(code, [])[:4]:
                v = al.get("value", "")
                if len(v) >= (2 if re.search("[぀-鿿가-힯]", v) else 4) and not v.isupper():
                    vals.append(v)
            key = {"zh-hans": "zh", "zh-hant": "zh-Hant"}.get(code, code)
            if key == "zh" and code == "zh" and labels.get("zh"):
                continue
            if vals:
                labels.setdefault(key, [])
                labels[key] = _uniq(labels[key] + vals)[:3]
        desc = ent.get("descriptions", {}).get("ru", {}).get("value") or \
            ent.get("descriptions", {}).get("en", {}).get("value", "")
        return {"id": hit["id"], "label": hit.get("label", text), "description": desc, "labels": labels}

    # ------------------------------------------------------------ машинный перевод
    def translate(self, text: str, src: str, dest: str):
        tl = MT_LANG.get(dest, dest)
        if dest == src:
            return {"text": text, "engine": "—"}
        try:
            url = "https://translate.googleapis.com/translate_a/single?client=gtx&dt=t&" + urlencode(
                {"sl": "auto", "tl": tl, "q": text})
            data = self.http.get_json(url, ttl=TTL_FOREVER, timeout=8, retries=1)
            t = "".join(part[0] for part in data[0] if part and part[0]).strip()
            if t:
                return {"text": _clean_mt(t), "engine": "Google"}
        except (FetchError, ValueError, TypeError, IndexError, KeyError):
            pass
        try:
            mm = {"zh": "zh-CN", "zh-Hant": "zh-TW"}
            url = "https://api.mymemory.translated.net/get?" + urlencode(
                {"q": text, "langpair": "%s|%s" % (mm.get(src, src), mm.get(dest, dest))})
            data = self.http.get_json(url, ttl=TTL_FOREVER, timeout=8, retries=1)
            t = (data.get("responseData") or {}).get("translatedText", "").strip()
            if t and "MYMEMORY WARNING" not in t.upper() and "INVALID" not in t.upper():
                return {"text": _clean_mt(t), "engine": "MyMemory"}
        except (FetchError, ValueError, TypeError, KeyError, AttributeError):
            pass
        return None


def _clean_mt(t: str) -> str:
    t = t.strip().strip("\"'«»“”„")
    return re.sub(r"\s+", " ", t)[:120]


def _same_script(a: str, code: str) -> bool:
    latin = code in ("en", "fr", "de", "es", "it", "tr", "uz", "pt")
    return latin and bool(re.match(r"^[A-Za-z]", a))


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        k = norm_text(x)
        if x and k not in seen:
            seen.add(k)
            out.append(x)
    return out


ROLE_LABELS = {
    "main": "ключевое слово или его перевод",
    "form": "словоформа ключевого слова",
    "related": "связанный термин",
    "ctx": "контекст",
    "manual": "термин, добавленный вручную",
}


def plan_origins(topics: list[dict], context: list[dict] | None = None) -> dict:
    """Происхождение каждого поискового термина: исходное ключевое слово, роль, языки, источник перевода.

    Ключ — нормализованный термин (как его возвращает TermMatcher.find)."""
    out: dict = {}

    def put(term, kw, role, code, src, of=""):
        k = norm_text(term)
        if not k:
            return
        cur = out.get(k)
        if cur is None:
            out[k] = {"t": term, "kw": kw, "role": role, "of": of, "langs": [code], "src": src}
        elif cur["kw"] == kw and cur["role"] == role and code not in cur["langs"]:
            cur["langs"].append(code)

    for e in topics or []:
        for code, t in (e.get("langs") or {}).items():
            rel = t.get("rel") or {}
            for term in t.get("q") or []:
                if term not in rel:
                    put(term, e["topic"], "main", code, t.get("src", ""))
    for e in topics or []:
        for code, t in (e.get("langs") or {}).items():
            rel = t.get("rel") or {}
            for term in (t.get("q") or []) + (t.get("m") or []):
                if term in rel:
                    put(term, e["topic"], "related", code, t.get("src", ""), rel[term])
    for e in topics or []:
        for code, t in (e.get("langs") or {}).items():
            rel = t.get("rel") or {}
            for term in t.get("m") or []:
                if term not in rel:
                    put(term, e["topic"], "form", code, t.get("src", ""))
    for e in context or []:
        for code, t in (e.get("langs") or {}).items():
            for term in (t.get("q") or []) + (t.get("m") or []):
                put(term, e["topic"], "ctx", code, t.get("src", ""))
    return out


def build_plan(expansions: list[dict], context: list[dict], exclude: list[dict], langs) -> dict:
    """Собрать итоговые термины по языкам: тема(ы) ИЛИ, контекст И, исключения НЕ."""
    plan = {}
    for code in list(langs) + (["zh-Hant"] if "zh" in langs else []):
        def collect(exps):
            q, m = [], []
            for e in exps:
                t = e["langs"].get(code) or (e["langs"].get("zh") if code == "zh-Hant" else None)
                if t:
                    q.extend(t["q"])
                    m.extend(t.get("m", []))
            return _uniq(q), _uniq(m)
        tq, tm = collect(expansions)
        cq, cm = collect(context)
        xq, _xm = collect(exclude)
        plan[code] = {"q": tq, "m": tm, "ctx": cq, "ctx_m": cm, "not": xq}
    return plan


__all__ = ["Languages", "Lexicon", "build_plan", "plan_origins", "ROLE_LABELS"]
