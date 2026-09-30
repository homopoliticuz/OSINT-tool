#!/bin/sh
# ОКО — запуск в Linux:  ./start_oko.sh   (параметры: --port 9000 --no-browser)
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 oko.py "$@"
fi
echo "Python 3 не найден. Установите пакет python3 (например: sudo apt install python3)."
exit 1
