"""Оркестрация поиска: планирование задач провайдеров, параллельное выполнение, строгая фильтрация
по периоду, объединение дублей и потоковая выдача результатов (события для интерфейса)."""
from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from .health import classify, describe
from .lexicon import ROLE_LABELS
from .net import FetchError
from .providers import extra, feeds, gdelt, gnews
from .util import TermMatcher, norm_text, now_ts, ts_to_date, utc_iso

log = logging.getLogger("oko.search")

PROVIDERS = [
    # id, подпись, функция планирования, параллельность, включён по умолчанию
    ("gnews", "Google News", gnews.tasks, 4, True),
    ("gdelt", "GDELT (мировые СМИ, 65 языков)", gdelt.tasks, 1, True),
    ("rss", "RSS-ленты источников реестра", feeds.rss_tasks, 16, True),
    ("wp", "Поиск по сайтам источников (WordPress API)", feeds.wp_tasks, 8, True),
    ("bing", "Bing News", extra.bing_tasks, 2, True),
    ("openalex", "OpenAlex (научные публикации)", extra.openalex_tasks, 1, True),
    ("worldbank", "Всемирный банк (документы и доклады)", extra.worldbank_tasks, 1, True),
    ("govuk", "GOV.UK (официальные публикации)", extra.govuk_tasks, 1, True),
    ("reliefweb", "ReliefWeb (доклады ООН и НКО)", extra.reliefweb_tasks, 1, False),
]
PROVIDER_IDS = [p[0] for p in PROVIDERS]
ENGINE_PROVIDERS = {"gnews", "gdelt", "bing", "openalex", "worldbank", "govuk", "reliefweb"}
HOST_NAMES = {"news.google.com": "Google News", "api.gdeltproject.org": "GDELT", "www.bing.com": "Bing"}
HIT_RANK = {"title": 3, "text": 2, "engine": 1}
MAX_TERMS = 12


def sanitize_plan(plan, lang_codes) -> dict:
    out = {}
    if not isinstance(plan, dict):
        return out
    allowed = set(lang_codes) | {"zh-Hant"}
    for code, p in plan.items():
        if code not in allowed or not isinstance(p, dict):
            continue
        clean = {}
        for k in ("q", "m", "ctx", "ctx_m", "not"):
            v = p.get(k) or []
            if isinstance(v, str):
                v = [v]
            clean[k] = [str(x).strip()[:120] for x in v if isinstance(x, (str, int)) and str(x).strip()][:MAX_TERMS]
        out[code] = clean
    return out


def sanitize_origins(raw, plan: dict, topics, context) -> dict:
    """Карта «нормализованный термин → происхождение» (ключевое слово, роль, языки).

    Термины плана, которых нет в карте, считаются добавленными вручную (если карта передана)
    или относятся к единственному ключевому слову запроса."""
    out = {}
    if isinstance(raw, dict):
        for k, v in list(raw.items())[:800]:
            if not isinstance(v, dict):
                continue
            nk = norm_text(str(k))[:120]
            if not nk:
                continue
            role = v.get("role") if v.get("role") in ROLE_LABELS else "main"
            langs = [str(x)[:8] for x in (v.get("langs") or []) if isinstance(x, str)][:12]
            out[nk] = {"t": str(v.get("t") or k)[:120], "kw": str(v.get("kw") or "")[:120], "role": role,
                       "of": str(v.get("of") or "")[:120], "langs": langs, "src": str(v.get("src") or "")[:20]}
    given = bool(out)
    topics = [str(x) for x in (topics or []) if str(x).strip()]
    context = [str(x) for x in (context or []) if str(x).strip()]
    kw0 = topics[0] if len(topics) == 1 else ""
    c0 = context[0] if len(context) == 1 else ""
    for code, p in plan.items():
        for key, role in (("q", "main"), ("m", "form"), ("ctx", "ctx"), ("ctx_m", "ctx")):
            for t in p.get(key) or []:
                nk = norm_text(t)
                if not nk:
                    continue
                cur = out.get(nk)
                if cur is not None:
                    if code not in cur["langs"] and len(cur["langs"]) < 12:
                        cur["langs"].append(code)
                    continue
                r = role if (not given or role == "ctx") else "manual"
                out[nk] = {"t": t, "kw": c0 if role == "ctx" else kw0, "role": r, "of": "", "langs": [code],
                           "src": "user" if r == "manual" else ""}
    return out


class SearchCtx:
    def __init__(self, app, job, params):
        self.http = app.http
        self.registry = app.registry
        self.languages = app.languages
        self.settings = app.state.settings()
        self.job = job
        self.cancel = job.cancel
        self.lang_codes = [c for c in params.get("langs", []) if c in self.languages.by_code]
        self.plan = sanitize_plan(params.get("plan"), self.lang_codes)
        self.t_from = int(params["t_from"])
        self.t_to = int(params["t_to"])
        self.types = set(params.get("types") or [])
        topic, ctxt, nott = [], [], []
        for p in self.plan.values():
            topic += p["q"] + p["m"]
            ctxt += p["ctx"] + p["ctx_m"]
            nott += p["not"]
        self.topic_matcher = TermMatcher(topic)
        self.ctx_matcher = TermMatcher(ctxt) if ctxt else None
        self.not_matcher = TermMatcher(nott) if nott else None
        self.origins = sanitize_origins(params.get("origins"), self.plan, params.get("topics"),
                                        params.get("context"))
        self.budget = {"gnews": int(self.settings.get("gnews_budget", 120))}
        self._lock = threading.Lock()
        self._tl = threading.local()

    # ------------------------------------------------------------ текущая задача (для «найдено по запросу»)
    def set_task(self, task):
        self._tl.task = task

    def current_task(self):
        return getattr(self._tl, "task", None)

    def origin(self, term: str):
        """Происхождение сработавшего термина (term — нормализованная форма из TermMatcher)."""
        return self.origins.get(term) if term else None

    def task_keywords(self, task) -> list:
        """Ключевые слова, из которых построен запрос задачи."""
        if "_kws" not in task.meta:
            kws = []
            for t in task.meta.get("terms") or []:
                o = self.origins.get(norm_text(t))
                if o and o["role"] != "ctx" and o["kw"] and o["kw"] not in kws:
                    kws.append(o["kw"])
            task.meta["_kws"] = kws
        return task.meta["_kws"]

    def source_allowed(self, s) -> bool:
        return not self.types or s.get("type") in self.types

    def take_budget(self, name: str) -> bool:
        with self._lock:
            if self.budget.get(name, 1) <= 0:
                return False
            if name in self.budget:
                self.budget[name] -= 1
            return True

    def match_item(self, title: str, text: str = ""):
        nt = norm_text(title)
        term = self.topic_matcher.find(nt, normalized=True)
        where = "title"
        if not term and text:
            term = self.topic_matcher.find(text)
            where = "text"
        if not term:
            return None
        if self.ctx_matcher and not (self.ctx_matcher.find(nt, normalized=True) or self.ctx_matcher.find(text)):
            return None
        return (where, term)

    def add(self, item) -> bool:
        return self.job.add(item)

    def note(self, msg: str):
        self.job.notes.append(msg)


class SearchJob:
    def __init__(self, app, params: dict):
        self.app = app
        self.id = uuid.uuid4().hex[:12]
        self.params = params
        self.cancel = threading.Event()
        self.events: "queue.Queue[dict]" = queue.Queue()
        self.items: dict[str, dict] = {}
        self._alias: dict[str, str] = {}
        self._by_title: dict[tuple, str] = {}
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self.notes: list[str] = []
        self.tasks_state: dict[str, dict] = {}
        self.stats = {"found": 0, "unique": 0, "no_date": 0, "out_of_range": 0, "excluded": 0,
                      "tasks": 0, "tasks_done": 0, "tasks_failed": 0, "tasks_skipped": 0}
        self.started = time.time()
        self.finished = None
        self.done = threading.Event()
        tz = int(params.get("tz_offset", 0) or 0)  # минуты к востоку от UTC
        self._tz = max(-840, min(840, tz)) * 60
        self._d_from = ts_to_date(int(params["t_from"]) + self._tz)
        self._d_to = ts_to_date(int(params["t_to"]) + self._tz)
        key = "|".join([norm_text(" ".join(params.get("topics") or [])), norm_text(" ".join(params.get("context") or [])),
                        norm_text(" ".join(params.get("exclude") or []))])
        self.seen_key = key
        self._seen = app.state.seen_get(key)

    # ------------------------------------------------------------ события
    def emit(self, typ: str, data):
        self.events.put({"type": typ, "data": data})

    # ------------------------------------------------------------ приём материалов
    def add(self, item: dict) -> bool:
        ts = item.get("ts")
        if not ts:
            self.stats["no_date"] += 1
            return False
        if item.get("prec") == "day":
            d = ts_to_date(ts)
            if d < self._d_from or d > self._d_to:
                self.stats["out_of_range"] += 1
                return False
        elif ts < self.ctx.t_from or ts > self.ctx.t_to:
            self.stats["out_of_range"] += 1
            return False
        if not item.get("title"):
            return False
        nm = self.ctx.not_matcher
        if nm and (nm.find(item["title"]) or nm.find(item.get("snippet", ""))):
            self.stats["excluded"] += 1
            return False
        if item.get("hit") == "engine":
            t = self.ctx.topic_matcher.find(item["title"])
            if t:
                item["hit"], item["term"] = "title", t
            elif item.get("snippet"):
                t = self.ctx.topic_matcher.find(item["snippet"])
                if t:
                    item["hit"], item["term"] = "text", t
        self._explain(item)
        if not item.get("source_id"):
            s = None
            if item.get("gn"):
                s = self.app.registry.lookup(item["src_url"]) if item.get("src_url") else None
            elif item.get("url"):
                s = self.app.registry.lookup(item["url"])
            if s:
                item["source_id"] = s["id"]
        self.stats["found"] += 1
        tkey = (item.get("domain") or item.get("src_name", "").lower(), norm_text(item["title"])[:160])
        with self._lock:
            eid = self._alias.get(item["id"], item["id"])
            existing = self.items.get(eid)
            if existing is None and tkey[0]:
                tid = self._by_title.get(tkey)
                existing = self.items.get(tid) if tid else None
            if existing is not None:
                self._merge(existing, item)
                self._alias[item["id"]] = existing["id"]
                self._pending.add(existing["id"])
                return True
            item["new"] = item["id"] not in self._seen
            item["found_at"] = now_ts()
            self.items[item["id"]] = item
            if tkey[0]:
                self._by_title[tkey] = item["id"]
            self._pending.add(item["id"])
            self.stats["unique"] = len(self.items)
            return True

    def _explain(self, item: dict):
        """Записать в материал, по какому ключевому слову / связанному термину и каким запросом он найден."""
        ctx = self.ctx
        o = ctx.origin(item.get("term") or "")
        if o:
            item.update(kw=o["kw"], role=o["role"], of=o.get("of", ""), tl=o.get("langs", [])[:6])
        task = ctx.current_task()
        if task is not None:
            if not o:
                kws = ctx.task_keywords(task)
                if kws:
                    item.update(kw=", ".join(kws), role="engine", of="", tl=[])
            item["q"] = [{"t": task.label, "q": task.meta.get("query", "")}]
        if ctx.ctx_matcher and not item.get("ctx_term"):
            c = ctx.ctx_matcher.find(item["title"]) or ctx.ctx_matcher.find(item.get("snippet") or "")
            if c:
                item["ctx_term"] = c

    @staticmethod
    def _merge(a: dict, b: dict):
        for k in ("prov", "via"):
            for v in b.get(k, []):
                if v not in a[k]:
                    a[k].append(v)
        if a.get("gn") and not b.get("gn") and b.get("url"):
            a["url"], a["gn"], a["curl"] = b["url"], False, b.get("curl", "")
            a["domain"] = b.get("domain") or a["domain"]
        if len(b.get("snippet") or "") > len(a.get("snippet") or ""):
            a["snippet"] = b["snippet"]
        for k in ("lang", "country", "source_id", "pdf", "src_url"):
            if not a.get(k) and b.get(k):
                a[k] = b[k]
        if not a.get("authors") and b.get("authors"):
            a["authors"] = b["authors"]
        if b.get("src_name") and (not a.get("src_name") or "." in a["src_name"]):
            a["src_name"] = b["src_name"]
        if b.get("ts") and (not a.get("ts") or b["ts"] < a["ts"]):
            a["ts"] = b["ts"]
        ra, rb = HIT_RANK.get(a.get("hit"), 0), HIT_RANK.get(b.get("hit"), 0)
        if rb > ra or (rb == ra and not a.get("kw") and b.get("kw")):
            for k in ("hit", "term", "kw", "role", "of", "tl"):
                if k in b:
                    a[k] = b[k]
        if b.get("ctx_term") and not a.get("ctx_term"):
            a["ctx_term"] = b["ctx_term"]
        for x in b.get("q") or []:
            qs = a.setdefault("q", [])
            if x not in qs and len(qs) < 5:
                qs.append(x)
        if b.get("related"):
            have = {r["title"] for r in a.get("related", [])}
            a.setdefault("related", []).extend(r for r in b["related"] if r["title"] not in have)
        for k, v in (b.get("extra") or {}).items():
            a.setdefault("extra", {}).setdefault(k, v)

    def _flush_items(self):
        with self._lock:
            ids = list(self._pending)
            self._pending.clear()
            batch = [dict(self.items[i]) for i in ids if i in self.items]
        if batch:
            self.emit("items", batch)

    # ------------------------------------------------------------ выполнение
    def start(self):
        threading.Thread(target=self._run_safe, name="oko-search-" + self.id, daemon=True).start()

    def _run_safe(self):
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            log.exception("search failed")
            self.emit("error", {"message": "внутренняя ошибка поиска: %s" % e})
        finally:
            self.finished = time.time()
            try:
                self._finish()
            finally:
                self.done.set()

    def _run(self):
        self.ctx = ctx = SearchCtx(self.app, self, self.params)
        enabled = set(self.params.get("providers") or [p[0] for p in PROVIDERS if p[4]])
        if not ctx.plan or not any(p["q"] for p in ctx.plan.values()):
            self.emit("error", {"message": "не заданы поисковые термины"})
            return
        lanes = []
        plan_info = []
        for pid, label, planner, conc, _default in PROVIDERS:
            if pid not in enabled:
                continue
            try:
                ts = planner(ctx)
            except Exception as e:  # noqa: BLE001
                log.exception("planner %s", pid)
                self.notes.append("%s: ошибка планирования (%s)" % (label, e))
                continue
            if not ts:
                continue
            lanes.append((pid, label, ts, conc))
            plan_info.append({"id": pid, "label": label, "tasks": len(ts)})
            for t in ts:
                self.tasks_state[t.key] = {"key": t.key, "provider": pid, "label": t.label, "status": "wait"}
        self.stats["tasks"] = sum(len(l[2]) for l in lanes)
        self.emit("plan", {"job": self.id, "providers": plan_info, "tasks": list(self.tasks_state.values()),
                           "notes": list(self.notes), "t_from": ctx.t_from, "t_to": ctx.t_to,
                           "langs": ctx.lang_codes})
        deadline = time.time() + float(self.app.state.settings().get("max_seconds", 300))
        stop_flush = threading.Event()

        def flusher():
            while not stop_flush.wait(0.45):
                self._flush_items()
                if time.time() > deadline and not self.cancel.is_set():
                    self.notes.append("достигнут лимит времени поиска — незавершённые запросы остановлены")
                    self.cancel.set()
        ft = threading.Thread(target=flusher, daemon=True)
        ft.start()

        health = self.app.health

        def skip(st, why, kind=""):
            st.update(status="skip", err=why, kind=kind)
            with self._lock:
                self.stats["tasks_done"] += 1
                self.stats["tasks_skipped"] = self.stats.get("tasks_skipped", 0) + 1
                if kind == "limit":
                    lim = self.stats.setdefault("limited", {})
                    lim[st["provider"]] = lim.get(st["provider"], 0) + 1
            self.emit("task", dict(st))

        def run_task(t):
            st = self.tasks_state[t.key]
            if self.cancel.is_set():
                return skip(st, "остановлено")
            off = health.skip_reason(t.key)
            if off:
                return skip(st, off, "off")
            host = t.meta.get("host")
            if host and self.app.http.host_blocked(host) > 0:
                return skip(st, "%s временно ограничил запросы — пропущено (пауза ещё %d мин)" % (
                    HOST_NAMES.get(host, host), max(1, int(self.app.http.host_blocked(host) // 60) + 1)), "limit")
            st["status"] = "run"
            self.emit("task", dict(st))
            t0 = time.time()
            ctx.set_task(t)
            try:
                n = t.fn(ctx, t) or 0
                st.update(status="ok", n=n)
                health.ok(t.key)
                if t.meta.get("skipped"):
                    st.update(status="skip", err=t.meta["skipped"])
            except FetchError as e:
                kind = classify(e)
                reason, hint = describe(kind)
                if kind == "limit" and host:
                    # пауза сервиса целиком, а не сбой канала — пропуск, а не ошибка
                    st["ms"] = int((time.time() - t0) * 1000)
                    return skip(st, "%s: %s — пропущено" % (HOST_NAMES.get(host, host), reason), "limit")
                h = health.fail(t.key, kind, str(e), label=t.label, provider=t.provider, url=e.url or "",
                                source_id=t.meta.get("source", ""), engine=t.provider in ENGINE_PROVIDERS)
                st.update(status="error", err="%s — %s" % (str(e)[:160], reason), kind=kind, hint=hint,
                          url=(e.url or "")[:300], streak=h.get("streak", 1))
                if h.get("until"):
                    st["hint"] = hint + "; канал отключён до " + time.strftime("%d.%m %H:%M", time.localtime(h["until"]))
            except Exception as e:  # noqa: BLE001
                log.error("task %s failed: %s", t.key, traceback.format_exc())
                reason, hint = describe("other")
                st.update(status="error", err="внутренняя ошибка: %s" % str(e)[:160], kind="other", hint=hint)
            finally:
                ctx.set_task(None)
            st["ms"] = int((time.time() - t0) * 1000)
            for k in ("note", "coverage", "partial"):
                if t.meta.get(k):
                    st["note"] = t.meta[k] if isinstance(t.meta[k], str) else "; ".join(t.meta[k])
            with self._lock:
                self.stats["tasks_done"] += 1
                if st["status"] == "error":
                    self.stats["tasks_failed"] += 1
            self.emit("task", dict(st))

        pools = []
        try:
            for pid, _label, ts, conc in lanes:
                ex = ThreadPoolExecutor(max_workers=conc, thread_name_prefix="oko-" + pid)
                pools.append(ex)
                for t in ts:
                    ex.submit(run_task, t)
            for ex in pools:
                ex.shutdown(wait=True)
        finally:
            stop_flush.set()
            ft.join(timeout=2)
            self._flush_items()
            try:
                self.app.registry.flush()
                self.app.health.flush()
            except OSError:
                pass

    def _finish(self):
        for pid, n in (self.stats.get("limited") or {}).items():
            label = {"gnews": "Google News", "gdelt": "GDELT", "bing": "Bing News"}.get(pid, pid)
            self.notes.append("%s временно ограничил частоту запросов: пропущено %d запросов. Уже найденное "
                              "сохранено — повторите поиск через 10–15 минут для полного охвата." % (label, n))
        took = (self.finished or time.time()) - self.started
        summary = dict(self.stats)
        summary.update(took=round(took, 1), notes=self.notes, cancelled=self.cancel.is_set() and not
                       any("лимит времени" in n for n in self.notes), http=dict(self.app.http.stats))
        try:
            if self.items:
                self.app.state.seen_add(self.seen_key, list(self.items))
                rid = self.app.state.save_report(self)
                summary["report"] = rid
        except OSError as e:
            summary["report_error"] = str(e)
        self.emit("done", summary)

    def snapshot(self) -> dict:
        return {"id": self.id, "params": self.params, "stats": self.stats, "notes": self.notes,
                "started": int(self.started), "finished": int(self.finished or time.time()),
                "items": list(self.items.values()), "tasks": list(self.tasks_state.values()),
                "period": [utc_iso(int(self.params["t_from"])), utc_iso(int(self.params["t_to"]))]}
