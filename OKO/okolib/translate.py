"""Экспресс-перевод на русский прямо в ОКО: заголовки, аннотации, полный текст статьи.

Движки по порядку: DeepL (если в настройках указан ключ — лучшее качество), Google Translate
(публичный веб-интерфейс, без ключа), MyMemory (запасной, короткие тексты). Переводы кэшируются.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

from .net import FetchError

TTL = 365 * 86400
GT_LANG = {"zh": "zh-CN", "zh-Hant": "zh-TW", "he": "iw"}
CHUNK = 1500
SEP = "\n\n"


def _gtx(http, text: str, to: str, src: str = "auto") -> str | None:
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&dt=t&" + urlencode(
        {"sl": GT_LANG.get(src, src), "tl": GT_LANG.get(to, to), "q": text})
    try:
        data = http.get_json(url, ttl=TTL, timeout=12, retries=1)
        out = "".join(part[0] for part in data[0] if part and part[0])
        return out or None
    except (FetchError, ValueError, TypeError, IndexError, KeyError):
        return None


def _clients5(http, texts: list, to: str, src: str = "auto") -> list | None:
    """Запасной веб-интерфейс Google (как у расширения Chrome): несколько текстов одним запросом."""
    params = [("client", "dict-chrome-ex"), ("sl", GT_LANG.get(src, src) if src else "auto"),
              ("tl", GT_LANG.get(to, to))] + [("q", t) for t in texts]
    try:
        data = http.get_json("https://clients5.google.com/translate_a/t?" + urlencode(params), ttl=TTL, timeout=12,
                             retries=1)
    except (FetchError, ValueError):
        return None
    return _parse_c5(data, len(texts))


def _parse_c5(data, n: int):
    if isinstance(data, dict):  # старый формат {"sentences": [{"trans": ...}]}
        s = "".join(x.get("trans", "") for x in data.get("sentences") or [] if isinstance(x, dict))
        return [s] if n == 1 and s else None
    if not isinstance(data, list):
        return None
    if n == 1 and len(data) == 2 and all(isinstance(x, str) for x in data) and len(data[1]) <= 6:
        return [data[0]]  # ["перевод", "en"]
    out = []
    for x in data:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, list) and x and isinstance(x[0], str):
            out.append(x[0])
        else:
            return None
    return out if len(out) == n and all(out) else None


def _lingva(http, text: str, to: str, src: str = "auto") -> str | None:
    """Последний запасной вариант: открытый прокси Google Переводчика Lingva."""
    if len(text) > 1500:
        return None
    try:
        data = http.get_json("https://lingva.ml/api/v1/%s/%s/%s" % (
            quote(GT_LANG.get(src, src) or "auto"), quote(GT_LANG.get(to, to)), quote(text, safe="")),
            ttl=TTL, timeout=10, retries=0)
        t = (data or {}).get("translation", "")
        return t.strip() or None
    except (FetchError, ValueError, AttributeError):
        return None


def _mymemory(http, text: str, to: str, src: str) -> str | None:
    if len(text) > 480 or not src or src == "auto":
        return None
    mm = {"zh": "zh-CN", "zh-Hant": "zh-TW"}
    url = "https://api.mymemory.translated.net/get?" + urlencode(
        {"q": text, "langpair": "%s|%s" % (mm.get(src, src), mm.get(to, to))})
    try:
        data = http.get_json(url, ttl=TTL, timeout=10, retries=1)
        t = (data.get("responseData") or {}).get("translatedText", "").strip()
        if t and "MYMEMORY WARNING" not in t.upper() and "INVALID" not in t.upper():
            return t
    except (FetchError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return None


def _deepl(http, texts: list, to: str, key: str) -> list | None:
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    body = urlencode([("text", t) for t in texts] + [("target_lang", to.upper()[:2])]).encode()
    try:
        r = http.post("https://%s/v2/translate" % host, body, ttl=TTL, timeout=20, retries=1,
                      headers={"Authorization": "DeepL-Auth-Key " + key,
                               "Content-Type": "application/x-www-form-urlencoded"})
        out = [x.get("text", "") for x in (json.loads(r.text()).get("translations") or [])]
        return out if len(out) == len(texts) else None
    except (FetchError, ValueError, TypeError, KeyError):
        return None


def chunks(text: str, size: int = CHUNK) -> list:
    """Разбить длинный текст на части по абзацам/предложениям."""
    parts, cur = [], ""
    for para in text.split("\n"):
        while len(para) > size:
            cut = para.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(para[:cut])
            para = para[cut:].lstrip()
        if len(cur) + len(para) + 1 > size and cur:
            parts.append(cur)
            cur = para
        else:
            cur = (cur + "\n" + para) if cur else para
    if cur:
        parts.append(cur)
    return parts


def translate_one(http, text: str, to: str = "ru", src: str = "auto", deepl_key: str = "") -> tuple[str, str]:
    """Перевести один текст любой длины → (перевод, движок)."""
    text = (text or "").strip()
    if not text:
        return "", ""
    pieces = chunks(text)
    if deepl_key:
        res = _deepl(http, pieces, to, deepl_key)
        if res:
            return "\n".join(res), "DeepL"
    out, engines = [], []
    for p in pieces:
        t, eng = _one_piece(http, p, to, src)
        if t is None:
            return "", ""
        out.append(t)
        engines.append(eng)
    return "\n".join(out), ", ".join(sorted(set(engines)))


def _one_piece(http, p: str, to: str, src: str):
    t = _gtx(http, p, to, src)
    if t:
        return t, "Google"
    r = _clients5(http, [p], to, src)
    if r:
        return r[0], "Google"
    t = _mymemory(http, p, to, src)
    if t:
        return t, "MyMemory"
    t = _lingva(http, p, to, src)
    if t:
        return t, "Lingva"
    return None, ""


def translate_many(http, texts: list, to: str = "ru", src: str = "auto", deepl_key: str = "") -> dict:
    """Перевести список коротких текстов (заголовки, аннотации) → {"texts": [...], "engine": ...}."""
    texts = [str(t or "")[:5000] for t in texts]
    if not texts:
        return {"texts": [], "engine": ""}
    if deepl_key:
        res = _deepl(http, texts, to, deepl_key)
        if res:
            return {"texts": res, "engine": "DeepL"}
    out = [""] * len(texts)
    engines = set()
    # короткие тексты (заголовки) — пачками одним запросом, так быстрее и бережнее к лимитам Google
    short = [i for i, t in enumerate(texts) if t.strip() and len(t) <= 400]
    batch, size = [], 0
    for i in short + [None]:
        if i is not None and len(batch) < 25 and size + len(texts[i]) <= 2500:
            batch.append(i)
            size += len(texts[i])
            continue
        if batch:
            res = _clients5(http, [texts[j] for j in batch], to, src)
            if res:
                for j, t in zip(batch, res):
                    out[j] = t
                engines.add("Google")
        batch, size = ([i], len(texts[i])) if i is not None else ([], 0)
    rest = [i for i, t in enumerate(texts) if t.strip() and not out[i]]
    with ThreadPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(lambda i: translate_one(http, texts[i], to, src), rest))
    for i, (t, e) in zip(rest, res):
        out[i] = t
        if e:
            engines.add(e)
    return {"texts": out, "engine": ", ".join(sorted(engines)),
            "failed": sum(1 for i, t in enumerate(texts) if t.strip() and not out[i])}


def translate_blocks(http, blocks: list, to: str = "ru", deepl_key: str = "", limit: int = 30000,
                     src: str = "auto") -> tuple[list, str]:
    """Перевести абзацы статьи, сохраняя структуру: [{"k", "t", "tr"}]."""
    out, total = [], 0
    for b in blocks:
        total += len(b.get("t", ""))
        if total > limit:
            break
        out.append(dict(b))
    joined = SEP.join(b["t"] for b in out)
    parts = chunks(joined, CHUNK)
    # переводим кусками, затем раскладываем обратно по абзацам
    if deepl_key:
        res = _deepl(http, [b["t"] for b in out], to, deepl_key)
        if res:
            for b, t in zip(out, res):
                b["tr"] = t
            return out, "DeepL"
    with ThreadPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(lambda p: _one_piece(http, p, to, src)[0] or "", parts))
    text = "\n".join(res)
    paras = [x for x in text.split("\n") if x.strip()]
    if len(paras) == len(out):
        for b, t in zip(out, paras):
            b["tr"] = t.strip()
    else:  # абзацы склеились — переводим поштучно
        with ThreadPoolExecutor(max_workers=3) as ex:
            res2 = list(ex.map(lambda b: translate_one(http, b["t"], to, src)[0], out))
        for b, t in zip(out, res2):
            b["tr"] = t
    return out, "Google"


__all__ = ["translate_one", "translate_many", "translate_blocks", "chunks"]
