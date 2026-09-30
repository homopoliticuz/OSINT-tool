#!/usr/bin/env python3
"""ОКО — платформа мониторинга аналитических источников.

Запуск:  python oko.py            (откроется браузер с интерфейсом)
         python oko.py --port 9000 --no-browser
Требуется только Python 3.8+ (сторонние библиотеки не нужны).
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import webbrowser

if sys.version_info < (3, 8):
    sys.exit("ОКО требует Python 3.8 или новее. Скачайте: https://www.python.org/downloads/")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from okolib import VERSION  # noqa: E402
from okolib.server import App, Handler  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


def free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 40)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("Не найден свободный порт для ОКО")


def main(argv=None):
    ap = argparse.ArgumentParser(description="ОКО — мониторинг аналитических источников")
    ap.add_argument("--port", type=int, default=8765, help="порт (по умолчанию 8765)")
    ap.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    ap.add_argument("--data", default=None, help="папка данных (по умолчанию ./data)")
    ap.add_argument("--fixtures", default=None, help=argparse.SUPPRESS)       # только для тестов
    ap.add_argument("--allow-private", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-discovery", action="store_true", help="не проверять ленты источников при запуске")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    port = free_port(args.port)
    app = App(ROOT, data_dir=args.data, fixtures=args.fixtures, allow_private=args.allow_private, port=port)
    Handler.app = app
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    if not args.no_discovery and not args.fixtures:
        app.start_background()
    url = "http://127.0.0.1:%d/" % port
    print("=" * 64)
    print("  ОКО %s — мониторинг аналитических источников" % VERSION)
    print("  Интерфейс:  %s" % url)
    print("  Источников в реестре: %d" % len(app.registry.sources))
    print("  Остановить: закройте это окно или нажмите Ctrl+C")
    print("=" * 64, flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nОКО остановлено.")
    finally:
        try:
            app.registry.flush()
        except OSError:
            pass
        httpd.server_close()


if __name__ == "__main__":
    main()
