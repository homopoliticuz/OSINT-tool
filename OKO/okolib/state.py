"""Постоянное состояние ОКО (папка data/state): настройки, глоссарий переводов, досье,
история запросов, отметки «уже видел», архив отчётов."""
from __future__ import annotations

import os
import re
import threading
import time

from .util import now_ts, read_json, safe_filename, write_json

SETTINGS_VERSION = 3
DEFAULT_SETTINGS = {
    "gnews_budget": 90,
    "max_seconds": 300,
    "reliefweb_appname": "",
    "auto_discovery": True,
    "providers": None,          # None — набор по умолчанию
    "report_keep": 120,
    # соцсети и внешние сервисы (ключи хранятся только на этом компьютере)
    "tg_channels_add": [],
    "tg_channels_off": [],
    "social_platforms": None,   # None — все платформы
    "vk_token": "",
    "x_bearer": "",
    "brave_key": "",
    "gcse_key": "",
    "gcse_cx": "",
    "youtube_key": "",
    "deepl_key": "",
    # Telegram-бот и доступ с телефона
    "tg_bot_token": "",
    "tg_bot_allowed": [],
    "tg_bot_topic": "Узбекистан",
    "tg_bot_digest": [],        # [{"chat": id, "time": "08:30", "topic": "..."}]
    "lan_password": "",
}
SECRET_KEYS = ("vk_token", "x_bearer", "brave_key", "gcse_key", "youtube_key", "deepl_key", "tg_bot_token",
               "lan_password")
MASK = "••••"


def public_settings(s: dict) -> dict:
    """Настройки для интерфейса: секреты скрыты (видны только последние символы)."""
    out = dict(s)
    for k in SECRET_KEYS:
        v = str(out.get(k) or "")
        out[k] = (MASK + v[-4:]) if v else ""
        out[k + "_set"] = bool(v)
    return out


class State:
    def __init__(self, directory: str):
        self.dir = directory
        self.reports_dir = os.path.join(directory, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._settings = None
        self._seen = None

    def _p(self, name):
        return os.path.join(self.dir, name + ".json")

    # ------------------------------------------------------------ настройки
    def settings(self) -> dict:
        with self._lock:
            if self._settings is None:
                s = dict(DEFAULT_SETTINGS)
                saved = read_json(self._p("settings"), {}) or {}
                if saved and saved.get("v", 1) < 3 and saved.get("gnews_budget") in (80, 120):
                    saved["gnews_budget"] = 90  # прежние значения по умолчанию: теперь меньше запросов, но точнее
                s.update(saved)
                s["v"] = SETTINGS_VERSION
                self._settings = s
            return dict(self._settings)

    def update_settings(self, patch: dict) -> dict:
        with self._lock:
            s = self.settings()
            for k, v in (patch or {}).items():
                if k in SECRET_KEYS and isinstance(v, str) and v.startswith(MASK):
                    continue  # маска — значение не менялось
                if k in DEFAULT_SETTINGS or k.startswith("ui_"):
                    s[k] = v.strip() if isinstance(v, str) else v
            s["gnews_budget"] = max(10, min(300, int(s.get("gnews_budget") or 90)))
            s["max_seconds"] = max(60, min(900, int(s.get("max_seconds") or 300)))
            write_json(self._p("settings"), s)
            self._settings = s
            return dict(s)

    # ------------------------------------------------------------ простые документы
    def get_doc(self, name: str, default):
        return read_json(self._p(name), default)

    def put_doc(self, name: str, data):
        with self._lock:
            write_json(self._p(name), data)

    def glossary(self) -> dict:
        return self.get_doc("glossary", {}) or {}

    # ------------------------------------------------------------ «уже видел»
    def _seen_load(self):
        if self._seen is None:
            self._seen = read_json(self._p("seen"), {}) or {}
        return self._seen

    def seen_get(self, key: str) -> set:
        with self._lock:
            return set((self._seen_load().get(key) or {}).keys())

    def seen_add(self, key: str, ids):
        with self._lock:
            data = self._seen_load()
            bucket = data.setdefault(key, {})
            now = now_ts()
            for i in ids:
                bucket.setdefault(i, now)
            cutoff = now - 90 * 86400
            for k in list(data):
                data[k] = {i: t for i, t in data[k].items() if t >= cutoff}
                if not data[k]:
                    del data[k]
            write_json(self._p("seen"), data)

    # ------------------------------------------------------------ архив отчётов
    def _index_path(self):
        return os.path.join(self.reports_dir, "index.json")

    def _index(self) -> list:
        idx = read_json(self._index_path(), None)
        if idx is None:  # восстановить индекс по файлам
            idx = []
            for f in sorted(os.listdir(self.reports_dir)):
                if f.endswith(".json") and f != "index.json":
                    d = read_json(os.path.join(self.reports_dir, f), None)
                    if d:
                        idx.append(_summary(f[:-5], d))
            write_json(self._index_path(), idx)
        return idx

    def save_report(self, job) -> str:
        snap = job.snapshot()
        topics = " ".join(job.params.get("topics") or []) or "поиск"
        rid = time.strftime("%Y%m%d-%H%M%S", time.localtime(job.started)) + "_" + safe_filename(topics, 40)
        snap["report_id"] = rid
        snap["title"] = topics
        with self._lock:
            write_json(os.path.join(self.reports_dir, rid + ".json"), snap)
            idx = [r for r in self._index() if r["id"] != rid]
            idx.append(_summary(rid, snap))
            keep = int(self.settings().get("report_keep", 120))
            idx.sort(key=lambda r: r["id"])
            while len(idx) > keep:
                old = idx.pop(0)
                try:
                    os.unlink(os.path.join(self.reports_dir, old["id"] + ".json"))
                except OSError:
                    pass
            write_json(self._index_path(), idx)
        return rid

    def list_reports(self):
        with self._lock:
            return sorted(self._index(), key=lambda r: r["id"], reverse=True)

    def load_report(self, rid: str):
        if not re.fullmatch(r"[\w\-.]+", rid or "") or rid == "index":
            return None
        return read_json(os.path.join(self.reports_dir, rid + ".json"), None)

    def delete_report(self, rid: str) -> bool:
        if not re.fullmatch(r"[\w\-.]+", rid or "") or rid == "index":
            return False
        with self._lock:
            try:
                os.unlink(os.path.join(self.reports_dir, rid + ".json"))
            except OSError:
                return False
            write_json(self._index_path(), [r for r in self._index() if r["id"] != rid])
        return True


def _summary(rid: str, d: dict) -> dict:
    p = d.get("params") or {}
    st = d.get("stats") or {}
    return {"id": rid, "title": d.get("title") or " ".join(p.get("topics") or []),
            "context": p.get("context") or [], "period": d.get("period"), "started": d.get("started"),
            "unique": st.get("unique", len(d.get("items") or [])), "langs": p.get("langs") or []}
