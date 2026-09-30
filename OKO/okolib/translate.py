"""Экспресс-перевод на русский прямо в ОКО: заголовки, аннотации, полный текст статьи.

Движки по порядку: DeepL (если в настройках указан ключ — лучшее качество), Google Translate
(публичный веб-интерфейс, без ключа), MyMemory (запасной, короткие тексты). Переводы кэшируются.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

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


def _mymemory(http, text: str, to: str, src: str) -> str | None:
    if len(text) > 480 or src == "auto":
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
    out, engine = [], "Google"
    for p in pieces:
        t = _gtx(http, p, to, src)
        if t is None:
            t = _mymemory(http, p, to, src)
            engine = "MyMemory" if t else engine
        if t is None:
            return "", ""
        out.append(t)
    return "\n".join(out), engine


def translate_many(http, texts: list, to: str = "ru", src: str = "auto", deepl_key: str = "") -> dict:
    """Перевести список коротких текстов (заголовки, аннотации) → {"texts": [...], "engine": ...}."""
    texts = [str(t or "")[:5000] for t in texts]
    if not texts:
        return {"texts": [], "engine": ""}
    if deepl_key:
        res = _deepl(http, texts, to, deepl_key)
        if res:
            return {"texts": res, "engine": "DeepL"}
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(lambda t: translate_one(http, t, to, src), texts))
    engines = {e for _, e in res if e}
    return {"texts": [t for t, _ in res], "engine": ", ".join(sorted(engines))}


def translate_blocks(http, blocks: list, to: str = "ru", deepl_key: str = "", limit: int = 30000) -> tuple[list, str]:
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
        res = list(ex.map(lambda p: _gtx(http, p, to) or _mymemory(http, p, to, "auto") or "", parts))
    text = "\n".join(res)
    paras = [x for x in text.split("\n") if x.strip()]
    if len(paras) == len(out):
        for b, t in zip(out, paras):
            b["tr"] = t.strip()
    else:  # абзацы склеились — переводим поштучно
        with ThreadPoolExecutor(max_workers=3) as ex:
            res2 = list(ex.map(lambda b: translate_one(http, b["t"], to)[0], out))
        for b, t in zip(out, res2):
            b["tr"] = t
    return out, "Google"


__all__ = ["translate_one", "translate_many", "translate_blocks", "chunks"]
