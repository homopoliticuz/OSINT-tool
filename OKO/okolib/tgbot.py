"""Telegram-бот ОКО: поиск и сводки с телефона.

Бот работает внутри запущенного ОКО (на компьютере или на телефоне через Termux) и отвечает только
Telegram ID из списка «Разрешённые» (Настройки → Телефон). Команды:

  тема или /search тема   — материалы за 24 часа (самые авторитетные, строго по теме) + HTML-сводка файлом
  /today [тема]           — то же за сегодня;  /week [тема] — за 7 дней
  /watch                  — новые публикации источников из «Мониторинга» за 24 часа
  /reports                — новые глобальные доклады и индексы за 7 дней
  /digest ЧЧ:ММ [тема]    — ежедневная сводка в указанное время;  /digest off — отключить
  /status                 — состояние ОКО;  /start, /help — справка и ваш Telegram ID
"""
from __future__ import annotations

import html
import json
import logging
import threading
import time
import uuid

from . import query, report
from .net import FetchError

log = logging.getLogger("oko.bot")
API = "https://api.telegram.org/bot%s/%s"
HELP = ("<b>ОКО — бот мониторинга</b>\n"
        "Напишите тему (например: <i>Узбекистан</i>) — пришлю самые авторитетные материалы за 24 часа "
        "и HTML-сводку файлом.\n\n"
        "/today [тема] — за сегодня\n/week [тема] — за 7 дней\n/watch — новое у источников из «Мониторинга»\n"
        "/reports — новые глобальные доклады и индексы\n/digest 08:30 [тема] — ежедневная сводка; /digest off\n"
        "/status — состояние ОКО")
TIER = {1: "A", 2: "B", 3: "C", 4: "D"}
MARK = {"primary": "✔", "reprint": "⟳", "unknown": "·"}


class TgBot:
    def __init__(self, app):
        self.app = app
        self.stop_ev = threading.Event()
        self.thread = None
        self.sched = None
        self.username = ""
        self.error = ""
        self.offset = 0
        self.busy = threading.Semaphore(1)
        self._sent_digest = {}

    # ------------------------------------------------------------ управление
    @property
    def token(self) -> str:
        return (self.app.state.settings().get("tg_bot_token") or "").strip()

    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if not self.token or self.running() or self.app.fixtures:
            return False
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name="oko-bot", daemon=True)
        self.thread.start()
        self.sched = threading.Thread(target=self._scheduler, name="oko-bot-digest", daemon=True)
        self.sched.start()
        return True

    def stop(self):
        self.stop_ev.set()

    def restart(self):
        self.stop()
        if self.thread:
            self.thread.join(timeout=3)
        self.thread = None
        self.error = ""
        return self.start()

    def status(self) -> dict:
        return {"running": self.running(), "username": self.username, "error": self.error,
                "configured": bool(self.token)}

    # ------------------------------------------------------------ Bot API
    def api(self, method: str, params: dict | None = None, files: dict | None = None, timeout: float = 20):
        url = API % (self.token, method)
        if files:
            boundary = "oko" + uuid.uuid4().hex
            body = b""
            for k, v in (params or {}).items():
                body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
            for k, (name, data, ctype) in files.items():
                body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                         % (boundary, k, name, ctype)).encode() + data + b"\r\n"
            body += ("--%s--\r\n" % boundary).encode()
            r = self.app.http.post(url, body, headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
                                   timeout=timeout, retries=0)
        else:
            r = self.app.http.post(url, json.dumps(params or {}).encode(), headers={"Content-Type": "application/json"},
                                   timeout=timeout, retries=0)
        data = r.json()
        if not data.get("ok"):
            raise FetchError("Telegram: %s" % data.get("description", "ошибка"))
        return data.get("result")

    def send(self, chat, text: str):
        for chunk in _split(text, 3900):
            try:
                self.api("sendMessage", {"chat_id": chat, "text": chunk, "parse_mode": "HTML",
                                         "disable_web_page_preview": True})
            except FetchError as e:
                log.warning("sendMessage: %s", e)

    def send_file(self, chat, name: str, content: str, caption: str = ""):
        try:
            self.api("sendDocument", {"chat_id": chat, "caption": caption[:1000]},
                     files={"document": (name, content.encode("utf-8"), "text/html")}, timeout=60)
        except FetchError as e:
            log.warning("sendDocument: %s", e)

    # ------------------------------------------------------------ цикл
    def _loop(self):
        try:
            me = self.api("getMe")
            self.username = me.get("username", "")
        except (FetchError, ValueError) as e:
            self.error = str(e)[:200]
            log.warning("бот не запущен: %s", e)
            return
        while not self.stop_ev.is_set():
            try:
                ups = self.api("getUpdates", {"offset": self.offset, "timeout": 45,
                                              "allowed_updates": ["message"]}, timeout=60)
                self.error = ""
            except (FetchError, ValueError) as e:
                self.error = str(e)[:200]
                self.stop_ev.wait(10)
                continue
            for u in ups or []:
                self.offset = max(self.offset, u.get("update_id", 0) + 1)
                msg = u.get("message") or {}
                if msg.get("text"):
                    threading.Thread(target=self.handle, args=(msg,), daemon=True).start()

    def allowed(self, uid) -> bool:
        ids = {int(x) for x in (self.app.state.settings().get("tg_bot_allowed") or []) if str(x).lstrip("-").isdigit()}
        return int(uid) in ids

    # ------------------------------------------------------------ команды
    def handle(self, msg: dict):
        chat = (msg.get("chat") or {}).get("id")
        uid = (msg.get("from") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat or not uid:
            return
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        if cmd in ("/start", "/help"):
            ok = self.allowed(uid)
            self.send(chat, HELP + "\n\nВаш Telegram ID: <code>%s</code> — %s" % (
                uid, "доступ разрешён" if ok else "добавьте его в ОКО: Настройки → «Разрешённые Telegram ID»"))
            return
        if not self.allowed(uid):
            self.send(chat, "Доступ запрещён. Ваш Telegram ID: <code>%s</code>. Добавьте его в ОКО: Настройки → "
                            "«Разрешённые Telegram ID»." % uid)
            return
        topic_def = self.app.state.settings().get("tg_bot_topic") or "Узбекистан"
        if cmd == "/status":
            st = self.app.bootstrap()
            self.send(chat, "ОКО %s работает. Источников: %d. Каналов с ошибками: %d." % (
                st["version"], st["sources"], len([x for x in self.app.health.snapshot() if x.get("disabled")])))
            return
        if cmd == "/digest":
            self._set_digest(chat, arg.strip(), topic_def)
            return
        if cmd == "/watch":
            return self._run(chat, "Мониторинг источников", 24, mode="watch")
        if cmd == "/reports":
            return self._run(chat, "Доклады", 24 * 7, mode="reports")
        hours = {"/today": _hours_today(), "/week": 24 * 7}.get(cmd, 24)
        if cmd.startswith("/") and cmd not in ("/search", "/today", "/week"):
            self.send(chat, "Не знаю такой команды.\n\n" + HELP)
            return
        topic = (arg if cmd.startswith("/") else text).strip() or topic_def
        self._run(chat, topic[:120], hours)

    def _run(self, chat, topic: str, hours: float, mode: str = "topic"):
        if not self.busy.acquire(blocking=False):
            self.send(chat, "Уже выполняю поиск — пришлю результат, затем повторите запрос.")
            return
        try:
            self.send(chat, "🔎 Ищу: <b>%s</b> за %s…" % (html.escape(topic), _period(hours)))
            if mode == "watch":
                w = self.app.state.get_doc("watch", None) or {}
                if not (w.get("sources") or w.get("channels")):
                    self.send(chat, "Список «Мониторинга» пуст — добавьте источники в ОКО (значок «глаз»).")
                    return
                params = {
                    "mode": "watch", "topics": [], "langs": query.default_langs(self.app), "plan": {}, "origins": {},
                    "sources": w.get("sources") or [], "channels": w.get("channels") or [],
                    "t_from": int(time.time() - hours * 3600), "t_to": int(time.time()), "title": "Мониторинг источников"}
            elif mode == "reports":
                params = {"mode": "reports", "topics": [], "langs": ["en"], "plan": {}, "origins": {},
                          "t_from": int(time.time() - hours * 3600), "t_to": int(time.time()), "title": "Доклады"}
            else:
                params = query.topic_params(self.app, topic, hours, title="Бот: " + topic)
            job = query.run_sync(self.app, params)
            media = query.ranked(self.app, job, strict=True, social=False)
            social = query.ranked(self.app, job, strict=True, social=True)
            if mode == "watch":
                media = [x for x in media if x.get("new")] or media
            self.send(chat, format_digest(topic, hours, media, social, job))
            if media or social:
                name = "OKO_%s_%s.html" % (time.strftime("%Y%m%d_%H%M"), "".join(c for c in topic if c.isalnum())[:30] or mode)
                self.send_file(chat, name, report.build_html("ОКО · " + topic, "Период: " + _period(hours) +
                                                             " · материалов: %d" % len(media), media, social),
                               "Полная сводка: %d материалов, %d из соцсетей" % (len(media), len(social)))
        except Exception as e:  # noqa: BLE001 — бот не должен падать из-за одного запроса
            log.exception("bot search")
            self.send(chat, "Ошибка поиска: %s" % html.escape(str(e)[:200]))
        finally:
            self.busy.release()

    def _set_digest(self, chat, arg: str, topic_def: str):
        st = self.app.state.settings()
        dig = [d for d in (st.get("tg_bot_digest") or []) if isinstance(d, dict) and d.get("chat") != chat]
        if arg.lower() in ("off", "выкл", "стоп"):
            self.app.state.update_settings({"tg_bot_digest": dig})
            self.send(chat, "Ежедневная сводка отключена.")
            return
        hhmm, _, topic = arg.partition(" ")
        try:
            h, m = [int(x) for x in hhmm.split(":")]
            assert 0 <= h < 24 and 0 <= m < 60
        except (ValueError, AssertionError):
            self.send(chat, "Формат: /digest 08:30 [тема]  или  /digest off")
            return
        dig.append({"chat": chat, "time": "%02d:%02d" % (h, m), "topic": topic.strip() or topic_def})
        self.app.state.update_settings({"tg_bot_digest": dig})
        self.send(chat, "Готово: сводка «%s» каждый день в %02d:%02d (время компьютера с ОКО)." % (
            html.escape(topic.strip() or topic_def), h, m))

    def _scheduler(self):
        while not self.stop_ev.wait(30):
            now = time.localtime()
            hhmm = "%02d:%02d" % (now.tm_hour, now.tm_min)
            day = time.strftime("%Y-%m-%d", now)
            allowed = self.app.state.settings().get("tg_bot_allowed") or []
            for d in self.app.state.settings().get("tg_bot_digest") or []:
                if not isinstance(d, dict) or d.get("time") != hhmm:
                    continue
                targets = [d["chat"]] if d.get("chat") else list(allowed)
                for chat in targets:
                    key = (chat, d.get("topic"), day)
                    if self._sent_digest.get(key):
                        continue
                    self._sent_digest[key] = True
                    threading.Thread(target=self._run, args=(chat, d.get("topic") or "Узбекистан", 24),
                                     daemon=True).start()


def format_digest(topic: str, hours: float, media: list, social: list, job) -> str:
    e = html.escape
    st = job.stats
    lines = ["<b>ОКО · %s · %s</b>" % (e(topic or "мониторинг"), _period(hours)),
             "Найдено: %d (по теме строго: %d), соцсети: %d. Каналов с ошибками: %d." % (
                 st.get("unique", 0), len(media), len(social), st.get("tasks_failed", 0)), ""]
    for i, x in enumerate(media[:12], 1):
        why = (" · ⌕ %s" % e(x.get("term") or x.get("kw") or "")) if (x.get("term") or x.get("kw")) else ""
        lines.append('%d. [%s] %s <a href="%s">%s</a>\n    <i>%s · %s%s</i>' % (
            i, TIER.get(x.get("tier", 4), "D"), MARK.get(x.get("status"), "·"), e(x.get("url", "")),
            e(x.get("title", "")[:180]), e(x.get("srcName") or ""), time.strftime("%d.%m %H:%M", time.localtime(x["ts"]))
            if x.get("ts") else "без даты", why))
    if len(media) > 12:
        lines.append("… и ещё %d — в файле сводки." % (len(media) - 12))
    if social:
        lines.append("\n<b>Соцсети</b>")
        for x in social[:5]:
            lines.append('• <a href="%s">%s</a> — %s' % (e(x.get("url", "")), e(x.get("title", "")[:140]),
                                                         e(x.get("srcName") or "")))
    if not media and not social:
        lines.append("За период материалов по теме не найдено.")
    lines.append("\n[A–D] уровень источника · ✔ первоисточник · ⟳ перепубликация")
    return "\n".join(lines)


def _period(hours: float) -> str:
    if hours >= 24 * 6.5:
        return "7 дней"
    if hours > 24:
        return "%d дн." % round(hours / 24)
    if hours < 24:
        return "сегодня"
    return "24 часа"


def _hours_today() -> float:
    lt = time.localtime()
    return max(1.0, lt.tm_hour + lt.tm_min / 60.0)


def _split(text: str, n: int):
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > n and cur:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return out


__all__ = ["TgBot", "format_digest"]
