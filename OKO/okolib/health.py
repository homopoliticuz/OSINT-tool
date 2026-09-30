"""Состояние каналов сбора: последовательные ошибки, понятная причина, подсказка, временное отключение.

Канал — это задача поиска с постоянным ключом (rss:<источник>, wp:<источник>:<язык>, gn:<издание>…).
После нескольких одинаковых сбоев подряд канал отключается на время (12 ч → 24 ч → 48 ч → 72 ч),
затем проверяется снова. Успешный ответ сразу снимает отключение. Временные ограничения поисковых
систем (HTTP 429/503) каналы не отключают — это пауза на уровне сервиса.
"""
from __future__ import annotations

import threading
import time

from .net import FetchError
from .util import read_json, write_json

KINDS = {
    "limit": ("сервис временно ограничил частоту запросов",
              "ОКО само делает паузу; повторите поиск через 10–15 минут"),
    "denied": ("сайт запрещает автоматические запросы (защита от ботов, HTTP 401/403)",
               "канал будет отключён; материалы источника по-прежнему ищутся через Google News и GDELT"),
    "gone": ("адрес ленты или API больше не существует (HTTP 404/410)",
             "ОКО само ищет новую ленту на сайте источника"),
    "server": ("ошибка на стороне сайта (HTTP 5xx)", "обычно временно — повтор при следующем поиске"),
    "network": ("сайт не отвечает или недоступен из вашей сети",
                "если сайт заблокирован у вашего провайдера — включите VPN; иначе канал временно пропускается"),
    "ssl": ("ошибка SSL-сертификата сайта",
            "на macOS запустите «Install Certificates.command» из папки Python; иначе у сайта неполная цепочка сертификатов"),
    "format": ("ответ не похож на ленту новостей или JSON",
               "ОКО само ищет новую ленту на сайте источника"),
    "other": ("ошибка обработки ответа", "если повторяется — пришлите «Отчёт об ошибках» разработчику"),
}
# ошибки, после которых канал имеет смысл временно отключать
PERSISTENT = {"denied", "gone", "network", "ssl", "format"}
BACKOFF_H = {3: 12, 4: 24, 5: 48}
MAX_BACKOFF_H = 72


def classify(err: BaseException) -> str:
    if isinstance(err, FetchError):
        st = err.status
        msg = str(err).lower()
        if st in (429, 503) or "ограничил" in msg:
            return "limit"
        if st in (401, 403, 451):
            return "denied"
        if st in (404, 410):
            return "gone"
        if st and st >= 500:
            return "server"
        if st and 400 <= st < 500:
            return "gone" if st in (400, 405, 501) else "denied"
        if "ssl" in msg or "сертификат" in msg:
            return "ssl"
        if any(x in msg for x in ("не json", "неожиданный ответ", "лента пуста", "повреждена", "вместо ленты",
                                  "не похож")):
            return "format"
        if any(x in msg for x in ("время ожидания", "нет соединения", "сбой соединения", "обрыв", "timed out",
                                  "refused", "reset", "name or service", "getaddrinfo", "unreachable")):
            return "network"
        return "other"
    return "other"


def describe(kind: str) -> tuple[str, str]:
    return KINDS.get(kind, KINDS["other"])


class Health:
    def __init__(self, path: str | None):
        self.path = path
        self.lock = threading.Lock()
        self.data: dict = (read_json(path, {}) if path else {}) or {}
        self._dirty = False

    def skip_reason(self, key: str) -> str | None:
        h = self.data.get(key)
        if not h or h.get("until", 0) <= time.time():
            return None
        return "канал временно отключён до %s: %d ошибок подряд — %s" % (
            time.strftime("%d.%m %H:%M", time.localtime(h["until"])), h.get("streak", 0),
            describe(h.get("kind", "other"))[0])

    def ok(self, key: str):
        with self.lock:
            h = self.data.get(key)
            if h and (h.get("streak") or h.get("until")):
                h.update(streak=0, until=0, last_ok=int(time.time()))
                self._dirty = True

    def fail(self, key: str, kind: str, message: str, *, label: str = "", provider: str = "", url: str = "",
             source_id: str = "", engine: bool = False) -> dict:
        now = int(time.time())
        with self.lock:
            h = self.data.setdefault(key, {"streak": 0, "until": 0})
            h["streak"] = h.get("streak", 0) + 1
            h.update(kind=kind, err=message[:240], label=label[:160], provider=provider, url=url[:400],
                     source=source_id, last=now, total=h.get("total", 0) + 1)
            h.setdefault("first", now)
            disable = kind in PERSISTENT and not (engine and kind not in ("gone", "format"))
            if disable and h["streak"] >= 3:
                hours = BACKOFF_H.get(h["streak"], MAX_BACKOFF_H)
                h["until"] = now + hours * 3600
            self._dirty = True
            return dict(h)

    def reset(self, key: str | None = None):
        with self.lock:
            if key is None:
                self.data.clear()
            else:
                self.data.pop(key, None)
            self._dirty = True
        self.flush()

    def snapshot(self) -> list:
        now = time.time()
        with self.lock:
            out = []
            for k, h in self.data.items():
                if not h.get("streak") and not h.get("until"):
                    continue
                reason, hint = describe(h.get("kind", "other"))
                out.append(dict(h, key=k, reason=reason, hint=hint, disabled=h.get("until", 0) > now))
        out.sort(key=lambda x: (-int(x["disabled"]), -x.get("streak", 0), x.get("label", "")))
        return out

    def flush(self):
        if not self.path:
            return
        with self.lock:
            if not self._dirty:
                return
            # не храним вечно записи о давно исправившихся каналах
            cutoff = time.time() - 30 * 86400
            for k in [k for k, h in self.data.items() if not h.get("streak") and h.get("last", 0) < cutoff]:
                self.data.pop(k, None)
            data = dict(self.data)
            self._dirty = False
        write_json(self.path, data)


__all__ = ["Health", "classify", "describe", "KINDS"]
