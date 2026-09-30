"""Сохранение страниц в PDF через установленный браузер на базе Chromium (Chrome, Edge, Яндекс,
Brave, Chromium) в режиме headless. Если браузер не найден, интерфейс предлагает «режим чтения»
с печатью в PDF через стандартный диалог печати."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time

from .util import safe_filename

_found = None
_lock = threading.Lock()


def _candidates():
    env = os.environ.get("OKO_CHROME")
    if env:
        yield env
    system = platform.system()
    if system == "Windows":
        roots = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        rel = [r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe",
               r"Yandex\YandexBrowser\Application\browser.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe",
               r"Chromium\Application\chrome.exe"]
        for root in roots:
            if root:
                for r in rel:
                    yield os.path.join(root, r)
    elif system == "Darwin":
        for app in ("Google Chrome.app/Contents/MacOS/Google Chrome", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                    "Chromium.app/Contents/MacOS/Chromium", "Yandex.app/Contents/MacOS/Yandex",
                    "Brave Browser.app/Contents/MacOS/Brave Browser"):
            yield "/Applications/" + app
            yield os.path.expanduser("~/Applications/" + app)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                 "microsoft-edge-stable", "brave-browser", "yandex-browser"):
        p = shutil.which(name)
        if p:
            yield p


def find_browser():
    global _found
    with _lock:
        if _found is None:
            _found = ""
            for c in _candidates():
                if c and os.path.isfile(c) and os.access(c, os.X_OK):
                    _found = c
                    break
        return _found or None


def print_to_pdf(url: str, out_dir: str, title: str = "", source: str = "", timeout: int = 75) -> str:
    """Напечатать страницу в PDF. Возвращает путь к файлу или бросает RuntimeError."""
    exe = find_browser()
    if not exe:
        raise RuntimeError("не найден браузер Chrome/Edge/Chromium для печати в PDF")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    name = "%s_%s_%s.pdf" % (stamp, safe_filename(source or "OKO", 30), safe_filename(title or "page", 60))
    out = os.path.join(out_dir, name)
    profile = tempfile.mkdtemp(prefix="oko-chrome-")
    args = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--hide-scrollbars", "--mute-audio", "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=12000", "--no-pdf-header-footer", "--print-to-pdf-no-header",
            "--user-data-dir=" + profile, "--print-to-pdf=" + out, url]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.insert(1, "--no-sandbox")
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError("браузер не успел сформировать PDF за %d с" % timeout) from None
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if not os.path.isfile(out) or os.path.getsize(out) < 800:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError("PDF не создан: %s" % (err[-1][:200] if err else "код %s" % proc.returncode))
    return out
