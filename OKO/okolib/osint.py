"""Анализ идентификаторов по открытым источникам: e-mail, телефон, имя пользователя, домен, ссылка, IP.

Только публичные данные: DNS, RDAP (WHOIS), публичные профили, веб-архив, упоминания в поисковиках.
ОКО не использует утёкшие базы, «пробив» и сервисы, раскрывающие владельцев номеров, не проверяет
существование аккаунтов через формы восстановления пароля и не собирает сведения о частных лицах
сверх того, что они сами опубликовали.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode, urlsplit

from . import htmlmeta
from .net import FetchError
from .util import strip_html

EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+\.)+[A-Za-z]{2,}$")
DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)
USERNAME = re.compile(r"^@?[A-Za-z0-9_.\-]{2,40}$")
DISPOSABLE = {"mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "temp-mail.org", "yopmail.com",
              "trashmail.com", "getnada.com", "sharklasers.com", "dispostable.com", "maildrop.cc", "throwawaymail.com"}
FREEMAIL = {"gmail.com", "mail.ru", "yandex.ru", "ya.ru", "bk.ru", "inbox.ru", "list.ru", "outlook.com", "hotmail.com",
            "yahoo.com", "icloud.com", "proton.me", "protonmail.com", "rambler.ru", "umail.uz", "gmx.de", "gmx.net"}
CC = {"998": "Узбекистан", "7": "Россия / Казахстан", "996": "Кыргызстан", "992": "Таджикистан", "993": "Туркменистан",
      "93": "Афганистан", "994": "Азербайджан", "995": "Грузия", "374": "Армения", "380": "Украина", "375": "Беларусь",
      "90": "Турция", "98": "Иран", "92": "Пакистан", "91": "Индия", "86": "Китай", "82": "Республика Корея",
      "81": "Япония", "1": "США / Канада", "44": "Великобритания", "49": "Германия", "33": "Франция", "39": "Италия",
      "34": "Испания", "971": "ОАЭ", "966": "Саудовская Аравия", "974": "Катар", "972": "Израиль", "20": "Египет",
      "48": "Польша", "31": "Нидерланды", "41": "Швейцария", "43": "Австрия", "46": "Швеция", "370": "Литва",
      "371": "Латвия", "372": "Эстония", "373": "Молдова", "976": "Монголия", "65": "Сингапур", "60": "Малайзия"}
UZ_OPERATORS = {"90": "Beeline", "91": "Beeline", "93": "Ucell", "94": "Ucell", "88": "Mobiuz", "97": "Mobiuz",
                "95": "Uzmobile", "99": "Uzmobile", "98": "Perfectum Mobile", "33": "Humans", "71": "городской (Ташкент)"}
PROFILE_SITES = [
    ("Telegram", "https://t.me/{}"), ("X (Twitter)", "https://x.com/{}"), ("Instagram", "https://www.instagram.com/{}/"),
    ("Facebook", "https://www.facebook.com/{}"), ("VK", "https://vk.com/{}"), ("GitHub", "https://github.com/{}"),
    ("YouTube", "https://www.youtube.com/@{}"), ("TikTok", "https://www.tiktok.com/@{}"),
    ("LinkedIn (поиск)", "https://www.linkedin.com/search/results/all/?keywords={}"), ("Reddit", "https://www.reddit.com/user/{}"),
    ("Medium", "https://medium.com/@{}"), ("Habr", "https://habr.com/ru/users/{}/"),
]


def detect(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if EMAIL.match(v):
        return "email"
    try:
        ipaddress.ip_address(v)
        return "ip"
    except ValueError:
        pass
    if re.match(r"^https?://", v, re.I):
        return "url"
    digits = re.sub(r"[\s()\-.]", "", v)
    if re.fullmatch(r"\+?\d{7,15}", digits):
        return "phone"
    if DOMAIN.match(v.lower().rstrip(".")):
        return "domain"
    if USERNAME.match(v):
        return "username"
    return ""


def _web_links(q: str) -> list:
    qq = quote('"%s"' % q)
    return [{"name": "Google", "url": "https://www.google.com/search?q=" + qq},
            {"name": "Яндекс", "url": "https://yandex.ru/search/?text=" + qq},
            {"name": "Bing", "url": "https://www.bing.com/search?q=" + qq},
            {"name": "DuckDuckGo", "url": "https://duckduckgo.com/?q=" + qq}]


def _doh(http, name: str, rtype: str) -> list:
    try:
        d = http.get_json("https://dns.google/resolve?" + urlencode({"name": name, "type": rtype}), ttl=3600,
                          timeout=8, retries=1)
        return [a.get("data", "") for a in d.get("Answer") or [] if a.get("data")]
    except (FetchError, ValueError):
        return []


def _rdap(http, kind: str, value: str) -> dict:
    try:
        d = http.get_json("https://rdap.org/%s/%s" % (kind, value), ttl=86400, timeout=12, retries=1,
                          headers={"Accept": "application/rdap+json, application/json"})
    except (FetchError, ValueError):
        return {}
    out = {}
    for ev in d.get("events") or []:
        a, t = ev.get("eventAction"), (ev.get("eventDate") or "")[:10]
        if a in ("registration", "expiration", "last changed"):
            out[a] = t
    for ent in d.get("entities") or []:
        if "registrar" in (ent.get("roles") or []):
            for item in ((ent.get("vcardArray") or [None, []])[1] or []):
                if item and item[0] == "fn":
                    out["registrar"] = item[3]
    if d.get("status"):
        out["status"] = ", ".join(d["status"][:4])
    ns = [n.get("ldhName", "").lower() for n in d.get("nameservers") or [] if n.get("ldhName")]
    if ns:
        out["nameservers"] = ", ".join(ns[:4])
    for k in ("name", "country", "handle"):
        if d.get(k) and kind == "ip":
            out[k] = d[k]
    if kind == "ip" and d.get("startAddress"):
        out["range"] = "%s — %s" % (d["startAddress"], d.get("endAddress", ""))
    return out


def _wayback_first(http, target: str) -> str:
    try:
        d = http.get_json("https://web.archive.org/cdx/search/cdx?" + urlencode(
            {"url": target, "limit": "1", "output": "json", "fl": "timestamp"}), ttl=86400, timeout=15, retries=0)
        if isinstance(d, list) and len(d) > 1 and d[1]:
            t = d[1][0]
            return "%s-%s-%s" % (t[:4], t[4:6], t[6:8])
    except (FetchError, ValueError, IndexError, TypeError):
        pass
    return ""


def analyze(http, value: str, registry=None) -> dict:
    v = (value or "").strip()
    kind = detect(v)
    res = {"value": v, "type": kind, "facts": [], "checks": [], "links": [], "notes": []}
    fact = lambda k, val: res["facts"].append({"k": k, "v": val}) if val else None  # noqa: E731

    def check(name, status, detail="", url=""):
        res["checks"].append({"name": name, "status": status, "detail": detail, "url": url})

    if not kind:
        res["notes"].append("Не удалось определить тип: укажите e-mail, номер телефона, имя пользователя, домен, "
                            "ссылку или IP-адрес.")
        return res
    if kind == "email":
        local, domain = v.rsplit("@", 1)
        domain = domain.lower()
        fact("Домен почты", domain)
        fact("Тип почтового сервиса", "бесплатная почта" if domain in FREEMAIL else (
            "одноразовая почта" if domain in DISPOSABLE else "корпоративный / собственный домен"))
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_mx = ex.submit(_doh, http, domain, "MX")
            f_rd = ex.submit(_rdap, http, "domain", domain) if domain not in FREEMAIL else None
            h = hashlib.sha256(v.lower().encode()).hexdigest()
            f_gr = ex.submit(lambda: http.get_json("https://gravatar.com/%s.json" % h, ttl=86400, timeout=8, retries=0))
            mx = f_mx.result()
            check("Почтовый сервер (MX)", "ok" if mx else "warn", ", ".join(sorted(mx))[:200] if mx else
                  "домен не принимает почту — адрес, вероятно, недействителен")
            rd = f_rd.result() if f_rd else {}
            if rd.get("registration"):
                fact("Домен зарегистрирован", rd["registration"])
            try:
                g = f_gr.result()
                entry = (g.get("entry") or [{}])[0]
                check("Публичный профиль Gravatar", "found", entry.get("displayName") or "профиль есть",
                      entry.get("profileUrl") or "")
            except (FetchError, ValueError, TypeError, IndexError, AttributeError):
                check("Публичный профиль Gravatar", "none", "не найден")
        res["links"] += _web_links(v)
        res["links"].append({"name": "Have I Been Pwned (утечки — проверьте сами)",
                             "url": "https://haveibeenpwned.com/account/" + quote(v)})
        res["links"].append({"name": "Имя пользователя «%s» в соцсетях" % local, "url": "", "hint": local})
    elif kind == "phone":
        digits = re.sub(r"\D", "", v)
        if v.startswith("8") and len(digits) == 11:
            digits = "7" + digits[1:]
        if len(digits) == 9:
            digits = "998" + digits  # местный узбекский формат
        country = next((CC[c] for c in sorted(CC, key=len, reverse=True) if digits.startswith(c)), "")
        fact("Международный формат", "+" + digits)
        fact("Страна по коду", country or "не определена")
        if digits.startswith("998") and len(digits) == 12:
            op = UZ_OPERATORS.get(digits[3:5], "")
            fact("Оператор (по коду сети)", (op + " — код " + digits[3:5]) if op else "код " + digits[3:5])
            fact("Местный формат", "%s %s-%s-%s" % (digits[3:5], digits[5:8], digits[8:10], digits[10:12]))
        fmts = {"+" + digits, digits}
        if digits.startswith("998") and len(digits) == 12:
            fmts.add("+998 %s %s-%s-%s" % (digits[3:5], digits[5:8], digits[8:10], digits[10:12]))
        for f in sorted(fmts):
            res["links"] += [dict(x, name=x["name"] + ": " + f) for x in _web_links(f)[:2]]
        res["notes"].append("ОКО не определяет владельца номера и не проверяет его привязку к мессенджерам — это "
                            "персональные данные. Показаны код страны/оператора и упоминания номера в открытом вебе.")
    elif kind == "username":
        u = v.lstrip("@")
        res["links"] += [{"name": n, "url": tpl.format(quote(u))} for n, tpl in PROFILE_SITES]
        res["links"] += _web_links(u)[:2]

        def gh():
            try:
                d = http.get_json("https://api.github.com/users/" + quote(u), ttl=86400, timeout=8, retries=0,
                                  headers={"Accept": "application/vnd.github+json"})
                return ("GitHub", "found", (d.get("name") or u) + (" · " + d["location"] if d.get("location") else ""),
                        d.get("html_url", ""))
            except FetchError as e:
                return ("GitHub", "none" if e.status == 404 else "unknown", "не найден" if e.status == 404 else e.short(), "")

        def tg():
            try:
                t = http.get("https://t.me/" + quote(u), ttl=86400, timeout=8, retries=0).text()
                m = re.search(r'<div class="tgme_page_title"[^>]*>\s*<span[^>]*>(.*?)</span>', t, re.S)
                extra = re.search(r'<div class="tgme_page_extra">\s*(.*?)\s*</div>', t, re.S)
                if m:
                    return ("Telegram", "found", strip_html(m.group(1)) + (" · " + strip_html(extra.group(1)) if extra else ""),
                            "https://t.me/" + u)
                return ("Telegram", "none", "не найден", "")
            except FetchError as e:
                return ("Telegram", "unknown", e.short(), "")

        def rd():
            try:
                d = http.get_json("https://www.reddit.com/user/%s/about.json" % quote(u), ttl=86400, timeout=8, retries=0)
                return ("Reddit", "found", "аккаунт есть", "https://www.reddit.com/user/" + u) if d.get("data") else \
                    ("Reddit", "none", "не найден", "")
            except FetchError as e:
                return ("Reddit", "none" if e.status == 404 else "unknown", "не найден" if e.status == 404 else e.short(), "")

        def yt():
            try:
                http.get("https://www.youtube.com/@" + quote(u), ttl=86400, timeout=8, retries=0)
                return ("YouTube", "found", "канал @" + u, "https://www.youtube.com/@" + u)
            except FetchError as e:
                return ("YouTube", "none" if e.status == 404 else "unknown", "не найден" if e.status == 404 else e.short(), "")
        with ThreadPoolExecutor(max_workers=4) as ex:
            for name, st, detail, url in ex.map(lambda f: f(), (tg, gh, rd, yt)):
                check(name, st, detail, url)
        res["notes"].append("Автоматически проверяются только платформы с открытыми страницами профилей; остальные — "
                            "ссылками. Совпадение имени пользователя не означает, что это один и тот же человек.")
    elif kind in ("domain", "url"):
        url = v if kind == "url" else "https://" + v.lower().rstrip(".")
        host = (urlsplit(url).hostname or "").lower()
        dom = host[4:] if host.startswith("www.") else host
        fact("Домен", dom)
        if registry is not None:
            s = registry.lookup(url)
            if s:
                fact("В реестре ОКО", "%s — уровень %s, %s" % (s["name"], "ABC"[max(0, min(2, s.get("tier", 3) - 1))],
                                                               s.get("type", "")))
        with ThreadPoolExecutor(max_workers=5) as ex:
            f_rd = ex.submit(_rdap, http, "domain", ".".join(dom.split(".")[-2:]) if not dom.endswith(
                (".co.uk", ".com.tr", ".gov.uz", ".org.uz", ".com.uz")) else ".".join(dom.split(".")[-3:]))
            f_a = ex.submit(_doh, http, dom, "A")
            f_mx = ex.submit(_doh, http, dom, "MX")
            f_wb = ex.submit(_wayback_first, http, dom)
            f_pg = ex.submit(lambda: http.get(url, ttl=3600, timeout=15, retries=1, max_bytes=3_000_000))
            rd = f_rd.result()
            for k, label in (("registration", "Домен зарегистрирован"), ("expiration", "Регистрация до"),
                             ("registrar", "Регистратор"), ("nameservers", "DNS-серверы"), ("status", "Статус домена")):
                fact(label, rd.get(k, ""))
            a = f_a.result()
            fact("IP-адреса (A)", ", ".join(a[:4]))
            fact("Почта домена (MX)", ", ".join(sorted(f_mx.result())[:3]))
            first = f_wb.result()
            fact("Первая копия в веб-архиве", first)
            try:
                r = f_pg.result()
                meta = htmlmeta.extract_meta(r.text(), r.url)
                check("Страница доступна", "ok", "HTTP %s · %s" % (r.status, r.url), r.url)
                fact("Заголовок страницы", meta.get("title", ""))
                fact("Название сайта", meta.get("site_name", ""))
                fact("Авторы", ", ".join(meta.get("authors") or []))
                if meta.get("published"):
                    import time as _t
                    fact("Опубликовано", _t.strftime("%Y-%m-%d %H:%M UTC", _t.gmtime(meta["published"])))
                fact("Каноническая ссылка", meta.get("canonical", ""))
                fact("Сервер", r.headers.get("server", ""))
            except FetchError as e:
                check("Страница доступна", "warn", e.short())
        res["links"] += [{"name": "Веб-архив (все копии)", "url": "https://web.archive.org/web/*/" + dom + "/*"},
                         {"name": "Сертификаты (crt.sh)", "url": "https://crt.sh/?q=" + quote(dom)},
                         {"name": "Упоминания домена", "url": "https://www.google.com/search?q=" + quote('"%s" -site:%s' % (dom, dom))}]
        if kind == "url":
            res["links"].insert(0, {"name": "Сохранить в веб-архив", "url": "https://web.archive.org/save/" + url})
    elif kind == "ip":
        rd = _rdap(http, "ip", v)
        for k, label in (("name", "Сеть"), ("country", "Страна"), ("range", "Диапазон"), ("handle", "Идентификатор")):
            fact(label, rd.get(k, ""))
        try:
            rev = ".".join(reversed(v.split("."))) + ".in-addr.arpa" if "." in v else ""
            if rev:
                fact("Обратная запись DNS", ", ".join(_doh(http, rev, "PTR")))
        except ValueError:
            pass
        res["links"] += _web_links(v)[:2]
    return res


__all__ = ["analyze", "detect"]
